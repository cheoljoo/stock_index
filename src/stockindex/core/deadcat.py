"""데드캣 바운스(일시적 기술적 반등) 판별 로직.

박종훈의 지식한칼 영상에서 제시한 4가지 판별 기준을 코드화한다:
  1. 외국인/기관 수급 성격 — 숏커버링(공매도 청산)인지 실질 신규 매수인지
  2. 거래량 패턴 — 하락 대비 반등 시 거래량이 살아있는지
  3. 외국인 vs 기관 vs 개인 수급 조합 — 쌍끌이 매수인지 개인 단독 매수인지
  4. 글로벌 주도주(미국 빅테크) 동반 상승 여부

각 signal 함수는 {"label": "dead_cat"|"real_rebound"|"neutral", "reason": str, "detail": dict}를 반환한다.
데이터가 없으면 label="unknown"으로 표시해 최종 결론에서 제외한다.
"""
from __future__ import annotations
from typing import Literal, TypedDict
import numpy as np
import pandas as pd

SignalLabel = Literal["dead_cat", "real_rebound", "neutral", "unknown"]

# 진짜 반등으로 보기 위한 최소 지속기간(거래일) — 2~3주
REAL_REBOUND_MIN_DAYS = 10
# 숏커버링 판단 시 참고하는 최근 구간(거래일)
SHORT_WINDOW = 15


class Signal(TypedDict):
    key: str
    title: str
    label: SignalLabel
    reason: str
    detail: dict


def _recent(s: pd.Series, n: int) -> pd.Series:
    return s.dropna().iloc[-n:] if s is not None else pd.Series(dtype=float)


def find_recent_low(close: pd.Series, lookback: int = 40) -> tuple[pd.Timestamp | None, float | None]:
    """최근 lookback 거래일 중 저점(날짜, 종가)을 찾는다."""
    s = close.dropna().iloc[-lookback:]
    if s.empty:
        return None, None
    idx = s.idxmin()
    return idx, float(s.loc[idx])


def signal_short_covering(shorting: pd.DataFrame, investor: pd.DataFrame) -> Signal:
    """① 공매도 잔고 감소 + 외국인/기관 매수 → 숏커버링 여부."""
    key, title = "short_covering", "공매도·숏커버링 여부"
    if shorting is None or shorting.empty or "short_balance_ratio" not in shorting.columns:
        return Signal(key=key, title=title, label="unknown",
                       reason="공매도 잔고 데이터 없음 (KRX 로그인 필요)", detail={})

    bal = shorting["short_balance_ratio"].dropna()
    if len(bal) < 3:
        return Signal(key=key, title=title, label="unknown", reason="데이터 부족", detail={})

    recent_bal = _recent(bal, SHORT_WINDOW)
    bal_change = float(recent_bal.iloc[-1] - recent_bal.iloc[0])  # %p 변화

    net_buy_sum = None
    net_buy_days = 0
    if investor is not None and not investor.empty:
        cols = [c for c in ("foreign", "institution") if c in investor.columns]
        if cols:
            combined = investor[cols].sum(axis=1).dropna()
            recent_flow = _recent(combined, SHORT_WINDOW)
            net_buy_sum = float(recent_flow.sum())
            net_buy_days = int((recent_flow > 0).sum())

    detail = {
        "공매도잔고비중_변화(%p)": round(bal_change, 3),
        "외국인+기관_순매수합(원)": net_buy_sum,
        "순매수_일수": net_buy_days,
        "관찰기간(거래일)": len(recent_bal),
    }

    if bal_change < -0.05 and (net_buy_sum or 0) > 0 and net_buy_days < REAL_REBOUND_MIN_DAYS:
        return Signal(key=key, title=title, label="dead_cat",
                      reason=f"최근 {len(recent_bal)}거래일 공매도잔고비중이 {bal_change:+.2f}%p 감소하며 매수세가 유입됐지만, "
                             f"순매수 지속일수({net_buy_days}일)가 {REAL_REBOUND_MIN_DAYS}일에 못 미쳐 숏커버링 성격이 강함",
                      detail=detail)
    if (net_buy_sum or 0) > 0 and net_buy_days >= REAL_REBOUND_MIN_DAYS:
        return Signal(key=key, title=title, label="real_rebound",
                      reason=f"외국인+기관 순매수가 {net_buy_days}거래일 지속되어 공매도 청산 범위를 넘어서는 신규 매수로 판단됨",
                      detail=detail)
    return Signal(key=key, title=title, label="neutral",
                  reason="공매도 잔고·수급 변화가 뚜렷한 방향성을 보이지 않음", detail=detail)


