"""Settings loaded from the environment / .env file.

Every value has a safe default so modules can be imported without a .env.
Relative paths are resolved against the repository root, so commands work
no matter which directory they are started from.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional at import time
    load_dotenv = None

REPO_ROOT = Path(__file__).resolve().parent.parent

if load_dotenv is not None:
    load_dotenv(REPO_ROOT / ".env", override=False)


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value.strip() if value is not None and value.strip() != "" else default


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _path(name: str, default: str) -> Path:
    raw = _env(name, default)
    if not raw:
        return Path()
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (REPO_ROOT / p).resolve()


@dataclass(frozen=True)
class Settings:
    # Google Sheets
    spreadsheet_id: str
    google_credentials_path: Path
    companies_tab: str
    no_ats_tab: str
    jobs_tab: str

    # Email
    email_method: str
    email_to: str
    email_from: str
    gmail_credentials_path: Path
    gmail_token_path: Path
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_app_password: str
    digest_max_attachments: int
    digest_send_empty: bool

    # Schedule
    timezone: str
    digest_time: str
    scan_interval_hours: int
    company_sync_interval_days: int

    # Company sources
    leetcode_repo: str
    github_token: str
    detection_batch_size: int

    # Personal files
    job_preference_path: Path
    resume_details_path: Path
    resume_template_path: Path | None

    # Paths
    output_dir: Path
    data_dir: Path
    resumes_dir: Path
    log_dir: Path

    # MCP
    mcp_transport: str
    mcp_host: str
    mcp_port: int

    @property
    def sheets_configured(self) -> bool:
        return (
            bool(self.spreadsheet_id)
            and self.spreadsheet_id != "your_spreadsheet_id_here"
            and self.google_credentials_path.is_file()
        )

    @property
    def state_db_path(self) -> Path:
        return self.data_dir / "state.db"

    def ensure_dirs(self) -> None:
        for d in (self.output_dir, self.data_dir, self.resumes_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    """Read settings fresh from the environment (cheap; call whenever needed)."""
    template = _env("RESUME_TEMPLATE_PATH")
    return Settings(
        spreadsheet_id=_env("GOOGLE_SPREADSHEET_ID"),
        google_credentials_path=_path("GOOGLE_CREDENTIALS_PATH", "google_credentials.json"),
        companies_tab=_env("SHEET_COMPANIES_TAB", "Companies"),
        no_ats_tab=_env("SHEET_NO_ATS_TAB", "Companies with no ATS"),
        jobs_tab=_env("SHEET_JOBS_TAB", "Jobs"),
        email_method=_env("EMAIL_METHOD", "gmail_api").lower(),
        email_to=_env("NOTIFY_EMAIL_TO"),
        email_from=_env("NOTIFY_EMAIL_FROM"),
        gmail_credentials_path=_path("GMAIL_CREDENTIALS_PATH", "gmail_credentials.json"),
        gmail_token_path=_path("GMAIL_TOKEN_PATH", "gmail_token.json"),
        smtp_host=_env("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=_int("SMTP_PORT", 587),
        smtp_username=_env("SMTP_USERNAME"),
        smtp_app_password=_env("SMTP_APP_PASSWORD"),
        digest_max_attachments=_int("DIGEST_MAX_ATTACHMENTS", 15),
        digest_send_empty=_env("DIGEST_SEND_EMPTY", "yes").lower() in ("yes", "true", "1", "on"),
        timezone=_env("TIMEZONE", "Asia/Kolkata"),
        digest_time=_env("DIGEST_TIME", "21:00"),
        scan_interval_hours=max(1, _int("SCAN_INTERVAL_HOURS", 6)),
        company_sync_interval_days=max(1, _int("COMPANY_SYNC_INTERVAL_DAYS", 7)),
        leetcode_repo=_env("LEETCODE_REPO", "liquidslr/leetcode-company-wise-problems"),
        github_token=_env("GITHUB_TOKEN"),
        detection_batch_size=max(1, _int("DETECTION_BATCH_SIZE", 60)),
        job_preference_path=_path("JOB_PREFERENCE_PATH", "job_preference.md"),
        resume_details_path=_path("RESUME_DETAILS_PATH", "resume_details.md"),
        resume_template_path=_path("RESUME_TEMPLATE_PATH", template) if template else None,
        output_dir=_path("OUTPUT_DIR", "output"),
        data_dir=_path("DATA_DIR", "data"),
        resumes_dir=_path("RESUMES_DIR", "resumes"),
        log_dir=_path("LOG_DIR", "logs"),
        mcp_transport=_env("MCP_TRANSPORT", "stdio"),
        mcp_host=_env("MCP_HOST", "127.0.0.1"),
        mcp_port=_int("MCP_PORT", 8765),
    )


def setup_logging(name: str = "jobscraper", to_stderr: bool = True) -> logging.Logger:
    """Log to logs/jobscraper.log and (optionally) stderr.

    stdout is never used so the MCP stdio transport stays clean.
    """
    settings = load_settings()
    settings.ensure_dirs()
    root = logging.getLogger("jobscraper")
    if not root.handlers:
        root.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        fh = logging.FileHandler(settings.log_dir / "jobscraper.log", encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
        if to_stderr:
            sh = logging.StreamHandler(sys.stderr)
            sh.setFormatter(fmt)
            root.addHandler(sh)
    return logging.getLogger(name)
