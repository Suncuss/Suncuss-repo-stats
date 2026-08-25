from pathlib import Path

OWNER = "Suncuss"
REPO = "BirdNET-PiPy"

# Our GHCR images. STATION_IMAGE is the one pulled exactly once per station per
# update (backend is pulled ~2.5x per station because three services use it).
IMAGES = ["birdnet-pipy-backend", "birdnet-pipy-frontend", "birdnet-pipy-icecast"]
STATION_IMAGE = "birdnet-pipy-frontend"

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
OWN_STATIONS = 3          # maintainer stations on the main channel, subtracted per release
ACTIVE_WINDOW_DAYS = 90   # a station counts as active if it pulled a release this recent
RUN_MATCH_MINUTES = 40    # a build batch belongs to CI runs started within this window

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
