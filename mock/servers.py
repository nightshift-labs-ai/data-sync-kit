"""Two tiny in-memory mock APIs (127.0.0.1 only) for demos and tests.

crm   (source): GET /contacts?updated_since=&page=&per_page=   auth: Authorization: Bearer <token>
sheet (target): GET /rows?crm_id=  POST /rows  PATCH /rows/<id> auth: X-Api-Key: <key>
Either server can be told to answer 429 (Retry-After: 0) to the next N requests.
"""
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

CRM_TOKEN = "demo-crm-token"
SHEET_KEY = "demo-sheet-key"


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def seed_contacts():
    people = [("Ana", "Petrova", "ana@example.com", "A", "2026-01-05"),
              ("Boris", "Ivanov", "boris@example.com", "A", "2026-02-11"),
              ("Chen", "Li", "chen@example.com", "I", "2026-03-20"),
              ("Dana", "Kim", "dana@example.com", "A", "2026-04-02"),
              ("Eli", "Novak", "eli@example.com", "I", "2026-05-17")]
    return {i: {"id": i, "first_name": f, "last_name": l, "email": e, "status": s, "created": c,
                "updated_at": f"2026-06-0{i}T10:00:00.000000Z"}
            for i, (f, l, e, s, c) in enumerate(people, start=1)}


class MockServer:
    def __init__(self, kind, port=0, fail_429=0, records=None):
        self.kind, self.fail_429, self.lock = kind, fail_429, threading.Lock()
        self.records = records if records is not None else (seed_contacts() if kind == "crm" else {})
        self.requests = []
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"

    def start(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def edit(self, rid, **fields):  # simulate a user editing a CRM record
        with self.lock:
            self.records[rid].update(fields, updated_at=now_iso())

    def _handler(self):
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj=None, headers=None):
                body = json.dumps(obj).encode() if obj is not None else b""
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _gate(self):
                srv.requests.append((self.command, self.path))
                with srv.lock:
                    if srv.fail_429 > 0:
                        srv.fail_429 -= 1
                        self._send(429, {"error": "rate limited"}, {"Retry-After": "0"})
                        return False
                ok = (self.headers.get("Authorization") == f"Bearer {CRM_TOKEN}" if srv.kind == "crm"
                      else self.headers.get("X-Api-Key") == SHEET_KEY)
                if not ok:
                    self._send(401, {"error": "unauthorized"})
                return ok

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n) or b"{}")

            def do_GET(self):
                if not self._gate():
                    return
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                with srv.lock:
                    if srv.kind == "crm" and u.path == "/contacts":
                        since = q.get("updated_since", "")
                        recs = sorted((r for r in srv.records.values() if r["updated_at"] > since),
                                      key=lambda r: (r["updated_at"], r["id"]))
                        page, per = int(q.get("page", 1)), int(q.get("per_page", 2))
                        chunk = recs[(page - 1) * per: page * per]
                        nxt = page + 1 if page * per < len(recs) else None
                        return self._send(200, {"data": [dict(r) for r in chunk], "next_page": nxt})
                    if srv.kind == "sheet" and u.path == "/rows":
                        rows = [dict(r) for r in srv.records.values()
                                if all(str(r.get(k)) == v for k, v in q.items())]
                        return self._send(200, {"data": rows})
                self._send(404, {"error": "not found"})

            def do_POST(self):
                if not self._gate():
                    return
                if srv.kind != "sheet" or self.path != "/rows":
                    return self._send(404, {"error": "not found"})
                row = self._body()
                if not row.get("email"):
                    return self._send(422, {"error": "email is required"})
                with srv.lock:
                    rid = max(srv.records, default=0) + 1
                    srv.records[rid] = dict(row, id=rid)
                self._send(201, srv.records[rid])

            def do_PATCH(self):
                if not self._gate():
                    return
                parts = self.path.strip("/").split("/")
                if srv.kind != "sheet" or len(parts) != 2 or parts[0] != "rows" or not parts[1].isdigit():
                    return self._send(404, {"error": "not found"})
                with srv.lock:
                    rid = int(parts[1])
                    if rid not in srv.records:
                        return self._send(404, {"error": "no such row"})
                    srv.records[rid].update(self._body(), id=rid)
                    self._send(200, srv.records[rid])

        return H
