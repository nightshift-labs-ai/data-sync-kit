import argparse
import sys

from .engine import load_config, run_sync


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m sync", description="Pull changed records from a source API and upsert them into a target API.")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run one sync pass")
    r.add_argument("--config", required=True)
    r.add_argument("--dry-run", action="store_true", help="read and plan only; write nothing to the target or state")
    a = p.parse_args(argv)
    cfg = load_config(a.config)
    s = run_sync(cfg, dry_run=a.dry_run)
    print("created={created} updated={updated} skipped={skipped} failed={failed}".format(**s["counts"]))
    print("summary: " + s["csv"])
    print("log:     " + s["log"])
    return 1 if s["counts"]["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
