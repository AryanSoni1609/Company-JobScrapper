"""Append-only Google Sheets access.

Rule for this project: sheets are NEVER cleared, deleted, re-created or
overwritten. The only write operations here are:
  * add_worksheet  — when a tab does not exist yet
  * append_rows    — adding rows after the last filled row
Existing rows are only ever read (for de-duplication).
"""

from __future__ import annotations

import logging
import time

from .config import Settings, load_settings

log = logging.getLogger("jobscraper.sheets")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

COMPANY_HEADERS = ["company_name", "career_url", "ats_type", "board_token",
                   "category", "scope_tags", "active", "notes", "job_count", "detected_date"]

JOB_HEADERS = ["date_added", "company", "title", "role_category", "location", "employment_type",
               "salary", "date_posted", "ats", "job_url", "apply_url", "match_score",
               "matched_keywords", "resume_file", "status", "job_id"]


class SheetsNotConfigured(RuntimeError):
    pass


class AppendOnlySheets:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_settings()
        if not self.settings.sheets_configured:
            raise SheetsNotConfigured(
                "Google Sheets is not configured: set GOOGLE_SPREADSHEET_ID and "
                "GOOGLE_CREDENTIALS_PATH in .env (and share the sheet with the service account).")
        import gspread
        from google.oauth2.service_account import Credentials

        self._gspread = gspread
        creds = Credentials.from_service_account_file(str(self.settings.google_credentials_path), scopes=SCOPES)
        self.client = gspread.authorize(creds)
        self.spreadsheet = self.client.open_by_key(self.settings.spreadsheet_id)

    # ── tabs ──────────────────────────────────────────────────────────────
    def tab(self, name: str, headers: list[str]):
        """Return the worksheet, creating it (with a header row) only if missing."""
        try:
            ws = self.spreadsheet.worksheet(name)
        except self._gspread.WorksheetNotFound:
            ws = self.spreadsheet.add_worksheet(title=name, rows=1000, cols=max(len(headers), 10))
            ws.append_row(headers, value_input_option="RAW")
            log.info("Created tab '%s'", name)
            return ws
        if not ws.row_values(1):
            # Tab exists but is completely empty — appending a header is still append-only.
            ws.append_row(headers, value_input_option="RAW")
        return ws

    def records(self, name: str, headers: list[str]) -> list[dict]:
        ws = self.tab(name, headers)
        return ws.get_all_records(default_blank="")

    def column_values(self, name: str, headers: list[str], column: str) -> set[str]:
        ws = self.tab(name, headers)
        header_row = [h.strip() for h in ws.row_values(1)]
        if column not in header_row:
            return set()
        idx = header_row.index(column) + 1
        return {v.strip() for v in ws.col_values(idx)[1:] if v.strip()}

    # ── writes (append only) ──────────────────────────────────────────────
    def append(self, name: str, headers: list[str], rows: list[dict | list], batch_size: int = 100) -> int:
        """Append rows to the end of a tab. Dict rows are mapped onto the tab's header order."""
        if not rows:
            return 0
        ws = self.tab(name, headers)
        header_row = [h.strip() for h in ws.row_values(1)] or headers
        values = []
        for row in rows:
            if isinstance(row, dict):
                values.append([_cell(row.get(h, "")) for h in header_row])
            else:
                values.append([_cell(v) for v in row])
        for i in range(0, len(values), batch_size):
            ws.append_rows(values[i:i + batch_size], value_input_option="RAW",
                           insert_data_option="INSERT_ROWS", table_range="A1")
            if i + batch_size < len(values):
                time.sleep(1)  # stay under the Sheets write quota
        log.info("Appended %d rows to '%s'", len(values), name)
        return len(values)

    # ── convenience ───────────────────────────────────────────────────────
    def company_names(self) -> set[str]:
        """Lower-cased names already present in the Companies and no-ATS tabs."""
        names = set()
        for tab in (self.settings.companies_tab, self.settings.no_ats_tab):
            names |= {n.lower() for n in self.column_values(tab, COMPANY_HEADERS, "company_name")}
        return names

    def active_companies(self) -> list[dict]:
        out = []
        for row in self.records(self.settings.companies_tab, COMPANY_HEADERS):
            if str(row.get("active", "")).strip().upper() == "YES":
                out.append({
                    "company_name": str(row.get("company_name", "")).strip(),
                    "ats_type": str(row.get("ats_type", "")).strip().lower(),
                    "board_token": str(row.get("board_token", "")).strip(),
                    "category": str(row.get("category", "")).strip(),
                })
        return [c for c in out if c["company_name"] and c["board_token"]]

    def job_urls(self) -> set[str]:
        return self.column_values(self.settings.jobs_tab, JOB_HEADERS, "job_url")


def _cell(value) -> str | int | float:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    return text[:49_000]  # Sheets cell limit is 50k characters
