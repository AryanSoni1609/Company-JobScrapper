"""Company names from https://github.com/liquidslr/leetcode-company-wise-problems.

Each top-level folder in that repo is one company (e.g. "Goldman Sachs").
The list is cached in data/leetcode_companies.json so a GitHub outage or
rate limit does not stop the scheduled sync.
"""

from __future__ import annotations

import json
import logging

import requests

from .config import load_settings

log = logging.getLogger("jobscraper.leetcode")

_IGNORE = {".github", "scripts", "assets", "docs", "images"}


def fetch_company_names(use_cache_on_error: bool = True) -> list[str]:
    settings = load_settings()
    cache = settings.data_dir / "leetcode_companies.json"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Company-JobScrapper"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    try:
        # The git tree API returns every top-level entry in one call (no 1000-item cap).
        url = f"https://api.github.com/repos/{settings.leetcode_repo}/git/trees/HEAD"
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        names = sorted(
            (e["path"] for e in resp.json().get("tree", [])
             if e.get("type") == "tree" and not e["path"].startswith(".") and e["path"].lower() not in _IGNORE),
            key=str.lower,
        )
        if names:
            settings.ensure_dirs()
            cache.write_text(json.dumps(names, indent=1), encoding="utf-8")
            return names
        raise ValueError("repository tree had no folders")
    except (requests.RequestException, ValueError) as e:
        if use_cache_on_error and cache.is_file():
            log.warning("Could not fetch LeetCode company list (%s); using cached copy", e)
            return json.loads(cache.read_text(encoding="utf-8"))
        raise
