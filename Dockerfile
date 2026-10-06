# Container image for running the job scraper 24/7 on a server or cloud VM.
#
# Build:   docker build -t jobscraper .
# Run:     docker compose up -d          (see docker-compose.yml)
#
# Secrets and personal files are NOT baked into the image; they are mounted
# at runtime (.env, google_credentials.json, gmail_token.json,
# job_preference.md, resume_details.md).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Kolkata

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p data output resumes logs secrets

EXPOSE 8765
# MCP server over HTTP with the scheduler inside: scans, company sync and the
# 21:00 IST Gmail digest run on their own. Use `daemon` instead of `serve ...`
# if you do not need the MCP endpoint.
CMD ["python", "-m", "jobscraper", "serve", "--transport", "streamable-http", "--host", "0.0.0.0", "--with-scheduler"]
