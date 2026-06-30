# Import all providers so they register themselves via __init_subclass__
from . import (  # noqa: F401
    yfinance_provider,
    fred_provider,
    coingecko_provider,
    ecos_provider,
    portfolio_provider,
)
from .base import get_provider, PROVIDERS  # noqa: F401
