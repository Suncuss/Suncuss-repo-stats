from pathlib import Path

OWNER = "Suncuss"
REPO = "BirdNET-PiPy"

# Our GHCR images. STATION_IMAGE is the one pulled exactly once per station per update.
IMAGES = ["birdnet-pipy-backend", "birdnet-pipy-frontend", "birdnet-pipy-icecast"]
STATION_IMAGE = "birdnet-pipy-frontend"

# Automated pulls. Since this date install.sh pulls each unique image once per
# update, so a station update is backend:frontend 1:1. `docker compose pull`
# pulls the backend once per service using it (BACKEND_SERVICES:1), which is how
# scripted or manual compose pulls are told apart from station updates.
BACKEND_IMAGE = "birdnet-pipy-backend"
BACKEND_SERVICES = 3
DEDUP_SINCE = "2026-04-09"

# Home Assistant analytics (opt-in). db21ed7f = alexbelgium/hassio-addons.
HA_SLUG = "db21ed7f_birdnet-pipy"
HA_REFERENCE_SLUGS = ["db21ed7f_birdnet-go", "db21ed7f_birdnet-pi", "db21ed7f_battybirdnet-pi"]

# Alex's add-on repo: per-version image pulls are an opt-in-independent HA signal.
ALEX_REPO = "alexbelgium/hassio-addons"
ALEX_ADDON = "birdnet-pipy"
ALEX_IMAGES = ["birdnet-pipy-amd64", "birdnet-pipy-aarch64"]

# Traffic history collected by jgehrcke/github-repo-stats into this repo.
STATS_REPO = "Suncuss/Suncuss-repo-stats"
TRAFFIC_BRANCH = "traffic-data"
TRAFFIC_CSV_PATH = f"{OWNER}/{REPO}/ghrs-data/views_clones_aggregate.csv"

# Estimation knobs (documented on the dashboard).
OWN_STATIONS = 1          # maintainer stations on the main channel, subtracted per main build
ACTIVE_WINDOW_DAYS = 90   # a station counts as active if it updated to a build current this recently
MIN_UPDATE_SHARE = 0.5    # high end: at least this share of active stations updates to any given build
RUN_MATCH_MINUTES = 40    # a build batch belongs to CI runs started within this window

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
