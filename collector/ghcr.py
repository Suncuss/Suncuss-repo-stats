"""GHCR download counts.

GitHub exposes no API for container download counts, so we scrape the package
"versions" pages (one "N Version downloads" per digest) and classify digests by
walking the registry anonymously (index / per-platform index / platform
manifest / attestation). One `docker pull` increments the tag's index AND the
platform manifest, so platform-manifest counts are the "station pulls".
"""
import html as htmlmod
import re
from concurrent.futures import ThreadPoolExecutor

from . import http

ROW_TAGGED = re.compile(
    r"(?P<pre>.*?)Published (?P<pub>.+?)\s*·\s*Digest\s*…?\s*sha256:(?P<sha>[0-9a-f]{64})\s+(?P<dl>\d[\d,]*)\s*$",
    re.S,
)
ROW_UNTAGGED = re.compile(r"sha256:(?P<sha>[0-9a-f]{64})\s+Published (?P<pub>.+?)\s+(?P<dl>\d[\d,]*)\s*$", re.S)
HEADER = re.compile(r"Versions (\d+) tagged (\d+) untagged")
TAG_TOKEN = re.compile(r"^[A-Za-z0-9][\w.\-]{0,127}$")
TAG_STOP = {"untagged", "tagged", "versions", "downloads", "digest"}

ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])


def strip_html(raw):
    text = re.sub(r"<script.*?</script>", " ", raw, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = htmlmod.unescape(text)
    return re.sub(r"\s+", " ", text)


def _tags_from_pre(pre):
    tags = []
    for tok in reversed(pre.replace(",", " ").split()):
        if tok.lower() in TAG_STOP or tok.isdigit() or not TAG_TOKEN.match(tok):
            break
        tags.append(tok)
        if len(tags) >= 6:
            break
    return list(reversed(tags))


def parse_versions_page(raw):
    """Return (rows, header). rows: [{sha, dl, tags, pub}] in page order."""
    text = strip_html(raw)
    hdr = HEADER.search(text)
    header = {"tagged": int(hdr.group(1)), "untagged": int(hdr.group(2))} if hdr else None
    rows = []
    for seg in text.split("Version downloads")[:-1]:
        m = ROW_TAGGED.search(seg)
        if m:
            rows.append({"sha": m.group("sha"), "dl": int(m.group("dl").replace(",", "")),
                         "tags": _tags_from_pre(m.group("pre")), "pub": m.group("pub").strip()})
            continue
        m = ROW_UNTAGGED.search(seg)
        if m:
            rows.append({"sha": m.group("sha"), "dl": int(m.group("dl").replace(",", "")),
                         "tags": [], "pub": m.group("pub").strip()})
    return rows, header


def fetch_versions(owner_repo, image, max_pages=40, fetch=http.get_text):
    """Scrape every versions page until a page yields nothing new."""
    seen, rows, header = set(), [], None
    for page in range(1, max_pages + 1):
        raw = fetch(f"https://github.com/{owner_repo}/pkgs/container/{image}/versions?page={page}")
        page_rows, page_header = parse_versions_page(raw or "")
        header = header or page_header
        new = [r for r in page_rows if r["sha"] not in seen]
        if not new:
            break
        for r in new:
            seen.add(r["sha"])
            rows.append(r)
    if header and len(rows) < header["tagged"] + header["untagged"] - 5:
        raise RuntimeError(f"{image}: scraped {len(rows)} versions but header says "
                           f"{header['tagged'] + header['untagged']} - page format changed?")
    if not rows:
        raise RuntimeError(f"{image}: no versions parsed - page format changed?")
    return rows, header


# ---- registry walk -------------------------------------------------------

def registry_token(image_path):
    return http.get_json(f"https://ghcr.io/token?scope=repository:{image_path}:pull")["token"]


def classify(manifest):
    """Classify a manifest JSON: index (multi-platform), pidx (single-platform
    index from push-by-digest), attest (in-toto attestation) or manifest."""
    if "manifests" in manifest:
        children = []
        for x in manifest["manifests"]:
            arch = (x.get("platform") or {}).get("architecture", "?")
            children.append({"digest": x["digest"], "arch": "attest" if arch == "unknown" else arch})
        real = [c for c in children if c["arch"] != "attest"]
        return {"kind": "index" if len(real) >= 2 else "pidx", "children": children}
    layers = manifest.get("layers") or []
    if layers and "in-toto" in (layers[0].get("mediaType") or ""):
        return {"kind": "attest"}
    return {"kind": "manifest", "config": (manifest.get("config") or {}).get("digest")}


class Registry:
    """Anonymous read access to one GHCR repository with token refresh."""

    def __init__(self, image_path):
        self.image_path = image_path
        self.token = registry_token(image_path)

    def _get(self, path, accept):
        url = f"https://ghcr.io/v2/{self.image_path}/{path}"
        try:
            return http.get_json(url, headers={"Authorization": f"Bearer {self.token}", "Accept": accept})
        except http.HttpError as e:
            if e.code != 401:
                raise
            self.token = registry_token(self.image_path)
            return http.get_json(url, headers={"Authorization": f"Bearer {self.token}", "Accept": accept})

    def describe(self, sha):
        info = classify(self._get(f"manifests/sha256:{sha}", ACCEPT))
        cfg_digest = info.pop("config", None)
        if info["kind"] == "manifest" and cfg_digest:
            cfg = self._get(f"blobs/{cfg_digest}", "*/*")
            info["created"] = (cfg.get("created") or "")[:19]
            info["arch"] = cfg.get("architecture", "?")
        return info


def update_registry(image_path, shas, registry, log=print, workers=8):
    """Describe digests not yet in `registry` (dict sha -> info). Returns count added."""
    todo = [s for s in shas if s not in registry]
    if not todo:
        return 0
    reg = Registry(image_path)

    def work(sha):
        try:
            return sha, reg.describe(sha)
        except Exception as e:  # noqa: BLE001 - keep walking, retry next run
            log(f"  manifest walk failed for {sha[:12]}: {e}")
            return sha, None

    added = 0
    with ThreadPoolExecutor(workers) as ex:
        for sha, info in ex.map(work, todo):
            if info is not None:
                registry[sha] = info
                added += 1
    return added
