from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import date
import pandas as pd

PROVIDERS: dict[str, "Provider"] = {}


class Provider(ABC):
    name: str

    @abstractmethod
    def fetch(self, symbol: str, start: date, end: date) -> pd.Series:
        """Return a pd.Series with DatetimeIndex and float values."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "name") and cls.name:
            PROVIDERS[cls.name] = cls()


def get_provider(name: str) -> Provider:
    if name not in PROVIDERS:
        raise KeyError(f"Provider '{name}' not registered. Available: {list(PROVIDERS)}")
    return PROVIDERS[name]
