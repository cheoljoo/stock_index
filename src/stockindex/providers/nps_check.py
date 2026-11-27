"""받아온 국민연금 자산배분이 믿을 만한지 검사한다. 걸린 값은 저장하지 않고 저장돼 있던 값을 지킨다.

값은 {기준일: {자산군: (비중 %, 금액 십억 원)}} 형태다.
1. 같은 기준일인데 두 출처가 다르다
2. 이미 저장한 과거 값이 바뀌었다
3. 새 값이 직전 기준일과 너무 크게 다르다 (경과 개월 수만큼 허용 폭이 넓어진다)
4. 새 자료가 오래 들어오지 않는다 (예전 값만 계속 읽히는 경우)
"""
from __future__ import annotations

from datetime import date

SAME_WEIGHT_PP = 0.3      # 같은 기준일에서 허용하는 비중 차이(%p): 반올림·잠정치 정정 수준
SAME_TOTAL_RATIO = 0.01   # 같은 기준일에서 허용하는 총액 차이
STALE_DAYS = 120          # 월말 값은 보통 두 달 안에 공개된다


def jump_limits(months: int) -> tuple[float, float]:
    """직전 기준일과의 허용 폭: (비중 %p, 총액 변화율). 실제 2021~2026 값은 모두 이 안에 있다."""
    return min(5 + months, 20), 0.15 + 0.03 * months


def _total(snapshot: dict) -> float:
    return sum(amount for _, amount in snapshot.values())


def same_date_diff(old: dict, new: dict) -> str | None:
    """같은 기준일의 두 값이 어긋나면 설명을, 아니면 None."""
    changed = []
    for asset in sorted(set(old) | set(new)):
        a, b = old.get(asset, (0.0, 0.0))[0], new.get(asset, (0.0, 0.0))[0]
        if abs(a - b) > SAME_WEIGHT_PP:
            changed.append(f"{asset} {a:.2f}%→{b:.2f}%")
    ratio = _total(new) / _total(old) - 1
    if abs(ratio) > SAME_TOTAL_RATIO:
        changed.append(f"총액 {ratio:+.1%}")
    return ", ".join(changed) or None


def jump_diff(prev_date: date, prev: dict, new_date: date, new: dict) -> str | None:
    months = max(1, (new_date.year - prev_date.year) * 12 + new_date.month - prev_date.month)
    weight_limit, total_limit = jump_limits(months)
    big = [f"{a} {prev[a][0]:.1f}%→{new[a][0]:.1f}%" for a in new
           if a in prev and abs(new[a][0] - prev[a][0]) > weight_limit]
    ratio = _total(new) / _total(prev) - 1
    if abs(ratio) > total_limit:
        big.append(f"총액 {ratio:+.1%}")
    return ", ".join(big) or None


def check(stored: dict, sources: dict, today: date, accept: bool = False) -> tuple[dict, list[str]]:
    """저장해도 되는 값과 문제 설명을 돌려준다.

    Args:
        stored: 저장돼 있는 값.
        sources: {출처 이름: 받아온 값}. 같은 기준일이면 뒤의 출처(더 정밀한 CSV)를 쓴다.
        accept: 사람이 확인한 뒤 받아들일 때. 문제는 알려 주되 모두 저장한다.
    """
    issues: list[str] = []
    candidates: dict = {}
    rejected: set = set()
    seen: dict = {}
    for label, snapshots in sources.items():
        for d, snapshot in snapshots.items():
            if d > today:
                issues.append(f"{d} 기준일이 미래입니다 ({label})")
                rejected.add(d)
            if d in candidates:
                diff = same_date_diff(candidates[d], snapshot)
                if diff:
                    issues.append(f"{d} 두 출처의 값이 다릅니다 ({seen[d]} / {label}): {diff}")
                    rejected.add(d)
            candidates[d], seen[d] = snapshot, label

    accepted: dict = {}
    known = dict(stored)
    for d in sorted(candidates):
        new = candidates[d]
        problem = None
        if d in stored:
            diff = same_date_diff(stored[d], new)
            problem = diff and f"{d} 저장해 둔 과거 값이 바뀌었습니다 ({seen[d]}): {diff}"
        else:
            earlier = [k for k in known if k < d]
            if earlier:
                p = max(earlier)
                diff = jump_diff(p, known[p], d, new)
                problem = diff and f"{d} 값이 직전({p})보다 너무 크게 달라졌습니다 ({seen[d]}): {diff}"
        if problem:
            issues.append(problem)
        if accept or (not problem and d not in rejected):
            accepted[d] = known[d] = new

    latest = max(set(stored) | set(accepted), default=None)
    if latest and (today - latest).days > STALE_DAYS:
        issues.append(f"가장 최근 자료가 {latest} 기준입니다 ({(today - latest).days}일 전) — 새 자료를 못 읽고 있을 수 있습니다")
    return accepted, issues
