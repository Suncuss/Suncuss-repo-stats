"""Turn raw snapshots into the dashboard model (pure functions + one assembler)."""
import datetime as dt
import re
from collections import Counter, defaultdict

from . import store
from .config import (ACTIVE_WINDOW_DAYS, ALEX_IMAGES, BACKEND_IMAGE, BACKEND_SERVICES, DATA_DIR, DEDUP_SINCE, HA_SLUG,
                     IMAGES, MIN_UPDATE_SHARE, OWN_STATIONS, RUN_MATCH_MINUTES, STATION_IMAGE)


def parse_iso(s):
    return dt.datetime.fromisoformat(s.replace("Z", ""))


def rel_age_days(pub):
    """'3 days ago' -> 3, 'about 1 month ago' -> 30, 'yesterday' -> 1, hours/minutes -> 0."""
    if not pub:
        return None
    if "yesterday" in pub:
        return 1
    m = re.search(r"(\d+)\s+(minute|hour|day|week|month|year)", pub)
    if not m:
        return 0 if re.search(r"hour|minute|now", pub) else None
    n, unit = int(m.group(1)), m.group(2)
    return {"minute": 0, "hour": 0, "day": n, "week": 7 * n, "month": 30 * n, "year": 365 * n}[unit]


def version_key(v):
    return tuple(int(x) if x.isdigit() else -1 for x in re.split(r"[.\-]", v.lstrip("v")))


def tag_time(tag):
    """UTC commit time of a tag; tags cached before times were recorded fall back to midnight."""
    return tag.get("time") or tag["date"] + "T00:00:00"


def sort_tags(tags):
    return sorted(tags, key=lambda t: (tag_time(t), version_key(t["name"])))


# ---- GHCR batches ---------------------------------------------------------

def build_batches(registry):
    """Group index manifests that share platform manifests into build batches.
    Each batch = one CI build's platform manifests (+ every tag index that
    pointed at them). Platform-manifest counts are the station pulls."""
    batches = []
    by_platform = {}
    for sha, info in registry.items():
        if info.get("kind") not in ("index", "pidx"):
            continue
        plats = {c["digest"].split(":")[1]: c["arch"] for c in info["children"] if c["arch"] != "attest"}
        attest = {c["digest"].split(":")[1] for c in info["children"] if c["arch"] == "attest"}
        if not plats:
            continue
        hits = []
        for d in plats:
            b = by_platform.get(d)
            if b is not None and b not in hits:
                hits.append(b)
        target = hits[0] if hits else {"indexes": set(), "platforms": {}, "attest": set()}
        if not hits:
            batches.append(target)
        for other in hits[1:]:  # an index bridging two batches: merge them
            target["indexes"] |= other["indexes"]
            target["platforms"].update(other["platforms"])
            target["attest"] |= other["attest"]
            batches.remove(other)
        target["indexes"].add(sha)
        target["platforms"].update(plats)
        target["attest"] |= attest
        for d in target["platforms"]:
            by_platform[d] = target
    out = []
    for b in batches:
        created = [registry.get(d, {}).get("created") for d in b["platforms"]]
        created = min([c for c in created if c] or [""])
        out.append({"id": min(b["platforms"])[:12], "created": created,
                    "indexes": sorted(b["indexes"]), "platforms": dict(sorted(b["platforms"].items())),
                    "attest": sorted(b["attest"])})
    return sorted(out, key=lambda b: b["created"])


def batch_counts(batch, counts):
    arch = Counter()
    for d, a in batch["platforms"].items():
        arch[a] += counts.get(d, 0)
    return {"index": sum(counts.get(s, 0) for s in batch["indexes"]),
            "attest": sum(counts.get(s, 0) for s in batch["attest"]),
            "arch": dict(sorted(arch.items())), "pulls": sum(arch.values())}


