import json
import time
import urllib.error
import urllib.request

UA = "Suncuss-repo-stats adoption collector (+https://github.com/Suncuss/Suncuss-repo-stats)"
RETRY_STATUS = {429, 500, 502, 503, 504}


class HttpError(Exception):
    def __init__(self, url, code):
        super().__init__(f"HTTP {code} for {url}")
        self.code = code


def get(url, headers=None, retries=3, timeout=30, ok404=False):
    hdrs = {"User-Agent": UA}
    hdrs.update(headers or {})
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404 and ok404:
                return None
            if e.code in RETRY_STATUS and attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise HttpError(url, e.code) from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise
    raise RuntimeError(f"unreachable: {url}")


def get_text(url, **kw):
    data = get(url, **kw)
    return None if data is None else data.decode("utf-8", "replace")


def get_json(url, **kw):
    text = get_text(url, **kw)
    return None if text is None else json.loads(text)
