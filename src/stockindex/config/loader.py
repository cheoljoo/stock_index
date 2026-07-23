"""프로젝트 루트의 `config/*.yaml` 파일을 읽어 pydantic 모델(`schema.py`)로 검증·반환한다.

모든 loader는 `path`를 생략하면 `<repo_root>/config/<파일명>.yaml`을 기본으로 사용하며,
테스트에서는 임시 파일 경로를 넘겨 격리할 수 있다.
"""
from __future__ import annotations
import os
from pathlib import Path
import yaml
from .schema import (
    IndicatorConfig, GroupConfig, ThresholdLevel, Settings,
)

_BASE = Path(__file__).parents[3] / "config"


def _load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings(path: Path | None = None) -> Settings:
    """`settings.yaml` (SMTP, 저장 경로, 수집 주기 등 전역 설정)을 로드한다."""
    p = path or (_BASE / "settings.yaml")
    return Settings.model_validate(_load_yaml(p))


def load_indicators(path: Path | None = None) -> dict[str, IndicatorConfig]:
    """`indicators.yaml`의 모든 지표 정의를 {key: IndicatorConfig}로 로드한다 (on/off 무관)."""
    p = path or (_BASE / "indicators.yaml")
    raw = _load_yaml(p).get("indicators", {})
    return {k: IndicatorConfig.model_validate(v) for k, v in raw.items()}


def load_groups(path: Path | None = None) -> dict[str, GroupConfig]:
    """`groups.yaml`의 지표 묶음 정의를 {key: GroupConfig}로 로드한다."""
    p = path or (_BASE / "groups.yaml")
    raw = _load_yaml(p).get("groups", {})
    return {k: GroupConfig.model_validate(v) for k, v in raw.items()}


def load_thresholds(path: Path | None = None) -> tuple[dict[str, list[str]], dict[str, list[ThresholdLevel]]]:
    """`thresholds.yaml`을 로드해 (수신자 그룹, 지표별 임계치 목록)을 반환한다.

    Returns:
        recipients: {수신자그룹key: 이메일 목록} (예: "default", "risk_team").
        thresholds: {지표key: [ThresholdLevel, ...]}.
    """
    p = path or (_BASE / "thresholds.yaml")
    raw = _load_yaml(p)
    recipients: dict[str, list[str]] = raw.get("recipients", {})
    thresholds: dict[str, list[ThresholdLevel]] = {
        k: [ThresholdLevel.model_validate(item) for item in v]
        for k, v in raw.get("thresholds", {}).items()
    }
    return recipients, thresholds


def enabled_indicators(path: Path | None = None) -> dict[str, IndicatorConfig]:
    """`load_indicators()` 중 `enabled: true`인 지표만 걸러서 반환한다."""
    return {k: v for k, v in load_indicators(path).items() if v.enabled}
