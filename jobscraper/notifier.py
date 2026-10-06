"""Send email through Gmail — Gmail API (OAuth) or SMTP with an App Password.

EMAIL_METHOD=gmail_api
    One-time: create an OAuth "Desktop app" client in Google Cloud Console,
    enable the Gmail API, save the JSON as GMAIL_CREDENTIALS_PATH and run
    `python -m jobscraper gmail-auth` to grant the gmail.send scope. The
    refresh token is stored in GMAIL_TOKEN_PATH (gitignored) and reused —
    copy it to a server to run headless there.
EMAIL_METHOD=smtp
    Turn on 2-Step Verification, create an App Password at
    https://myaccount.google.com/apppasswords and put it in SMTP_APP_PASSWORD.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import smtplib
from email.message import EmailMessage
from pathlib import Path

from .config import Settings, load_settings

log = logging.getLogger("jobscraper.notifier")

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
MAX_TOTAL_ATTACHMENT_BYTES = 20 * 1024 * 1024  # Gmail's limit is 25 MB incl. encoding overhead


class EmailNotConfigured(RuntimeError):
    pass


def build_message(settings: Settings, subject: str, html: str, text: str,
                  attachments: list[Path] | None = None) -> tuple[EmailMessage, list[Path]]:
    if not settings.email_to:
        raise EmailNotConfigured("NOTIFY_EMAIL_TO is not set in .env")
    msg = EmailMessage()
    msg["To"] = settings.email_to
    msg["From"] = settings.email_from or settings.smtp_username or settings.email_to
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    attached, total = [], 0
    for path in attachments or []:
        path = Path(path)
        if not path.is_file():
            continue
        size = path.stat().st_size
        if total + size > MAX_TOTAL_ATTACHMENT_BYTES:
            log.warning("Attachment limit reached; %s not attached", path.name)
            continue
        ctype, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
        attached.append(path)
        total += size
    return msg, attached


def gmail_credentials(settings: Settings, interactive: bool = False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = None
    if settings.gmail_token_path.is_file():
        creds = Credentials.from_authorized_user_file(str(settings.gmail_token_path), GMAIL_SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif interactive:
        from google_auth_oauthlib.flow import InstalledAppFlow
        if not settings.gmail_credentials_path.is_file():
            raise EmailNotConfigured(
                f"OAuth client file not found: {settings.gmail_credentials_path}. Download it from "
                "Google Cloud Console > APIs & Services > Credentials (Desktop app).")
        flow = InstalledAppFlow.from_client_secrets_file(str(settings.gmail_credentials_path), GMAIL_SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True)
    else:
        raise EmailNotConfigured(
            "No valid Gmail token. Run `python -m jobscraper gmail-auth` once on a machine with a "
            "browser (or switch EMAIL_METHOD=smtp).")
    settings.gmail_token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _send_gmail_api(settings: Settings, msg: EmailMessage) -> str:
    from googleapiclient.discovery import build

    service = build("gmail", "v1", credentials=gmail_credentials(settings), cache_discovery=False)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return sent.get("id", "")


def _send_smtp(settings: Settings, msg: EmailMessage) -> str:
    if not (settings.smtp_username and settings.smtp_app_password):
        raise EmailNotConfigured("SMTP_USERNAME and SMTP_APP_PASSWORD must be set for EMAIL_METHOD=smtp")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=60) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_username, settings.smtp_app_password)
        smtp.send_message(msg)
    return "smtp"


def send_email(subject: str, html: str, text: str, attachments: list[Path] | None = None) -> dict:
    settings = load_settings()
    msg, attached = build_message(settings, subject, html, text, attachments)
    if settings.email_method == "smtp":
        message_id = _send_smtp(settings, msg)
    elif settings.email_method in ("gmail_api", "gmail", "api"):
        message_id = _send_gmail_api(settings, msg)
    else:
        raise EmailNotConfigured(f"Unknown EMAIL_METHOD '{settings.email_method}' (use gmail_api or smtp)")
    log.info("Email sent to %s via %s (%d attachments)", settings.email_to, settings.email_method, len(attached))
    return {"to": settings.email_to, "method": settings.email_method, "message_id": message_id,
            "attachments": [p.name for p in attached]}
