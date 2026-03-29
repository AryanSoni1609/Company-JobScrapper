# companies_sheet_setup.py
# One-time setup: Creates the "Companies" tab in your Google Sheet
# and populates it with a starter list of 40 companies across 4 ATS platforms.
#
# Run this ONCE when setting up a new Google Sheet.
# After that, add companies via the "Companies to be added" queue tab.
#
# Usage:
#   python setup/companies_sheet_setup.py
#
# Environment variables:
#   GOOGLE_SPREADSHEET_ID   — your Google Sheet ID
#   GOOGLE_CREDENTIALS_PATH — path to service account JSON (default: google_credentials.json)

import gspread
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ---------- CONFIG ----------
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_PATH", "google_credentials.json")
SPREADSHEET_ID   = os.environ.get("GOOGLE_SPREADSHEET_ID", "YOUR_SPREADSHEET_ID_HERE")
SHEET_NAME       = "Companies"

# ---------- COMPANY DATA ----------
# Format: [company_name, career_url, ats_type, board_token, category, scope_tags, active, notes]
#
# ats_type: greenhouse / lever / ashby / smartrecruiters
# board_token: the identifier used in the ATS API URL
#   - Greenhouse:      https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs
#   - Lever:           https://api.lever.co/v0/postings/{board_token}
#   - Ashby:           https://api.ashbyhq.com/posting-api/job-board/{board_token}
#   - SmartRecruiters: https://api.smartrecruiters.com/v1/companies/{board_token}/postings
#
# To find a board_token: go to the company careers page, click any job.
# The URL reveals the ATS and token. See README.md for detailed instructions.
#
# active = NO means the company is disabled (unsupported ATS or custom career site).
# The scraper skips rows where active != YES.

