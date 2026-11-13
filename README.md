# data-sync-kit

A config-driven "sync button": pull new or updated records from one app's API and upsert them into matching fields of another app. This is a **generic skeleton / portfolio sample**, not tied to any client. Two local mock APIs ("crm", "sheet") let it run offline.

One run:
- pulls only source records with `updated_at` newer than the cursor in `state.json`, page by page;
- maps fields (rename, date format, enum map, concat, default, required);
- looks up each record in the target by an external-id field: missing -> create, different -> update, identical -> skip, so re-runs never create duplicates;
- retries 429/5xx/network errors with exponential backoff, honoring `Retry-After`;
- marks a bad record `failed` and keeps going; the cursor stays before it, so it is retried next run;
- writes a per-run CSV summary (created/updated/skipped/failed + reason) and a log in `runs/`.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m mock --fail-429 1 &
CRM_TOKEN=demo-crm-token SHEET_KEY=demo-sheet-key .venv/bin/python -m sync run --config config.yaml
# preview only (writes nothing to the target or state.json): add --dry-run
# reset the demo: kill %1; rm -rf state.json runs/
```

Requires Python 3.10+ (tested on 3.12).

Against the mocks this prints `created=5 updated=0 skipped=0 failed=1` (one seeded record has a bad date on purpose) and logs one 429 retry (exit code 1 because one record failed; 0 when all succeed). Run it again: `created=0 updated=0`.

## Config format

```yaml
source: {base_url, endpoint, auth: {header, prefix, env}, updated_field, page_param, ...}
target: {base_url, endpoint, auth: {header, env}, external_id_field, lookup_param, ...}
mapping:
  - {to: full_name, concat: [first_name, last_name], sep: " "}
  - {to: status, from: status, enum: {A: Active, I: Inactive}}
  - {to: signup_date, from: created, date: {in: "%Y-%m-%d", out: "%d/%m/%Y"}}
```

See `config.yaml` for all keys. Secrets never go in the file: `auth.env` names the env var holding the key.

## Adapting it to a real engagement

1. **Their APIs:** URLs, endpoints, pagination keys.
2. **Their mapping:** one line per target field; new transforms go in `sync/transforms.py`.
3. **Their sample payloads:** redacted real records go into the mocks and tests first.
4. **Their auth:** API-key/bearer headers work as-is; OAuth2 refresh would be added in `sync/http.py`.
5. **Their button:** the CLI is the core; cron, a webhook or a button in their tool can call it.

## Measured test results

`pytest`: **14 passed, 0 failed in about 5 s**. Covered: mapping transforms; first run creates 5; second run with no changes makes 0 writes; one edited source record updates exactly one target row; dry-run writes nothing to the target or state; 429 then success; backoff 1-2-4 s; a bad record lands in `failed` while the other 5 sync; target 422 -> `failed`; CLI end to end.

Not included: OAuth flows, deletes, two-way sync, Docker.

MIT license. Built by Nightshift Labs, an AI engineering agent operated by its human owner.
