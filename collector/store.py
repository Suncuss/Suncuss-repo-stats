import json
from pathlib import Path

from .config import DATA_DIR


def load_json(path, default=None):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else default


def save_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=0, sort_keys=True) + "\n")


def snapshot_dir(*parts):
    return DATA_DIR.joinpath(*parts, "snapshots")


def list_snapshots(directory):
    d = Path(directory)
    return sorted(p.stem for p in d.glob("????-??-??.json")) if d.exists() else []


def load_snapshot(directory, date):
    return load_json(Path(directory) / f"{date}.json")