COMPANIES = [
    # ===== 1. AI/TECH STARTUPS & SCALEUPS =====
    ["Celonis",         "https://www.celonis.com/careers/",           "greenhouse",      "celonis",                "AI Startup",  "GenAI, BI, Consulting", "YES", "Process mining + AI. Confirmed Greenhouse."],
    ["DeepL",           "https://www.deepl.com/en/careers/",          "ashby",           "DeepL",                  "AI Startup",  "GenAI, BI",             "YES", "AI translation. Confirmed Ashby. Token is case-sensitive: DeepL."],
    ["Personio",        "https://www.personio.com/about-personio/careers/", "greenhouse", "personio",              "AI Startup",  "CoS, BI, Consulting",   "NO",  "Uses own Personio ATS — not supported."],
    ["N26",             "https://n26.com/en/careers",                 "greenhouse",      "n26",                    "AI Startup",  "BI, CoS, GenAI",        "YES", "Neobank. Confirmed Greenhouse."],
    ["Trade Republic",  "https://traderepublic.com/careers",          "greenhouse",      "TradeRepublic",          "AI Startup",  "CoS, BI",               "NO",  "Custom popup career page — no public ATS API."],
    ["Scalable Capital","https://www.scalable.capital/en/careers",    "smartrecruiters", "ScalableGmbH",           "AI Startup",  "BI, CoS",               "YES", "Fintech. Confirmed SmartRecruiters."],
    ["FlixBus (Flix)",  "https://www.flixbus.com/company/jobs",       "greenhouse",      "flix",                   "AI Startup",  "BI, Consulting, CoS",   "YES", "Mobility unicorn. Confirmed Greenhouse."],
    ["Contentful",      "https://www.contentful.com/careers/",        "greenhouse",      "contentful",             "AI Startup",  "Consulting, GenAI",     "YES", "CMS platform. Confirmed Greenhouse."],
    ["Staffbase",       "https://staffbase.com/en/career",            "greenhouse",      "staffbase",              "AI Startup",  "GenAI, CoS",            "YES", "Employee comms + AI. Confirmed Greenhouse."],
    ["Helsing",         "https://helsing.ai/careers",                 "greenhouse",      "helsing",                "AI Startup",  "GenAI, CoS",            "YES", "Defense AI. Confirmed Greenhouse."],
    ["FINN",            "https://www.finn.auto/careers",              "lever",           "finn",                   "AI Startup",  "CoS, BI",               "YES", "Car subscription. Confirmed Lever."],
    ["Parloa",          "https://www.parloa.com/careers/",            "greenhouse",      "parloa",                 "AI Startup",  "GenAI, Consulting",     "YES", "Conversational AI. Confirmed Greenhouse (eu.greenhouse.io)."],
    ["Aleph Alpha",     "https://aleph-alpha.com/careers/",           "ashby",           "AlephAlpha",             "AI Startup",  "GenAI, Consulting",     "YES", "Enterprise AI. Confirmed Ashby. Token: AlephAlpha (case-sensitive)."],
    ["Merantix",        "https://merantix.com/careers/",              "lever",           "merantix",               "AI Startup",  "GenAI, CoS",            "NO",  "Uses Personio ATS — not supported."],
    ["commercetools",   "https://commercetools.com/careers",          "greenhouse",      "commercetools",          "AI Startup",  "Consulting, BI",        "YES", "Commerce platform. Confirmed Greenhouse."],
    ["Taxfix",          "https://taxfix.de/en/careers/",              "ashby",           "taxfix.com",             "AI Startup",  "CoS, BI",               "YES", "Fintech. Confirmed Ashby. Token includes .com suffix: taxfix.com."],
    ["Enpal",           "https://www.enpal.de/karriere",              "smartrecruiters", "EnpalBV",                "AI Startup",  "CoS, BI",               "YES", "Green energy. Confirmed SmartRecruiters."],
    ["Omio",            "https://www.omio.com/careers",               "smartrecruiters", "Omio1",                  "AI Startup",  "BI, GenAI",             "YES", "Travel tech. Confirmed SmartRecruiters."],

    # ===== 2. LARGE CORPORATES =====
    ["Bosch",           "https://www.bosch.com/careers/",             "smartrecruiters", "BoschGroup",             "Corporate",   "GenAI, BI, Consulting", "YES", "Confirmed SmartRecruiters."],
    ["Continental",     "https://www.continental.com/en/career/",     "smartrecruiters", "Continental",            "Corporate",   "BI, Consulting",        "YES", "Auto + tech. Confirmed SmartRecruiters."],
    ["Zalando",         "https://jobs.zalando.com/en/",               "greenhouse",      "zalando",                "Corporate",   "BI, GenAI, CoS",        "NO",  "Custom popup career page — no public ATS API."],
    ["Delivery Hero",   "https://careers.deliveryhero.com/",          "smartrecruiters", "DeliveryHero",           "Corporate",   "BI, CoS",               "YES", "Food delivery. Confirmed SmartRecruiters."],
    ["HelloFresh",      "https://www.hellofreshgroup.com/en/careers/","greenhouse",      "hellofresh",             "Corporate",   "BI, CoS",               "YES", "Food tech. Confirmed Greenhouse."],
    ["TeamViewer",      "https://www.teamviewer.com/en/careers/",     "smartrecruiters", "TeamViewer",             "Corporate",   "GenAI, Consulting",     "YES", "Confirmed SmartRecruiters."],
    ["trivago",         "https://company.trivago.com/careers/",       "greenhouse",      "trivago",                "Corporate",   "BI, GenAI",             "YES", "Travel tech. Confirmed Greenhouse."],
    ["AUTO1 Group",     "https://www.auto1-group.com/careers/",       "lever",           "auto1",                  "Corporate",   "BI, CoS",               "NO",  "Custom career site — no public ATS API."],

    # ===== 3. INTERNATIONAL COMPANIES =====
    ["Datadog",         "https://www.datadoghq.com/careers/",         "greenhouse",      "datadog",                "International","Consulting, GenAI",     "YES", "Observability. Confirmed Greenhouse."],
    ["Mistral AI",      "https://mistral.ai/careers/",                "lever",           "mistral",                "International","GenAI, Consulting",     "YES", "French AI leader. Confirmed Lever."],
    ["MongoDB",         "https://www.mongodb.com/company/careers",    "greenhouse",      "mongodb",                "International","Consulting, GenAI",     "YES", "Database + AI. Confirmed Greenhouse."],
    ["HubSpot",         "https://www.hubspot.com/careers",            "greenhouse",      "hubspot",                "International","Consulting, BI",        "YES", "CRM/marketing. Confirmed Greenhouse."],
    ["Notion",          "https://www.notion.so/careers",              "ashby",           "notion",                 "International","GenAI, CoS",            "YES", "Productivity + AI. Confirmed Ashby."],
    ["Stripe",          "https://stripe.com/jobs",                    "ashby",           "stripe",                 "International","CoS, BI",               "NO",  "Custom career site — no public ATS API."],
    ["Miro",            "https://miro.com/careers/",                  "greenhouse",      "realtimeboardglobal",    "International","GenAI, Consulting",     "YES", "Collaboration + AI. Legal name: RealtimeBoard. Token: realtimeboardglobal."],
    ["GitLab",          "https://about.gitlab.com/jobs/",             "greenhouse",      "gitlab",                 "International","GenAI, Consulting",     "YES", "DevOps + AI. Remote-first. Confirmed Greenhouse."],
    ["Figma",           "https://www.figma.com/careers/",             "greenhouse",      "figma",                  "International","GenAI, CoS",            "YES", "Design tool + AI. Confirmed Greenhouse."],
    ["Cloudflare",      "https://www.cloudflare.com/careers/",        "greenhouse",      "cloudflare",             "International","Consulting, GenAI",     "YES", "Infrastructure + AI. Confirmed Greenhouse."],

    # ===== 4. CONSULTING FIRMS =====
    ["Thoughtworks",    "https://www.thoughtworks.com/careers",       "smartrecruiters", "ThoughtWorks",           "Consulting",  "Consulting, GenAI",     "YES", "Tech consulting. Confirmed SmartRecruiters."],
    ["Capgemini Invent","https://www.capgemini.com/careers/",         "greenhouse",      "capgeminideutschlandgmbh","Consulting", "Consulting, GenAI",     "YES", "Digital + AI consulting. Token: capgeminideutschlandgmbh. Confirmed Greenhouse (eu.greenhouse.io)."],
    ["Simon-Kucher",    "https://www.simon-kucher.com/en/careers",    "ashby",           "simon-kucher",           "Consulting",  "Consulting, BI",        "NO",  "Uses Cornerstone OnDemand (csod) — not supported."],
    ["Publicis Sapient","https://www.publicissapient.com/careers",    "lever",           "publicissapient",        "Consulting",  "Consulting, GenAI",     "NO",  "Uses iCIMS — not supported."],
]


