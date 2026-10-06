"""Command line entry point:  python -m jobscraper <command>

Commands:
    sync-companies   detect ATS for new LeetCode-list companies, append to sheet
    scan             scrape active companies, append new matching jobs to the Jobs tab
    status           show local state counters and the active preferences
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import setup_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m jobscraper", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("sync-companies", help="add new companies from the LeetCode list")
    p.add_argument("--batch-size", type=int, default=None, help="max companies to detect this run")
    p.add_argument("--all", action="store_true", help="detect every remaining company (slow)")

    p = sub.add_parser("scan", help="scrape companies and append new matching jobs")
    p.add_argument("--company", action="append", help="only scan this company (repeatable)")

    sub.add_parser("status", help="show state counters and preferences")

    args = parser.parse_args(argv)
    setup_logging()

    if args.command == "sync-companies":
        from .pipeline import sync_companies
        result = sync_companies(batch_size=10_000 if args.all else args.batch_size)
    elif args.command == "scan":
        from .pipeline import scan_jobs
        result = scan_jobs(company_filter=args.company)
    elif args.command == "status":
        from .preferences import load_preferences
        from .state import State
        prefs = load_preferences()
        result = {**State().stats(), "preferences_file": prefs.source_path, "preferences": prefs.summary()}
    else:  # pragma: no cover
        parser.error(f"unknown command {args.command}")
        return 2

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
