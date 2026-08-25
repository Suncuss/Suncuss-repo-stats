from collector import ha
from collector.estimate import alex_versions_from_rows, ha_estimate, rel_age_days

STATS = """2026-08-21 2026-08-14 2026-08-07 2026-07-31 Date
1000 900 800 700 Totals
123 68 - 140 birdnet-pipy
5 4 3 2 birdnet-go
"""


def test_parse_alex_stats_aligns_dates_and_skips_dashes():
    series = ha.parse_alex_stats(STATS, "birdnet-pipy")
    assert series == [{"date": "2026-07-31", "value": 140}, {"date": "2026-08-14", "value": 68},
                      {"date": "2026-08-21", "value": 123}]
    assert ha.parse_alex_stats(STATS, "missing") == []


def test_rel_age_days():
    assert rel_age_days("3 days ago") == 3
    assert rel_age_days("about 1 month ago") == 30
    assert rel_age_days("2 months ago") == 60
    assert rel_age_days("about 5 hours ago") == 0
    assert rel_age_days("yesterday") == 1
    assert rel_age_days(None) is None


def test_alex_versions_and_ha_estimate():
    rows = {"birdnet-pipy-amd64": [["a", 79, ["latest", "0.8.8"], "3 days ago"], ["b", 90, ["0.8.6"], "12 days ago"]],
            "birdnet-pipy-aarch64": [["c", 22, ["latest", "0.8.8"], "3 days ago"], ["d", 35, ["0.8.6"], "12 days ago"]]}
    versions = alex_versions_from_rows(rows)
    assert list(versions) == ["0.8.6", "0.8.8"]
    assert versions["0.8.6"] == {"total": 125, "age_days": 12, "amd64": 90, "aarch64": 35}
    est = ha_estimate({"total": 27, "versions": {"0.8.8": 19}, "auto_update": 5}, versions)
    assert est["pulls_base"] == 125 and est["estimated"] == 125 and est["opt_in_rate"] == 0.22
    # analytics wins when pulls data is missing
    assert ha_estimate({"total": 27}, {})["estimated"] == 27
