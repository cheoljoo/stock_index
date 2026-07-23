"""상승/하락 추세 전환 판별 로직.

"바닥을 잡는 대신 오르기 시작할 때 사라"는 원칙에 따라, 아래 7가지 기술적/수급적
근거를 코드화한다. 각 지표는 상승 신호뿐 아니라 대칭되는 하락 신호도 함께 판별한다:
  1. 이동평균선 골든/데드크로스 & 정배열·역배열
  2. RSI 50 상향/하향 돌파 (+ 과매도 탈출 / 과매수 이탈)
  3. MACD 시그널선·기준선(0) 상향/하향 돌파
  4. 다우 이론 N자형 상승(Higher-Low·Higher-High) / 역N자형 하락(Lower-High·Lower-Low)
  5. 박스권 상단 저항선 돌파 / 하단 지지선 이탈
  6. 거래량 급증을 동반한 양봉(매수 유입) / 음봉(투매)
  7. 외국인+기관 N일 연속 동시 순매수(쌍끌이 매수) / 동시 순매도(쌍끌이 매도)

각 signal 함수는 {"label": "bullish"|"bearish"|"neutral"|"unknown", "reason": str, "detail": dict}를 반환한다.
데이터가 없으면 label="unknown"으로 표시해 최종 결론에서 제외한다.
"""
from __future__ import annotations
from typing import Literal, TypedDict
import numpy as np
import pandas as pd
from scipy.signal import find_peaks

SignalLabel = Literal["bullish", "bearish", "neutral", "unknown"]

# 최근 N거래일 내에 크로스/돌파가 발생했는지 확인하는 관찰 구간
RECENT_WINDOW = 5
# 외국인+기관 동시 순매수/순매도로 인정하는 최소 연속일
TWIN_FLOW_MIN_DAYS = 3


class Signal(TypedDict):
    key: str
    title: str
    label: SignalLabel
    reason: str
    detail: dict


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD 라인, 시그널 라인, 히스토그램을 반환한다."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def signal_golden_cross(close: pd.Series, short: int = 20, long: int = 60) -> Signal:
    """① 단기(20일)·장기(60일) 이평선의 골든/데드크로스 및 정배열/역배열."""
    key, title = "golden_cross", "이평선 골든·데드크로스"
    c = close.dropna()
    if len(c) < long + RECENT_WINDOW:
        return Signal(key=key, title=title, label="unknown", reason="데이터 부족(이평선 계산에 필요한 기간 미달)", detail={})

    ma_short = c.rolling(short).mean()
    ma_long = c.rolling(long).mean()
    diff = (ma_short - ma_long).dropna()
    if len(diff) < RECENT_WINDOW + 1:
        return Signal(key=key, title=title, label="unknown", reason="데이터 부족", detail={})

    recent = diff.iloc[-(RECENT_WINDOW + 1):]
    golden_crossed = bool((recent.iloc[:-1] < 0).any() and recent.iloc[-1] > 0)
    dead_crossed = bool((recent.iloc[:-1] > 0).any() and recent.iloc[-1] < 0)
    aligned_up = bool(ma_short.iloc[-1] > ma_long.iloc[-1])

    detail = {
        f"{short}일선": round(float(ma_short.iloc[-1]), 2),
        f"{long}일선": round(float(ma_long.iloc[-1]), 2),
        f"최근{RECENT_WINDOW}일내_골든크로스": golden_crossed,
        f"최근{RECENT_WINDOW}일내_데드크로스": dead_crossed,
    }

    if golden_crossed:
        return Signal(key=key, title=title, label="bullish",
                      reason=f"최근 {RECENT_WINDOW}거래일 내 {short}일선이 {long}일선을 상향 돌파(골든크로스)",
                      detail=detail)
    if dead_crossed:
        return Signal(key=key, title=title, label="bearish",
                      reason=f"최근 {RECENT_WINDOW}거래일 내 {short}일선이 {long}일선을 하향 돌파(데드크로스)",
                      detail=detail)
    if aligned_up:
        return Signal(key=key, title=title, label="bullish",
                      reason=f"{short}일선이 {long}일선 위에서 정배열을 유지 중", detail=detail)
    return Signal(key=key, title=title, label="bearish",
                  reason=f"{short}일선이 {long}일선 아래에서 역배열을 유지 중", detail=detail)