def batch_stats(batch, counts, automated=None):
    """batch_counts with automated pulls taken out of `arch`/`pulls` and reported separately."""
    c = batch_counts(batch, counts)
    auto = {a: round(n) for a, n in (automated or {}).items()}
    c["arch"] = {a: max(0, n - auto.get(a, 0)) for a, n in c["arch"].items()}
    c["automated"] = c["pulls"] - sum(c["arch"].values())
    c["pulls"] = sum(c["arch"].values())
    return c


def attribute(batches, runs, tags, tag_evidence=None, window_min=RUN_MATCH_MINUTES, margin_s=120):
    """Label each batch with a channel and, for main builds, the release tag
    current when it was built (the newest tag committed before the build).

    Evidence, strongest first: tags observed on the batch's index digests
    (recorded daily in tag_history.json), then CI runs started within
    `window_min` of the batch. With main and staging runs both in the window,
    the batch goes to the clearly nearer one (by more than `margin_s`);
    otherwise it is ambiguous and counted as main. When main and staging were
    pushed together but built different content, only tag evidence can tell the
    two batches apart; a proximity-only "main" batch next to an evidenced main
    batch is demoted.
    """
    run_times = [(parse_iso(r["created"]), r["branch"]) for r in runs]
    tag_list = sort_tags(tags)
    tag_evidence = tag_evidence or {}
    evidenced_main = []
    for b in batches:
        b["branches"], b["channel"], b["release"], b["evidence"], b["ambiguous"] = [], "unknown", None, "none", False
        seen = set().union(*(set(tag_evidence.get(s, ())) for s in b["indexes"]))
        if not b["created"]:
            continue
        t = parse_iso(b["created"])
        near = {}
        for rt, br in run_times:
            gap = abs((rt - t).total_seconds())
            if gap <= window_min * 60:
                near[br] = min(gap, near.get(br, gap))
        b["branches"] = sorted(near)
        if "main" in seen:
            b["channel"], b["evidence"] = "main", "tag"
            evidenced_main.append(t)
        elif "staging" in seen:
            b["channel"], b["evidence"] = "staging", "tag"
        elif "main" in near and "staging" in near and near["staging"] + margin_s < near["main"]:
            b["channel"], b["evidence"] = "staging", "run"
        elif "main" in near:
            b["channel"], b["evidence"] = "main", "run"
            b["ambiguous"] = "staging" in near and near["staging"] <= near["main"] + margin_s
        elif near:
            b["channel"], b["evidence"] = "staging", "run"
    for b in batches:
        if b["channel"] == "main" and b["evidence"] == "run":
            t = parse_iso(b["created"])
            if any(abs((m - t).total_seconds()) <= window_min * 60 for m in evidenced_main):
                b["channel"] = "staging"
        if b["channel"] == "main":
            prior = [x["name"] for x in tag_list if tag_time(x) <= b["created"]]
            b["release"] = prior[-1] if prior else "untagged"
    return batches


def releases_from_batches(batches, stats, today):
    """Aggregate main-channel batches per release tag. stats: {batch id: batch_stats(...)}."""
    rel = {}
    for b in batches:
        if b["channel"] != "main":
            continue
        c = stats[b["id"]]
        r = rel.setdefault(b["release"], {"release": b["release"], "created": b["created"], "pulls": 0, "automated": 0,
                                          "index": 0, "arch": Counter(), "batches": 0, "mixed": False})
        r["created"] = min(r["created"], b["created"])
        r["pulls"] += c["pulls"]
        r["automated"] += c.get("automated", 0)
        r["index"] += c["index"]
        r["arch"].update(c["arch"])
        r["batches"] += 1
        r["mixed"] = r["mixed"] or b.get("ambiguous", False)
    out = sorted(rel.values(), key=lambda r: r["created"])
    for i, r in enumerate(out):
        end = parse_iso(out[i + 1]["created"]) if i + 1 < len(out) else parse_iso(today + "T23:59:59")
        r["days_live"] = round((end - parse_iso(r["created"])).total_seconds() / 86400, 1)
        r["current"] = i + 1 == len(out)
        r["arch"] = dict(r["arch"])
    return out


