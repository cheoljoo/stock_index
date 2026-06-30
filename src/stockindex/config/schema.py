from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field


class IndicatorConfig(BaseModel):
    enabled: bool = True
    display_name: str = ""
    provider: str
    symbol: str
    unit: str = ""
    category: str = "misc"
    trend_window: int = 20


class GroupConfig(BaseModel):
    display_name: str
    members: list[str]


class ThresholdCondition(BaseModel):
    op: Literal[">=", "<=", "pct_change", "cross"]
    value: float
    window: int = 1


class ThresholdLevel(BaseModel):
    level: str
    condition: ThresholdCondition
    notify: str | list[str]

    def notify_keys(self) -> list[str]:
        if isinstance(self.notify, str):
            return [self.notify]
        return self.notify


class StorageConfig(BaseModel):
    db_path: str = "data/meta.db"
    parquet_dir: str = "data/series"


class SmtpConfig(BaseModel):
    host: str = "smtp.gmail.com"
    port: int = 587
    user: str = ""
    password_env: str = "SMTP_PASSWORD"
    from_: str = Field("", alias="from")

    model_config = {"populate_by_name": True}


class ScheduleConfig(BaseModel):
    run_time: str = "18:00"
    tz: str = "Asia/Seoul"


class CollectConfig(BaseModel):
    lookback_days: int = 365
    retry_max: int = 3
    retry_wait_seconds: int = 5


class AlertConfig(BaseModel):
    suppress_duplicate_days: int = 1


class Settings(BaseModel):
    site_url: str = "http://localhost:8501"
    storage: StorageConfig = StorageConfig()
    smtp: SmtpConfig = SmtpConfig()
    schedule: ScheduleConfig = ScheduleConfig()
    collect: CollectConfig = CollectConfig()
    alert: AlertConfig = AlertConfig()