def signal_rsi(close: pd.Series, period: int = 14, oversold: float = 30, overbought: float = 70, mid: float = 50) -> Signal:
    """② RSI 50선 상향/하향 돌파 (+ 과매도 탈출 / 과매수 이탈)."""
    key, title = "rsi", "RSI 50선 돌파"
    c = close.dropna()
    r = rsi(c, period).dropna()
    if len(r) < RECENT_WINDOW + 5:
        return Signal(key=key, title=title, label="unknown", reason="데이터 부족", detail={})

    recent = r.iloc[-(RECENT_WINDOW + 1):]
    crossed_up = bool((recent.iloc[:-1] < mid).any() and recent.iloc[-1] > mid)
    crossed_down = bool((recent.iloc[:-1] > mid).any() and recent.iloc[-1] < mid)
    was_oversold = bool((r.iloc[-20:] < oversold).any())
    was_overbought = bool((r.iloc[-20:] > overbought).any())
    current = float(r.iloc[-1])

    detail = {
        "현재RSI": round(current, 1),
        f"최근20일_과매도({oversold:.0f})경험": was_oversold,
        f"최근20일_과매수({overbought:.0f})경험": was_overbought,
        f"최근{RECENT_WINDOW}일내_50상향돌파": crossed_up,
        f"최근{RECENT_WINDOW}일내_50하향돌파": crossed_down,
    }

    if crossed_up and was_oversold:
        return Signal(key=key, title=title, label="bullish",
                      reason=f"과매도(RSI<{oversold:.0f}) 이후 RSI가 중립선({mid:.0f})을 상향 돌파 — 매도 압력 소진 후 반등 시작",
                      detail=detail)
    if crossed_down and was_overbought:
        return Signal(key=key, title=title, label="bearish",
                      reason=f"과매수(RSI>{overbought:.0f}) 이후 RSI가 중립선({mid:.0f})을 하향 돌파 — 매수 압력 소진 후 하락 시작",
                      detail=detail)
    if crossed_up:
        return Signal(key=key, title=title, label="bullish",
                      reason=f"RSI가 최근 {RECENT_WINDOW}거래일 내 중립선({mid:.0f})을 상향 돌파", detail=detail)
    if crossed_down:
        return Signal(key=key, title=title, label="bearish",
                      reason=f"RSI가 최근 {RECENT_WINDOW}거래일 내 중립선({mid:.0f})을 하향 돌파", detail=detail)
    if current >= mid:
        return Signal(key=key, title=title, label="bullish", reason=f"RSI({current:.1f})가 중립선({mid:.0f}) 위에서 유지 중", detail=detail)
    return Signal(key=key, title=title, label="bearish", reason=f"RSI({current:.1f})가 중립선({mid:.0f}) 아래에서 유지 중", detail=detail)


