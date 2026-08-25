"""Home Assistant signals: opt-in analytics + Alex's add-on repo."""
import re

from . import http
from .config import ALEX_ADDON, ALEX_REPO

ADDONS_URL = "https://analytics.home-assistant.io/addons.json"
ALEX_RAW = f"https://raw.githubusercontent.com/{ALEX_REPO}/master"


def fetch_addons():
    return http.get_json(ADDONS_URL)


def snapshot(addons, slugs):
    return {slug: addons.get(slug) for slug in slugs}


def parse_alex_stats(text, slug):
    """Alex's `Stats` file: header = dates newest-first then 'Date'; each row =
    values newest-first then the add-on slug. Values are the current version's
    GHCR downloads at snapshot time (summed over arches)."""
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return []
    dates = [t for t in lines[0].split() if re.match(r"\d{4}-\d{2}-\d{2}$", t)]
    for line in lines[1:]:
        toks = line.split()
        if toks and toks[-1] == slug:
            series = []
            for date, val in zip(dates, toks[:-1]):
                if val.isdigit():
                    series.append({"date": date, "value": int(val)})
            return sorted(series, key=lambda x: x["date"])
    return []


def fetch_alex_stats(slug=ALEX_ADDON):
    return parse_alex_stats(http.get_text(f"{ALEX_RAW}/Stats") or "", slug)


def fetch_alex_addon_version(addon=ALEX_ADDON):
    text = http.get_text(f"{ALEX_RAW}/{addon}/config.yaml") or ""
    m = re.search(r'^version:\s*"?([^"\s]+)', text, re.M)
    return m.group(1) if m else None
