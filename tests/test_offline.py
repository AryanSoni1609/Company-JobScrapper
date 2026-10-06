"""Offline tests (no network, no Google account needed).

Run:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TMP = tempfile.mkdtemp(prefix="jobscraper-tests-")
os.environ.update({"DATA_DIR": f"{TMP}/data", "LOG_DIR": f"{TMP}/logs", "RESUMES_DIR": f"{TMP}/resumes",
                   "OUTPUT_DIR": f"{TMP}/output"})

from jobscraper.compensation import from_structured, from_text, meets_minimum  # noqa: E402
from jobscraper.filters import evaluate, location_ok  # noqa: E402
from jobscraper.preferences import EXAMPLE_PATH, load_preferences, parse_preferences  # noqa: E402

PREFS = load_preferences(EXAMPLE_PATH)


def job(**kw):
    base = {"title": "Product Management Intern", "location": "Bengaluru, India", "description": "",
            "employment_type": "", "date_posted": "", "compensation": None}
    base.update(kw)
    return base


class PreferencesTest(unittest.TestCase):
    def test_example_defaults(self):
        self.assertIn("intern", PREFS.job_types)
        self.assertEqual(PREFS.minimum_lpa, 8)
        self.assertTrue(PREFS.include_unknown_salary)
        self.assertIn("project manager", PREFS.managerial_roles)
        self.assertAlmostEqual(PREFS.minimum_inr_per_year, 720_000)

    def test_edit_takes_effect(self):
        p = parse_preferences("## Job types\n- full time\n## Compensation\n- minimum_lpa: 12\n"
                              "- include_unknown_salary: no\n")
        self.assertEqual(p.job_types, ["full time"])
        self.assertEqual(p.minimum_lpa, 12)
        self.assertFalse(p.include_unknown_salary)


class CompensationTest(unittest.TestCase):
    def test_text_formats(self):
        cases = {"CTC 8-12 LPA": 12.0, "Stipend: ₹50,000/month": 6.0, "Rs. 1,00,000 per month": 12.0,
                 "INR 6,00,000 - 9,00,000 per annum": 9.0, "10 lakhs per annum": 10.0}
        for text, lpa in cases.items():
            c = from_text(text, PREFS)
            self.assertIsNotNone(c, text)
            self.assertAlmostEqual(c.max_inr_year / 100_000, lpa, places=1, msg=text)

    def test_noise_ignored(self):
        self.assertIsNone(from_text("We raised $100 million and have 500 employees", PREFS))

    def test_structured_and_minimum(self):
        c = from_structured(20_000, 30_000, "INR", "per-month-salary", PREFS)
        self.assertEqual(c.max_inr_year, 360_000)
        self.assertFalse(meets_minimum(c, PREFS))  # 3.6 LPA < 8 LPA - 10%
        self.assertTrue(meets_minimum(None, PREFS))  # unknown pay kept by default
        self.assertTrue(meets_minimum(from_text("7.5 LPA", PREFS), PREFS))  # within tolerance


class FilterTest(unittest.TestCase):
    def test_keeps_managerial_and_technical_interns(self):
        self.assertTrue(evaluate(job(), PREFS)[0])
        self.assertTrue(evaluate(job(title="Software Engineer Intern", location="Remote"), PREFS)[0])

    def test_rejections(self):
        self.assertFalse(evaluate(job(title="Senior Product Manager"), PREFS)[0])          # not intern
        self.assertFalse(evaluate(job(title="Internal Tools Engineer"), PREFS)[0])         # whole words
        self.assertFalse(evaluate(job(location="London, UK"), PREFS)[0])                   # location
        self.assertFalse(evaluate(job(description="Stipend ₹15,000/month"), PREFS)[0])    # pay too low
        self.assertTrue(evaluate(job(description="Stipend ₹80,000/month"), PREFS)[0])

    def test_remote_tied_to_other_country(self):
        self.assertFalse(location_ok("San Francisco, CA, Remote", PREFS)[0])
        self.assertFalse(location_ok("Remote - USA", PREFS)[0])
        self.assertTrue(location_ok("Bengaluru; Remote, USA", PREFS)[0])


class FakeWorksheet:
    def __init__(self, rows=None):
        self.rows = [list(r) for r in rows or []]
        self.destructive_calls = []

    def row_values(self, i):
        return self.rows[i - 1] if len(self.rows) >= i else []

    def col_values(self, i):
        return [r[i - 1] if len(r) >= i else "" for r in self.rows]

    def get_all_records(self, **_):
        head = self.rows[0]
        return [dict(zip(head, r + [""] * (len(head) - len(r)))) for r in self.rows[1:]]

    def append_row(self, row, **_):
        self.rows.append(list(row))

    def append_rows(self, rows, **_):
        self.rows.extend(list(r) for r in rows)

    def __getattr__(self, name):  # clear, delete_rows, update, update_cell, ...
        def forbidden(*a, **k):
            self.destructive_calls.append(name)
            raise AssertionError(f"destructive sheet call: {name}")
        return forbidden


class AppendOnlySheetsTest(unittest.TestCase):
    def test_append_maps_headers_and_never_overwrites(self):
        from jobscraper.sheets import JOB_HEADERS, AppendOnlySheets

        existing = [JOB_HEADERS, ["2026-01-01", "Old Co", "Old Intern"] + [""] * (len(JOB_HEADERS) - 3)]
        ws = FakeWorksheet(existing)
        sheets = AppendOnlySheets.__new__(AppendOnlySheets)
        sheets.tab = lambda name, headers: ws
        sheets.append("Jobs", JOB_HEADERS, [{"company": "New Co", "title": "PM Intern", "job_url": "u"}])
        self.assertEqual(ws.rows[1][1], "Old Co")  # untouched
        new = dict(zip(JOB_HEADERS, ws.rows[2]))
        self.assertEqual((new["company"], new["title"], new["job_url"]), ("New Co", "PM Intern", "u"))
        self.assertEqual(ws.destructive_calls, [])


class ResumeTest(unittest.TestCase):
    def test_tailor_uses_only_own_content(self):
        from jobscraper.resume import load_resume, tailor_for_job

        resume = load_resume(Path(__file__).resolve().parent.parent / "resume_details.example.md")
        jd = {"title": "Product Management Intern", "company": "Acme", "job_id": "1",
              "description": "You will use JIRA and Agile, run A/B testing and write SQL. Kubernetes and Rust a plus."}
        t, path = tailor_for_job(jd, resume)
        self.assertTrue(path.is_file())
        for kw in ("jira", "agile", "a/b testing", "sql"):
            self.assertIn(kw, t.matched_keywords)
        self.assertIn("rust", t.missing_keywords)
        self.assertNotIn("Rust", path.with_suffix(".md").read_text(encoding="utf-8"))
        self.assertIn("Product Management Intern at Acme", t.resume.summary)
        self.assertGreater(t.match_score, 50)


class DigestTest(unittest.TestCase):
    def test_marks_reported_only_after_send(self):
        from jobscraper import digest
        from jobscraper.state import State

        state = State()
        state.add_job({"url": "https://x/job/1", "company": "Acme", "title": "PM Intern",
                       "apply_url": "https://x/apply/1"}, 80)
        with mock.patch("jobscraper.notifier.send_email", side_effect=RuntimeError("smtp down")):
            with self.assertRaises(RuntimeError):
                digest.send_digest()
        self.assertEqual(len(state.list_jobs(only_unnotified=True)), 1)
        with mock.patch("jobscraper.notifier.send_email", return_value={"message_id": "1"}):
            out = digest.send_digest()
        self.assertTrue(out["sent"])
        self.assertEqual(len(state.list_jobs(only_unnotified=True)), 0)


if __name__ == "__main__":
    unittest.main()
