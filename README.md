# Suncuss-repo-stats

Adoption statistics for [BirdNET-PiPy](https://github.com/Suncuss/BirdNET-PiPy).
The app has no telemetry, so everything here is inferred from public signals.

**Dashboard:** https://suncuss.github.io/Suncuss-repo-stats/

## What runs here

| workflow | schedule | what it does |
|---|---|---|
| `repo-stats.yml` | daily 23:00 UTC | [`jgehrcke/github-repo-stats`](https://github.com/jgehrcke/github-repo-stats) — keeps GitHub traffic (clones/views/stars/forks) history on the `traffic-data` branch, since GitHub only serves 14 days |
| `collect-adoption.yml` | daily 23:40 UTC | `python -m collector.run` — snapshots every source into `data/`, rebuilds `data/dashboard.json`, commits, and deploys `site/` + the JSON to GitHub Pages |

## Sources

- **GHCR pulls (ours)** — GitHub has no API for container download counts; the collector scrapes each image's package *versions* page and classifies every digest through the registry (`collector/ghcr.py`). Platform-manifest pulls of the frontend image ≈ one per station update.
- **Home Assistant analytics** — `analytics.home-assistant.io/addons.json`, slug `db21ed7f_birdnet-pipy` (opt-in installs, per version).
- **Alex's add-on images** — per-version pulls of `ghcr.io/alexbelgium/birdnet-pipy-{amd64,aarch64}` (≈ one per HA install per add-on version) plus his weekly `Stats` series.
- **GitHub** — stars, tags, issues, discussions, build runs, and the traffic CSV from `traffic-data`.

Estimation rules and caveats are on the dashboard's *Method* section and in `collector/estimate.py`.

## Layout

```
collector/   stdlib-only collector + estimation (run: python -m collector.run)
site/        static dashboard (Chart.js), served by GitHub Pages
data/        committed snapshots: ghcr/<image>/snapshots/<date>.json, ha/, alex/, github/, dashboard.json
tests/       pytest (python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/pytest)
```

Run locally with a token for higher API limits: `GITHUB_TOKEN=$(gh auth token) python -m collector.run`.
