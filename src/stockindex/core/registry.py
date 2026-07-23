"""config(`indicators.yaml`)의 지표 정의를 실제 Provider 인스턴스와 연결하는 조립 계층.

`collect_all()`이 매 수집마다 호출해 "어떤 지표를, 어떤 provider로 가져올지"의
매핑 테이블을 만든다. 지표를 추가/삭제하려면 코드가 아니라 `config/indicators.yaml`만
수정하면 되는 것이 이 프로젝트의 핵심 확장 지점이다.
"""
from __future__ import annotations
from stockindex.config.loader import enabled_indicators
from stockindex.config.schema import IndicatorConfig
from stockindex.providers import get_provider, PROVIDERS


def build_registry() -> dict[str, tuple[IndicatorConfig, object]]:
    """enabled=true인 모든 지표에 대해 {key: (config, provider_instance)}를 만든다.

    config에 등록되지 않은 provider 이름이면 해당 지표만 건너뛰고 경고를 출력한다
    (전체 수집이 중단되지 않도록).
    """
    indicators = enabled_indicators()
    result = {}
    for key, cfg in indicators.items():
        try:
            provider = get_provider(cfg.provider)
            result[key] = (cfg, provider)
        except KeyError as e:
            print(f"[registry] WARNING: {e} — skipping '{key}'")
    return result
