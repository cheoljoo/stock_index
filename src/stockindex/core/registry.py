from __future__ import annotations
from stockindex.config.loader import enabled_indicators
from stockindex.config.schema import IndicatorConfig
from stockindex.providers import get_provider, PROVIDERS


def build_registry() -> dict[str, tuple[IndicatorConfig, object]]:
    """Return {key: (config, provider_instance)} for all enabled indicators."""
    indicators = enabled_indicators()
    result = {}
    for key, cfg in indicators.items():
        try:
            provider = get_provider(cfg.provider)
            result[key] = (cfg, provider)
        except KeyError as e:
            print(f"[registry] WARNING: {e} — skipping '{key}'")
    return result
