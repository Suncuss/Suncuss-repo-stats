"""GitHub API data (public endpoints; token optional but raises rate limits)."""
import csv
import io
import os

from . import http
from .config import STATS_REPO, TRAFFIC_BRANCH, TRAFFIC_CSV_PATH

API = "https://api.github.com"


def _headers(accept="application/vnd.github+json"):
    h = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def api(path, accept=None):
    return http.get_json(f"{API}/{path}", headers=_headers(accept or "application/vnd.github+json"))


def paginate(path, accept=None, max_pages=30):
    sep = "&" if "?" in path else "?"
    out = []
    for page in range(1, max_pages + 1):
        chunk = api(f"{path}{sep}per_page=100&page={page}", accept)
        items = chunk.get("workflow_runs") if isinstance(chunk, dict) else chunk
        out.extend(items or [])
        if not items or len(items) < 100:
            break
    return out


def fetch_repo(owner, repo):
    r = api(f"repos/{owner}/{repo}")
    return {"stars": r["stargazers_count"], "forks": r["forks_count"], "watchers": r["subscribers_count"],
            "open_issues": r["open_issues_count"], "created": r["created_at"][:10]}


def fetch_stars(owner, repo):
    items = paginate(f"repos/{owner}/{repo}/stargazers", accept="application/vnd.github.star+json")
    return sorted(x["starred_at"][:10] for x in items)


def fetch_tags(owner, repo, cache):
    """cache: dict name -> {date, sha}; only unknown tags cost a commit lookup."""
    for t in paginate(f"repos/{owner}/{repo}/tags"):
        if t["name"] not in cache:
            commit = api(f"repos/{owner}/{repo}/commits/{t['commit']['sha']}")
            cache[t["name"]] = {"date": commit["commit"]["committer"]["date"][:10], "sha": t["commit"]["sha"][:10]}
    return sorted(({"name": k, **v} for k, v in cache.items()), key=lambda x: (x["date"], x["name"]))


def fetch_issues(owner, repo):
    out = []
    for i in paginate(f"repos/{owner}/{repo}/issues?state=all"):
        out.append({"number": i["number"], "created": i["created_at"][:10], "author": i["user"]["login"],
                    "is_pr": "pull_request" in i, "state": i["state"], "comments": i["comments"]})
    return out


def fetch_discussions(owner, repo):
    """GraphQL needs a token; returns None without one."""
    if not (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")):
        return None
    import json
    import urllib.request
    q = {"query": '{ repository(owner:"%s", name:"%s") { discussions(first:100) { totalCount nodes { author { login } createdAt } } } }' % (owner, repo)}
    req = urllib.request.Request(f"{API}/graphql", data=json.dumps(q).encode(), headers={**_headers(), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)["data"]["repository"]["discussions"]
    return {"total": data["totalCount"],
            "items": [{"created": n["createdAt"][:10], "author": (n["author"] or {}).get("login", "?")} for n in data["nodes"]]}


def fetch_build_runs(owner, repo, cache, workflow="build-images.yml"):
    """cache: dict id -> {created, branch}. Successful runs only."""
    for r in paginate(f"repos/{owner}/{repo}/actions/workflows/{workflow}/runs?status=success", max_pages=5):
        cache[str(r["id"])] = {"created": r["created_at"][:19], "branch": r["head_branch"]}
    return sorted(cache.values(), key=lambda x: x["created"])


def fetch_traffic():
    url = f"https://raw.githubusercontent.com/{STATS_REPO}/{TRAFFIC_BRANCH}/{TRAFFIC_CSV_PATH}"
    text = http.get_text(url, ok404=True)
    if not text:
        return []
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        rows.append({"date": r["time_iso8601"][:10], "clones": int(float(r["clones_total"] or 0)),
                     "clones_unique": int(float(r["clones_unique"] or 0)), "views": int(float(r["views_total"] or 0)),
                     "views_unique": int(float(r["views_unique"] or 0))})
    return sorted(rows, key=lambda x: x["date"])
