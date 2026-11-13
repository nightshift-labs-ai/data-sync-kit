import csv
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .http import Client, HttpError
from .transforms import MappingError, map_record

log = logging.getLogger("sync")


def load_config(path):
    path = Path(path)
    cfg = yaml.safe_load(path.read_text())
    base = path.resolve().parent
    for key, default in (("state_file", "state.json"), ("runs_dir", "runs")):
        p = Path(cfg.get(key, default))
        cfg[key] = str(p if p.is_absolute() else base / p)
    return cfg


def _auth_headers(side):
    auth = side.get("auth")
    if not auth:
        return {}
    value = os.environ.get(auth["env"])
    if not value:
        raise SystemExit(f"missing env var {auth['env']} (auth for {side['base_url']})")
    return {auth["header"]: auth.get("prefix", "") + value}


def _client(side, cfg, sleep):
    r = cfg.get("retry", {})
    return Client(side["base_url"], _auth_headers(side), max_attempts=r.get("max_attempts", 5),
                  base_delay=r.get("base_delay", 0.5), max_delay=r.get("max_delay", 30), sleep=sleep)


def fetch_changed(client, src, since):
    """Yield source records with updated_at > since, following page-number pagination."""
    page = 1
    while page:
        params = {src.get("page_param", "page"): page, src.get("per_page_param", "per_page"): src.get("per_page", 100)}
        if since:
            params[src.get("since_param", "updated_since")] = since
        body = client.request("GET", src["endpoint"], params=params)
        for rec in body[src.get("data_key", "data")]:
            yield rec
        page = body.get(src.get("next_key", "next_page"))


def run_sync(cfg, dry_run=False, sleep=None):
    import time
    sleep = sleep or time.sleep
    src, tgt, mapping = cfg["source"], cfg["target"], cfg["mapping"]
    state_path, runs = Path(cfg["state_file"]), Path(cfg["runs_dir"])
    runs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f")
    log_path, csv_path = runs / f"{stamp}.log", runs / f"{stamp}_summary.csv"

    handler = logging.FileHandler(log_path)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        since = state.get("cursor")
        log.info("run start dry_run=%s cursor=%s", dry_run, since)
        sc, tc = _client(src, cfg, sleep), _client(tgt, cfg, sleep)
        id_f, upd_f = src.get("id_field", "id"), src.get("updated_field", "updated_at")
        ext_f, lookup = tgt["external_id_field"], tgt.get("lookup_param", tgt["external_id_field"])
        rows, counts = [], {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
        max_ok, first_fail, ok_updates = since, None, []

        for rec in fetch_changed(sc, src, since):
            sid, upd, ext = rec.get(id_f), rec.get(upd_f), None
            try:
                out = map_record(mapping, rec)
                ext = out.get(ext_f)
                if ext in (None, ""):
                    raise MappingError(f"{ext_f}: external id is empty")
                found = tc.request("GET", tgt["endpoint"], params={lookup: ext})[tgt.get("data_key", "data")]
                if len(found) > 1:
                    raise MappingError(f"{len(found)} target rows share {ext_f}={ext}")
                if not found:
                    action, reason = "created", "new record"
                    if not dry_run:
                        tc.request("POST", tgt["endpoint"], body=out)
                else:
                    row = found[0]
                    diff = sorted(k for k, v in out.items() if row.get(k) != v)
                    if not diff:
                        action, reason = "skipped", "unchanged"
                    else:
                        action, reason = "updated", "changed: " + ",".join(diff)
                        if not dry_run:
                            path = f"{tgt['endpoint'].rstrip('/')}/{row[tgt.get('row_id_field', 'id')]}"
                            tc.request(tgt.get("update_method", "PATCH"), path, body=out)
                if upd:
                    ok_updates.append(upd)
                    if max_ok is None or upd > max_ok:
                        max_ok = upd
            except (MappingError, HttpError) as e:
                action, reason = "failed", str(e)
                if upd and (first_fail is None or upd < first_fail):
                    first_fail = upd
            counts[action] += 1
            rows.append({"source_id": sid, "external_id": ext or "", "action": action,
                         "reason": reason, "dry_run": dry_run})
            log.info("%s source_id=%s %s", action, sid, reason)

        # Never move the cursor past a failed record, so it is retried next run
        # (records after it are re-read and come back as "skipped: unchanged").
        cursor = max_ok
        if first_fail is not None:
            cursor = max([u for u in ok_updates if u < first_fail], default=since)
        if not dry_run:
            state.update({"cursor": cursor, "last_run": stamp, "last_counts": counts})
            state_path.write_text(json.dumps(state, indent=2))
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["source_id", "external_id", "action", "reason", "dry_run"])
            w.writeheader()
            w.writerows(rows)
        log.info("run end counts=%s retries=%d cursor=%s", counts, sc.retries + tc.retries, cursor)
        return {"counts": counts, "rows": rows, "csv": str(csv_path), "log": str(log_path),
                "cursor": cursor, "retries": sc.retries + tc.retries}
    finally:
        log.removeHandler(handler)
        handler.close()
