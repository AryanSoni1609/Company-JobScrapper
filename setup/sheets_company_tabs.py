# sheets_company_tabs.py
# Manages the company tabs in your Job Tracker Google Sheet.
# Does 3 things:
#
#   1. --setup        Upload companies with no ATS to "Companies with no ATS" tab
#                     (reads from ats_detection_history.csv)
#
#   2. --create-queue Create "Companies to be added" tab
#                     (a queue where you write company names to check)
#
#   3. --process      Process the "Companies to be added" queue:
#                     - Checks for duplicates
#                     - Runs ATS detection on each name
#                     - Routes to "Companies" tab (active=YES) or "Companies with no ATS"
#                     - Clears processed names from the queue automatically
#
#   --all             Run all 3 steps
#
# Usage:
#   python setup/sheets_company_tabs.py --all        (first-time setup)
#   python setup/sheets_company_tabs.py --process    (ongoing — after adding names to queue tab)
#
# Environment variables:
#   GOOGLE_SPREADSHEET_ID   — your Google Sheet ID
#   GOOGLE_CREDENTIALS_PATH — path to service account JSON (default: google_credentials.json)
#   OUTPUT_DIR              — where ats_detection_history.csv lives (default: ./output)

import sys
import csv
import time
import argparse
import requests
import os
from pathlib import Path
import gspread
from google.oauth2.service_account import Credentials

# ── CONFIG ────────────────────────────────────────────────────────────────────
SPREADSHEET_ID   = os.environ.get("GOOGLE_SPREADSHEET_ID", "YOUR_SPREADSHEET_ID_HERE")
CREDENTIALS_PATH = os.environ.get("GOOGLE_CREDENTIALS_PATH", "google_credentials.json")
OUTPUT_DIR       = os.environ.get("OUTPUT_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output"))
HISTORY_CSV      = os.path.join(OUTPUT_DIR, "ats_detection_history.csv")

TAB_COMPANIES = "Companies"           # existing tab (active=YES companies)
TAB_NO_ATS    = "Companies with no ATS"
TAB_QUEUE     = "Companies to be added"

HEADERS = [
    "company_name", "career_url", "ats_type", "board_token",
    "category", "scope_tags", "active", "notes", "job_count", "detected_date"
]

MIN_JOBS = 1   # must return at least this many jobs to count as valid


# ── GOOGLE SHEETS HELPERS ────────────────────────────────────────────────────

def connect_sheets():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    gc    = gspread.authorize(creds)
    sh    = gc.open_by_key(SPREADSHEET_ID)
    return sh


def get_or_create_tab(sh, tab_name, headers):
    """Return worksheet, creating it with headers if it doesn't exist."""
    try:
        ws = sh.worksheet(tab_name)
        print(f"  Tab '{tab_name}' already exists.")
        return ws
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab_name, rows=1000, cols=len(headers))
        ws.append_row(headers, value_input_option="RAW")
        print(f"  Created tab '{tab_name}' with headers.")
        return ws


def get_all_company_names(sh):
    """Return a set of lowercased company names already in Companies + No-ATS tabs."""
    names = set()
    for tab in [TAB_COMPANIES, TAB_NO_ATS]:
        try:
            ws   = sh.worksheet(tab)
            data = ws.get_all_records()
            for row in data:
                n = str(row.get("company_name", "")).strip().lower()
                if n:
                    names.add(n)
        except gspread.WorksheetNotFound:
            pass
    return names


def append_rows_to_tab(ws, rows, batch_size=50):
    """Append rows to a worksheet in batches."""
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        ws.append_rows(batch, value_input_option="RAW")
        time.sleep(1)


# ── ATS DETECTION ────────────────────────────────────────────────────────────

def make_token_variations(name):
    """Generate token candidates from a company name."""
    import re
    base = name.strip()

    suffixes = [
        r"\s+(GmbH|AG|SE|KG|OHG|UG|BV|NV|SAS|SRL|Ltd|LLC|Inc|Corp|Co\.|Group|Holding|Technologies|Technology|Solutions|Software|Labs|Studio|Studios|AI|io)\.?$"
    ]
    cleaned = base
    for pat in suffixes:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE).strip()

    variations = []
    for s in [cleaned, base]:
        lower   = s.lower()
        nospace = re.sub(r"\s+", "", lower)
        hyphen  = re.sub(r"\s+", "-", lower)
        nopunct = re.sub(r"[^a-z0-9]", "", lower)
        camel   = re.sub(r"\s+", "", s)

        for v in [lower, nospace, hyphen, nopunct, camel]:
            if v and v not in variations:
                variations.append(v)

    return variations


