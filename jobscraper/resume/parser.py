"""Parse resume_details.md into a structured Resume (see resume_details.example.md)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..config import REPO_ROOT, load_settings

EXAMPLE_PATH = REPO_ROOT / "resume_details.example.md"


@dataclass
class Entry:
    """One ### item: an internship, project, degree, ..."""
    title: str = ""
    organization: str = ""
    dates: str = ""
    location: str = ""
    extra: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join([self.title, self.organization, *self.extra, *self.bullets])

    def as_dict(self) -> dict:
        return {"title": self.title, "organization": self.organization, "dates": self.dates,
                "location": self.location, "extra": self.extra, "bullets": self.bullets}


@dataclass
class SkillGroup:
    category: str
    items: list[str]

    def as_dict(self) -> dict:
        return {"category": self.category, "items": self.items, "text": ", ".join(self.items)}


@dataclass
class Section:
    name: str
    paragraph: str = ""
    bullets: list[str] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)


@dataclass
class Resume:
    name: str = ""
    contact: dict[str, str] = field(default_factory=dict)
    summary: str = ""
    skills: list[SkillGroup] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)  # every other section, in file order

    def section(self, name: str) -> Section | None:
        for s in self.sections:
            if s.name.lower() == name.lower():
                return s
        return None

    @property
    def all_skills(self) -> list[str]:
        return [i for g in self.skills for i in g.items]

    @property
    def full_text(self) -> str:
        parts = [self.summary, *self.all_skills]
        for s in self.sections:
            parts += [s.paragraph, *s.bullets, *(e.text for e in s.entries)]
        return "\n".join(p for p in parts if p)


_DATE_HINT = re.compile(r"\b(19|20)\d{2}\b|present|current|ongoing", re.IGNORECASE)


def _entry_from_heading(heading: str) -> Entry:
    parts = [p.strip() for p in heading.split("|")]
    e = Entry(title=parts[0])
    rest = parts[1:]
    if rest and not _DATE_HINT.search(rest[0]):
        e.organization = rest.pop(0)
    for p in rest:
        if not e.dates and _DATE_HINT.search(p):
            e.dates = p
        elif not e.location and not re.search(r"\d", p) and len(p) < 40 and e.dates:
            e.location = p
        else:
            e.extra.append(p)
    return e


def parse_resume(text: str) -> Resume:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    resume = Resume()
    section: Section | None = None
    entry: Entry | None = None
    in_header = True

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# ") and not resume.name:
            resume.name = stripped[2:].strip()
            continue
        m = re.match(r"^##\s+(.+)$", stripped)
        if m and not stripped.startswith("###"):
            in_header = False
            section = Section(name=m.group(1).strip())
            resume.sections.append(section)
            entry = None
            continue
        m = re.match(r"^###\s+(.+)$", stripped)
        if m and section is not None:
            entry = _entry_from_heading(m.group(1))
            section.entries.append(entry)
            continue
        bullet = re.match(r"^[-*+]\s+(.+)$", stripped)
        if in_header:
            kv = re.match(r"^([A-Za-z ]+):\s*(.+)$", bullet.group(1) if bullet else stripped)
            if kv:
                resume.contact[kv.group(1).strip().lower()] = kv.group(2).strip()
            continue
        if section is None:
            continue
        if bullet:
            (entry.bullets if entry else section.bullets).append(bullet.group(1).strip())
        elif entry:
            entry.extra.append(stripped)
        else:
            section.paragraph = f"{section.paragraph} {stripped}".strip()

    # Pull Summary and Skills out of the generic sections
    rest = []
    for s in resume.sections:
        key = s.name.lower()
        if key in ("summary", "profile", "about", "objective"):
            resume.summary = s.paragraph or " ".join(s.bullets)
        elif key in ("skills", "technical skills", "skills & tools"):
            for b in s.bullets:
                cat, _, items = b.partition(":")
                if not items:
                    cat, items = "Skills", cat
                resume.skills.append(SkillGroup(cat.strip(), [i.strip() for i in items.split(",") if i.strip()]))
        else:
            rest.append(s)
    resume.sections = rest
    return resume


def resume_details_path() -> Path | None:
    p = load_settings().resume_details_path
    return p if p.is_file() else None


def load_resume(path: Path | None = None, allow_example: bool = False) -> Resume:
    path = path or resume_details_path()
    if path is None:
        if not allow_example:
            raise FileNotFoundError(
                "resume_details.md not found. Copy resume_details.example.md to resume_details.md "
                "and fill in your details (or set RESUME_DETAILS_PATH in .env).")
        path = EXAMPLE_PATH
    return parse_resume(Path(path).read_text(encoding="utf-8"))
