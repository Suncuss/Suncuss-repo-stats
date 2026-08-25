"""Turn raw snapshots into the dashboard model (pure functions + one assembler)."""
import datetime as dt
import re
from collections import Counter, defaultdict

from . import store
from .config import (ACTIVE_WINDOW_DAYS, ALEX_IMAGES, DATA_DIR, HA_SLUG, IMAGES, OWN_STATIONS,
                     RUN_MATCH_MINUTES, STATION_IMAGE)


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
    return tuple(int(x) if x.isdigit() else -1 for x in re.split(r"[.\-]", v))


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


def attribute(batches, runs, tags, tag_evidence=None, window_min=RUN_MATCH_MINUTES):
    """Label each batch with a channel and, for main builds, the release tag
    current when it was built.

    Evidence, strongest first: tags observed on the batch's index digests
    (recorded daily in tag_history.json), then CI runs started within
    `window_min` of the batch. When main and staging were pushed together but
    built different content, only tag evidence can tell the two batches apart;
    a proximity-only "main" batch next to an evidenced main batch is demoted.
    """
    run_times = [(parse_iso(r["created"]), r["branch"]) for r in runs]
    tag_list = sorted(tags, key=lambda t: (t["date"], t["name"]))
    tag_evidence = tag_evidence or {}
    evidenced_main = []
    for b in batches:
        b["branches"], b["channel"], b["release"], b["evidence"] = [], "unknown", None, "none"
        seen = set().union(*(set(tag_evidence.get(s, ())) for s in b["indexes"]))
        if not b["created"]:
            continue
        t = parse_iso(b["created"])
        b["branches"] = sorted({br for rt, br in run_times if abs((rt - t).total_seconds()) <= window_min * 60})
        if "main" in seen:
            b["channel"], b["evidence"] = "main", "tag"
            evidenced_main.append(t)
        elif "staging" in seen:
            b["channel"], b["evidence"] = "staging", "tag"
        elif "main" in b["branches"]:
            b["channel"], b["evidence"] = "main", "run"
        elif b["branches"]:
            b["channel"], b["evidence"] = "staging", "run"
    for b in batches:
        if b["channel"] == "main" and b["evidence"] == "run":
            t = parse_iso(b["created"])
            if any(abs((m - t).total_seconds()) <= window_min * 60 for m in evidenced_main):
                b["channel"] = "staging"
        if b["channel"] == "main":
            prior = [x["name"] for x in tag_list if x["date"] <= b["created"][:10]]
            b["release"] = prior[-1] if prior else "untagged"
    return batches


def releases_from_batches(batches, counts, today):
    """Aggregate main-channel batches per release tag at one snapshot."""
    rel = {}
    for b in batches:
        if b["channel"] != "main":
            continue
        c = batch_counts(b, counts)
        r = rel.setdefault(b["release"], {"release": b["release"], "created": b["created"], "pulls": 0, "index": 0,
                                          "arch": Counter(), "batches": 0, "mixed": False})
        r["created"] = min(r["created"], b["created"])
        r["pulls"] += c["pulls"]
        r["index"] += c["index"]
        r["arch"].update(c["arch"])
        r["batches"] += 1
        r["mixed"] = r["mixed"] or "staging" in b["branches"]
    out = sorted(rel.values(), key=lambda r: r["created"])
    for i, r in enumerate(out):
        end = parse_iso(out[i + 1]["created"]) if i + 1 < len(out) else parse_iso(today + "T23:59:59")
        r["days_live"] = round((end - parse_iso(r["created"])).total_seconds() / 86400, 1)
        r["current"] = i + 1 == len(out)
        r["arch"] = dict(r["arch"])
    return out