def try_greenhouse(token):
    for url in [
        f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
        f"https://job-boards.eu.greenhouse.io/{token}/jobs",
    ]:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                jobs = r.json().get("jobs", [])
                if len(jobs) >= MIN_JOBS:
                    return token, f"https://boards.greenhouse.io/{token}", len(jobs)
        except Exception:
            pass
    return None


def try_lever(token):
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    try:
        r    = requests.get(url, timeout=10)
        jobs = r.json()
        if r.status_code == 200 and isinstance(jobs, list) and len(jobs) >= MIN_JOBS:
            return token, f"https://jobs.lever.co/{token}", len(jobs)
    except Exception:
        pass
    return None


def try_ashby(token):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    try:
        r    = requests.get(url, timeout=10)
        jobs = r.json().get("jobPostings", []) if r.status_code == 200 else []
        if len(jobs) >= MIN_JOBS:
            return token, f"https://jobs.ashbyhq.com/{token}", len(jobs)
    except Exception:
        pass
    return None


def try_smartrecruiters(token):
    url = f"https://api.smartrecruiters.com/v1/companies/{token}/postings"
    try:
        r    = requests.get(url, timeout=10)
        jobs = r.json().get("content", []) if r.status_code == 200 else []
        if len(jobs) >= MIN_JOBS:
            return token, f"https://careers.smartrecruiters.com/{token}", len(jobs)
    except Exception:
        pass
    return None


def detect_ats(company_name):
    """
    Try all ATS platforms with all token variations.
    Returns (ats_type, token, career_url, job_count) or None.
    """
    variations = make_token_variations(company_name)
    checkers   = [
        ("greenhouse",      try_greenhouse),
        ("ashby",           try_ashby),
        ("lever",           try_lever),
        ("smartrecruiters", try_smartrecruiters),
    ]
    for token in variations:
        for ats_name, fn in checkers:
            result = fn(token)
            if result:
                found_token, career_url, job_count = result
                return ats_name, found_token, career_url, job_count
            time.sleep(0.2)
    return None


# ── STEP 1: Upload No-ATS history ────────────────────────────────────────────

