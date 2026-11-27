#!/usr/bin/env python3
"""국민연금 자산배분 자료를 받아 저장된 값과 비교한다.

  python scripts/check_nps.py            # 검사만 한다 (DB를 바꾸지 않음)
  python scripts/check_nps.py --accept   # 바뀐 값이 맞다고 확인한 뒤 DB에 반영한다
"""
from __future__ import annotations

import argparse

from stockindex.config.loader import load_settings
from stockindex.providers.portfolio_provider import refresh


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accept", action="store_true", help="검사에 걸린 값도 DB에 반영")
    args = parser.parse_args()
    count = refresh(load_settings().storage.db_path, accept=args.accept, write=args.accept)
    print(f"[nps] {'반영한' if args.accept else '검사를 통과한'} 기준일 {count}개")


if __name__ == "__main__":
    main()
