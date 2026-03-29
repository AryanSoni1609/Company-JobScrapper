# company_scraper.py
# Scrapes job listings directly from company career pages using their ATS APIs.
# Reads company list from Google Sheet "Companies" tab.
# Output: raw_jobs_companies.csv
#
# Supported ATS platforms (API-only, no browser needed):
#   - Greenhouse (public JSON API)
#   - Lever (public JSON API)
#   - Ashby (official public REST API)
#   - SmartRecruiters (public JSON API)
#
# Usage:
#   python scraper/company_scraper.py
#
# Environment variables (set in .env or export before running):
#   GOOGLE_SPREADSHEET_ID   — your Google Sheet ID
#   GOOGLE_CREDENTIALS_PATH — path to your service account JSON (default: google_credentials.json)
#   OUTPUT_DIR              — where to write output CSV (default: ./output)

import requests
import csv
import os
import sys
import time
import re
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ---------- CONFIG ----------
SPREADSHEET_ID   = os.environ.get("GOOGLE_SPREADSHEET_ID", "YOUR_SPREADSHEET_ID_HERE")
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_PATH", "google_credentials.json")
OUTPUT_DIR       = os.environ.get("OUTPUT_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output"))
OUTPUT_FILE      = os.path.join(OUTPUT_DIR, "raw_jobs_companies.csv")
SHEET_NAME       = "Companies"

# ---------- KEYWORD FILTERS ----------
# 24 broad keywords — companies are pre-selected for relevance,
# broad keywords catch more role title variations than narrow ones.
SEARCH_KEYWORDS = [
    "ai", "strategy", "digital", "transformation", "intelligence",
    "analytics", "data", "consultant", "operations", "product",
    "chief of staff", "founder", "business", "advisor", "manager",
    "program", "project", "associate", "automation", "innovation",
    "change management", "stakeholder", "implementation", "deployment",
]

# Location keywords to identify Germany-based or remote/EMEA roles
GERMANY_LOCATIONS = [
    "germany", "deutschland", "munich", "muenchen", "berlin", "hamburg",
    "frankfurt", "stuttgart", "cologne", "koeln", "duesseldorf", "dusseldorf",
    "hannover", "hanover", "bonn", "heidelberg", "remote", "emea", "europe", "eu", "dach"
]

REQUEST_TIMEOUT          = 30
DELAY_BETWEEN_COMPANIES  = 1  # seconds between API calls


