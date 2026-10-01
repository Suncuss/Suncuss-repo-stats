from collector import estimate


def reg_entry(kind, children):
    return {"kind": kind, "children": [{"digest": f"sha256:{d}", "arch": a} for d, a in children]}


REGISTRY = {
    # build 1: arm64 p1 + amd64 p2, tagged twice (main + staging indexes) and a per-arch pidx
    "i1": reg_entry("index", [("p1", "arm64"), ("p2", "amd64"), ("t1", "attest")]),
    "i2": reg_entry("index", [("p1", "arm64"), ("p2", "amd64"), ("t1", "attest")]),
    "x1": reg_entry("pidx", [("p1", "arm64"), ("t1", "attest")]),
    "p1": {"kind": "manifest", "arch": "arm64", "created": "2026-08-08T20:11:00"},
    "p2": {"kind": "manifest", "arch": "amd64", "created": "2026-08-08T20:12:00"},
    "t1": {"kind": "attest"},
    # build 2: new arm64 p3, amd64 p4
    "i3": reg_entry("index", [("p3", "arm64"), ("p4", "amd64")]),
    "p3": {"kind": "manifest", "arch": "arm64", "created": "2026-08-21T04:22:00"},
    "p4": {"kind": "manifest", "arch": "amd64", "created": "2026-08-21T04:22:30"},
}
RUNS = [{"created": "2026-08-08T20:00:00", "branch": "main"}, {"created": "2026-08-08T20:01:00", "branch": "staging"},
        {"created": "2026-08-21T04:05:00", "branch": "main"}]
TAGS = [{"name": "v0.8.6", "date": "2026-08-08"}, {"name": "v0.8.8", "date": "2026-08-21"}]
COUNTS = {"i1": 254, "i2": 11, "x1": 1, "p1": 124, "p2": 54, "t1": 100, "i3": 15, "p3": 14, "p4": 6}


def test_build_batches_merges_indexes_sharing_platforms():
    batches = estimate.build_batches(REGISTRY)
    assert [b["created"] for b in batches] == ["2026-08-08T20:11:00", "2026-08-21T04:22:00"]
    assert batches[0]["indexes"] == ["i1", "i2", "x1"]
    assert batches[0]["platforms"] == {"p1": "arm64", "p2": "amd64"}
    c = estimate.batch_counts(batches[0], COUNTS)
    assert c == {"index": 266, "attest": 100, "arch": {"amd64": 54, "arm64": 124}, "pulls": 178}


def test_attribute_and_releases():
    batches = estimate.attribute(estimate.build_batches(REGISTRY), RUNS, TAGS)
    assert batches[0]["channel"] == "main" and batches[0]["release"] == "v0.8.6" and batches[0]["branches"] == ["main", "staging"]
    assert batches[1]["release"] == "v0.8.8" and batches[1]["branches"] == ["main"]
    stats = {b["id"]: estimate.batch_stats(b, COUNTS) for b in batches}
    rels = estimate.releases_from_batches(batches, stats, "2026-08-24")
    assert [r["release"] for r in rels] == ["v0.8.6", "v0.8.8"]
    assert rels[0]["pulls"] == 178 and rels[0]["mixed"] is True and rels[0]["days_live"] == 12.3
    assert rels[1]["current"] is True and rels[1]["pulls"] == 20


def test_cohort_model_drains_proportionally():
    builds = [{"key": "v1", "created": "2026-06-01T00:00:00", "pulls": 103},
              {"key": "v2", "created": "2026-08-08T00:00:00", "pulls": 53},
              {"key": "v3", "created": "2026-08-21T00:00:00", "pulls": 23}]
    m = estimate.cohort_model(builds, own_stations=3, today="2026-08-24", active_days=90)
    # v1: 100 stations; v2: 50 updaters drained from v1 -> v1 50, v2 50;
    # v3: 20 updaters drained proportionally (10 from each) -> v1 40, v2 40, v3 20
    assert m["on_build"] == {"v1": 40, "v2": 40, "v3": 20}
    assert m["active"] == 100 and m["not_updating"] == 0 and m["pulled"] == 170
    # dormancy runs from when a build was replaced, not when it was built: v1 was current until 08-08
    assert estimate.cohort_model(builds, own_stations=3, today="2026-09-15")["not_updating"] == 0
    old = estimate.cohort_model(builds, own_stations=3, today="2026-11-10", active_days=90)
    assert old["not_updating"] == 40 and old["active"] == 60 and old["pulled"] == 70


