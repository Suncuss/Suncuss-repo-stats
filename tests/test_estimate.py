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
    rels = estimate.releases_from_batches(batches, COUNTS, "2026-08-24")
    assert [r["release"] for r in rels] == ["v0.8.6", "v0.8.8"]
    assert rels[0]["pulls"] == 178 and rels[0]["mixed"] is True and rels[0]["days_live"] == 12.3
    assert rels[1]["current"] is True and rels[1]["pulls"] == 20


def test_cohort_model_drains_proportionally():
    rels = [{"release": "v1", "created": "2026-06-01T00:00:00", "pulls": 103},
            {"release": "v2", "created": "2026-08-08T00:00:00", "pulls": 53},
            {"release": "v3", "created": "2026-08-21T00:00:00", "pulls": 23}]
    m = estimate.cohort_model(rels, own_stations=3, today="2026-08-24", active_days=90)
    # v1: 100 stations; v2: 50 updaters drained from v1 -> v1 50, v2 50;
    # v3: 20 updaters drained proportionally (10 from each) -> v1 40, v2 40, v3 20
    assert m["on_release"] == {"v1": 40, "v2": 40, "v3": 20}
    assert m["active"] == 100 and m["not_updating"] == 0
    old = estimate.cohort_model(rels, own_stations=3, today="2026-09-15", active_days=90)
    assert old["not_updating"] == 40 and old["active"] == 60


def test_cohort_model_new_stations_beyond_pool():
    rels = [{"release": "v1", "created": "2026-08-01T00:00:00", "pulls": 10},
            {"release": "v2", "created": "2026-08-10T00:00:00", "pulls": 30}]
    m = estimate.cohort_model(rels, own_stations=0, today="2026-08-24")
    assert m["on_release"] == {"v2": 30} and m["active"] == 30


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


def test_batch_with_two_manifests_for_one_arch():
    reg = {"i1": reg_entry("index", [("a1", "arm64"), ("b1", "amd64")]),
           "i2": reg_entry("index", [("a1", "arm64"), ("b2", "amd64")]),
           "a1": {"kind": "manifest", "arch": "arm64", "created": "2026-08-17T02:38:00"},
           "b1": {"kind": "manifest", "arch": "amd64", "created": "2026-08-17T02:38:00"},
           "b2": {"kind": "manifest", "arch": "amd64", "created": "2026-08-17T02:40:00"}}
    batches = estimate.build_batches(reg)
    assert len(batches) == 1 and batches[0]["platforms"] == {"a1": "arm64", "b1": "amd64", "b2": "amd64"}
    assert estimate.batch_counts(batches[0], {"a1": 68, "b1": 10, "b2": 21})["arch"] == {"amd64": 31, "arm64": 68}