def signal_macd(close: pd.Series) -> Signal:
    """③ MACD의 시그널선·기준선(0) 상향/하향 돌파."""
    key, title = "macd", "MACD 시그널·기준선 돌파"
    c = close.dropna()
    if len(c) < 35 + RECENT_WINDOW:
        return Signal(key=key, title=title, label="unknown", reason="데이터 부족", detail={})

    macd_line, signal_line, hist = macd(c)
    diff = (macd_line - signal_line).dropna()
    if len(diff) < RECENT_WINDOW + 1:
        return Signal(key=key, title=title, label="unknown", reason="데이터 부족", detail={})

    recent = diff.iloc[-(RECENT_WINDOW + 1):]
    signal_cross_up = bool((recent.iloc[:-1] < 0).any() and recent.iloc[-1] > 0)
    signal_cross_down = bool((recent.iloc[:-1] > 0).any() and recent.iloc[-1] < 0)
    zero_recent = macd_line.iloc[-(RECENT_WINDOW + 1):]
    zero_cross_up = bool((zero_recent.iloc[:-1] < 0).any() and zero_recent.iloc[-1] > 0)
    zero_cross_down = bool((zero_recent.iloc[:-1] > 0).any() and zero_recent.iloc[-1] < 0)

    macd_now = float(macd_line.iloc[-1])
    signal_now = float(signal_line.iloc[-1])
    detail = {
        "MACD": round(macd_now, 3), "Signal": round(signal_now, 3),
        "시그널선_상향돌파": signal_cross_up, "시그널선_하향돌파": signal_cross_down,
        "기준선(0)_상향돌파": zero_cross_up, "기준선(0)_하향돌파": zero_cross_down,
    }

    if signal_cross_up and zero_cross_up:
        return Signal(key=key, title=title, label="bullish",
                      reason="MACD가 시그널선과 기준선(0)을 모두 상향 돌파 — 강한 상승 추세 진입 신호", detail=detail)
    if signal_cross_down and zero_cross_down:
        return Signal(key=key, title=title, label="bearish",
                      reason="MACD가 시그널선과 기준선(0)을 모두 하향 돌파 — 강한 하락 추세 진입 신호", detail=detail)
    if signal_cross_up:
        return Signal(key=key, title=title, label="bullish", reason=f"MACD가 최근 {RECENT_WINDOW}거래일 내 시그널선을 상향 돌파", detail=detail)
    if signal_cross_down:
        return Signal(key=key, title=title, label="bearish", reason=f"MACD가 최근 {RECENT_WINDOW}거래일 내 시그널선을 하향 돌파", detail=detail)
    if macd_now > 0 and signal_now > 0:
        return Signal(key=key, title=title, label="bullish", reason="MACD·시그널선이 모두 기준선(0) 위에서 유지 중", detail=detail)
    if macd_now < 0 and signal_now < 0:
        return Signal(key=key, title=title, label="bearish", reason="MACD·시그널선이 모두 기준선(0) 아래에서 유지 중", detail=detail)
    return Signal(key=key, title=title, label="neutral", reason="MACD가 기준선 부근에서 방향성 없이 혼조세", detail=detail)