def cohort_model(releases, own_stations=OWN_STATIONS, today=None, active_days=ACTIVE_WINDOW_DAYS):
    """Estimate which release self-hosted stations are on.

    Each release's station pulls (minus the maintainer's own stations) are
    updaters drawn proportionally from the pool of stations on older releases;
    pulls beyond that pool are new stations. Stations whose last pull is older
    than `active_days` count as 'not updating' rather than active.
    """
    pool = {}
    for r in releases:
        p = max(0, r["pulls"] - own_stations)
        total = sum(pool.values())
        drain = min(p, total)
        if total > 0 and drain > 0:
            for k in pool:
                pool[k] -= drain * pool[k] / total
        pool[r["release"]] = pool.get(r["release"], 0) + p
    created = {r["release"]: r["created"] for r in releases}
    cutoff = (parse_iso(today + "T00:00:00") - dt.timedelta(days=active_days)).isoformat() if today else ""
    dist, dormant = {}, 0.0
    for k, v in pool.items():
        if round(v) <= 0:
            continue
        if created.get(k, "") >= cutoff:
            dist[k] = round(v)
        else:
            dormant += v
    return {"on_release": dist, "active": sum(dist.values()), "not_updating": round(dormant)}


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
    reporting = (ha_entry or {}).get("total", 0)
    complete = [v for v in alex_versions.values() if (v.get("age_days") or 0) >= min_age_days]
    recent = [v["total"] for v in complete[-2:]]
    pulls_base = max(recent) if recent else 0
    est = max(reporting, pulls_base)
    return {"reporting": reporting, "pulls_base": pulls_base, "estimated": est,
            "opt_in_rate": round(reporting / est, 2) if est else None,
            "versions": (ha_entry or {}).get("versions", {}), "auto_update": (ha_entry or {}).get("auto_update")}


# ---- assembly -------------------------------------------------------------

def _month(date):
    return date[:7]


def _counts_from_snapshot(snap):
    return {r[0]: r[1] for r in snap["rows"]}


