# Resume templates

Tailored resumes are written to `resumes/<date>/<Company>_<Title>_<id>.docx`
(plus a `.md` copy). There are two ways to control how they look.

## 1. Built-in layout (default)

Leave `RESUME_TEMPLATE_PATH` empty in `.env`. A clean single-column,
ATS-friendly DOCX is generated from `resume_details.md`.

## 2. Your own Word template

1. Create a starter template and open it in Word / Google Docs / LibreOffice:

       python -m jobscraper make-template

   This writes `templates/resume_template.docx` (gitignored, so your design
   stays private).
2. Restyle it however you like (fonts, columns, colours) but keep the tags.
3. Set `RESUME_TEMPLATE_PATH=templates/resume_template.docx` in `.env`.

You can also add the tags to your existing resume `.docx` instead.
Templates use [docxtpl](https://docxtpl.readthedocs.io/) (Jinja2 inside Word).
A tag on its own paragraph written as `{%p for ... %}` / `{%p endfor %}`
removes that paragraph from the output.

### Available tags

| Tag | Content |
|---|---|
| `{{ name }}` | your name |
| `{{ contact_line }}` | email, phone, location, links joined with `\|` |
| `{{ contact.email }}`, `{{ contact.phone }}`, `{{ contact.linkedin }}` ... | single contact fields (any `- key: value` line under your name) |
| `{{ summary }}` | summary with `{role}` / `{company}` filled in |
| `{{ key_skills }}` | the job's keywords you already have, most important first |
| `skills` | list of `{category, items, text}` — re-ordered by relevance |
| `sections` | every other section in file order: `{name, paragraph, bullets, entries}` |
| `experience`, `projects`, `education` | entries of those sections: `{title, organization, dates, location, extra, bullets}` |
| `certifications`, `achievements` | bullet lists of those sections |
| `{{ job_title }}`, `{{ company }}` | the job this resume was tailored for |

Example loop:

    {%p for e in experience %}
    {{ e.title }} | {{ e.organization }} | {{ e.dates }}
    {%p for b in e.bullets %}
    • {{ b }}
    {%p endfor %}
    {%p endfor %}
