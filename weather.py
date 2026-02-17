import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_GEOCODING_SEARCH_URL = "https://geocoding-api.open-meteo.com/v1/search"
_NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"


def timezone_to_city(tz_name: str | None) -> str | None:
    if not tz_name or "/" not in tz_name:
        return None
    city_part = tz_name.split("/")[-1].strip()
    if not city_part:
        return None
    return city_part.replace("_", " ")


def _emoji_for_weather_code(code: int | None) -> str:
    if code is None:
        return "❔"
    if code == 0:
        return "☀️"
    if code in {1, 2, 3}:
        return "☁️"
    if code in {45, 48}:
        return "🌫️"
    if code in {51, 53, 55, 56, 57}:
        return "🌦️"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "🌧️"
    if code in {71, 73, 75, 77, 85, 86}:
        return "❄️"
    if code in {95, 96, 99}:
        return "⛈️"
    return "🌤️"


def _format_temperature(temp_c: float | None) -> str:
    if temp_c is None:
        return "--°C"
    rounded = int(round(temp_c))
    return f"{rounded:+d}°C"


@dataclass
class WeatherInfo:
    city: str
    temperature_text: str
    emoji: str
    fetched_at: datetime


@dataclass
class _WeatherCacheItem:
    city_key: str
    data: WeatherInfo
    saved_at: datetime


