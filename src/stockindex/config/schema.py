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


class ScreenerConfig(BaseModel):
    """KOSPI200 외국인·기관 수급 스크리너(`core/screener.py`) 설정."""
    min_days: int = 3           # DB에 남길 최소 연속일수
    notify_min_days: int = 5    # 이 이상이면 일일 다이제스트 메일 발송 대상
    notify: str = "default"
    foreign_start_days: int = 3   # 외국인 순매수가 같은 방향으로 이만큼 이어지면 흐름 시작으로 본다

    # ── 외국인 지분율 스크리너(twin-buy 연속일수와 별개) ──────────────────
    ownership_lookback_days: int = 30
    ownership_steady_min_change_pct: float = 0.5     # 지속 증가로 볼 최소 전체 변화폭(%p)
    ownership_steady_min_up_ratio: float = 0.6       # 지속 증가로 볼 최소 상승일 비율(0~1)
    ownership_spike_min_daily_change_pct: float = 0.3  # 일시 급증으로 볼 최소 하루 변화폭(%p)


class ReportConfig(BaseModel):
    """`run_daily.py` 실행 결과 메일(`notify/report.py`). 로그가 첨부되므로 수신자는 본인만 두는 것을 권장."""
    enabled: bool = True
    to: list[str] = []


class Settings(BaseModel):
    site_url: str = "http://localhost:8501"
    storage: StorageConfig = StorageConfig()
    smtp: SmtpConfig = SmtpConfig()
    schedule: ScheduleConfig = ScheduleConfig()
    collect: CollectConfig = CollectConfig()
    alert: AlertConfig = AlertConfig()
    screener: ScreenerConfig = ScreenerConfig()
    report: ReportConfig = ReportConfig()
