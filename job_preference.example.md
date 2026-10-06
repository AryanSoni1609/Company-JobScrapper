# Job Preferences

This file controls which jobs the scraper keeps. It is re-read on **every**
scan, so edits take effect on the next run — no code changes or restarts.

Copy it to `job_preference.md` (gitignored) and edit that copy:

    copy job_preference.example.md job_preference.md      (Windows)
    cp job_preference.example.md job_preference.md        (macOS / Linux)

How it is read:
- Each `## Heading` is a setting. Each `- bullet` underneath is one value.
  Several values can share a bullet separated by commas.
- Matching is case-insensitive and on whole words ("intern" does not match
  "internal").
- A job is kept only if its title matches a **job type** AND (a **technical**
  OR a **managerial** role), it is in an allowed **location**, it contains no
  **exclude keyword**, and its pay (when listed) is at or above the minimum.
- An empty section means "no restriction" for that setting.
- Text inside HTML comments is ignored.

## Job types
<!-- The job title (or the ATS employment type) must contain one of these. -->
- intern, internship, interns
- trainee, apprentice, apprenticeship
- summer analyst, summer associate
- co-op

## Technical roles
- software, sde, swe, developer, engineer, engineering
- data, data science, data scientist, data analyst, analytics
- machine learning, ml, ai, artificial intelligence, deep learning, nlp
- backend, frontend, full stack, fullstack, web, mobile, android, ios
- cloud, devops, sre, infrastructure, platform, security, cyber
- research, quant, quantitative

## Managerial roles
- project manager, project management, project
- product manager, product management, associate product manager, apm, product
- program manager, program management, technical program manager, program
- business analyst, business analytics, business operations, operations
- strategy, consulting, consultant, business development, growth
- management, scrum master, chief of staff

## Exclude keywords
<!-- Jobs whose title contains any of these are skipped. -->
- senior, sr, staff, principal, director, head of, vice president, vp
- manager ii, manager iii, lead engineer

## Locations
<!-- The job location must contain one of these. Leave empty for anywhere. -->
- india
- bengaluru, bangalore, hyderabad, pune, mumbai, chennai, kolkata, ahmedabad
- delhi, new delhi, gurgaon, gurugram, noida, ncr
- remote

## Exclude locations
<!--
Only used when a job matched on "remote" alone: drops "Remote - US" style
postings that need residency elsewhere. A job that also lists an allowed
city (e.g. "Bengaluru; Remote, USA") is always kept.
-->
- united states, usa, canada, united kingdom

## Compensation
<!--
minimum_lpa:            yearly CTC / annualised stipend in lakhs INR (LPA)
tolerance_percent:      "around" the minimum — 10 means 7.2 LPA still passes for 8
include_unknown_salary: keep jobs that do not list pay (most postings don't)
usd_to_inr / eur_to_inr / gbp_to_inr: conversion rates for foreign pay
-->
- minimum_lpa: 8
- tolerance_percent: 10
- include_unknown_salary: yes
- usd_to_inr: 88
- eur_to_inr: 100
- gbp_to_inr: 115

## Options
<!--
include_unknown_location: keep jobs with an empty location field
match_roles_in_description: also look for role keywords in the job description
                            (broader but noisier; titles only by default)
max_job_age_days: skip postings older than this (0 = no limit)
-->
- include_unknown_location: no
- match_roles_in_description: no
- max_job_age_days: 60