def build_dashboard(today, now_iso):
    gh = {k: store.load_json(DATA_DIR / "github" / f"{k}.json", default) for k, default in
          [("repo", {}), ("stars", []), ("tags_cache", {}), ("issues", []), ("discussions", None), ("build_runs_cache", {}), ("traffic", [])]}
    tags = sorted(({"name": k, **v} for k, v in gh["tags_cache"].items()), key=lambda x: (x["date"], x["name"]))
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
        "tags": tags,
        "issues": {"total": len(issues), "unique_authors": len({i["author"] for i in issues}),
                   "by_month": dict(sorted(Counter(_month(i["created"]) for i in issues).items()))},
        "discussions": None if gh["discussions"] is None else {
            "total": gh["discussions"]["total"], "unique_authors": len({d["author"] for d in gh["discussions"]["items"]})},
        "traffic": {"daily": gh["traffic"], "monthly": [{"month": m, **c} for m, c in sorted(traffic_monthly.items())]},
    }

    # GHCR section
    ghcr = {"lifetime": {}, "tags": {}, "releases": [], "staging": [], "daily": [], "snapshots": []}
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
        per_image[image] = {"dates": dates, "sdir": sdir, "batches": batches, "counts": counts}
        ghcr["lifetime"][image] = sum(counts.values())
        ghcr["tags"][image] = {}
        for sha, dl, tgs in latest["rows"]:
            for t in tgs:
                b = next((b for b in batches if sha in b["indexes"]), None)
                ghcr["tags"][image][t] = {"index": dl, **({"arch": batch_counts(b, counts)["arch"]} if b else {})}
    station = per_image.get(STATION_IMAGE)
    estimate_history = []
    if station:
        ghcr["snapshots"] = station["dates"]
        rels = releases_from_batches(station["batches"], station["counts"], today)
        for r in rels:
            r["other_images"] = {}
            for image, info in per_image.items():
                if image == STATION_IMAGE:
                    continue
                same = [b for b in info["batches"] if b["channel"] == "main" and b["release"] == r["release"]]
                r["other_images"][image] = sum(batch_counts(b, info["counts"])["pulls"] for b in same)
        ghcr["releases"] = rels
        ghcr["staging"] = [{"created": b["created"], "branches": b["branches"], **batch_counts(b, station["counts"])}
                           for b in station["batches"] if b["channel"] == "staging" and b["created"] >= "2026-06-01"]
        # daily per-release pulls from consecutive snapshots
        prev = None
        for d in station["dates"]:
            snap = store.load_snapshot(station["sdir"], d)
            counts_d = _counts_from_snapshot(snap)
            if prev is not None:
                pd, pc = prev
                day = defaultdict(lambda: Counter())
                for b in station["batches"]:
                    label = b["release"] if b["channel"] == "main" else b["channel"]
                    for digest, arch in b["platforms"].items():
                        delta = counts_d.get(digest, 0) - pc.get(digest, 0)
                        if delta:
                            day[label][arch] += delta
                ghcr["daily"].append({"date": d, "since": pd, "pulls": {k: dict(v) for k, v in day.items()}})
            prev = (d, counts_d)

    # HA section
    ha_dir = store.snapshot_dir("ha")
    ha_dates = store.list_snapshots(ha_dir)
    ha_history, ha_latest, addon_version = [], None, None
    for d in ha_dates:
        snap = store.load_snapshot(ha_dir, d)
        entry = (snap.get("addons") or {}).get(HA_SLUG) or {}
        ha_history.append({"date": d, "total": entry.get("total", 0), "versions": entry.get("versions", {}),
                           "auto_update": entry.get("auto_update")})
        ha_latest, addon_version = snap, snap.get("addon_version")
    alex_rows = {}
    for image in ALEX_IMAGES:
        adir = store.snapshot_dir("alex", image)
        adates = store.list_snapshots(adir)
        if adates:
            alex_rows[image] = store.load_snapshot(adir, adates[-1])["rows"]
    alex_versions = alex_versions_from_rows(alex_rows)
    ha_entry = ((ha_latest or {}).get("addons") or {}).get(HA_SLUG)
    ha = {"latest": ha_history[-1] if ha_history else None, "history": ha_history,
          "reference": {k: (v or {}).get("total") for k, v in ((ha_latest or {}).get("addons") or {}).items() if k != HA_SLUG},
          "alex_versions": alex_versions, "alex_weekly": store.load_json(DATA_DIR / "ha" / "alex_weekly.json", []),
          "addon_version": addon_version}

    # Estimates (latest + history over GHCR snapshot dates)
    ha_est = ha_estimate(ha_entry, alex_versions)
    self_est = cohort_model(ghcr["releases"], today=today) if ghcr["releases"] else {"on_release": {}, "active": 0, "not_updating": 0}
    if station:
        ha_by_date = {h["date"]: h["total"] for h in ha_history}
        for d in station["dates"]:
            counts_d = _counts_from_snapshot(store.load_snapshot(station["sdir"], d))
            rels_d = releases_from_batches(station["batches"], counts_d, d)
            model = cohort_model(rels_d, today=d)
            ha_d = max(ha_by_date.get(d, 0), ha_est["pulls_base"]) if d == station["dates"][-1] else ha_by_date.get(d, ha_est["estimated"])
            estimate_history.append({"date": d, "self_hosted": model["active"], "not_updating": model["not_updating"],
                                     "ha": ha_d, "total": model["active"] + ha_d, "on_release": model["on_release"]})
    total = self_est["active"] + ha_est["estimated"]
    estimate = {
        "self_hosted": {**self_est, "method": "cohort model on station-image platform pulls per release (main channel)",
                        "own_stations_excluded": OWN_STATIONS, "active_window_days": ACTIVE_WINDOW_DAYS},
        "ha": {**ha_est, "method": "max(HA analytics opt-in total, pulls of the most recent add-on version older than 7 days)"},
        "total": {"mid": total, "low": round(total * 0.7), "high": round(total * 1.3)},
        "history": estimate_history,
    }
    return {"generated": now_iso, "today": today,
            "config": {"station_image": STATION_IMAGE, "own_stations": OWN_STATIONS, "active_window_days": ACTIVE_WINDOW_DAYS},
            "github": github, "ghcr": ghcr, "ha": ha, "estimate": estimate}