# ---- automated pulls ------------------------------------------------------

def automated_share(frontend, backend, services=BACKEND_SERVICES):
    """Per-arch platform pulls of the frontend and backend images over one
    period -> how many of the frontend pulls were automated.

    A station update (install.sh) pulls each image once, backend:frontend 1:1;
    `docker compose pull` pulls the backend once per service, services:1. With
    f = a + o and b = services*a + o, a = (b - f) / (services - 1).
    """
    out = {}
    for arch, f in frontend.items():
        a = (backend.get(arch, 0) - f) / (services - 1)
        out[arch] = min(max(a, 0.0), f)
    return out


def level_off(values, amount):
    """Take `amount` off the largest values first, levelling them down
    (water-filling from the top). Returns {key: amount taken}."""
    vals = sorted(((v, k) for k, v in values.items() if v > 0), reverse=True)
    if amount <= 0 or not vals:
        return {}
    if amount >= sum(v for v, _ in vals):
        return {k: v for v, k in vals}
    s = 0.0
    for i, (v, _) in enumerate(vals):
        s += v
        level = (s - amount) / (i + 1)
        if level >= (vals[i + 1][0] if i + 1 < len(vals) else 0):
            return {k: x - level for x, k in vals[: i + 1]}
    return {}


def station_pulls(batches, f_snaps, f_plat, b_snaps=(), b_plat=None, since=DEDUP_SINCE, services=BACKEND_SERVICES):
    """Split every frontend batch's platform pulls into station updates and
    automated pulls, snapshot by snapshot.

    f_snaps/b_snaps: [(date, {digest: count})] for the frontend and backend
    images; f_plat/b_plat: {digest: (arch, created)} for their platform
    manifests. Pulls before the first snapshot are split once, over everything
    built since `since`; after that, one day at a time. The automated share
    comes off the batches pulled most that day (`level_off`): a compose pull
    follows one tag. Returns one entry per frontend snapshot:
    {date, raw: {id: {arch: n}}, automated: {id: {arch: n}} (both cumulative),
    day: {raw, automated} (that day's deltas, None for the first snapshot)}.
    """
    b_plat = b_plat or {}
    b_by_date = dict(b_snaps)
    owner = {d: b["id"] for b in batches for d in b["platforms"]}
    raw, auto = defaultdict(Counter), defaultdict(Counter)
    out, prev_f, prev_b = [], None, None
    for date, fc in f_snaps:
        bc = b_by_date.get(date)
        if prev_f is None:
            f_delta = {d: n for d, n in fc.items() if d in f_plat and f_plat[d][1][:10] >= since}
            b_delta = {d: n for d, n in (bc or {}).items() if d in b_plat and b_plat[d][1][:10] >= since}
            first = {d: n for d, n in fc.items() if d in f_plat}
        else:
            f_delta = {d: max(0, n - prev_f[1].get(d, 0)) for d, n in fc.items() if d in f_plat}
            b_delta = {d: max(0, n - prev_b[1].get(d, 0)) for d, n in (bc or {}).items() if d in b_plat}
            first = f_delta
        # Backend and frontend deltas must cover the same period to be compared.
        comparable = bc is not None and (prev_f is None or (prev_b is not None and prev_b[0] == prev_f[0]))
        day_raw, day_auto = defaultdict(Counter), defaultdict(Counter)
        for d, n in first.items():
            if d in owner and n:
                day_raw[owner[d]][f_plat[d][0]] += n
        if comparable:
            F, B, split = Counter(), Counter(), defaultdict(Counter)
            for d, n in f_delta.items():
                F[f_plat[d][0]] += n
                if d in owner:
                    split[f_plat[d][0]][owner[d]] += n
            for d, n in b_delta.items():
                B[b_plat[d][0]] += n
            for arch, a in automated_share(F, B, services).items():
                for bid, x in level_off(split[arch], a).items():
                    day_auto[bid][arch] += x
        for bid, c in day_raw.items():
            raw[bid].update(c)
        for bid, c in day_auto.items():
            auto[bid].update(c)
        out.append({"date": date, "raw": {k: dict(v) for k, v in raw.items()}, "automated": {k: dict(v) for k, v in auto.items()},
                    "day": None if prev_f is None else {"raw": {k: dict(v) for k, v in day_raw.items()},
                                                        "automated": {k: dict(v) for k, v in day_auto.items()}}})
        prev_f = (date, fc)
        if bc is not None:
            prev_b = (date, bc)
    return out


