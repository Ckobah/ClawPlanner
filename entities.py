import datetime
import enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from config import MONTH_NAMES
from i18n import tr


class Recurrent(enum.StrEnum):
    never = "never"
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    annual = "annual"

    def get_name(self, locale: str | None = None) -> str:
        if self.value == "never":
            return tr("Никогда", locale)
        elif self.value == "daily":
            return tr("Ежедневно", locale)
        elif self.value == "weekly":
            return tr("Еженедельно", locale)
        elif self.value == "monthly":
            return tr("Ежемесячно", locale)
        else:
            return tr("Каждый год", locale)

    @staticmethod
    def get_all_names(locale: str | None = None) -> list[tuple]:
        return [(item.get_name(locale), item.value) for item in Recurrent]


class Event(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_date: datetime.date
    description: str | None = None
    emoji: str | None = None
    start_time: datetime.time | None = None
    stop_time: datetime.time | None = None
    recurrent: Recurrent = Recurrent.never
    participants: list[int | None] = Field(default_factory=list)
    all_user_participants: dict[int, str] = Field(default_factory=dict)
    tg_id: int | None = None
    creator_tg_id: int | None = None
    max_id: int | None = None
    creator_max_id: int | None = None

    def get_date(self) -> tuple[int, int, int]:
        return self.event_date.year, self.event_date.month, self.event_date.day

    def get_format_date(self) -> str:
        return f"{self.event_date.day} {(MONTH_NAMES[int(self.event_date.month) - 1]).title()} {self.event_date.year} года"


class TgUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tg_id: int = Field(int, alias="id")
    is_active: bool = True
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None
    time_zone: str | None = None
    title: str | None = None

    @model_validator(mode="after")
    def names(self) -> "TgUser":
        if self.title:
            self.username = self.first_name = self.title

        return self


class MaxUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    max_id: int = Field(int, alias="id")
    is_active: bool = True
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None
    time_zone: str | None = None
    title: str | None = None

    @model_validator(mode="after")
    def names(self) -> "MaxUser":
        if self.title:
            self.username = self.first_name = self.title

        return self
