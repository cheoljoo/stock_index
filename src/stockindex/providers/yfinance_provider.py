from __future__ import annotations
from datetime import date, timedelta
import pandas as pd
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_fixed
from .base import Provider


class YFinanceProvider(Provider):
    """야후 파이낸스 종가 데이터 (주가지수·ETF·환율·원자재·VIX 등). 무료, 키 불필요."""
    name = "yfinance"

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def fetch(self, symbol: str, start: date, end: date) -> pd.Series:
        """일별 종가(Close, 배당·분할 조정) 시계열을 조회한다. 실패 시 최대 3회 재시도."""
        end_dl = end + timedelta(days=1)  # yfinance end is exclusive
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=str(start), end=str(end_dl), auto_adjust=True)
        if df.empty:
            return pd.Series(dtype=float, name=symbol)
        s = df["Close"].dropna()
        s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
        return s.rename(symbol)


@retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
def fetch_ohlcv(symbol: str, start: date, end: date) -> pd.DataFrame:
    """미국 등 해외 종목의 일별 시가/고가/저가/종가/거래량을 조회한다.

    `krx_provider.get_price_volume()`과 같은 컬럼명(시가/고가/저가/종가/거래량)을 써서,
    데드캣·상승추세 분석의 신호 계산 함수들을 KRX 종목과 동일하게 재사용할 수 있게 한다.
    공매도·투자자별 수급은 해외 종목에 대해 제공되지 않으므로 호출부에서 빈 DataFrame으로 채운다.
    """
    end_dl = end + timedelta(days=1)  # yfinance end is exclusive
    ticker = yf.Ticker(symbol)
    df = ticker.history(start=str(start), end=str(end_dl), auto_adjust=True)
    if df.empty:
        return pd.DataFrame()
    df = df.rename(columns={"Open": "시가", "High": "고가", "Low": "저가", "Close": "종가", "Volume": "거래량"})
    df = df[["시가", "고가", "저가", "종가", "거래량"]].dropna(subset=["종가"])
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.index.name = "date"
    return df.sort_index()
