from collector import github_data

COMMITS = {"557e287fbcaa": "2026-09-20T04:30:15Z", "2bc4dee0b2aa": "2026-09-20T23:45:14Z"}


def test_fetch_tags_backfills_commit_time(monkeypatch):
    tags = [{"name": "v0.8.10", "commit": {"sha": "2bc4dee0b2aa"}}, {"name": "v0.8.9", "commit": {"sha": "557e287fbcaa"}}]
    monkeypatch.setattr(github_data, "paginate", lambda path, accept=None, max_pages=30: tags)
    calls = []

    def api(path, accept=None):
        calls.append(path)
        return {"commit": {"committer": {"date": COMMITS[path.rsplit("/", 1)[1]]}}}
    monkeypatch.setattr(github_data, "api", api)
    # v0.8.9 was cached before times were recorded; v0.8.10 already has one
    cache = {"v0.8.9": {"date": "2026-09-20", "sha": "557e287fbc"},
             "v0.8.10": {"date": "2026-09-20", "time": "2026-09-20T23:45:14", "sha": "2bc4dee0b2"}}
    out = github_data.fetch_tags("o", "r", cache)
    assert calls == ["repos/o/r/commits/557e287fbcaa"]
    assert cache["v0.8.9"] == {"date": "2026-09-20", "time": "2026-09-20T04:30:15", "sha": "557e287fbc"}
    assert [t["name"] for t in out] == ["v0.8.9", "v0.8.10"]
