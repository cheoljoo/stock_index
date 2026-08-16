#!/usr/bin/env python3
"""KOSPI200 외국인·기관 수급 스크리너를 지금 바로 실행한다 (cron을 기다리지 않을 때 사용).

대시보드(Streamlit) 안에서 직접 스캔 버튼을 눌러 실행하게 했더니, 여러 종목을 연달아
빠르게 KRX에 실시간 조회하는 패턴이 streamlit 프로세스를 세그폴트(SIGSEGV)로 죽이는
문제가 있어(공유 대시보드 전체가 같이 죽음) 버튼을 없애고 이 스크립트로 뺐다. 별도
프로세스라 여기서 죽어도 대시보드에는 영향이 없다.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[1] / ".env")

from datetime import date
from stockindex.config.loader import load_settings
from stockindex.core.screener import screen_kospi200, screen_ownership_kospi200
from stockindex.storage import db as _db


def _print_progress(done: int, total: int, name: str) -> None:
    print(f"  ({done}/{total}) {name}...", end="\r")


def main():
    settings = load_settings()
    db_path = settings.storage.db_path
    today = date.today()
    _db.init_db(db_path)

    print("=== 동반매수/매도 연속일수 스크리너 ===")
    run = screen_kospi200(min_days=settings.screener.min_days, on_progress=_print_progress)
    print()
    if not run.is_full_kospi200 and run.universe_size:
        print(f"⚠️ KOSPI200 정식 API 조회 실패 — 대형주 근사 리스트({run.universe_size}종목)로 대체")
    _db.save_screen_run(db_path, today, run.universe_size, run.is_full_kospi200)
    if run.results:
        _db.save_investor_flow_screen(db_path, today, run.results)
        print(f"[screener] {len(run.results)}/{run.universe_size} stock(s) with >= {settings.screener.min_days}d streak")
        for r in run.results:
            print(f"  {r.name}({r.ticker}) 동반매수={r.twin_buy_streak} 동반매도={r.twin_sell_streak} "
                  f"외국인단독={r.foreign_only_buy_streak} 현재가={r.latest_close}")
    else:
        print("[screener] no results (KRX 로그인 미설정이거나 조건 충족 종목 없음)")

    print("\n=== 외국인 지분율 지속증가/일시급증 스크리너 ===")
    screener_cfg = settings.screener
    own_run = screen_ownership_kospi200(
        lookback_days=screener_cfg.ownership_lookback_days,
        steady_min_change=screener_cfg.ownership_steady_min_change_pct,
        steady_min_up_ratio=screener_cfg.ownership_steady_min_up_ratio,
        spike_min_daily_change=screener_cfg.ownership_spike_min_daily_change_pct,
        on_progress=_print_progress,
    )
    print()
    if not own_run.is_full_kospi200 and own_run.universe_size:
        print(f"⚠️ KOSPI200 정식 API 조회 실패 — 대형주 근사 리스트({own_run.universe_size}종목)로 대체")
    _db.save_ownership_screen_run(db_path, today, own_run.universe_size, own_run.is_full_kospi200)
    if own_run.results:
        _db.save_ownership_screen(db_path, today, own_run.results)
        print(f"[ownership] {len(own_run.results)}/{own_run.universe_size} stock(s)")
        for r in own_run.results:
            tag = "지속증가" if r.is_steady_increase else ("급증" if r.is_spike else "")
            print(f"  {r.name}({r.ticker}) [{tag}] {r.change_pct_points:+.3f}%p "
                  f"(상승일비율={r.up_day_ratio:.0%}, 최대일간={r.max_daily_jump:+.3f}%p) "
                  f"현재지분율={r.latest_ratio:.2f}% 현재가={r.latest_close}")
    else:
        print("[ownership] no results (KRX 로그인 미설정이거나 조건 충족 종목 없음)")


if __name__ == "__main__":
    main()
