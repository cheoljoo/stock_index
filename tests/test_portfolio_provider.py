"""국민연금 자산배분 파싱 테스트 — 네트워크를 쓰지 않는다."""
from datetime import date

import pytest

from stockindex.providers import nps_check, portfolio_provider as pp

SITE = """<h4 class="con-title">포트폴리오 개요 <p class="data-unit">( 2026년 9월 말 기준)</p></h4><p>전체자산 1663.7 조 원</p><script>columns : [
["금융부문", "1661.9"] ,["국내주식", "435.2"] ,["국내채권", "280.4"] ,["해외주식", "604.8"]
,["해외채권", "95.7"] ,["대체투자", "237.0"] ,["단기자금", "3.6"] ,["복지 ·기타 부문", "1.8"] ]</script>"""

CSV = """구분,현황(말잔_십억원),2026년 7월(십억 원),2025년(십억 원)
전체 자산(시장가),100,100,96
복지부문,1,1,1
금융부문(국내주식),24,24,22
금융부문(해외주식),36,36,34
금융부문(국내채권),17,17,19
금융부문(해외채권),6,6,6
금융부문(대체투자),14,14,13
금융부문(단기자금),1,1,1
기타부문,1,1,0
"""


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "_CHECK_LOG", tmp_path / "data_check.log")
    monkeypatch.setattr(pp, "_REJECTED", tmp_path / "rejected")
    return tmp_path


def _snap(domestic=20.0, total=1000.0):
    """국내주식 비중과 총액만 바꿀 수 있는 검사용 값."""
    weights = {"국내주식": domestic, "해외주식": 100 - domestic - 30, "국내채권": 30.0}
    return {k: (w, total * w / 100) for k, w in weights.items()}


def test_parse_site():
    ((d, amounts),) = pp.parse_site(SITE).items()
    assert d == date(2026, 9, 30) and "금융부문" not in amounts
    weights = {k: w for k, (w, _) in pp.to_snapshot(amounts).items()}
    assert weights["국내주식"] == pytest.approx(26.2, abs=0.1)
    assert sum(weights.values()) == pytest.approx(100, abs=0.1)


def test_parse_csv_month_and_year_end():
    snaps = pp.parse_csv(CSV)
    assert sorted(snaps) == [date(2025, 12, 31), date(2026, 7, 31)]
    assert snaps[date(2026, 7, 31)]["국내주식"] == 24 and snaps[date(2026, 7, 31)][pp.OTHER] == 2


@pytest.mark.parametrize("old,new", [
    ("구분,", "항목,"),                                   # 열 이름
    ("(십억 원)", "(조 원)"),                              # 단위
    ("금융부문(해외채권)", "금융부문(가상자산)"),            # 처음 보는 자산군
    ("24,24,22", "24,240,22"),                          # 합계 불일치
])
def test_csv_format_changes_are_rejected(old, new):
    with pytest.raises(ValueError):
        pp.parse_csv(CSV.replace(old, new))


@pytest.mark.parametrize("old,new", [
    ("포트폴리오 개요", "자산 현황"), ('["단기자금", "3.6"]', ""), ('"435.2"', '"43.5"'),
])
def test_site_format_changes_are_rejected(old, new):
    with pytest.raises(ValueError):
        pp.parse_site(SITE.replace(old, new))


def test_changed_past_value_is_not_overwritten():
    stored = {date(2025, 12, 31): _snap(20)}
    accepted, issues = nps_check.check(stored, {"a": {date(2025, 12, 31): _snap(23)}}, date(2026, 1, 31))
    assert accepted == {} and "과거 값이 바뀌었습니다" in issues[0]
    accepted, _ = nps_check.check(stored, {"a": {date(2025, 12, 31): _snap(23)}}, date(2026, 1, 31), accept=True)
    assert accepted


def test_big_jump_and_unit_error_are_rejected_but_normal_move_passes():
    stored = {date(2026, 8, 31): _snap(20)}
    sep = date(2026, 9, 30)
    for bad in (_snap(35), _snap(20, total=10_000)):
        accepted, issues = nps_check.check(stored, {"a": {sep: bad}}, date(2026, 11, 1))
        assert accepted == {} and "너무 크게" in issues[0]
    accepted, issues = nps_check.check(stored, {"a": {sep: _snap(23, total=1050)}}, date(2026, 11, 1))
    assert sep in accepted and issues == []


def test_sources_disagree_and_stale_data():
    d = date(2026, 9, 30)
    accepted, issues = nps_check.check({}, {"a": {d: _snap(20)}, "b": {d: _snap(25)}}, date(2026, 11, 1))
    assert accepted == {} and "두 출처" in issues[0]
    _, issues = nps_check.check({d: _snap(20)}, {}, date(2027, 6, 1))
    assert "못 읽고" in issues[0]


def test_one_source_failing_keeps_the_other_and_logs(_isolated, monkeypatch, capsys):
    monkeypatch.setattr(pp, "_download_site", lambda: "<html></html>")
    monkeypatch.setattr(pp, "_download_portal", lambda: CSV)
    assert pp.refresh(str(_isolated / "m.db")) == 2
    assert "코드 점검 필요: 기금운용본부" in capsys.readouterr().out
    assert "코드 점검 필요" in (_isolated / "data_check.log").read_text()
    assert list((_isolated / "rejected").glob("*_site.html"))


def test_network_error_does_not_ask_for_code_change(_isolated, monkeypatch, capsys):
    def down():
        raise ConnectionError("timeout")
    monkeypatch.setattr(pp, "_download_site", down)
    monkeypatch.setattr(pp, "_download_portal", down)
    assert pp.refresh(str(_isolated / "m.db")) == 0
    out = capsys.readouterr().out
    assert "접속 실패" in out and "코드 점검 필요" not in out
