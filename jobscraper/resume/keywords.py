"""Keyword extraction from job descriptions.

A keyword is any phrase from the built-in vocabulary (common technical and
managerial skills) or from the candidate's own resume skills. Phrases are
matched whole-word and case-insensitively; a few aliases are folded together
(e.g. "js" -> "javascript", "k8s" -> "kubernetes").
"""

from __future__ import annotations

from collections import Counter

from ..filters import _pattern

TECH_TERMS = """
python java c++ c# c golang go rust kotlin swift scala ruby php javascript typescript sql nosql bash r matlab
html css react react native angular vue next.js node.js express django flask fastapi spring spring boot
.net graphql rest apis rest api microservices grpc kafka rabbitmq redis elasticsearch spark hadoop airflow
dbt snowflake bigquery redshift databricks postgresql mysql mongodb dynamodb cassandra sqlite oracle
aws azure gcp google cloud docker kubernetes terraform ansible jenkins ci/cd github actions gitlab linux unix
git distributed systems system design data structures algorithms object oriented programming oop
operating systems computer networks networking databases dbms multithreading concurrency
machine learning deep learning nlp natural language processing computer vision llm llms generative ai
genai rag prompt engineering transformers pytorch tensorflow keras scikit-learn pandas numpy opencv
statistics probability data analysis data analytics data science data engineering data visualization
etl data pipelines data modeling a/b testing experimentation tableau power bi looker excel
android ios mobile development flutter frontend backend full stack web development testing unit testing
selenium automation qa debugging performance security cybersecurity cryptography cloud computing
devops sre observability monitoring embedded systems firmware verilog vlsi fpga iot robotics
"""

MANAGEMENT_TERMS = """
project management product management program management agile scrum kanban waterfall jira confluence
asana trello notion roadmap roadmapping product roadmap prd prds requirements gathering user stories
stakeholder management stakeholder communication cross-functional collaboration cross functional
go-to-market gtm market research competitive analysis user research customer research usability
product strategy business strategy strategy consulting business analysis business analytics kpis okrs
metrics dashboards reporting risk management resource planning budgeting scheduling sprint planning
prioritization process improvement operations supply chain lean six sigma change management
communication presentation leadership teamwork problem solving critical thinking negotiation
client management account management sales business development marketing growth pricing
financial modeling excel modeling powerpoint documentation vendor management pmp prince2 scrum master
"""

ALIASES = {
    "js": "javascript", "ts": "typescript", "k8s": "kubernetes", "golang": "go", "ml": "machine learning",
    "dl": "deep learning", "ai/ml": "machine learning", "nodejs": "node.js", "node": "node.js",
    "reactjs": "react", "react.js": "react", "postgres": "postgresql", "gcp": "google cloud",
    "ci cd": "ci/cd", "ab testing": "a/b testing", "oop": "object oriented programming",
    "rest api": "rest apis", "llm": "llms", "cross functional": "cross-functional collaboration",
    "roadmapping": "roadmap", "product roadmap": "roadmap", "prd": "prds", "genai": "generative ai",
}

def _vocab_from_block(block: str) -> list[str]:
    # The blocks above are whitespace separated; recover multi-word phrases by
    # greedily matching against this curated list of known multi-word terms.
    multi = [
        "c++", "react native", "spring boot", "rest apis", "rest api", "google cloud", "github actions",
        "ci/cd", "distributed systems", "system design", "data structures", "object oriented programming",
        "operating systems", "computer networks", "machine learning", "deep learning",
        "natural language processing", "computer vision", "generative ai", "prompt engineering",
        "data analysis", "data analytics", "data science", "data engineering", "data visualization",
        "data pipelines", "data modeling", "a/b testing", "power bi", "mobile development",
        "full stack", "web development", "unit testing", "cloud computing", "embedded systems",
        "project management", "product management", "program management", "product roadmap",
        "requirements gathering", "user stories", "stakeholder management", "stakeholder communication",
        "cross-functional collaboration", "cross functional", "go-to-market", "market research",
        "competitive analysis", "user research", "customer research", "product strategy",
        "business strategy", "strategy consulting", "business analysis", "business analytics",
        "risk management", "resource planning", "sprint planning", "process improvement",
        "supply chain", "six sigma", "change management", "problem solving", "critical thinking",
        "client management", "account management", "business development", "financial modeling",
        "excel modeling", "vendor management", "scrum master", "next.js", "node.js",
    ]
    text = " " + block.lower().replace("\n", " ") + " "
    found = []
    for phrase in sorted(multi, key=len, reverse=True):
        if f" {phrase} " in text:
            found.append(phrase)
            text = text.replace(f" {phrase} ", " ")
    found += [w for w in text.split() if w]
    return found


VOCABULARY = list(dict.fromkeys(_vocab_from_block(TECH_TERMS) + _vocab_from_block(MANAGEMENT_TERMS)))

# Words too generic to be useful as resume keywords on their own
_STOP = {"c", "r", "go", "git", "excel", "notion", "testing", "security", "performance", "sales",
         "marketing", "growth", "operations", "strategy", "metrics", "reporting", "documentation"}


def canonical(term: str) -> str:
    t = term.strip().lower()
    return ALIASES.get(t, t)


def extract_keywords(text: str, extra_terms: list[str] | None = None, top_n: int = 40) -> list[tuple[str, int]]:
    """Return [(keyword, count)] found in text, most frequent first."""
    t = (text or "").lower()
    counts: Counter[str] = Counter()
    terms = list(dict.fromkeys([*(e.lower() for e in extra_terms or [] if e.strip()), *VOCABULARY, *ALIASES]))
    for term in terms:
        if term in _STOP and term not in {e.lower() for e in extra_terms or []}:
            continue
        n = len(_pattern(term).findall(t))
        if n:
            counts[canonical(term)] += n
    return counts.most_common(top_n)


def keyword_hits(text: str, keywords: list[str]) -> int:
    t = (text or "").lower()
    return sum(1 for k in keywords if _pattern(k).search(t))
