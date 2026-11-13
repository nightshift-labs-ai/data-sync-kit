import csv
import json
import os
import subprocess
import sys
from pathlib import Path

from sync.engine import run_sync

ROOT = Path(__file__).resolve().parents[1]


def counts(r):
    return r["counts"]


def test_first_run_creates_all(env):
    r = run_sync(env["cfg"])
    assert counts(r) == {"created": 5, "updated": 0, "skipped": 0, "failed": 0}
    rows = env["sheet"].records
    assert len(rows) == 5
    ana = next(x for x in rows.values() if x["crm_id"] == 1)
    assert ana["full_name"] == "Ana Petrova" and ana["status"] == "Active" and ana["signup_date"] == "05/01/2026"
    with open(r["csv"]) as f:
        assert [x["action"] for x in csv.DictReader(f)] == ["created"] * 5
    assert Path(r["log"]).read_text().count("created source_id=") == 5


def test_second_run_no_changes_does_nothing(env):
    run_sync(env["cfg"])
    before = json.dumps(env["sheet"].records, sort_keys=True)
    r = run_sync(env["cfg"])
    assert counts(r) == {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
    assert json.dumps(env["sheet"].records, sort_keys=True) == before


def test_edit_updates_exactly_one(env):
    run_sync(env["cfg"])
    env["crm"].edit(3, status="A", last_name="Li-Wong")
    writes_before = len(env["sheet"].requests)
    r = run_sync(env["cfg"])
    assert counts(r) == {"created": 0, "updated": 1, "skipped": 0, "failed": 0}
    assert r["rows"][0]["reason"] == "changed: full_name,status"
    assert len(env["sheet"].records) == 5
    chen = next(x for x in env["sheet"].records.values() if x["crm_id"] == 3)
    assert chen["full_name"] == "Chen Li-Wong" and chen["status"] == "Active"
    assert [m for m, _ in env["sheet"].requests[writes_before:] if m != "GET"] == ["PATCH"]


def test_dry_run_writes_nothing(env):
    r = run_sync(env["cfg"], dry_run=True)
    assert counts(r)["created"] == 5
    assert env["sheet"].records == {}
    assert not any(m != "GET" for m, _ in env["sheet"].requests)
    assert not Path(env["cfg"]["state_file"]).exists()


def test_429_then_success(env):
    env["crm"].fail_429 = 1
    env["sheet"].fail_429 = 1
    slept = []
    r = run_sync(env["cfg"], sleep=slept.append)
    assert counts(r)["created"] == 5
    assert r["retries"] == 2 and slept == [0.0, 0.0]  # Retry-After: 0 honored over backoff


def test_post_is_not_retried_after_5xx(env):
    """A POST that saved the row but lost its response must not be re-sent (that would duplicate the row)."""
    env["sheet"].fail_500_after_save = 1
    r = run_sync(env["cfg"], sleep=lambda d: None)
    ids = [row.get("crm_id") for row in env["sheet"].records.values()]
    assert len(ids) == len(set(ids)), f"duplicate target rows: {sorted(ids)}"
    assert counts(r)["failed"] == 1
    r2 = run_sync(env["cfg"], sleep=lambda d: None)  # next run finds the saved row by external id
    assert counts(r2)["failed"] == 0 and counts(r2)["created"] == 0


def test_backoff_is_exponential_without_retry_after():
    from sync.http import Client
    import urllib.error
    slept = []
    c = Client("http://127.0.0.1:9", max_attempts=4, base_delay=1, sleep=slept.append, timeout=1)
    try:
        c.request("GET", "/x")
    except urllib.error.URLError:
        pass
    assert slept == [1, 2, 4]


def test_bad_record_fails_without_stopping(env):
    env["crm"].records[6] = {"id": 6, "first_name": "Bad", "last_name": "Date", "email": "b@x.io", "status": "A",
                             "created": "31/12/2026", "updated_at": "2026-06-03T12:00:00.000000Z"}
    r = run_sync(env["cfg"])
    assert counts(r) == {"created": 5, "updated": 0, "skipped": 0, "failed": 1}
    bad = next(x for x in r["rows"] if x["action"] == "failed")
    assert bad["source_id"] == 6 and "bad date" in bad["reason"]
    # cursor stays before the failed record; after a fix it syncs, later records are just re-checked
    assert r["cursor"] == "2026-06-03T10:00:00.000000Z"
    env["crm"].edit(6, created="2026-12-31")
    r2 = run_sync(env["cfg"])
    assert counts(r2) == {"created": 1, "updated": 0, "skipped": 2, "failed": 0} and len(env["sheet"].records) == 6


def test_target_rejection_is_failed(env):
    env["crm"].records[2]["email"] = ""
    env["cfg"]["mapping"] = [m for m in env["cfg"]["mapping"] if m["to"] != "email"] + [{"to": "email", "from": "email"}]
    r = run_sync(env["cfg"])
    assert counts(r)["failed"] == 1 and "HTTP 422" in next(x["reason"] for x in r["rows"] if x["action"] == "failed")


def test_cli_end_to_end(env):
    e = dict(os.environ, PYTHONPATH=str(ROOT))
    cmd = [sys.executable, "-m", "sync", "run", "--config", str(env["path"])]
    out = subprocess.run(cmd + ["--dry-run"], capture_output=True, text=True, env=e, cwd=ROOT)
    assert "created=5" in out.stdout and env["sheet"].records == {}
    out = subprocess.run(cmd, capture_output=True, text=True, env=e, cwd=ROOT)
    assert out.returncode == 0 and "created=5" in out.stdout and len(env["sheet"].records) == 5
    e.pop("SHEET_KEY")
    out = subprocess.run(cmd, capture_output=True, text=True, env=e, cwd=ROOT)
    assert out.returncode != 0 and "SHEET_KEY" in out.stderr