def test_cohort_model_new_stations_beyond_pool():
    builds = [{"key": "a", "created": "2026-08-01T00:00:00", "pulls": 10},
              {"key": "b", "created": "2026-08-10T00:00:00", "pulls": 30}]
    m = estimate.cohort_model(builds, own_stations=0, today="2026-08-24")
    assert m["on_build"] == {"b": 30} and m["active"] == 30


def test_cohort_counts_untagged_rebuilds_as_their_own_wave():
    # The same 20 stations update to a release and then to an untagged main
    # push of it: per build that is 20 stations, not 40.
    builds = [{"key": "rel", "created": "2026-08-21T00:00:00", "pulls": 20},
              {"key": "push", "created": "2026-09-05T00:00:00", "pulls": 20}]
    assert estimate.cohort_model(builds, own_stations=0, today="2026-09-20")["active"] == 20


def test_self_hosted_model_sums_channels_and_maps_releases():
    batches = [{"id": "m1", "created": "2026-09-05T19:10:44", "channel": "main", "release": "v0.8.8"},
               {"id": "m2", "created": "2026-09-20T23:46:07", "channel": "main", "release": "v0.8.10"},
               {"id": "s1", "created": "2026-09-12T21:02:10", "channel": "staging", "release": None},
               {"id": "u1", "created": "2026-09-12T21:02:10", "channel": "unknown", "release": None},
               {"id": "m3", "created": "2026-10-02T00:00:00", "channel": "main", "release": "v0.8.11"}]
    pulls = {"m1": {"arm64": 21}, "m2": {"arm64": 9, "amd64": 2}, "s1": {"arm64": 12}, "u1": {"arm64": 50}, "m3": {"arm64": 9}}
    m = estimate.self_hosted_model(batches, pulls, "2026-10-01", own_stations=1, min_share=0.5)
    # main: 20 on m1, then 10 drained to m2; staging 12; unknown and future builds ignored
    assert m["on_release"] == {"v0.8.8": 10, "v0.8.10": 10, "staging": 12}
    assert m["active"] == 32 and m["channels"] == {"main": 20, "staging": 12}
    assert m["high"] == 42  # 64 at half the stations per wave, capped by the 42 pulls seen


def test_same_day_releases_use_commit_time_and_version_order():
    tags = [{"name": "v0.8.10", "date": "2026-09-20", "time": "2026-09-20T23:45:14"},
            {"name": "v0.8.9", "date": "2026-09-20", "time": "2026-09-20T04:30:15"}]
    reg = {"i1": reg_entry("index", [("p1", "arm64")]), "p1": {"kind": "manifest", "arch": "arm64", "created": "2026-09-20T04:30:46"},
           "i2": reg_entry("index", [("p2", "arm64")]), "p2": {"kind": "manifest", "arch": "arm64", "created": "2026-09-20T23:46:07"}}
    runs = [{"created": "2026-09-20T04:30:00", "branch": "main"}, {"created": "2026-09-20T23:45:31", "branch": "main"}]
    assert [b["release"] for b in estimate.attribute(estimate.build_batches(reg), runs, tags)] == ["v0.8.9", "v0.8.10"]
    # without commit times, same-day tags still order by version, not as strings
    dated = [{k: v for k, v in t.items() if k != "time"} for t in tags]
    assert [t["name"] for t in estimate.sort_tags(dated)] == ["v0.8.9", "v0.8.10"]


def test_automated_share_from_backend_surplus():
    # compose pull: backend 3x frontend; station update: 1:1
    assert estimate.automated_share({"amd64": 6, "arm64": 15}, {"amd64": 18, "arm64": 39}) == {"amd64": 6.0, "arm64": 12.0}
    assert estimate.automated_share({"arm64": 10}, {"arm64": 10}) == {"arm64": 0.0}
    assert estimate.automated_share({"arm64": 10}, {"arm64": 4}) == {"arm64": 0.0}
    assert estimate.automated_share({"arm64": 10}, {"arm64": 90}) == {"arm64": 10}


