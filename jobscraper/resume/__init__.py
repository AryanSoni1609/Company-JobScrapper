"""Resume tailoring: resume_details.md -> keyword-matched DOCX per job."""

from __future__ import annotations

from pathlib import Path

from .parser import Resume, load_resume, parse_resume
from .render import make_starter_template, render_resume, to_markdown
from .tailor import TailoredResume, tailor_resume

__all__ = ["Resume", "TailoredResume", "load_resume", "parse_resume", "tailor_resume",
           "render_resume", "to_markdown", "make_starter_template", "tailor_for_job"]


def tailor_for_job(job: dict, resume: Resume | None = None) -> tuple[TailoredResume, Path]:
    """Tailor the user's resume to one job and write it to resumes/<date>/."""
    resume = resume or load_resume()
    tailored = tailor_resume(resume, job)
    return tailored, render_resume(tailored, job.get("job_id", ""))
