"""Collect every source, persist snapshots, rebuild data/dashboard.json.

Exit code 2 if any source failed (data from the others is still written), so
the scheduled run shows red without losing the day's snapshot.
"""
import datetime as dt
import sys
import traceback

from . import estimate, ghcr, github_data, ha, store
from .config import (ALEX_ADDON, ALEX_IMAGES, ALEX_REPO, DATA_DIR, HA_REFERENCE_SLUGS, HA_SLUG, IMAGES,
                     OWNER, REPO)


def log(msg):
    print(msg, flush=True)


def collect_ghcr(today):
    for image in IMAGES:
        rows, header = ghcr.fetch_versions(f"{OWNER}/{REPO}", image)
        reg_path = DATA_DIR / "ghcr" / image / "manifests.json"
        registry = store.load_json(reg_path, {})
        added = ghcr.update_registry(f"{OWNER.lower()}/{image}", [r["sha"] for r in rows], registry, log)
        store.save_json(reg_path, registry)
        hist_path = DATA_DIR / "ghcr" / image / "tag_history.json"
        history = store.load_json(hist_path, {})
        for r in rows:
            for tag in r["tags"]:
                span = history.setdefault(r["sha"], {}).setdefault(tag, [today, today])
                span[1] = today
        store.save_json(hist_path, history)
        store.save_json(store.snapshot_dir("ghcr", image) / f"{today}.json",
                        {"date": today, "header": header, "rows": [[r["sha"], r["dl"], r["tags"]] for r in rows]})
        log(f"ghcr {image}: {len(rows)} versions, {sum(r['dl'] for r in rows)} downloads, {added} new manifests described")


def collect_alex(today):
    for image in ALEX_IMAGES:
        rows, header = ghcr.fetch_versions(ALEX_REPO, image, max_pages=6)
        tagged = [[r["sha"], r["dl"], r["tags"], r["pub"]] for r in rows if r["tags"]]
        store.save_json(store.snapshot_dir("alex", image) / f"{today}.json",
                        {"date": today, "header": header, "total": sum(r["dl"] for r in rows), "rows": tagged})
        log(f"alex {image}: {len(tagged)} tagged versions")


def collect_ha(today):
    addons = ha.fetch_addons()
    snap = {"date": today, "addons": ha.snapshot(addons, [HA_SLUG, *HA_REFERENCE_SLUGS]),
            "addon_version": ha.fetch_alex_addon_version(ALEX_ADDON)}
    store.save_json(store.snapshot_dir("ha") / f"{today}.json", snap)
    store.save_json(DATA_DIR / "ha" / "alex_weekly.json", ha.fetch_alex_stats(ALEX_ADDON))
    entry = snap["addons"].get(HA_SLUG) or {}
    log(f"ha: {entry.get('total')} reporting installs, add-on version {snap['addon_version']}")


def collect_github():
    gdir = DATA_DIR / "github"
    store.save_json(gdir / "repo.json", github_data.fetch_repo(OWNER, REPO))
    store.save_json(gdir / "stars.json", github_data.fetch_stars(OWNER, REPO))
    tags_cache = store.load_json(gdir / "tags_cache.json", {})
    github_data.fetch_tags(OWNER, REPO, tags_cache)
    store.save_json(gdir / "tags_cache.json", tags_cache)
    store.save_json(gdir / "issues.json", github_data.fetch_issues(OWNER, REPO))
    discussions = github_data.fetch_discussions(OWNER, REPO)
    if discussions is not None:
        store.save_json(gdir / "discussions.json", discussions)
    runs_cache = store.load_json(gdir / "build_runs_cache.json", {})
    github_data.fetch_build_runs(OWNER, REPO, runs_cache)
    store.save_json(gdir / "build_runs_cache.json", runs_cache)
    store.save_json(gdir / "traffic.json", github_data.fetch_traffic())
    log(f"github: {len(tags_cache)} tags, {len(runs_cache)} build runs cached")


def main():
    now = dt.datetime.now(dt.timezone.utc)
    today = now.date().isoformat()
    errors = {}
    for name, fn in [("github", lambda: collect_github()), ("ghcr", lambda: collect_ghcr(today)),
                     ("alex", lambda: collect_alex(today)), ("ha", lambda: collect_ha(today))]:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - one source failing must not lose the others
            errors[name] = f"{type(e).__name__}: {e}"
            log(f"!! {name} failed: {errors[name]}")
            traceback.print_exc()
    dashboard = estimate.build_dashboard(today, now.isoformat(timespec="seconds"))
    dashboard["errors"] = errors
    store.save_json(DATA_DIR / "dashboard.json", dashboard)
    store.save_json(DATA_DIR / "last_run.json", {"date": today, "generated": dashboard["generated"], "errors": errors})
    est = dashboard["estimate"]
    log(f"estimate: self-hosted {est['self_hosted']['active']} + HA {est['ha']['estimated']} = {est['total']['mid']}")
    sys.exit(2 if errors else 0)


if __name__ == "__main__":
    main()
