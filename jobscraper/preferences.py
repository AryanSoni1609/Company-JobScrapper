"""Parse job_preference.md into a Preferences object.

The file is re-read on every call to load_preferences(), so the user can edit
it while the scheduler is running and the next scan picks the change up.

Format (see job_preference.example.md):
    ## Section heading      -> setting name (lowercased, spaces -> "_")
    - value, value          -> list values
    - key: value            -> key/value settings (Compensation, Options)
    <!-- comments -->       -> ignored
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import REPO_ROOT, load_settings

log = logging.getLogger("jobscraper.preferences")

EXAMPLE_PATH = REPO_ROOT / "job_preference.example.md"

_TRUE = {"yes", "y", "true", "1", "on"}


@dataclass
class Preferences:
    job_types: list[str] = field(default_factory=list)
    technical_roles: list[str] = field(default_factory=list)
    managerial_roles: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    exclude_locations: list[str] = field(default_factory=list)

    minimum_lpa: float = 0.0
    tolerance_percent: float = 0.0
    include_unknown_salary: bool = True
    usd_to_inr: float = 88.0
    eur_to_inr: float = 100.0
    gbp_to_inr: float = 115.0

    include_unknown_location: bool = False
    match_roles_in_description: bool = False
    max_job_age_days: int = 0

    source_path: str = ""

    @property
    def role_keywords(self) -> list[str]:
        return self.technical_roles + self.managerial_roles

    @property
    def minimum_inr_per_year(self) -> float:
        """Lowest acceptable yearly pay in INR after applying the tolerance."""
        return self.minimum_lpa * 100_000 * (1 - self.tolerance_percent / 100)

    def summary(self) -> str:
        return (
            f"job types: {', '.join(self.job_types) or 'any'} | "
            f"roles: {len(self.technical_roles)} technical + {len(self.managerial_roles)} managerial keywords | "
            f"locations: {', '.join(self.locations) or 'any'} | "
            f"min pay: {self.minimum_lpa:g} LPA (-{self.tolerance_percent:g}% tolerance), "
            f"unknown pay {'kept' if self.include_unknown_salary else 'dropped'}"
        )


def _split_values(text: str) -> list[str]:
    return [v.strip().lower() for v in text.split(",") if v.strip()]


def parse_preferences(text: str, source_path: str = "") -> Preferences:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        heading = re.match(r"^##\s+(.+?)\s*#*$", line)
        if heading:
            current = re.sub(r"[^a-z0-9]+", "_", heading.group(1).lower()).strip("_")
            sections.setdefault(current, [])
            continue
        bullet = re.match(r"^[-*+]\s+(.+)$", line)
        if bullet and current:
            sections[current].append(bullet.group(1).strip())

    prefs = Preferences(source_path=source_path)

    list_fields = {
        "job_types": "job_types",
        "job_type": "job_types",
        "technical_roles": "technical_roles",
        "managerial_roles": "managerial_roles",
        "management_roles": "managerial_roles",
        "exclude_keywords": "exclude_keywords",
        "locations": "locations",
        "exclude_locations": "exclude_locations",
    }
    for section, attr in list_fields.items():
        for item in sections.get(section, []):
            getattr(prefs, attr).extend(_split_values(item))

    # key: value settings may live under any section (Compensation / Options)
    for items in sections.values():
        for item in items:
            kv = re.match(r"^([A-Za-z_ ]+?)\s*[:=]\s*(.+)$", item)
            if not kv:
                continue
            key = re.sub(r"\s+", "_", kv.group(1).strip().lower())
            value = kv.group(2).strip().lower()
            if not hasattr(prefs, key) or key == "source_path":
                continue
            current_value = getattr(prefs, key)
            try:
                if isinstance(current_value, bool):
                    setattr(prefs, key, value in _TRUE)
                elif isinstance(current_value, int):
                    setattr(prefs, key, int(float(re.sub(r"[^\d.]", "", value) or 0)))
                elif isinstance(current_value, float):
                    setattr(prefs, key, float(re.sub(r"[^\d.]", "", value) or 0))
            except ValueError:
                log.warning("Ignoring invalid preference %s: %r", key, value)

    for attr in list_fields.values():
        # de-duplicate while preserving order
        setattr(prefs, attr, list(dict.fromkeys(getattr(prefs, attr))))
    return prefs


def load_preferences(path: Path | None = None) -> Preferences:
    """Load job_preference.md, falling back to the example file."""
    path = path or load_settings().job_preference_path
    if not path.is_file():
        log.warning("%s not found — using %s. Copy it to job_preference.md to customise.",
                    path, EXAMPLE_PATH.name)
        path = EXAMPLE_PATH
    return parse_preferences(path.read_text(encoding="utf-8"), str(path))