def setup_no_ats_tab(sh):
    print("\n── STEP 1: Setting up 'Companies with no ATS' tab ──")

    try:
        active_ws    = sh.worksheet(TAB_COMPANIES)
        active_data  = active_ws.get_all_records()
        active_names = {str(r.get("company_name", "")).strip().lower() for r in active_data}
        print(f"  Found {len(active_names)} companies in '{TAB_COMPANIES}' tab.")
    except gspread.WorksheetNotFound:
        active_names = set()

    no_ats_ws       = get_or_create_tab(sh, TAB_NO_ATS, HEADERS)
    existing_no_ats = no_ats_ws.get_all_records()
    existing_names  = {str(r.get("company_name", "")).strip().lower() for r in existing_no_ats}
    print(f"  '{TAB_NO_ATS}' tab already has {len(existing_names)} rows.")

    history_path = Path(HISTORY_CSV)
    if not history_path.exists():
        print(f"  ERROR: History file not found at: {HISTORY_CSV}")
        print("  Make sure OUTPUT_DIR is set correctly and ats_detection_history.csv exists.")
        return

    rows_to_add    = []
    total_in_csv   = 0
    skipped_yes    = 0
    skipped_active = 0
    skipped_dup    = 0

    with open(history_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_in_csv += 1
            name       = str(row.get("company_name", "")).strip()
            name_lower = name.lower()
            active_val = str(row.get("active", "")).strip().upper()

            if active_val == "YES":
                skipped_yes += 1
                continue
            if name_lower in active_names:
                skipped_active += 1
                continue
            if name_lower in existing_names:
                skipped_dup += 1
                continue

            rows_to_add.append([
                name,
                str(row.get("career_url",    "")),
                str(row.get("ats_type",      "")),
                str(row.get("board_token",   "")),
                str(row.get("category",      "")),
                str(row.get("scope_tags",    "")),
                "NO",
                str(row.get("notes",         "")),
                str(row.get("job_count",     "")),
                str(row.get("detected_date", "")),
            ])

    print(f"\n  History CSV summary:")
    print(f"    Total rows in CSV:          {total_in_csv}")
    print(f"    Skipped (active=YES):       {skipped_yes}")
    print(f"    Skipped (in Companies tab): {skipped_active}")
    print(f"    Skipped (already in tab):   {skipped_dup}")
    print(f"    New rows to upload:         {len(rows_to_add)}")

    if not rows_to_add:
        print("  Nothing new to upload.")
        return

    print(f"  Uploading {len(rows_to_add)} rows to '{TAB_NO_ATS}' tab...")
    append_rows_to_tab(no_ats_ws, rows_to_add)
    print(f"  Done.")


# ── STEP 2: Create Queue tab ──────────────────────────────────────────────────

def create_queue_tab(sh):
    print("\n── STEP 2: Setting up 'Companies to be added' tab ──")
    get_or_create_tab(sh, TAB_QUEUE, ["company_name"])
    print(f"  Tab ready. Go to Google Sheet → '{TAB_QUEUE}' tab.")
    print("  Type one company name per row in column A.")
    print("  Then run:  python setup/sheets_company_tabs.py --process")


# ── STEP 3: Process Queue tab ────────────────────────────────────────────────

def process_queue(sh):
    print("\n── STEP 3: Processing 'Companies to be added' tab ──")

    try:
        queue_ws = sh.worksheet(TAB_QUEUE)
    except gspread.WorksheetNotFound:
        print(f"  ERROR: '{TAB_QUEUE}' tab not found. Run --create-queue first.")
        return

    queue_data     = queue_ws.get_all_records()
    names_to_check = [
        str(r.get("company_name", "")).strip()
        for r in queue_data
        if str(r.get("company_name", "")).strip()
    ]

    if not names_to_check:
        print("  No companies found in the queue tab. Add company names in column A.")
        return

    print(f"  Found {len(names_to_check)} companies to process: {names_to_check}")

    existing     = get_all_company_names(sh)
    companies_ws = sh.worksheet(TAB_COMPANIES)
    no_ats_ws    = get_or_create_tab(sh, TAB_NO_ATS, HEADERS)

    from datetime import date
    today = date.today().strftime("%Y-%m-%d")

    to_remove = []

    for i, name in enumerate(names_to_check):
        name_lower = name.lower()
        print(f"\n  [{i+1}/{len(names_to_check)}] Checking: {name}")

        if name_lower in existing:
            print(f"    → DUPLICATE — '{name}' already exists. Removing from queue.")
            to_remove.append(name)
            continue

        result = detect_ats(name)

        if result:
            ats_type, token, career_url, job_count = result
            print(f"    → FOUND: {ats_type.upper()} | token={token} | {job_count} jobs")
            row = [name, career_url, ats_type, token, "", "", "YES",
                   "Added via Companies to be added tab", job_count, today]
            companies_ws.append_row(row, value_input_option="RAW")
            existing.add(name_lower)
            print(f"    → Added to '{TAB_COMPANIES}' tab.")
        else:
            print(f"    → NOT FOUND: No supported ATS detected.")
            row = [name, "", "", "", "", "", "NO",
                   "No supported ATS found — checked via Companies to be added tab", 0, today]
            no_ats_ws.append_row(row, value_input_option="RAW")
            existing.add(name_lower)
            print(f"    → Added to '{TAB_NO_ATS}' tab.")

        to_remove.append(name)
        time.sleep(1)

    if to_remove:
        print(f"\n  Clearing {len(to_remove)} processed entries from queue tab...")
        all_rows  = queue_ws.get_all_records()
        remaining = [
            r for r in all_rows
            if str(r.get("company_name", "")).strip() not in to_remove
        ]
        queue_ws.clear()
        queue_ws.append_row(["company_name"], value_input_option="RAW")
        if remaining:
            queue_ws.append_rows(
                [[str(r.get("company_name", ""))] for r in remaining],
                value_input_option="RAW"
            )
        print("  Queue tab cleared of processed entries.")

    print("\n  Processing complete.")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Manage company tabs in Job Tracker Google Sheet")
    parser.add_argument("--setup",        action="store_true", help="Step 1: Upload no-ATS history to sheet")
    parser.add_argument("--create-queue", action="store_true", help="Step 2: Create 'Companies to be added' tab")
    parser.add_argument("--process",      action="store_true", help="Step 3: Process queue tab")
    parser.add_argument("--all",          action="store_true", help="Run all 3 steps")
    args = parser.parse_args()

    if not any([args.setup, args.create_queue, args.process, args.all]):
        parser.print_help()
        print("\nExamples:")
        print("  python setup/sheets_company_tabs.py --all")
        print("  python setup/sheets_company_tabs.py --setup")
        print("  python setup/sheets_company_tabs.py --create-queue")
        print("  python setup/sheets_company_tabs.py --process")
        return

    print("Connecting to Google Sheets...")
    sh = connect_sheets()
    print(f"Connected to spreadsheet.")

    if args.all or args.setup:
        setup_no_ats_tab(sh)
    if args.all or args.create_queue:
        create_queue_tab(sh)
    if args.all or args.process:
        process_queue(sh)

    print("\nAll done.")


if __name__ == "__main__":
    main()