def test_level_off_takes_from_the_top():
    assert estimate.level_off({"a": 20, "b": 5, "c": 3}, 10) == {"a": 10}
    assert estimate.level_off({"a": 20, "b": 5, "c": 3}, 18) == {"a": 16.5, "b": 1.5}
    assert estimate.level_off({"a": 2, "b": 1}, 5) == {"a": 2, "b": 1}
    assert estimate.level_off({"a": 2}, 0) == {}


def test_station_pulls_removes_compose_pulls_day_by_day():
    batches = [{"id": "A", "platforms": {"fa": "arm64"}}, {"id": "B", "platforms": {"fb": "arm64"}}]
    f_plat = {"fa": ("arm64", "2026-09-01T00:00:00"), "fb": ("arm64", "2026-09-10T00:00:00")}
    b_plat = {"ba": ("arm64", "2026-09-01T00:00:00")}
    f_snaps = [("2026-09-08", {"fa": 10}),
               ("2026-09-09", {"fa": 18}),            # 3 updates + 5 compose pulls
               ("2026-09-11", {"fa": 19, "fb": 6})]   # 1 update on A; 2 updates + 4 compose pulls on B
    b_snaps = [("2026-09-08", {"ba": 10}), ("2026-09-09", {"ba": 28}), ("2026-09-11", {"ba": 43})]
    out = estimate.station_pulls(batches, f_snaps, f_plat, b_snaps, b_plat)
    assert out[0]["automated"] == {} and out[0]["day"] is None
    assert out[1]["day"]["automated"] == {"A": {"arm64": 5.0}}
    assert out[2]["day"]["automated"] == {"B": {"arm64": 4.0}}
    assert out[2]["raw"] == {"A": {"arm64": 19}, "B": {"arm64": 6}}
    assert out[2]["automated"] == {"A": {"arm64": 5.0}, "B": {"arm64": 4.0}}


def test_station_pulls_skips_days_without_a_matching_backend_snapshot():
    batches = [{"id": "A", "platforms": {"fa": "arm64"}}]
    f_plat, b_plat = {"fa": ("arm64", "2026-09-01T00:00:00")}, {"ba": ("arm64", "2026-09-01T00:00:00")}
    f_snaps = [("2026-09-08", {"fa": 10}), ("2026-09-09", {"fa": 15}), ("2026-09-10", {"fa": 20})]
    b_snaps = [("2026-09-08", {"ba": 10}), ("2026-09-10", {"ba": 40})]  # 09-09 missing
    out = estimate.station_pulls(batches, f_snaps, f_plat, b_snaps, b_plat)
    # 09-09 has no backend counts; 09-10's backend delta spans two days, so neither day is compared
    assert out[1]["day"]["automated"] == {} and out[2]["day"]["automated"] == {}


def test_station_pulls_splits_history_before_first_snapshot():
    batches = [{"id": "old", "platforms": {"fo": "arm64"}}, {"id": "A", "platforms": {"fa": "arm64"}},
               {"id": "B", "platforms": {"fb": "arm64"}}]
    f_plat = {"fo": ("arm64", "2026-03-01T00:00:00"), "fa": ("arm64", "2026-08-01T00:00:00"), "fb": ("arm64", "2026-08-10T00:00:00")}
    b_plat = {"bo": ("arm64", "2026-03-01T00:00:00"), "ba": ("arm64", "2026-08-01T00:00:00")}
    # since 2026-04-09: frontend 60 + 10, backend 120 -> (120 - 70) / 2 = 25 automated, taken off the top
    out = estimate.station_pulls(batches, [("2026-08-25", {"fo": 300, "fa": 60, "fb": 10})], f_plat,
                                 [("2026-08-25", {"bo": 900, "ba": 120})], b_plat)
    assert out[0]["raw"] == {"old": {"arm64": 300}, "A": {"arm64": 60}, "B": {"arm64": 10}}
    assert out[0]["automated"] == {"A": {"arm64": 25.0}}


