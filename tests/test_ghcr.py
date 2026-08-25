from collector import ghcr

SHA_A = "c8e957f1c71fdc8446f5d4a6a64b4818c4d99d25c17432fb3dc6c96339befa07"
SHA_B = "0f420b4f4c4d457" + "0" * 49
SHA_C = "6cd66fa8e0345118aca7e1d7d57267f8f576080074940b3fd3d06719b14d94dd"
SHA_D = "84089a2b4daf48a5f83cb04c049233599df1231a649b16718ca00351dc55365c"

PAGE = f"""<html><body><h2>Versions</h2><span>2 tagged</span> <span>1 untagged</span>
<a>staging</a> Published <relative-time>4 days ago</relative-time> &middot; Digest &hellip; <code>sha256:{SHA_A}</code>
<span>212</span> Version downloads
<a>main</a> Published <relative-time>4 days ago</relative-time> &middot; Digest &hellip; <code>sha256:{SHA_B}</code>
<span>56</span> Version downloads
<code>sha256:{SHA_C}</code> Published <relative-time>8 days ago</relative-time> <span>2</span> Version downloads
<script>var x = "Version downloads";</script></body></html>"""

ALEX_PAGE = f"""Versions 57 tagged 81 untagged <a>latest</a> <a>0.8.8</a> Published 3 days ago · Digest … sha256:{SHA_D} 1,079 Version downloads
sha256:{SHA_C} Published 3 days ago 12 Version downloads"""


def test_parse_versions_page_tagged_and_untagged():
    rows, header = ghcr.parse_versions_page(PAGE)
    assert header == {"tagged": 2, "untagged": 1}
    assert rows == [
        {"sha": SHA_A, "dl": 212, "tags": ["staging"], "pub": "4 days ago"},
        {"sha": SHA_B, "dl": 56, "tags": ["main"], "pub": "4 days ago"},
        {"sha": SHA_C, "dl": 2, "tags": [], "pub": "8 days ago"},
    ]


def test_parse_multi_tag_row_and_thousands():
    rows, _ = ghcr.parse_versions_page(ALEX_PAGE)
    assert rows[0]["tags"] == ["latest", "0.8.8"] and rows[0]["dl"] == 1079
    assert rows[1]["tags"] == [] and rows[1]["dl"] == 12


def test_fetch_versions_stops_when_page_repeats():
    pages = {1: PAGE, 2: PAGE, 3: ""}
    calls = []

    def fake(url):
        page = int(url.rsplit("=", 1)[1])
        calls.append(page)
        return pages[page]

    rows, header = ghcr.fetch_versions("Suncuss/BirdNET-PiPy", "img", fetch=fake, max_pages=5)
    assert len(rows) == 3 and calls == [1, 2]


def test_fetch_versions_raises_on_format_change():
    import pytest
    with pytest.raises(RuntimeError):
        ghcr.fetch_versions("o/r", "img", fetch=lambda url: "<html>nothing here</html>")


def test_classify_kinds():
    idx = {"manifests": [{"digest": "sha256:a", "platform": {"architecture": "arm64"}},
                         {"digest": "sha256:b", "platform": {"architecture": "amd64"}},
                         {"digest": "sha256:c", "platform": {"architecture": "unknown"}}]}
    assert ghcr.classify(idx)["kind"] == "index"
    assert [c["arch"] for c in ghcr.classify(idx)["children"]] == ["arm64", "amd64", "attest"]
    pidx = {"manifests": idx["manifests"][:1] + idx["manifests"][2:]}
    assert ghcr.classify(pidx)["kind"] == "pidx"
    assert ghcr.classify({"layers": [{"mediaType": "application/vnd.in-toto+json"}]})["kind"] == "attest"
    assert ghcr.classify({"config": {"digest": "sha256:cfg"}, "layers": [{"mediaType": "tar"}]}) == {"kind": "manifest", "config": "sha256:cfg"}