# ---------- HELPER: Strip HTML ----------
def strip_html(text):
    if not text:
        return ""
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<li[^>]*>', '\n- ', text, flags=re.IGNORECASE)
    text = re.sub(r'<p[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&#x27;', "'", text)
    text = re.sub(r'&#x2F;', '/', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ---------- HELPER: Check relevance ----------
def is_relevant_job(title, location, description=""):
    title_lower    = (title or "").lower()
    location_lower = (location or "").lower()
    desc_lower     = (description or "").lower()

    location_match = any(loc in location_lower for loc in GERMANY_LOCATIONS)
    if not location_match:
        return False

    search_text = title_lower + " " + desc_lower
    return any(kw in search_text for kw in SEARCH_KEYWORDS)


# ---------- ATS SCRAPERS ----------

def scrape_greenhouse(company_name, board_token):
    """Scrape jobs from Greenhouse public API."""
    url  = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
    jobs = []
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 404:
            print(f"    WARNING: board_token '{board_token}' not found on Greenhouse")
            return jobs, "NOT_FOUND"
        resp.raise_for_status()
        for job in resp.json().get("jobs", []):
            title       = job.get("title", "")
            location    = job.get("location", {}).get("name", "")
            description = strip_html(job.get("content", ""))
            job_url     = job.get("absolute_url", "")
            updated     = job.get("updated_at", "")
            if is_relevant_job(title, location, description):
                jobs.append({
                    "title": title, "company": company_name, "location": location,
                    "description": description, "url": job_url,
                    "source": f"{company_name} Careers",
                    "date_posted": updated[:10] if updated else "",
                })
        return jobs, "OK"
    except requests.exceptions.Timeout:
        print(f"    TIMEOUT for {company_name}")
        return jobs, "TIMEOUT"
    except Exception as e:
        print(f"    ERROR for {company_name}: {e}")
        return jobs, f"ERROR: {e}"


def scrape_lever(company_name, board_token):
    """Scrape jobs from Lever public API."""
    url  = f"https://api.lever.co/v0/postings/{board_token}?mode=json"
    jobs = []
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 404:
            print(f"    WARNING: board_token '{board_token}' not found on Lever")
            return jobs, "NOT_FOUND"
        resp.raise_for_status()
        for job in resp.json():
            title      = job.get("text", "")
            categories = job.get("categories", {})
            location   = categories.get("location", "")
            if isinstance(location, list):
                location = ", ".join(location) if location else ""

            desc_parts = []
            for section in job.get("lists", []):
                if section.get("text"):
                    desc_parts.append(section["text"])
                if section.get("content"):
                    desc_parts.append(strip_html(section["content"]))
            opening = job.get("descriptionPlain", "") or strip_html(job.get("description", ""))
            if opening:
                desc_parts.insert(0, opening)
            additional = job.get("additionalPlain", "") or strip_html(job.get("additional", ""))
            if additional:
                desc_parts.append(additional)

            description = "\n\n".join(desc_parts)
            job_url     = job.get("hostedUrl", "") or job.get("applyUrl", "")
            created     = job.get("createdAt", 0)
            date_str    = ""
            if created:
                try:
                    date_str = datetime.fromtimestamp(created / 1000).strftime("%Y-%m-%d")
                except Exception:
                    pass

            if is_relevant_job(title, location, description):
                jobs.append({
                    "title": title, "company": company_name, "location": location,
                    "description": description, "url": job_url,
                    "source": f"{company_name} Careers", "date_posted": date_str,
                })
        return jobs, "OK"
    except requests.exceptions.Timeout:
        print(f"    TIMEOUT for {company_name}")
        return jobs, "TIMEOUT"
    except Exception as e:
        print(f"    ERROR for {company_name}: {e}")
        return jobs, f"ERROR: {e}"


def scrape_ashby(company_name, board_token):
    """
    Scrape jobs from Ashby using the official public REST API.
    Endpoint: GET https://api.ashbyhq.com/posting-api/job-board/{token}

    IMPORTANT: Ashby tokens are case-sensitive (e.g. 'DeepL' not 'deepl').
    This function auto-tries common casing variants if the stored token fails.
    The old GraphQL endpoint (jobs.ashbyhq.com/api/non-user-graphql) was
    unreliable — always use this REST API instead.
    """
    jobs = []
    seen, token_variants = set(), []
    for t in [board_token, board_token.title(), board_token.lower(),
              board_token.capitalize(), board_token.upper()]:
        if t not in seen:
            seen.add(t)
            token_variants.append(t)

    working_token, all_job_data = None, None
    try:
        for variant in token_variants:
            resp = requests.get(
                f"https://api.ashbyhq.com/posting-api/job-board/{variant}",
                timeout=REQUEST_TIMEOUT
            )
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            data = resp.json()
            if data.get("jobs") is not None:
                working_token = variant
                all_job_data  = data.get("jobs", [])
                break

        if working_token is None:
            print(f"    WARNING: board_token '{board_token}' not found on Ashby")
            return jobs, "NOT_FOUND"
        if working_token != board_token:
            print(f"    NOTE: token '{board_token}' worked as '{working_token}' on Ashby")

        for job in all_job_data:
            title    = job.get("title", "")
            location = job.get("location", "")
            secondary = job.get("secondaryLocations", [])
            if secondary:
                sec_locs = [s.get("location", "") for s in secondary if s.get("location")]
                if sec_locs:
                    location = ", ".join([location] + sec_locs) if location else ", ".join(sec_locs)
            description = strip_html(job.get("descriptionHtml", "")) or job.get("descriptionPlain", "")
            job_url     = job.get("jobUrl", "") or job.get("applyUrl", "")
            published   = job.get("publishedAt", "")

            if is_relevant_job(title, location, description):
                jobs.append({
                    "title": title, "company": company_name, "location": location,
                    "description": description, "url": job_url,
                    "source": f"{company_name} Careers",
                    "date_posted": published[:10] if published else "",
                })
        return jobs, "OK"
    except requests.exceptions.Timeout:
        print(f"    TIMEOUT for {company_name}")
        return jobs, "TIMEOUT"
    except Exception as e:
        print(f"    ERROR for {company_name}: {e}")
        return jobs, f"ERROR: {e}"


def scrape_smartrecruiters(company_name, board_token):
    """Scrape jobs from SmartRecruiters public API.
    NOTE: SmartRecruiters returns HTTP 200 with 0 jobs for invalid company names.
    The MIN_JOBS_REQUIRED=1 check in ats_detector.py prevents false positives.
    """
    jobs   = []
    offset = 0
    limit  = 100
    try:
        while True:
            url  = f"https://api.smartrecruiters.com/v1/companies/{board_token}/postings?limit={limit}&offset={offset}"
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 404:
                print(f"    WARNING: board_token '{board_token}' not found on SmartRecruiters")
                return jobs, "NOT_FOUND"
            resp.raise_for_status()
            data     = resp.json()
            postings = data.get("content", [])
            if not postings:
                break

            for job in postings:
                title        = job.get("name", "")
                location_obj = job.get("location", {})
                location     = ", ".join(
                    x for x in [location_obj.get("city", ""),
                                 location_obj.get("region", ""),
                                 location_obj.get("country", "")] if x
                )
                department  = job.get("department", {}).get("label", "")
                description = f"Department: {department}" if department else ""
                job_url     = job.get("ref", "")
                if not job_url and job.get("id"):
                    job_url = f"https://jobs.smartrecruiters.com/{board_token}/{job['id']}"
                released = job.get("releasedDate", "")

                if is_relevant_job(title, location, description):
                    jobs.append({
                        "title": title, "company": company_name, "location": location,
                        "description": description, "url": job_url,
                        "source": f"{company_name} Careers",
                        "date_posted": released[:10] if released else "",
                    })

            total_found = data.get("totalFound", 0)
            offset += limit
            if offset >= total_found:
                break
        return jobs, "OK"
    except requests.exceptions.Timeout:
        print(f"    TIMEOUT for {company_name}")
        return jobs, "TIMEOUT"
    except Exception as e:
        print(f"    ERROR for {company_name}: {e}")
        return jobs, f"ERROR: {e}"


# ---------- DISPATCHER ----------
ATS_SCRAPERS = {
    "greenhouse":      scrape_greenhouse,
    "lever":           scrape_lever,
    "ashby":           scrape_ashby,
    "smartrecruiters": scrape_smartrecruiters,
}


# ---------- LOAD COMPANIES FROM GOOGLE SHEET ----------
def load_companies_from_sheet():
    """Load active companies from the Google Sheet 'Companies' tab."""
    try:
        import gspread
        gc          = gspread.service_account(filename=CREDENTIALS_FILE)
        spreadsheet = gc.open_by_key(SPREADSHEET_ID)
        worksheet   = spreadsheet.worksheet(SHEET_NAME)
        records     = worksheet.get_all_records()

        companies = []
        for row in records:
            if str(row.get("active", "")).strip().upper() == "YES":
                companies.append({
                    "company_name": row.get("company_name", "").strip(),
                    "career_url":   row.get("career_url",   "").strip(),
                    "ats_type":     row.get("ats_type",     "").strip().lower(),
                    "board_token":  row.get("board_token",  "").strip(),
                    "category":     row.get("category",     "").strip(),
                    "scope_tags":   row.get("scope_tags",   "").strip(),
                })
        return companies

    except Exception as e:
        print(f"ERROR loading companies from Google Sheet: {e}")
        print("Check that:")
        print("  1. GOOGLE_CREDENTIALS_PATH points to a valid service account JSON file")
        print("  2. GOOGLE_SPREADSHEET_ID is correct")
        print("  3. The 'Companies' tab exists (run setup/companies_sheet_setup.py first)")
        return []


# ---------- MAIN ----------
def main():
    print("=" * 60)
    print("COMPANY CAREER PAGE SCRAPER")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("\nLoading companies from Google Sheet...")
    companies = load_companies_from_sheet()

    if not companies:
        print("No active companies found. Exiting.")
        return

    print(f"Found {len(companies)} active companies to scrape.")

    all_jobs        = []
    success_count   = 0
    fail_count      = 0
    not_found_count = 0

    for i, company in enumerate(companies, 1):
        name        = company["company_name"]
        ats_type    = company["ats_type"]
        board_token = company["board_token"]

        if ats_type not in ATS_SCRAPERS:
            print(f"\n[{i}/{len(companies)}] {name} - SKIPPED (unsupported ATS: {ats_type})")
            fail_count += 1
            continue

        print(f"\n[{i}/{len(companies)}] {name} ({ats_type})...", end=" ", flush=True)
        scraper      = ATS_SCRAPERS[ats_type]
        jobs, status = scraper(name, board_token)

        if status == "OK":
            print(f"found {len(jobs)} relevant jobs")
            all_jobs.extend(jobs)
            success_count += 1
        elif status == "NOT_FOUND":
            not_found_count += 1
        else:
            fail_count += 1

        if i < len(companies):
            time.sleep(DELAY_BETWEEN_COMPANIES)

    # Deduplicate by URL
    seen_urls, unique_jobs = set(), []
    for job in all_jobs:
        url = job.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_jobs.append(job)
        elif not url:
            unique_jobs.append(job)

    print(f"\n{'=' * 60}")
    print("RESULTS:")
    print(f"  Companies scraped successfully: {success_count}")
    print(f"  Companies with errors:          {fail_count}")
    print(f"  Board tokens not found:         {not_found_count}")
    print(f"  Total relevant jobs found:      {len(unique_jobs)}")

    fieldnames = ["title", "company", "location", "description", "url", "source", "date_posted"]
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        if unique_jobs:
            writer.writerows(unique_jobs)

    print(f"\nSaved to: {OUTPUT_FILE}")

    if not_found_count > 0:
        print(f"\nIMPORTANT: {not_found_count} companies had invalid board_tokens.")
        print("Open your Google Sheet > Companies tab and fix the board_token column")
        print("for any companies that showed 'NOT_FOUND' above.")

    print(f"\nFinished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