def signal_volume_pattern(price_volume: pd.DataFrame, low_date: pd.Timestamp | None) -> Signal:
    """② 하락 구간 대비 반등 구간의 거래량 패턴."""
    key, title = "volume_pattern", "거래량 패턴"
    if price_volume is None or price_volume.empty or "거래량" not in price_volume.columns:
        return Signal(key=key, title=title, label="unknown", reason="거래량 데이터 없음", detail={})

    vol = price_volume["거래량"].dropna()
    if low_date is None or low_date not in vol.index or len(vol) < 6:
        return Signal(key=key, title=title, label="unknown", reason="저점 구간을 특정할 수 없음", detail={})

    pos = vol.index.get_loc(low_date)
    decline_window = vol.iloc[max(0, pos - 5):pos + 1]
    rebound_window = vol.iloc[pos + 1:pos + 6]

    if len(rebound_window) < 2 or decline_window.empty:
        return Signal(key=key, title=title, label="unknown", reason="반등 구간 거래일이 부족함(관찰 지속 필요)", detail={})

    decline_avg = float(decline_window.mean())
    rebound_avg = float(rebound_window.mean())
    ratio = rebound_avg / decline_avg if decline_avg else np.nan

    first_day_share = float(rebound_window.iloc[0] / rebound_window.sum()) if rebound_window.sum() else 0
    rebound_trend_up = rebound_window.iloc[-1] >= rebound_window.iloc[0] * 0.7

    detail = {
        "저점일": str(low_date.date()),
        "하락구간_평균거래량": round(decline_avg, 0),
        "반등구간_평균거래량": round(rebound_avg, 0),
        "반등/하락_거래량비": round(ratio, 2) if not np.isnan(ratio) else None,
        "반등첫날_거래량비중": round(first_day_share, 2),
    }

    if ratio < 0.6 or (first_day_share > 0.5 and not rebound_trend_up):
        return Signal(key=key, title=title, label="dead_cat",
                      reason=f"반등 구간 평균 거래량이 하락 구간의 {ratio:.0%}에 그치거나, "
                             f"반등 첫날 거래량({first_day_share:.0%})에만 쏠려 이후 급감 — 확신 없는 무거래량 반등",
                      detail=detail)
    if ratio >= 0.9 and rebound_trend_up:
        return Signal(key=key, title=title, label="real_rebound",
                      reason=f"반등 구간 거래량이 하락 구간 대비 {ratio:.0%} 수준으로 유지·증가 — 손바꿈 후 계단식 매수세",
                      detail=detail)
    return Signal(key=key, title=title, label="neutral", reason="거래량 패턴이 애매함 — 며칠 더 관찰 필요", detail=detail)


def signal_investor_combo(investor: pd.DataFrame) -> Signal:
    """③ 외국인 vs 기관 vs 개인 수급 조합."""
    key, title = "investor_combo", "투자자 수급 조합"
    if investor is None or investor.empty:
        return Signal(key=key, title=title, label="unknown",
                       reason="투자자별 수급 데이터 없음 (KRX 로그인 필요)", detail={})

    needed = {"foreign", "institution", "individual"}
    if not needed.issubset(investor.columns):
        return Signal(key=key, title=title, label="unknown", reason="투자자 구분 데이터 불완전", detail={})

    recent = investor[list(needed)].dropna().iloc[-SHORT_WINDOW:]
    if recent.empty:
        return Signal(key=key, title=title, label="unknown", reason="데이터 부족", detail={})

    foreign_sum = float(recent["foreign"].sum())
    inst_sum = float(recent["institution"].sum())
    indiv_sum = float(recent["individual"].sum())

    detail = {
        "외국인_순매수합(원)": foreign_sum,
        "기관_순매수합(원)": inst_sum,
        "개인_순매수합(원)": indiv_sum,
        "관찰기간(거래일)": len(recent),
    }

    twin_buy = foreign_sum > 0 and inst_sum > 0
    indiv_alone = indiv_sum > 0 and foreign_sum < 0 and inst_sum < 0

    if indiv_alone:
        return Signal(key=key, title=title, label="dead_cat",
                      reason="개인만 순매수를 지속하고 외국인·기관은 순매도 — 물타기/빚투 성격의 데드캣 바운스 패턴",
                      detail=detail)
    if twin_buy:
        return Signal(key=key, title=title, label="real_rebound",
                      reason="외국인·기관이 동시에 순매수하는 '쌍끌이 매수' — 추세 전환 가능성이 높은 조합",
                      detail=detail)
    return Signal(key=key, title=title, label="neutral", reason="투자자 주체 간 수급이 엇갈려 방향성이 불명확함", detail=detail)


