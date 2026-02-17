from __future__ import annotations

from datetime import timedelta

import pytest

from weather import WeatherService


def test_weather_cache_ttl_is_two_hours():
    service = WeatherService()
    assert service._weather_ttl == timedelta(hours=2)


@pytest.mark.asyncio
async def test_get_weather_for_city_uses_cache_within_ttl(monkeypatch):
    service = WeatherService()
    resolve_calls = 0
    fetch_calls = 0

    async def fake_resolve_city_coords(city: str):
        nonlocal resolve_calls
        resolve_calls += 1
        return 55.7558, 37.6176

    async def fake_fetch_forecast(latitude: float, longitude: float):
        nonlocal fetch_calls
        fetch_calls += 1
        return "+5°C", "☀️"

    monkeypatch.setattr(service, "_resolve_city_coords", fake_resolve_city_coords)
    monkeypatch.setattr(service, "_fetch_forecast", fake_fetch_forecast)

    first = await service.get_weather_for_city(user_id=1, city="Moscow", platform="tg")
    second = await service.get_weather_for_city(user_id=1, city="Moscow", platform="tg")

    assert first is not None
    assert second is not None
    assert first == second
    assert resolve_calls == 1
    assert fetch_calls == 1