def test_ha_estimate_range():
    alex = {"0.8.8": {"total": 159, "age_days": 30}, "0.8.10": {"total": 113, "age_days": 7}, "0.8.11": {"total": 5, "age_days": 0}}
    entry = {"total": 25, "auto_update": 5, "versions": {"0.7.5": 1, "0.8.10": 20, "0.8.4": 1, "0.8.8": 3}}
    e = estimate.ha_estimate(entry, alex)
    assert (e["estimated"], e["low"], e["high"], e["opt_in_rate"]) == (159, 113, 173, 0.16)
    # analytics alone when no add-on version is old enough yet
    assert estimate.ha_estimate(entry, {"0.8.11": {"total": 5, "age_days": 0}})["estimated"] == 25


def test_attribute_prefers_tag_evidence_over_run_proximity():
    reg = dict(REGISTRY)
    # a staging build pushed in the same minute as the v0.8.8 main build, different content
    reg["i9"] = reg_entry("index", [("p9", "arm64"), ("p10", "amd64")])
    reg["p9"] = {"kind": "manifest", "arch": "arm64", "created": "2026-08-21T04:23:00"}
    reg["p10"] = {"kind": "manifest", "arch": "amd64", "created": "2026-08-21T04:23:10"}
    runs = RUNS + [{"created": "2026-08-21T04:05:30", "branch": "staging"}]
    no_evidence = estimate.attribute(estimate.build_batches(reg), runs, TAGS)
    assert [b["channel"] for b in no_evidence] == ["main", "main", "main"]  # ambiguous without tags
    with_evidence = estimate.attribute(estimate.build_batches(reg), runs, TAGS, {"i3": {"main"}, "i9": {"staging"}})
    assert [(b["channel"], b["evidence"]) for b in with_evidence] == [("main", "run"), ("main", "tag"), ("staging", "tag")]
    # evidence on one batch demotes the proximity-only sibling even without a staging tag
    demoted = estimate.attribute(estimate.build_batches(reg), runs, TAGS, {"i3": {"main"}})
    assert [b["channel"] for b in demoted] == ["main", "main", "staging"]


def test_attribute_picks_the_clearly_nearer_run():
    # v0.8.9: staging and main runs five minutes apart, each followed by its own build
    reg = {"i1": reg_entry("index", [("p1", "arm64")]), "p1": {"kind": "manifest", "arch": "arm64", "created": "2026-09-20T04:30:46"},
           "i2": reg_entry("index", [("p2", "arm64")]), "p2": {"kind": "manifest", "arch": "arm64", "created": "2026-09-20T04:36:19"}}
    runs = [{"created": "2026-09-20T04:30:19", "branch": "staging"}, {"created": "2026-09-20T04:35:51", "branch": "main"}]
    tags = [{"name": "v0.8.9", "date": "2026-09-20", "time": "2026-09-20T04:30:15"}]
    batches = estimate.attribute(estimate.build_batches(reg), runs, tags)
    assert [(b["channel"], b["ambiguous"]) for b in batches] == [("staging", False), ("main", False)]
    rels = estimate.releases_from_batches(batches, {b["id"]: estimate.batch_stats(b, {}) for b in batches}, "2026-09-21")
    assert rels[0]["mixed"] is False and rels[0]["batches"] == 1


def test_batch_with_two_manifests_for_one_arch():
    reg = {"i1": reg_entry("index", [("a1", "arm64"), ("b1", "amd64")]),
           "i2": reg_entry("index", [("a1", "arm64"), ("b2", "amd64")]),
           "a1": {"kind": "manifest", "arch": "arm64", "created": "2026-08-17T02:38:00"},
           "b1": {"kind": "manifest", "arch": "amd64", "created": "2026-08-17T02:38:00"},
           "b2": {"kind": "manifest", "arch": "amd64", "created": "2026-08-17T02:40:00"}}
    batches = estimate.build_batches(reg)
    assert len(batches) == 1 and batches[0]["platforms"] == {"a1": "arm64", "b1": "amd64", "b2": "amd64"}
    assert estimate.batch_counts(batches[0], {"a1": 68, "b1": 10, "b2": 21})["arch"] == {"amd64": 31, "arm64": 68}
