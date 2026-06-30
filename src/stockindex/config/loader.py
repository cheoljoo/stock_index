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
    p = path or (_BASE / "settings.yaml")
    return Settings.model_validate(_load_yaml(p))


def load_indicators(path: Path | None = None) -> dict[str, IndicatorConfig]:
    p = path or (_BASE / "indicators.yaml")
    raw = _load_yaml(p).get("indicators", {})
    return {k: IndicatorConfig.model_validate(v) for k, v in raw.items()}


def load_groups(path: Path | None = None) -> dict[str, GroupConfig]:
    p = path or (_BASE / "groups.yaml")
    raw = _load_yaml(p).get("groups", {})
    return {k: GroupConfig.model_validate(v) for k, v in raw.items()}


def load_thresholds(path: Path | None = None) -> tuple[dict[str, list[str]], dict[str, list[ThresholdLevel]]]:
    p = path or (_BASE / "thresholds.yaml")
    raw = _load_yaml(p)
    recipients: dict[str, list[str]] = raw.get("recipients", {})
    thresholds: dict[str, list[ThresholdLevel]] = {
        k: [ThresholdLevel.model_validate(item) for item in v]
        for k, v in raw.get("thresholds", {}).items()
    }
    return recipients, thresholds


def enabled_indicators(path: Path | None = None) -> dict[str, IndicatorConfig]:
    return {k: v for k, v in load_indicators(path).items() if v.enabled}
