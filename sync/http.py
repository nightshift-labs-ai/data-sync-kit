import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("sync")
RETRY_STATUSES = {429, 500, 502, 503, 504}


class HttpError(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body


class Client:
    def __init__(self, base_url, headers=None, max_attempts=5, base_delay=0.5, max_delay=30, timeout=20, sleep=time.sleep):
        self.base = base_url.rstrip("/")
        self.headers = dict(headers or {})
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.timeout = timeout
        self.sleep = sleep
        self.retries = 0

    def request(self, method, path, params=None, body=None):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Accept": "application/json", **self.headers}
        if data is not None:
            headers["Content-Type"] = "application/json"
        for attempt in range(1, self.max_attempts + 1):
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as e:
                status, text, retry_after = e.code, e.read().decode(errors="replace"), e.headers.get("Retry-After")
                # POST is not idempotent: after a 5xx the row may already be saved, so only 429 is retried.
                retryable = status == 429 if method == "POST" else status in RETRY_STATUSES
                if not retryable or attempt == self.max_attempts:
                    raise HttpError(status, text)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if method == "POST" or attempt == self.max_attempts:
                    raise
                status, retry_after = f"network error ({getattr(e, 'reason', e)})", None
            delay = min(self.base_delay * 2 ** (attempt - 1), self.max_delay)
            if retry_after:
                try:
                    delay = min(float(retry_after), self.max_delay)
                except ValueError:
                    pass
            self.retries += 1
            log.warning("%s %s -> %s; retry %d/%d in %.2fs", method, path, status, attempt, self.max_attempts - 1, delay)
            self.sleep(delay)