def signal_higher_low_high(close: pd.Series, lookback: int = 60, distance: int = 5) -> Signal:
    """④ N자형 상승(Higher-Low·Higher-High) / 역N자형 하락(Lower-High·Lower-Low)."""
    key, title = "higher_low_high", "가격 파동 패턴(N자/역N자)"
    c = close.dropna().iloc[-lookback:]
    if len(c) < distance * 4:
        return Signal(key=key, title=title, label="unknown", reason="데이터 부족", detail={})

    values = c.values
    trough_idx, _ = find_peaks(-values, distance=distance)
    peak_idx, _ = find_peaks(values, distance=distance)

    if len(trough_idx) < 2 or len(peak_idx) < 2:
        return Signal(key=key, title=title, label="unknown", reason="저점·고점 파동을 특정하기에 데이터가 부족함", detail={})

    last_trough, prev_trough = trough_idx[-1], trough_idx[-2]
    higher_low = bool(values[last_trough] > values[prev_trough])
    lower_low = bool(values[last_trough] < values[prev_trough])

    last_peak, prev_peak = peak_idx[-1], peak_idx[-2]
    lower_high = bool(values[last_peak] < values[prev_peak])

    # 상승 판정: 마지막 저점 이전의 전고점을 현재가가 돌파했는지
    prior_peaks = peak_idx[peak_idx < last_trough]
    higher_high = bool(len(prior_peaks) > 0 and float(values[-1]) > float(values[prior_peaks[-1]]))

    # 하락 판정: 마지막 고점 이전의 전저점을 현재가가 하향 이탈했는지
    prior_troughs = trough_idx[trough_idx < last_peak]
    broke_prior_low = bool(len(prior_troughs) > 0 and float(values[-1]) < float(values[prior_troughs[-1]]))

    detail = {
        "전저점": round(float(values[prev_trough]), 2), "최근저점": round(float(values[last_trough]), 2),
        "전고점": round(float(values[prev_peak]), 2), "최근고점": round(float(values[last_peak]), 2),
        "현재가": round(float(values[-1]), 2),
        "Higher_Low": higher_low, "Higher_High": higher_high,
        "Lower_High": lower_high, "Lower_Low_또는_전저점붕괴": lower_low or broke_prior_low,
    }

    if higher_low and higher_high:
        return Signal(key=key, title=title, label="bullish",
                      reason="전저점을 깨지 않은 반등(Higher Low) 후 전고점을 상향 돌파(Higher High) — 추세 전환형 N자 패턴 완성",
                      detail=detail)
    if lower_high and (lower_low or broke_prior_low):
        return Signal(key=key, title=title, label="bearish",
                      reason="전고점을 넘지 못한 반등(Lower High) 후 전저점을 하향 이탈(Lower Low) — 하락 지속형 역N자 패턴",
                      detail=detail)
    return Signal(key=key, title=title, label="neutral", reason="저점·고점 패턴이 뚜렷한 방향성을 보이지 않음", detail=detail)


def signal_box_breakout(price_volume: pd.DataFrame, lookback: int = 60) -> Signal:
    """⑤ 최근 N일 박스권 상단(저항선) 돌파 / 하단(지지선) 이탈 여부."""
    key, title = "box_breakout", "박스권 저항선/지지선 이탈"
    if price_volume is None or price_volume.empty or "종가" not in price_volume.columns:
        return Signal(key=key, title=title, label="unknown", reason="시세 데이터 없음", detail={})

    close = price_volume["종가"].dropna()
    if len(close) < lookback + 1:
        return Signal(key=key, title=title, label="unknown", reason="데이터 부족", detail={})

    window = close.iloc[-(lookback + 1):-1]
    resistance = float(window.max())
    support = float(window.min())
    today = float(close.iloc[-1])

    detail = {f"최근{lookback}일_저항선": round(resistance, 2), f"최근{lookback}일_지지선": round(support, 2), "현재가": round(today, 2)}

    if today > resistance:
        return Signal(key=key, title=title, label="bullish",
                      reason=f"현재가({today:,.0f})가 최근 {lookback}거래일 저항선({resistance:,.0f})을 상향 돌파", detail=detail)
    if today < support:
        return Signal(key=key, title=title, label="bearish",
                      reason=f"현재가({today:,.0f})가 최근 {lookback}거래일 지지선({support:,.0f})을 하향 이탈", detail=detail)
    return Signal(key=key, title=title, label="neutral",
                  reason=f"박스권({support:,.0f}~{resistance:,.0f}) 내에서 움직이는 중 (현재가 {today:,.0f})", detail=detail)