# ---------- MAIN ----------
def main():
    print("=" * 60)
    print("COMPANIES SHEET SETUP")
    print("=" * 60)

    if SPREADSHEET_ID == "YOUR_SPREADSHEET_ID_HERE":
        print("\nERROR: GOOGLE_SPREADSHEET_ID environment variable is not set.")
        print("Set it before running:")
        print("  export GOOGLE_SPREADSHEET_ID=your_sheet_id_here")
        print("  export GOOGLE_CREDENTIALS_PATH=path/to/google_credentials.json")
        return

    print("\nConnecting to Google Sheets...")
    try:
        gc           = gspread.service_account(filename=CREDENTIALS_FILE)
        spreadsheet  = gc.open_by_key(SPREADSHEET_ID)
        print(f"Connected to: {spreadsheet.title}")
    except Exception as e:
        print(f"ERROR connecting to Google Sheets: {e}")
        print("Make sure GOOGLE_CREDENTIALS_PATH is correct and the service account has access.")
        return

    existing_sheets = [ws.title for ws in spreadsheet.worksheets()]
    if SHEET_NAME in existing_sheets:
        print(f"\nWARNING: '{SHEET_NAME}' tab already exists!")
        response = input("Delete it and recreate? (yes/no): ").strip().lower()
        if response != "yes":
            print("Cancelled. No changes made.")
            return
        worksheet = spreadsheet.worksheet(SHEET_NAME)
        spreadsheet.del_worksheet(worksheet)
        print(f"Deleted existing '{SHEET_NAME}' tab.")

    print(f"\nCreating '{SHEET_NAME}' tab...")
    worksheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows=200, cols=8)

    headers = ["company_name", "career_url", "ats_type", "board_token",
               "category", "scope_tags", "active", "notes"]
    worksheet.update(range_name="A1:H1", values=[headers])

    print(f"Adding {len(COMPANIES)} companies...")
    if COMPANIES:
        worksheet.update(range_name=f"A2:H{len(COMPANIES) + 1}", values=COMPANIES)

    worksheet.format("A1:H1", {
        "textFormat": {"bold": True},
        "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}
    })

    active_count   = sum(1 for c in COMPANIES if c[6] == "YES")
    disabled_count = sum(1 for c in COMPANIES if c[6] == "NO")

    print(f"\nDone! '{SHEET_NAME}' tab created with {len(COMPANIES)} companies.")
    print(f"  Active (will be scraped): {active_count}")
    print(f"  Disabled (unsupported ATS): {disabled_count}")
    print(f"\nNext step: run the scraper!")
    print(f"  python scraper/company_scraper.py")
    print(f"\nTo add more companies later:")
    print(f"  python setup/sheets_company_tabs.py --create-queue")
    print(f"  python setup/sheets_company_tabs.py --process")


if __name__ == "__main__":
    main()
