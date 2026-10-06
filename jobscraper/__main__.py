"""Command line entry point:  python -m jobscraper <command>

Commands:
    sync-companies   detect ATS for new LeetCode-list companies, append to sheet
    scan             scrape active companies, append new matching jobs to the Jobs tab
    tailor           (re)build the tailored resume for a tracked job URL
    digest           email new companies/jobs + tailored resumes (use --dry-run to preview)
    nightly          scan, then send the digest (what the 21:00 schedule runs)
    gmail-auth       one-time Gmail OAuth consent (EMAIL_METHOD=gmail_api)
    daemon           run forever: scans, company sync and the 21:00 digest on schedule
    serve            start the MCP server (stdio by default; --with-scheduler to run autonomously)
    make-template    write a starter Word template (templates/resume_template.docx)
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

    p = sub.add_parser("tailor", help="(re)build the tailored resume for a tracked job")
    p.add_argument("job_url")

    p = sub.add_parser("make-template", help="write a starter docxtpl Word template")
    p.add_argument("--path", default="templates/resume_template.docx")

    p = sub.add_parser("digest", help="send the email digest now")
    p.add_argument("--dry-run", action="store_true", help="write output/digest_preview.html, send nothing")
    p.add_argument("--skip-if-empty", action="store_true", help="do not email when nothing is new")

    sub.add_parser("nightly", help="scan then send the digest")
    sub.add_parser("gmail-auth", help="authorise Gmail sending (opens a browser)")

    sub.add_parser("daemon", help="run the scheduler in the foreground")

    p = sub.add_parser("serve", help="start the MCP server")
    p.add_argument("--transport", choices=["stdio", "streamable-http", "sse"], default=None,
                   help="default: MCP_TRANSPORT from .env (stdio)")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--with-scheduler", action="store_true",
                   help="also run scans, company sync and the 21:00 digest inside the server")

    sub.add_parser("status", help="show state counters and preferences")

    args = parser.parse_args(argv)
    if args.command == "serve":
        from .mcp_server import serve
        serve(args.transport, args.with_scheduler, args.host, args.port)
        return 0
    setup_logging()

    if args.command == "sync-companies":
        from .pipeline import sync_companies
        result = sync_companies(batch_size=10_000 if args.all else args.batch_size)
    elif args.command == "scan":
        from .pipeline import scan_jobs
        result = scan_jobs(company_filter=args.company)
    elif args.command == "tailor":
        from .pipeline import tailor_existing_job
        result = tailor_existing_job(args.job_url)
    elif args.command == "make-template":
        from pathlib import Path

        from .config import REPO_ROOT
        from .resume import make_starter_template
        path = Path(args.path)
        path = make_starter_template(path if path.is_absolute() else REPO_ROOT / path)
        result = {"template": str(path),
                  "next_step": f"Restyle it in Word, then set RESUME_TEMPLATE_PATH={args.path} in .env"}
    elif args.command == "digest":
        from .digest import send_digest
        result = send_digest(send_if_empty=not args.skip_if_empty, dry_run=args.dry_run)
    elif args.command == "nightly":
        from .pipeline import run_nightly
        result = run_nightly()
    elif args.command == "gmail-auth":
        from .config import load_settings
        from .notifier import gmail_credentials
        gmail_credentials(load_settings(), interactive=True)
        result = {"ok": True, "token_saved_to": str(load_settings().gmail_token_path)}
    elif args.command == "daemon":
        from .scheduler import run_forever
        run_forever()
        return 0
    elif args.command == "status":
        from .preferences import load_preferences
        from .state import State
        from .config import load_settings
        prefs = load_preferences()
        settings = load_settings()
        result = {**State().stats(), "preferences_file": prefs.source_path, "preferences": prefs.summary(),
                  "sheets_configured": settings.sheets_configured,
                  "resume_details_present": settings.resume_details_path.is_file(),
                  "email_method": settings.email_method, "email_to": settings.email_to or "(not set)",
                  "digest_time": f"{settings.digest_time} {settings.timezone}"}
    else:  # pragma: no cover
        parser.error(f"unknown command {args.command}")
        return 2

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
