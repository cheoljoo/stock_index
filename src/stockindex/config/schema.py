"""`config/*.yaml`을 검증하는 pydantic 모델. yaml의 각 블록이 여기 클래스 1:1로 매핑된다.

`indicators.yaml` → IndicatorConfig, `groups.yaml` → GroupConfig,
`thresholds.yaml` → ThresholdLevel(ThresholdCondition), `settings.yaml` → Settings.
"""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field


class IndicatorConfig(BaseModel):
    """`indicators.yaml`의 지표 한 개 정의."""
    enabled: bool = True
    display_name: str = ""
    provider: str
    symbol: str
    unit: str = ""
    category: str = "misc"
    trend_window: int = 20


class GroupConfig(BaseModel):
    """`groups.yaml`의 지표 묶음 한 개 정의 (members는 지표 key 목록)."""
    display_name: str
    members: list[str]


class ThresholdCondition(BaseModel):
    """임계치 판정 조건. op별 의미는 `core/alerts.evaluate_threshold` 참고."""
    op: Literal[">=", "<=", "pct_change", "cross"]
    value: float
    window: int = 1


class ThresholdLevel(BaseModel):
    """지표 하나의 임계치 단계 하나 (예: kospi200의 "급등" 단계)."""
    level: str
    condition: ThresholdCondition
    notify: str | list[str]

    def notify_keys(self) -> list[str]:
        """`notify`가 단일 문자열이든 리스트든 항상 리스트로 정규화해 반환한다."""
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