def signal_volume_spike(price_volume: pd.DataFrame, window: int = 20, multiplier: float = 2.5) -> Signal:
    """⑥ 평균 거래량 대비 급증한 거래량을 동반한 양봉(매수 유입) / 음봉(투매) 여부."""
    key, title = "volume_spike", "거래량 급증 동반 양봉/음봉"
    needed = {"거래량", "종가", "시가"}
    if price_volume is None or price_volume.empty or not needed.issubset(price_volume.columns):
        return Signal(key=key, title=title, label="unknown", reason="시세·거래량 데이터 없음", detail={})

    df = price_volume.dropna(subset=list(needed))
    if len(df) < window + 1:
        return Signal(key=key, title=title, label="unknown", reason="데이터 부족", detail={})

    avg_vol = float(df["거래량"].iloc[-(window + 1):-1].mean())
    today_vol = float(df["거래량"].iloc[-1])
    ratio = today_vol / avg_vol if avg_vol else np.nan
    bullish_candle = bool(df["종가"].iloc[-1] > df["시가"].iloc[-1])
    bearish_candle = bool(df["종가"].iloc[-1] < df["시가"].iloc[-1])

    detail = {f"{window}일_평균거래량": round(avg_vol, 0), "당일_거래량": round(today_vol, 0),
               "거래량배율": round(ratio, 2) if not np.isnan(ratio) else None,
               "당일_양봉": bullish_candle, "당일_음봉": bearish_candle}

    if not np.isnan(ratio) and ratio >= multiplier and bullish_candle:
        return Signal(key=key, title=title, label="bullish",
                      reason=f"당일 거래량이 {window}일 평균의 {ratio:.1f}배로 급증하며 양봉 마감 — 신규 매수세 유입", detail=detail)
    if not np.isnan(ratio) and ratio >= multiplier and bearish_candle:
        return Signal(key=key, title=title, label="bearish",
                      reason=f"당일 거래량이 {window}일 평균의 {ratio:.1f}배로 급증하며 음봉 마감 — 투매성 매물 출회", detail=detail)
    return Signal(key=key, title=title, label="neutral",
                  reason=f"거래량 급증(평균 대비 {multiplier:.1f}배 이상)·뚜렷한 양봉/음봉 조건을 아직 충족하지 못함", detail=detail)


def signal_investor_twin_buy(investor: pd.DataFrame, min_days: int = TWIN_FLOW_MIN_DAYS) -> Signal:
    """⑦ 외국인+기관 N일 연속 동시 순매수(쌍끌이 매수) / 동시 순매도(쌍끌이 매도) 여부."""
    key, title = "investor_twin_buy", "외국인·기관 쌍끌이 매수/매도"
    if investor is None or investor.empty:
        return Signal(key=key, title=title, label="unknown", reason="투자자별 수급 데이터 없음 (KRX 로그인 필요)", detail={})

    needed = {"foreign", "institution"}
    if not needed.issubset(investor.columns):
        return Signal(key=key, title=title, label="unknown", reason="투자자 구분 데이터 불완전", detail={})

    df = investor[list(needed)].dropna()
    if df.empty:
        return Signal(key=key, title=title, label="unknown", reason="데이터 부족", detail={})

    buy_days = (df["foreign"] > 0) & (df["institution"] > 0)
    sell_days = (df["foreign"] < 0) & (df["institution"] < 0)

    def _tail_streak(mask: pd.Series) -> int:
        streak = 0
        for v in reversed(mask.tolist()):
            if v:
                streak += 1
            else:
                break
        return streak

    buy_streak = _tail_streak(buy_days)
    sell_streak = _tail_streak(sell_days)

    detail = {"연속_쌍끌이매수_일수": buy_streak, "연속_쌍끌이매도_일수": sell_streak, "기준일수": min_days}

    if buy_streak >= min_days:
        return Signal(key=key, title=title, label="bullish",
                      reason=f"외국인·기관이 {buy_streak}거래일 연속 동시 순매수 — 쌍끌이 매수로 추세적 상승 가능성 높음", detail=detail)
    if sell_streak >= min_days:
        return Signal(key=key, title=title, label="bearish",
                      reason=f"외국인·기관이 {sell_streak}거래일 연속 동시 순매도 — 쌍끌이 매도로 추세적 하락 가능성 높음", detail=detail)
    return Signal(key=key, title=title, label="neutral",
                  reason=f"외국인·기관 동시 매매 지속일수(매수 {buy_streak}일/매도 {sell_streak}일)가 기준({min_days}일)에 못 미침", detail=detail)