def signal_global_correlation(kr_close: pd.Series, us_series_map: dict[str, pd.Series], window: int = 10) -> Signal:
    """④ 글로벌 주도주(미국 빅테크/나스닥) 동반 상승 여부."""
    key, title = "global_correlation", "글로벌 동조화"
    if kr_close is None or kr_close.dropna().empty or not us_series_map:
        return Signal(key=key, title=title, label="unknown", reason="비교할 글로벌 지수 데이터 없음", detail={})

    kr = kr_close.dropna()
    kr_ret = kr.pct_change().dropna().iloc[-window:]
    if kr_ret.empty:
        return Signal(key=key, title=title, label="unknown", reason="데이터 부족", detail={})

    corrs = {}
    us_up_count = 0
    for name, s in us_series_map.items():
        us = s.dropna()
        if us.empty:
            continue
        us_ret = us.pct_change().dropna()
        aligned = pd.concat([kr_ret, us_ret], axis=1, join="inner").dropna()
        if len(aligned) < 5:
            continue
        corr = float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
        corrs[name] = round(corr, 2)
        if float(us_ret.iloc[-window:].sum()) > 0:
            us_up_count += 1

    if not corrs:
        return Signal(key=key, title=title, label="unknown", reason="글로벌 지수와의 비교 데이터 부족", detail={})

    kr_up = float(kr_ret.sum()) > 0
    avg_corr = float(np.mean(list(corrs.values())))
    detail = {"상관계수": corrs, "평균상관계수": round(avg_corr, 2), "KR_최근수익률": round(float(kr_ret.sum()) * 100, 2)}

    if kr_up and us_up_count == len(corrs) and avg_corr > 0.3:
        return Signal(key=key, title=title, label="real_rebound",
                      reason=f"국내 반등이 미국 빅테크·나스닥 동반 상승과 함께 나타남 (평균 상관계수 {avg_corr:+.2f})",
                      detail=detail)
    if kr_up and (us_up_count == 0 or avg_corr < 0.1):
        return Signal(key=key, title=title, label="dead_cat",
                      reason=f"글로벌 주도주는 동반 상승하지 않는데 국내만 반등 (평균 상관계수 {avg_corr:+.2f}) — 국장 단독 기술적 반등 우려",
                      detail=detail)
    return Signal(key=key, title=title, label="neutral", reason="글로벌 지수와의 동조화가 뚜렷하지 않음", detail=detail)


class Conclusion(TypedDict):
    verdict: Literal["dead_cat_likely", "real_rebound_likely", "inconclusive"]
    verdict_label: str
    dead_cat_score: int
    real_rebound_score: int
    unknown_count: int
    reasons: list[str]
    as_of: str | None
    last_close: float | None
    prev_close: float | None
    change_pct: float | None


def conclude(signals: list[Signal], close: pd.Series | None = None) -> Conclusion:
    """어제 종가를 기준으로 데드캣 바운스 여부에 대한 최종 결론을 낸다."""
    dead = [s for s in signals if s["label"] == "dead_cat"]
    real = [s for s in signals if s["label"] == "real_rebound"]
    unknown = [s for s in signals if s["label"] == "unknown"]

    last_close = prev_close = change_pct = None
    as_of = None
    if close is not None and not close.dropna().empty:
        c = close.dropna()
        as_of = str(c.index[-1].date())
        last_close = float(c.iloc[-1])
        if len(c) >= 2:
            prev_close = float(c.iloc[-2])
            change_pct = (last_close - prev_close) / prev_close * 100

    known_count = len(signals) - len(unknown)
    if known_count == 0:
        verdict: Literal["dead_cat_likely", "real_rebound_likely", "inconclusive"] = "inconclusive"
        verdict_label = "판단 보류 — 유효 데이터 부족"
    elif len(dead) > len(real):
        verdict = "dead_cat_likely"
        verdict_label = "데드캣 바운스 가능성 높음 (일시적 반등 경계)"
    elif len(real) > len(dead):
        verdict = "real_rebound_likely"
        verdict_label = "진짜 반등 가능성 높음 (추세 전환 신호)"
    else:
        verdict = "inconclusive"
        verdict_label = "판단 보류 — 신호가 엇갈림"

    reasons = [f"[{s['title']}] {s['reason']}" for s in signals if s["label"] != "unknown"]
    if unknown:
        reasons.append(
            "참고: " + ", ".join(s["title"] for s in unknown) + " 지표는 데이터가 없어 판단에서 제외됨"
        )

    return Conclusion(
        verdict=verdict,
        verdict_label=verdict_label,
        dead_cat_score=len(dead),
        real_rebound_score=len(real),
        unknown_count=len(unknown),
        reasons=reasons,
        as_of=as_of,
        last_close=last_close,
        prev_close=prev_close,
        change_pct=change_pct,
    )