# ---- self-hosted cohorts --------------------------------------------------

def cohort_model(builds, own_stations=OWN_STATIONS, today=None, active_days=ACTIVE_WINDOW_DAYS):
    """Estimate how many stations sit on each build of one channel.

    builds: [{key, created, pulls}] in build order. Each build's station pulls
    (minus the maintainer's own stations) are updaters drawn proportionally from
    the pool of stations on older builds; pulls beyond that pool are new
    stations. A build's stations last updated while it was current, so cohorts
    on builds replaced more than `active_days` ago count as 'not updating'.

    on_build is unrounded: frequent builds each keep a fraction of a station
    after draining, so round only after summing.

    The pool total is the largest single wave of pulls, so `active` is a floor:
    stations that skipped that build are only counted if they show up in a
    bigger wave. `pulled` sums the pulls of every build current within the
    window; each station that updated in the window is in there at least once.
    """
    pool, ended = {}, {}
    for i, b in enumerate(builds):
        p = max(0.0, b["pulls"] - own_stations)
        total = sum(pool.values())
        drain = min(p, total)
        if total > 0 and drain > 0:
            for k in pool:
                pool[k] -= drain * pool[k] / total
        pool[b["key"]] = pool.get(b["key"], 0) + p
        ended[b["key"]] = builds[i + 1]["created"] if i + 1 < len(builds) else f"{today or '9999-12-31'}T23:59:59"
    cutoff = (parse_iso(today + "T00:00:00") - dt.timedelta(days=active_days)).isoformat() if today else ""
    pulled = sum(max(0.0, b["pulls"] - own_stations) for b in builds if ended[b["key"]] >= cutoff)
    on_build, dormant = {}, 0.0
    for k, v in pool.items():
        if ended[k] >= cutoff:
            if v > 1e-9:
                on_build[k] = v
        else:
            dormant += v
    active = round(sum(on_build.values()))
    return {"on_build": on_build, "active": active, "not_updating": round(dormant), "pulled": max(active, round(pulled))}


def channel_builds(batches, pulls, channel, upto):
    """Builds of one channel that existed by date `upto`, with their station pulls.
    pulls: {batch id: {arch: n}}."""
    return [{"key": b["id"], "created": b["created"], "pulls": sum(pulls.get(b["id"], {}).values())}
            for b in batches if b["channel"] == channel and b["created"] and b["created"][:10] <= upto]


def self_hosted_model(batches, pulls, today, own_stations=OWN_STATIONS, min_share=MIN_UPDATE_SHARE):
    """Cohort models for the main (release) and staging (latest) channels.
    on_release maps main builds to their release tag; staging is one bucket.
    `high` assumes only `min_share` of active stations took the biggest wave,
    capped by the pulls actually seen."""
    main = cohort_model(channel_builds(batches, pulls, "main", today), own_stations, today)
    staging = cohort_model(channel_builds(batches, pulls, "staging", today), 0, today)
    release = {b["id"]: b["release"] for b in batches}
    on_release = Counter()
    for k, n in main["on_build"].items():
        on_release[release[k]] += n
    on_release = Counter({r: round(n) for r, n in on_release.items() if round(n) > 0})
    if staging["active"]:
        on_release["staging"] += staging["active"]
    active = main["active"] + staging["active"]
    return {"on_release": dict(on_release), "active": active,
            "high": max(active, min(round(active / min_share), main["pulled"] + staging["pulled"])),
            "not_updating": main["not_updating"] + staging["not_updating"],
            "channels": {"main": main["active"], "staging": staging["active"]}}


