from __future__ import annotations
import os
from datetime import date
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_fixed

# pykrx는 import 시점에 KRX_ID/KRX_PW 환경변수를 읽어 세션을 만든다.
# 공매도·투자자별 수급 데이터는 data.krx.co.kr 회원 로그인이 있어야 조회된다.
# (미로그인 시에도 시세/거래량은 조회 가능하다.)
from pykrx import stock as _krx
from pykrx.website.comm import get_auth_session as _get_krx_auth_session


def krx_authenticated() -> bool:
    return bool(os.environ.get("KRX_ID") and os.environ.get("KRX_PW"))


def check_krx_login() -> tuple[bool, str]:
    """KRX_ID/KRX_PW로 실제 로그인이 되는지 확인한다.

    KRX 로그인은 자격 증명이 틀려도 예외를 던지지 않고 세션이 None이 되는 방식이라
    (krx_provider의 다른 함수들처럼) 실패를 조용히 삼키면 화면에서 원인을 알 수 없다.
    반환값: (성공 여부, 사용자에게 보여줄 메시지)
    """
    if not krx_authenticated():
        return False, "KRX_ID/KRX_PW가 설정되지 않았습니다."
    try:
        session = _get_krx_auth_session()
    except Exception as e:
        return False, f"KRX 로그인 확인 중 오류가 발생했습니다: {e}"
    if session is None:
        return False, "KRX 로그인 실패: KRX_ID 또는 KRX_PW를 확인해주세요."
    return True, "KRX 로그인 성공"


def get_stock_name(ticker: str) -> str:
    try:
        name = _krx.get_market_ticker_name(ticker)
        return name or ticker
    except Exception:
        return ticker


@retry(stop=stop_after_attempt(2), wait=wait_fixed(3))
def get_price_volume(ticker: str, start: date, end: date) -> pd.DataFrame:
    """일별 OHLCV. 로그인 불필요. columns: 시가, 고가, 저가, 종가, 거래량, 등락률"""
    df = _krx.get_market_ohlcv_by_date(
        start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), ticker
    )
    if df is None or df.empty:
        return pd.DataFrame()
    df.index = pd.to_datetime(df.index).normalize()
    return df.sort_index()


def get_shorting(ticker: str, start: date, end: date) -> pd.DataFrame:
    """공매도 거래량/비중 + 공매도 잔고/잔고비중. KRX 로그인 필요.

    실패(미로그인 등) 시 빈 DataFrame 반환 — 호출부에서 데이터 유무로 판단한다.
    columns: short_volume, short_volume_ratio, short_balance_ratio
    """
    if not krx_authenticated():
        return pd.DataFrame()
    fromdate, todate = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    try:
        vol_df = _krx.get_shorting_volume_by_date(fromdate, todate, ticker)
    except Exception:
        vol_df = pd.DataFrame()
    try:
        bal_df = _krx.get_shorting_balance_by_date(fromdate, todate, ticker)
    except Exception:
        bal_df = pd.DataFrame()

    if vol_df.empty and bal_df.empty:
        return pd.DataFrame()

    out = pd.DataFrame(index=pd.DatetimeIndex([]))
    if not vol_df.empty:
        vol_df = vol_df.copy()
        vol_df.index = pd.to_datetime(vol_df.index).normalize()
        col = "공매도" if "공매도" in vol_df.columns else "공매도거래량"
        ratio_col = "비중" if "비중" in vol_df.columns else None
        out["short_volume"] = vol_df[col]
        if ratio_col:
            out["short_volume_ratio"] = vol_df[ratio_col]
    if not bal_df.empty:
        bal_df = bal_df.copy()
        bal_df.index = pd.to_datetime(bal_df.index).normalize()
        ratio_col = next((c for c in bal_df.columns if "비중" in c), None)
        if ratio_col:
            out = out.join(bal_df[[ratio_col]].rename(columns={ratio_col: "short_balance_ratio"}), how="outer")
    return out.sort_index()


def get_investor_trading(ticker: str, start: date, end: date) -> pd.DataFrame:
    """투자자별(외국인/기관/개인) 순매수 거래대금. KRX 로그인 필요.

    실패 시 빈 DataFrame. columns: foreign, institution, individual
    """
    if not krx_authenticated():
        return pd.DataFrame()
    try:
        df = _krx.get_market_trading_value_by_date(
            start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), ticker
        )
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df.index = pd.to_datetime(df.index).normalize()
    rename = {}
    for c in df.columns:
        if "외국인" in c and "기타" not in c:
            rename[c] = "foreign"
        elif "기관" in c and "기타" not in c:
            rename[c] = "institution"
        elif c == "개인":
            rename[c] = "individual"
    out = df.rename(columns=rename)[[v for v in rename.values()]]
    return out.sort_index()