class WeatherService:
    def __init__(self) -> None:
        self._weather_cache: dict[tuple[str, int], _WeatherCacheItem] = {}
        self._geocode_cache: dict[str, tuple[float, float, datetime]] = {}
        self._lock = asyncio.Lock()
        self._weather_ttl = timedelta(hours=2)
        self._geocode_ttl = timedelta(hours=24)

    @staticmethod
    def _city_key(city: str) -> str:
        return city.strip().lower()

    @staticmethod
    def _feature_priority(feature_code: str | None) -> int:
        if not feature_code:
            return 9
        priorities = {
            "PPLC": 0,  # capital
            "PPLA": 1,  # seat of admin division
            "PPLA2": 1,
            "PPLA3": 1,
            "PPLA4": 1,
            "PPL": 2,  # populated place
            "PPLG": 2,
            "PPLL": 2,
            "PPLX": 3,
        }
        return priorities.get(feature_code, 8)

    @staticmethod
    def _distance_km(latitude_1: float, longitude_1: float, latitude_2: float, longitude_2: float) -> float:
        r = 6371.0
        lat_1 = math.radians(latitude_1)
        lat_2 = math.radians(latitude_2)
        d_lat = math.radians(latitude_2 - latitude_1)
        d_lon = math.radians(longitude_2 - longitude_1)
        a = math.sin(d_lat / 2) ** 2 + math.cos(lat_1) * math.cos(lat_2) * math.sin(d_lon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return r * c

    @classmethod
    def _search_result_score(
        cls,
        result: dict[str, Any],
        origin_latitude: float,
        origin_longitude: float,
    ) -> tuple[int, int, int, float]:
        latitude = result.get("latitude")
        longitude = result.get("longitude")
        if latitude is None or longitude is None:
            distance = 10_000.0
        else:
            distance = cls._distance_km(origin_latitude, origin_longitude, float(latitude), float(longitude))

        if distance <= 80:
            distance_bucket = 0
        elif distance <= 180:
            distance_bucket = 1
        else:
            distance_bucket = 2

        population_raw = result.get("population")
        try:
            population = int(population_raw) if population_raw is not None else 0
        except (TypeError, ValueError):
            population = 0

        feature_priority = cls._feature_priority(result.get("feature_code"))
        return distance_bucket, feature_priority, -population, distance

    @staticmethod
    def _extract_locality(address: dict[str, Any]) -> str | None:
        if not isinstance(address, dict):
            return None
        for key in ("city", "town", "municipality", "county", "state_district", "village", "hamlet"):
            value = address.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    async def _reverse_geocode_nominatim(self, latitude: float, longitude: float, locale: str | None) -> tuple[str | None, str | None]:
        params = {
            "lat": latitude,
            "lon": longitude,
            "format": "jsonv2",
            "addressdetails": 1,
            "zoom": 10,
            "accept-language": (locale or "ru")[:2],
        }
        headers = {"User-Agent": "tg-organazer/1.0 (weather city resolver)"}
        try:
            async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
                response = await client.get(_NOMINATIM_REVERSE_URL, params=params)
                response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            logger.exception("Failed to reverse geocode by coordinates: lat=%s lon=%s", latitude, longitude)
            return None, None

        address = payload.get("address") if isinstance(payload, dict) else None
        city = self._extract_locality(address if isinstance(address, dict) else {})
        country_code_raw = address.get("country_code") if isinstance(address, dict) else None
        country_code = str(country_code_raw).upper() if isinstance(country_code_raw, str) and country_code_raw else None
        return city, country_code

    async def _choose_major_nearby_city(
        self,
        seed_city: str,
        latitude: float,
        longitude: float,
        country_code: str | None,
        locale: str | None,
    ) -> str | None:
        language = (locale or "ru")[:2]
        search_variants = [
            {"name": seed_city, "count": 30, "format": "json", "language": language},
            {"name": seed_city, "count": 30, "format": "json", "language": "en"},
            {"name": seed_city, "count": 30, "format": "json"},
        ]
        if country_code and len(country_code) == 2:
            for params in search_variants:
                params["countryCode"] = country_code

        results: list[dict[str, Any]] = []
        for params in search_variants:
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    response = await client.get(_GEOCODING_SEARCH_URL, params=params)
                    response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError):
                logger.exception("Failed to resolve major city by seed: %s params=%s", seed_city, params)
                continue

            current_results = payload.get("results") if isinstance(payload, dict) else None
            if not isinstance(current_results, list) or not current_results:
                continue
            results = [item for item in current_results if isinstance(item, dict)]
            if results:
                break

        if not results:
            return seed_city

        ranked = sorted(results, key=lambda item: self._search_result_score(item, latitude, longitude))
        for item in ranked:
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            lat = item.get("latitude")
            lon = item.get("longitude")
            if lat is not None and lon is not None:
                self._geocode_cache[self._city_key(name)] = (float(lat), float(lon), datetime.now(timezone.utc))
            return name.strip()

        return seed_city

    async def resolve_city_from_coords(self, latitude: float, longitude: float, locale: str | None = None) -> str | None:
        city, country_code = await self._reverse_geocode_nominatim(latitude=latitude, longitude=longitude, locale=locale)
        if not city:
            return None

        major_city = await self._choose_major_nearby_city(
            seed_city=city,
            latitude=latitude,
            longitude=longitude,
            country_code=country_code,
            locale=locale,
        )
        return major_city or city

    async def get_weather_for_city(self, user_id: int, city: str | None, platform: str = "tg") -> WeatherInfo | None:
        if not city or not city.strip():
            return None

        city_key = self._city_key(city)
        now = datetime.now(timezone.utc)
        cache_key = (platform, int(user_id))

        async with self._lock:
            cached = self._weather_cache.get(cache_key)
            if cached and cached.city_key == city_key and now - cached.saved_at < self._weather_ttl:
                return cached.data

        coords = await self._resolve_city_coords(city=city)
        if not coords:
            return None

        temperature_text, weather_emoji = await self._fetch_forecast(latitude=coords[0], longitude=coords[1])
        if temperature_text is None:
            return None

        weather_data = WeatherInfo(city=city.strip(), temperature_text=temperature_text, emoji=weather_emoji, fetched_at=now)

        async with self._lock:
            self._weather_cache[cache_key] = _WeatherCacheItem(city_key=city_key, data=weather_data, saved_at=now)

        return weather_data

    async def _resolve_city_coords(self, city: str) -> tuple[float, float] | None:
        city_key = self._city_key(city)
        now = datetime.now(timezone.utc)
        cached = self._geocode_cache.get(city_key)
        if cached and now - cached[2] < self._geocode_ttl:
            return cached[0], cached[1]

        search_variants = (
            {"name": city, "count": 1, "language": "ru", "format": "json"},
            {"name": city, "count": 1, "language": "en", "format": "json"},
            {"name": city, "count": 1, "format": "json"},
        )

        latitude = None
        longitude = None
        for params in search_variants:
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    response = await client.get(_GEOCODING_SEARCH_URL, params=params)
                    response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError):
                logger.exception("Failed to resolve city coordinates: city=%s params=%s", city, params)
                continue

            results = payload.get("results") if isinstance(payload, dict) else None
            if not results:
                continue

            first = results[0]
            latitude = first.get("latitude")
            longitude = first.get("longitude")
            if latitude is not None and longitude is not None:
                break

        if latitude is None or longitude is None:
            return None

        lat = float(latitude)
        lon = float(longitude)
        self._geocode_cache[city_key] = (lat, lon, now)
        return lat, lon

    async def _fetch_forecast(self, latitude: float, longitude: float) -> tuple[str | None, str]:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,weather_code",
            "timezone": "auto",
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(_FORECAST_URL, params=params)
                response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            logger.exception("Failed to fetch weather forecast for lat=%s lon=%s", latitude, longitude)
            return None, "❔"

        current = payload.get("current") if isinstance(payload, dict) else None
        if not isinstance(current, dict):
            return None, "❔"

        temperature = current.get("temperature_2m")
        weather_code = current.get("weather_code")

        temp_value = float(temperature) if temperature is not None else None
        temp_text = _format_temperature(temp_value)

        try:
            code_value = int(weather_code) if weather_code is not None else None
        except (TypeError, ValueError):
            code_value = None
        return temp_text, _emoji_for_weather_code(code_value)


weather_service = WeatherService()
