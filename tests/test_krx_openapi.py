"""KRX Open API 경로 테스트 — 네트워크 호출은 가짜로 대체한다."""
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from stockindex.providers import krx_openapi as oa
from stockindex.providers import krx_provider as krx


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("KRX_CACHE_DIR", str(tmp_path / "krx_cache"))
    monkeypatch.setenv("KRX_OPENAPI_KEY", "test-key")
    monkeypatch.setenv("KRX_OPENAPI_MIN_INTERVAL", "0")
    monkeypatch.setattr(oa, "_stop", None)
    monkeypatch.setattr(oa, "_days", {})
    monkeypatch.setattr(oa, "_empty_seen", {})


def _row(code, close, diff):
    return {"ISU_CD": code, "TDD_OPNPRC": str(close), "TDD_HGPRC": str(close), "TDD_LWPRC": str(close),
            "TDD_CLSPRC": str(close), "ACC_TRDVOL": "100", "FLUC_RT": "0.0", "CMPPREVDD_PRC": str(diff)}


def _weekdays(n):
    out, d = [], date.today() - timedelta(days=30)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _fake_get(monkeypatch, by_date, status=200):
    calls = []

    def get(url, params, headers, timeout):
        calls.append((url.rsplit("/", 1)[-1], params["basDd"]))
        return SimpleNamespace(status_code=status,
                               json=lambda: {"OutBlock_1": by_date.get(params["basDd"], [])})

    monkeypatch.setattr(oa.requests, "get", get)
    return calls


def test_one_call_per_date_shared_by_all_tickers(monkeypatch):
    days = _weekdays(3)
    data = {d.strftime("%Y%m%d"): [_row("000001", 100, 0), _row("000002", 200, 0)] for d in days}
    calls = _fake_get(monkeypatch, data)
    a = krx.get_price_volume("000001", days[0], days[-1])
    n = len(calls)
    b = krx.get_price_volume("000002", days[0], days[-1])
    assert len(calls) == n                       # 두 번째 종목은 추가 호출 없음
    assert list(a.columns) == ["시가", "고가", "저가", "종가", "거래량", "등락률"]
    assert len(a) == len(b) == 3 and b["종가"].iloc[-1] == 200


def test_split_is_adjusted(monkeypatch):
    days = _weekdays(3)
    k = [d.strftime("%Y%m%d") for d in days]
    # 둘째 날 5:1 액면분할: 전일 종가 1000 → 기준가 200, 종가 210(+10)
    calls = _fake_get(monkeypatch, {k[0]: [_row("000001", 1000, 0)], k[1]: [_row("000001", 210, 10)],
                                    k[2]: [_row("000001", 220, 10)]})
    df = krx.get_price_volume("000001", days[0], days[-1])
    assert list(df["종가"]) == [200, 210, 220]
    assert list(df["거래량"]) == [500, 100, 100]


def test_unlisted_ticker_falls_back_to_pykrx(monkeypatch):
    days = _weekdays(2)
    _fake_get(monkeypatch, {d.strftime("%Y%m%d"): [_row("000001", 100, 0)] for d in days})
    assert oa.price_volume("999999", days[0], days[-1]) is None


def test_unauthorized_stops_calls_and_returns_none(monkeypatch):
    days = _weekdays(3)
    calls = _fake_get(monkeypatch, {}, status=401)
    assert oa.price_volume("000001", days[0], days[-1]) is None
    assert oa.price_volume("000001", days[0], days[-1]) is None
    assert len(calls) == 1 and not oa.available()


def test_no_key_means_no_calls(monkeypatch):
    monkeypatch.delenv("KRX_OPENAPI_KEY")
    calls = _fake_get(monkeypatch, {})
    assert oa.price_volume("000001", date.today() - timedelta(days=5), date.today()) is None
    assert calls == []


def test_names(monkeypatch):
    def get(url, params, headers, timeout):
        return SimpleNamespace(status_code=200, json=lambda: {"OutBlock_1": [
            {"ISU_SRT_CD": "005930", "ISU_ABBRV": "삼성전자"}]})
    monkeypatch.setattr(oa.requests, "get", get)
    assert krx.get_stock_name("005930") == "삼성전자"
