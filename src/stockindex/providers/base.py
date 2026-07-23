"""데이터 소스 확장 지점: `Provider` 서브클래스 하나 = 새 데이터 소스 하나.

`Provider`를 상속하는 클래스는 정의되는 즉시(모듈 import 시점) `__init_subclass__`가
자동으로 인스턴스를 만들어 `PROVIDERS[cls.name]`에 등록한다. 새 소스를 추가하려면:
  1. 이 파일을 상속한 `xxx_provider.py`를 작성하고 `fetch()`만 구현
  2. `providers/__init__.py`에서 import (등록 트리거)
  3. `config/indicators.yaml`에서 `provider: xxx`로 참조
코드 수정 없이 config만으로 지표를 추가할 수 있는 구조의 핵심이다.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import date
import pandas as pd

PROVIDERS: dict[str, "Provider"] = {}


class Provider(ABC):
    name: str

    @abstractmethod
    def fetch(self, symbol: str, start: date, end: date) -> pd.Series:
        """[start, end] 구간의 시계열을 조회한다.

        Returns:
            DatetimeIndex(오름차순) + float 값을 가진 pd.Series. 데이터가 없으면 빈 Series.
        """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "name") and cls.name:
            PROVIDERS[cls.name] = cls()


def get_provider(name: str) -> Provider:
    """등록된 provider 인스턴스를 이름으로 조회한다. 없으면 KeyError."""
    if name not in PROVIDERS:
        raise KeyError(f"Provider '{name}' not registered. Available: {list(PROVIDERS)}")
    return PROVIDERS[name]