# ---- HA -------------------------------------------------------------------

def alex_versions_from_rows(rows_by_image):
    """rows_by_image: {image: [[sha, dl, tags, pub], ...]} -> {version: {arch counts, total, age_days}}."""
    out = {}
    for image, rows in rows_by_image.items():
        arch = image.rsplit("-", 1)[-1]
        for sha, dl, tags, pub in rows:
            for tag in tags:
                if tag == "latest" or not re.match(r"\d", tag):
                    continue
                v = out.setdefault(tag, {"total": 0, "age_days": rel_age_days(pub)})
                v[arch] = v.get(arch, 0) + dl
                v["total"] += dl
    return dict(sorted(out.items(), key=lambda kv: version_key(kv[0])))


def ha_estimate(ha_entry, alex_versions, min_age_days=7):
    """HA installs from pulls of Alex's per-version add-on images: each install
    pulls a version once when it updates. Over the two newest versions out at
    least `min_age_days`: the more-pulled one is the estimate, the other the
    low end; the high end scales the estimate by the share of opt-in installs on
    one of those versions or newer (the rest never pulled them)."""
    entry = ha_entry or {}
    reporting = entry.get("total", 0)
    versions = entry.get("versions", {})
    recent = [(v, x["total"]) for v, x in alex_versions.items() if (x.get("age_days") or 0) >= min_age_days][-2:]
    totals = [n for _, n in recent]
    est = max([reporting, *totals])
    low = max([reporting, min(totals)]) if totals else reporting
    high = est
    if recent and reporting:
        floor = version_key(recent[0][0])
        current = sum(n for v, n in versions.items() if version_key(v) >= floor)
        if current:
            high = max(est, round(est * reporting / current))
    return {"reporting": reporting, "pulls_base": max(totals) if totals else 0, "estimated": est, "low": low,
            "high": high, "opt_in_rate": round(reporting / est, 2) if est else None,
            "versions": versions, "auto_update": entry.get("auto_update")}


# ---- assembly -------------------------------------------------------------

def _month(date):
    return date[:7]


def _counts_from_snapshot(snap):
    return {r[0]: r[1] for r in snap["rows"]}


def _platforms(registry):
    return {sha: (info.get("arch"), info.get("created", "")) for sha, info in registry.items() if info.get("kind") == "manifest"}


def _on_or_before(dates, d):
    prior = [x for x in dates if x <= d]
    return prior[-1] if prior else None


def _sub(a, b):
    return {k: a.get(k, 0) - b.get(k, 0) for k in a}


