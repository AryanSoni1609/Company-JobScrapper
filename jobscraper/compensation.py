"""Extract pay from job postings and normalise it to INR per year.

Sources, in order of trust:
  1. Structured ATS fields (Lever salaryRange, Ashby compensation)
  2. Free text in the title/description: "8-12 LPA", "₹50,000/month",
     "$45/hour", "€60k per year", ...

Everything is converted to rupees per year so it can be compared with
job_preference.md's minimum_lpa. Stipends (monthly) are multiplied by 12,
hourly pay by 2080 (40 h x 52 weeks).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .preferences import Preferences

HOURS_PER_YEAR = 2080


@dataclass
class Compensation:
    min_inr_year: float
    max_inr_year: float
    source: str          # "structured" or "text"
    raw: str             # what we parsed, for the sheet / email

    @property
    def display(self) -> str:
        lo, hi = self.min_inr_year / 100_000, self.max_inr_year / 100_000
        rng = f"{lo:.1f} LPA" if abs(hi - lo) < 0.05 else f"{lo:.1f}-{hi:.1f} LPA"
        return f"{rng} (from: {self.raw})"


def _rate(currency: str, prefs: Preferences) -> float | None:
    c = (currency or "").strip().upper()
    if c in ("INR", "₹", "RS", "RS."):
        return 1.0
    if c in ("USD", "$", "US$"):
        return prefs.usd_to_inr
    if c in ("EUR", "€"):
        return prefs.eur_to_inr
    if c in ("GBP", "£"):
        return prefs.gbp_to_inr
    return None


def _per_year(interval: str) -> float:
    i = (interval or "").lower()
    if "hour" in i:
        return HOURS_PER_YEAR
    if "week" in i:
        return 52
    if "month" in i:
        return 12
    return 1


def from_structured(min_value, max_value, currency: str, interval: str,
                    prefs: Preferences) -> Compensation | None:
    rate = _rate(currency, prefs)
    try:
        lo = float(min_value) if min_value not in (None, "") else None
        hi = float(max_value) if max_value not in (None, "") else None
    except (TypeError, ValueError):
        return None
    if rate is None or (lo is None and hi is None):
        return None
    lo = lo if lo is not None else hi
    hi = hi if hi is not None else lo
    mult = _per_year(interval) * rate
    raw = f"{currency} {lo:,.0f}-{hi:,.0f} {interval}".strip()
    return Compensation(lo * mult, hi * mult, "structured", raw)


_NUM = r"(\d{1,3}(?:,\d{2,3})+|\d+(?:\.\d+)?)"
_SEP = r"\s*(?:-|–|—|to)\s*"
_INTERVAL = (r"(?P<interval>per\s+(?:annum|year|month|hour|week)|/\s*(?:yr|year|annum|mo|month|hr|hour|week)"
             r"|p\.?a\.?\b|p\.?m\.?\b|annually|monthly|hourly|a\s+year|an\s+hour|a\s+month)")

# "8 LPA", "8-12 LPA", "10 lakhs per annum", "12 L"
_LPA_RE = re.compile(
    rf"(?<![\w.]){_NUM}(?:{_SEP}{_NUM})?\s*(?:lpa|lakhs?(?:\s+per\s+annum)?|lacs?|l\.p\.a\.?)\b",
    re.IGNORECASE,
)
# "₹50,000/month", "INR 6,00,000 - 9,00,000 per annum", "$45/hour", "€60k a year"
_MONEY_RE = re.compile(
    rf"(?P<cur>₹|inr|rs\.?|\$|usd|us\$|€|eur|£|gbp)\s*{_NUM}\s*(?P<k1>k\b)?"
    rf"(?:{_SEP}(?:₹|inr|rs\.?|\$|usd|us\$|€|eur|£|gbp)?\s*{_NUM}\s*(?P<k2>k\b)?)?"
    rf"\s*(?:{_INTERVAL})?",
    re.IGNORECASE,
)

_CUR_MAP = {"₹": "INR", "inr": "INR", "rs": "INR", "rs.": "INR",
            "$": "USD", "usd": "USD", "us$": "USD",
            "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP"}


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _interval_from_token(tok: str | None) -> str:
    t = (tok or "").lower().replace(" ", "")
    if any(x in t for x in ("hour", "hr")):
        return "hour"
    if "week" in t:
        return "week"
    if any(x in t for x in ("month", "/mo", "p.m", "pm")):
        return "month"
    if any(x in t for x in ("annum", "year", "yr", "p.a", "pa", "annually")):
        return "year"
    return ""


def from_text(text: str, prefs: Preferences) -> Compensation | None:
    """Best-effort pay extraction from free text. Returns the highest offer found."""
    if not text:
        return None
    found: list[Compensation] = []

    for m in _LPA_RE.finditer(text):
        lo = _num(m.group(1))
        hi = _num(m.group(2)) if m.group(2) else lo
        if 0.5 <= lo <= 200 and 0.5 <= hi <= 200:
            found.append(Compensation(lo * 100_000, hi * 100_000, "text", m.group(0).strip()))

    for m in _MONEY_RE.finditer(text):
        cur = _CUR_MAP.get(m.group("cur").lower().rstrip(), "")
        rate = _rate(cur, prefs)
        if rate is None:
            continue
        nums = [g for g in m.groups()[1:] if g and re.fullmatch(_NUM, g)]
        if not nums:
            continue
        lo = _num(nums[0]) * (1000 if m.group("k1") else 1)
        hi = (_num(nums[1]) * (1000 if (m.group("k2") or m.group("k1")) else 1)) if len(nums) > 1 else lo
        interval = _interval_from_token(m.group("interval"))
        if not interval:
            # Without an explicit interval only trust clear salary-looking figures:
            # INR >= 5,000 (small = monthly stipend) or foreign amounts like "$60k".
            if cur == "INR" and hi >= 5_000:
                interval = "month" if hi < 200_000 else "year"
            elif cur != "INR" and (m.group("k1") or m.group("k2")):
                interval = "year"
            else:
                continue
        annual_lo = lo * _per_year(interval) * rate
        annual_hi = hi * _per_year(interval) * rate
        # Sanity bounds: ignore funding rounds, revenue figures, etc.
        if 20_000 <= annual_hi <= 50_000_000:
            found.append(Compensation(annual_lo, annual_hi, "text", m.group(0).strip()))

    if not found:
        return None
    return max(found, key=lambda c: c.max_inr_year)


def meets_minimum(comp: Compensation | None, prefs: Preferences) -> bool:
    if comp is None:
        return prefs.include_unknown_salary
    if prefs.minimum_lpa <= 0:
        return True
    return comp.max_inr_year >= prefs.minimum_inr_per_year
