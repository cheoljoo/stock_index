"""krx_provider 안전장치(throttle·캐시·차단감지·일일상한) 테스트 — 실제 KRX에는 접속하지 않는다."""
import json
import subprocess
import sys
import time
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from stockindex.providers import krx_provider as krx


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("KRX_CACHE_DIR", str(tmp_path / "krx_cache"))
    monkeypatch.delenv("KRX_OPENAPI_KEY", raising=False)
    monkeypatch.setenv("KRX_ID", "x")
    monkeypatch.setenv("KRX_PW", "y")
    monkeypatch.setenv("KRX_MIN_INTERVAL", "0")
    monkeypatch.setattr(krx, "_stop", None)
    monkeypatch.setattr(krx, "_last_call", 0.0)


def _ohlcv(s: str, e: str) -> pd.DataFrame:
    idx = pd.bdate_range(s, e)
    return pd.DataFrame({"종가": range(len(idx))}, index=idx)


class FakeKrx:
    def __init__(self, exc=None):
        self.calls = []
        self.exc = exc

    def get_market_ohlcv_by_date(self, s, e, ticker):
        self.calls.append((s, e))
        if self.exc:
            raise self.exc
        return _ohlcv(s, e)

    def get_market_trading_value_by_date(self, s, e, ticker):
        self.calls.append((s, e))
        if self.exc:
            raise self.exc
        idx = pd.bdate_range(s, e)
        return pd.DataFrame({"외국인합계": 1, "기관합계": 2, "개인": 3}, index=idx)


def _use(monkeypatch, fake):
    monkeypatch.setattr(krx, "_stock_api", lambda: fake)


def test_cache_fetches_only_missing_range(monkeypatch):
    fake = FakeKrx()
    _use(monkeypatch, fake)
    end = date.today() - timedelta(days=10)
    start = end - timedelta(days=20)
    df1 = krx.get_price_volume("005930", start, end)
    assert len(fake.calls) == 1 and not df1.empty
    krx.get_price_volume("005930", start, end)            # 같은 구간 → 네트워크 없음
    assert len(fake.calls) == 1
    krx.get_price_volume("005930", start, end + timedelta(days=5))   # 뒤쪽만 증분
    assert len(fake.calls) == 2
    s2, e2 = fake.calls[1]
    assert s2 == (end + timedelta(days=1)).strftime("%Y%m%d")
    assert e2 == (end + timedelta(days=5)).strftime("%Y%m%d")
    krx.get_price_volume("005930", start - timedelta(days=7), end)   # 앞쪽만 증분
    assert len(fake.calls) == 3 and fake.calls[2][1] == (start - timedelta(days=1)).strftime("%Y%m%d")


def test_today_data_refetched_at_most_once_per_day(monkeypatch):
    fake = FakeKrx()
    _use(monkeypatch, fake)
    today = date.today()
    krx.get_investor_trading("005930", today - timedelta(days=10), today)
    n = len(fake.calls)
    krx.get_investor_trading("005930", today - timedelta(days=10), today)
    assert len(fake.calls) == n


def test_failure_is_not_cached_as_empty(monkeypatch):
    fake = FakeKrx(exc=ValueError("boom"))
    _use(monkeypatch, fake)
    end = date.today() - timedelta(days=5)
    assert krx.get_price_volume("005930", end - timedelta(days=5), end).empty
    fake.exc = None
    assert not krx.get_price_volume("005930", end - timedelta(days=5), end).empty
    assert len(fake.calls) == 2


def test_block_detected_stops_all_further_calls_and_persists(monkeypatch, tmp_path):
    fake = FakeKrx(exc=json.JSONDecodeError("Expecting value", "<html>", 0))
    _use(monkeypatch, fake)
    end = date.today() - timedelta(days=5)
    assert krx.get_price_volume("005930", end - timedelta(days=5), end).empty
    assert krx.stop_reason() and "차단" in krx.stop_reason()
    assert (tmp_path / "krx_block.json").exists()
    n = len(fake.calls)
    krx.get_price_volume("000660", end - timedelta(days=5), end)
    krx.get_investor_trading("000660", end - timedelta(days=5), end)
    assert len(fake.calls) == n                               # 더 이상 KRX를 두드리지 않는다
    ok, msg = krx.check_krx_login()
    assert ok is False and "차단" in msg


def test_block_file_expires(monkeypatch, tmp_path):
    (tmp_path / "krx_block.json").write_text(json.dumps(
        {"blocked_until": (pd.Timestamp.now() - pd.Timedelta(hours=1)).isoformat(), "reason": "old"}))
    assert krx.stop_reason() is None


def test_http_403_counts_as_block(monkeypatch):
    import requests
    resp = requests.Response()
    resp.status_code = 403
    fake = FakeKrx(exc=requests.exceptions.HTTPError(response=resp))
    _use(monkeypatch, fake)
    end = date.today() - timedelta(days=5)
    krx.get_price_volume("005930", end - timedelta(days=5), end)
    assert krx.stop_reason()


def test_daily_call_budget(monkeypatch):
    monkeypatch.setenv("KRX_MAX_CALLS_PER_DAY", "2")
    fake = FakeKrx()
    _use(monkeypatch, fake)
    end = date.today() - timedelta(days=5)
    for t in ["000001", "000002", "000003", "000004"]:
        krx.get_price_volume(t, end - timedelta(days=5), end)
    assert len(fake.calls) == 2
    assert "상한" in krx.stop_reason()


def test_min_interval_enforced(monkeypatch):
    monkeypatch.setenv("KRX_MIN_INTERVAL", "0.2")
    fake = FakeKrx()
    _use(monkeypatch, fake)
    end = date.today() - timedelta(days=5)
    t0 = time.monotonic()
    for t in ["000001", "000002", "000003"]:
        krx.get_price_volume(t, end - timedelta(days=5), end)
    assert time.monotonic() - t0 >= 0.4 - 0.05                # 첫 호출은 즉시, 이후 2번이 0.2초 이상씩


def test_import_does_not_login():
    """모듈 import만으로는 pykrx(=KRX 로그인)가 로드되지 않아야 한다."""
    out = subprocess.run(
        [sys.executable, "-I", "-c",
         "import sys; from stockindex.providers import krx_provider; print('pykrx' in sys.modules)"],
        capture_output=True, text=True, env={"PATH": "", "PYTHONPATH": ":".join(sys.path)},
    )
    assert out.stdout.strip() == "False", out.stderr


def test_unauthenticated_makes_no_calls(monkeypatch):
    monkeypatch.delenv("KRX_ID")
    fake = FakeKrx()
    _use(monkeypatch, fake)
    end = date.today() - timedelta(days=5)
    assert krx.get_investor_trading("005930", end - timedelta(days=5), end).empty
    assert fake.calls == []