def build_dashboard(today, now_iso):
    gh = {k: store.load_json(DATA_DIR / "github" / f"{k}.json", default) for k, default in
          [("repo", {}), ("stars", []), ("tags_cache", {}), ("issues", []), ("discussions", None), ("build_runs_cache", {}), ("traffic", [])]}
    tags = sort_tags({"name": k, **v} for k, v in gh["tags_cache"].items())
    runs = sorted(gh["build_runs_cache"].values(), key=lambda x: x["created"])

    # GitHub section
    stars_by_month = Counter(_month(d) for d in gh["stars"])
    cum, stars_cum = 0, []
    for m in sorted(stars_by_month):
        cum += stars_by_month[m]
        stars_cum.append({"month": m, "new": stars_by_month[m], "total": cum})
    issues = [i for i in gh["issues"] if not i["is_pr"]]
    traffic_monthly = defaultdict(lambda: Counter())
    for r in gh["traffic"]:
        traffic_monthly[_month(r["date"])].update({k: r[k] for k in ("clones", "clones_unique", "views", "views_unique")})
    github = {
        "repo": gh["repo"],
        "stars": stars_cum,
        "tags": [{k: t[k] for k in ("name", "date", "sha") if k in t} for t in tags],
        "issues": {"total": len(issues), "unique_authors": len({i["author"] for i in issues}),
                   "by_month": dict(sorted(Counter(_month(i["created"]) for i in issues).items()))},
        "discussions": None if gh["discussions"] is None else {
            "total": gh["discussions"]["total"], "unique_authors": len({d["author"] for d in gh["discussions"]["items"]})},
        "traffic": {"daily": gh["traffic"], "monthly": [{"month": m, **c} for m, c in sorted(traffic_monthly.items())]},
    }

    # GHCR section
    ghcr = {"lifetime": {}, "tags": {}, "releases": [], "staging": [], "daily": [], "snapshots": [], "automated": {}}
    per_image = {}
    for image in IMAGES:
        sdir = store.snapshot_dir("ghcr", image)
        dates = store.list_snapshots(sdir)
        registry = store.load_json(DATA_DIR / "ghcr" / image / "manifests.json", {})
        tag_history = store.load_json(DATA_DIR / "ghcr" / image / "tag_history.json", {})
        if not dates:
            continue
        latest = store.load_snapshot(sdir, dates[-1])
        counts = _counts_from_snapshot(latest)
        batches = attribute(build_batches(registry), runs, tags, {sha: set(t) for sha, t in tag_history.items()})
        per_image[image] = {"dates": dates, "sdir": sdir, "batches": batches, "counts": counts, "registry": registry}
        ghcr["lifetime"][image] = sum(counts.values())
        ghcr["tags"][image] = {}
        for sha, dl, tgs in latest["rows"]:
            for t in tgs:
                b = next((b for b in batches if sha in b["indexes"]), None)
                ghcr["tags"][image][t] = {"index": dl, **({"arch": batch_counts(b, counts)["arch"]} if b else {})}
    station = per_image.get(STATION_IMAGE)
    series = []
    if station:
        backend = per_image.get(BACKEND_IMAGE)

        def snaps(info):
            return [(d, _counts_from_snapshot(store.load_snapshot(info["sdir"], d))) for d in info["dates"]]
        series = station_pulls(station["batches"], snaps(station), _platforms(station["registry"]),
                               snaps(backend) if backend else (), _platforms(backend["registry"]) if backend else None)
        final = series[-1]
        stats = {b["id"]: batch_stats(b, station["counts"], final["automated"].get(b["id"])) for b in station["batches"]}
        ghcr["snapshots"] = station["dates"]
        rels = releases_from_batches(station["batches"], stats, today)
        for r in rels:
            r["other_images"] = {}
            for image, info in per_image.items():
                if image == STATION_IMAGE:
                    continue
                same = [b for b in info["batches"] if b["channel"] == "main" and b["release"] == r["release"]]
                r["other_images"][image] = sum(batch_counts(b, info["counts"])["pulls"] for b in same)
        ghcr["releases"] = rels
        ghcr["staging"] = [{"created": b["created"], "branches": b["branches"], **stats[b["id"]]}
                           for b in station["batches"] if b["channel"] == "staging" and b["created"] >= "2026-06-01"]
        label = {b["id"]: (b["release"] if b["channel"] == "main" else b["channel"]) for b in station["batches"]}
        for prev, cur in zip(series, series[1:]):
            day = defaultdict(Counter)
            for bid, c in cur["day"]["raw"].items():
                day[label[bid]].update({a: n - round(cur["day"]["automated"].get(bid, {}).get(a, 0)) for a, n in c.items()})
            automated = Counter()
            for c in cur["day"]["automated"].values():
                automated.update(c)
            ghcr["daily"].append({"date": cur["date"], "since": prev["date"],
                                  "pulls": {k: {a: n for a, n in v.items() if n} for k, v in day.items() if any(v.values())},
                                  "automated": {a: round(n) for a, n in sorted(automated.items())}})
        auto_total = Counter()
        for c in final["automated"].values():
            auto_total.update(c)
        raw_total = sum(sum(c.values()) for c in final["raw"].values())
        ghcr["automated"] = {"pulls": round(sum(auto_total.values())), "arch": {a: round(n) for a, n in sorted(auto_total.items())},
                             "share": round(sum(auto_total.values()) / raw_total, 2) if raw_total else None, "since": DEDUP_SINCE}

    # HA section
    ha_dir = store.snapshot_dir("ha")
    ha_dates = store.list_snapshots(ha_dir)
    ha_history, ha_entries, addon_version, ha_latest = [], {}, None, None
    for d in ha_dates:
        snap = store.load_snapshot(ha_dir, d)
        entry = (snap.get("addons") or {}).get(HA_SLUG) or {}
        ha_entries[d] = entry
        ha_history.append({"date": d, "total": entry.get("total", 0), "versions": entry.get("versions", {}),
                           "auto_update": entry.get("auto_update")})
        ha_latest, addon_version = snap, snap.get("addon_version")
    alex_by_date = defaultdict(dict)
    for image in ALEX_IMAGES:
        adir = store.snapshot_dir("alex", image)
        for d in store.list_snapshots(adir):
            alex_by_date[d][image] = store.load_snapshot(adir, d)["rows"]
    alex_dates = sorted(alex_by_date)
    alex_versions = alex_versions_from_rows(alex_by_date[alex_dates[-1]]) if alex_dates else {}
    ha = {"latest": ha_history[-1] if ha_history else None, "history": ha_history,
          "reference": {k: (v or {}).get("total") for k, v in ((ha_latest or {}).get("addons") or {}).items() if k != HA_SLUG},
          "alex_versions": alex_versions, "alex_weekly": store.load_json(DATA_DIR / "ha" / "alex_weekly.json", []),
          "addon_version": addon_version}

    def ha_on(d):
        hd, ad = _on_or_before(ha_dates, d), _on_or_before(alex_dates, d)
        return ha_estimate(ha_entries.get(hd), alex_versions_from_rows(alex_by_date[ad]) if ad else {})

    # Estimates: latest + one point per GHCR snapshot, each from the data available that day
    ha_est = ha_estimate(ha_entries.get(ha_dates[-1]) if ha_dates else None, alex_versions)
    empty = {"on_release": {}, "active": 0, "high": 0, "not_updating": 0, "channels": {"main": 0, "staging": 0}}
    self_est, estimate_history = empty, []
    if station:
        for snap in series:
            d = snap["date"]
            pulls = {bid: _sub(c, snap["automated"].get(bid, {})) for bid, c in snap["raw"].items()}
            model = self_hosted_model(station["batches"], pulls, today if d == series[-1]["date"] else d)
            ha_d = ha_on(d)["estimated"]
            estimate_history.append({"date": d, "self_hosted": model["active"], "not_updating": model["not_updating"],
                                     "ha": ha_d, "total": model["active"] + ha_d, "on_release": model["on_release"]})
            self_est = model
    estimate = {
        "self_hosted": {**self_est, "method": "cohort model per build and channel on station-image platform pulls, automated pulls removed",
                        "own_stations_excluded": OWN_STATIONS, "active_window_days": ACTIVE_WINDOW_DAYS,
                        "min_update_share": MIN_UPDATE_SHARE},
        "ha": {**ha_est, "method": "pulls of the most-pulled of the two newest add-on versions out at least 7 days (at least the HA analytics opt-in total)"},
        "total": {"mid": self_est["active"] + ha_est["estimated"], "low": self_est["active"] + ha_est["low"],
                  "high": self_est["high"] + ha_est["high"]},
        "history": estimate_history,
    }
    return {"generated": now_iso, "today": today,
            "config": {"station_image": STATION_IMAGE, "own_stations": OWN_STATIONS, "active_window_days": ACTIVE_WINDOW_DAYS,
                       "backend_services": BACKEND_SERVICES, "dedup_since": DEDUP_SINCE, "min_update_share": MIN_UPDATE_SHARE},
            "github": github, "ghcr": ghcr, "ha": ha, "estimate": estimate}