class Conclusion(TypedDict):
    verdict: Literal["strong_uptrend", "building", "neutral", "weakening", "strong_downtrend", "inconclusive"]
    verdict_label: str
    bullish_count: int
    bearish_count: int
    neutral_count: int
    total_known: int
    unknown_count: int
    reasons: list[str]
    as_of: str | None
    last_close: float | None
    prev_close: float | None
    change_pct: float | None


def conclude(signals: list[Signal], close: pd.Series | None = None) -> Conclusion:
    """상승/하락 신호를 종합해 최종 결론을 낸다.

    판정 기준:
      - strong_uptrend   : 7개 중 상승(bullish) 신호가 5개 이상
      - strong_downtrend : 7개 중 하락(bearish) 신호가 5개 이상
      - building         : 상승이 하락보다 많고, 상승 비율이 유효 지표의 40% 이상 (상승 초입)
      - weakening        : 하락이 상승보다 많고, 하락 비율이 유효 지표의 40% 이상 (하락 초입/진행 중)
      - neutral          : 그 외 — 신호가 뒤섞이거나 부족해 방향성 판단 보류
      - inconclusive     : 유효 데이터가 아예 없음
    """
    bull = [s for s in signals if s["label"] == "bullish"]
    bear = [s for s in signals if s["label"] == "bearish"]
    neutral = [s for s in signals if s["label"] == "neutral"]
    unknown = [s for s in signals if s["label"] == "unknown"]
    known_count = len(signals) - len(unknown)

    last_close = prev_close = change_pct = None
    as_of = None
    if close is not None and not close.dropna().empty:
        c = close.dropna()
        as_of = str(c.index[-1].date())
        last_close = float(c.iloc[-1])
        if len(c) >= 2:
            prev_close = float(c.iloc[-2])
            change_pct = (last_close - prev_close) / prev_close * 100

    verdict: Literal["strong_uptrend", "building", "neutral", "weakening", "strong_downtrend", "inconclusive"]
    if known_count == 0:
        verdict = "inconclusive"
        verdict_label = "판단 보류 — 유효 데이터 부족"
    elif len(bull) >= 5:
        verdict = "strong_uptrend"
        verdict_label = f"상승 추세 전환 신호 강함 (상승 {len(bull)}/하락 {len(bear)}, 총 {known_count}개 중)"
    elif len(bear) >= 5:
        verdict = "strong_downtrend"
        verdict_label = f"하락 추세 진행 신호 강함 (하락 {len(bear)}/상승 {len(bull)}, 총 {known_count}개 중)"
    elif len(bull) > len(bear) and len(bull) / known_count >= 0.4:
        verdict = "building"
        verdict_label = f"상승 초입 — 모멘텀 형성 중 (상승 {len(bull)}/하락 {len(bear)}, 총 {known_count}개 중)"
    elif len(bear) > len(bull) and len(bear) / known_count >= 0.4:
        verdict = "weakening"
        verdict_label = f"하락 초입 또는 진행 중 (하락 {len(bear)}/상승 {len(bull)}, 총 {known_count}개 중)"
    else:
        verdict = "neutral"
        verdict_label = f"방향성 불명확 — 신호가 뒤섞이거나 부족함 (상승 {len(bull)}/하락 {len(bear)}/중립 {len(neutral)})"

    reasons = [f"[{s['title']}] {s['reason']}" for s in signals if s["label"] != "unknown"]
    if unknown:
        reasons.append("참고: " + ", ".join(s["title"] for s in unknown) + " 지표는 데이터가 없어 판단에서 제외됨")

    return Conclusion(
        verdict=verdict,
        verdict_label=verdict_label,
        bullish_count=len(bull),
        bearish_count=len(bear),
        neutral_count=len(neutral),
        total_known=known_count,
        unknown_count=len(unknown),
        reasons=reasons,
        as_of=as_of,
        last_close=last_close,
        prev_close=prev_close,
        change_pct=change_pct,
    )
