"""RQ job: draft a suggested reply with OpenAI and email it to the REopt team via SendGrid."""
import logging
import os
from typing import Dict, Optional

import requests
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("worker")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL", "reopt-notify@nlr.gov")
REOPT_EMAIL = os.getenv("REOPT_EMAIL", "REopt@nlr.gov")
SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"

_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()  # reads OPENAI_API_KEY from the environment
    return _client


def craft_prompt(title: str, body: str, url: str, author: Optional[str] = None) -> str:
    return f"""You are an assistant that creates a short summary and a suggested reply for REopt GitHub Discussions.
Discussion title: {title}
Link: {url}
User comment: {body}
Author: {author or 'unknown'}

Provide:

1. A 1-2 sentence summary.
2. A suggested 2-3 sentence public reply, polite and helpful, including clarifying questions if needed.
3. A short list (2-4) of recommended next actions for the REopt team (bullet points).

Respond in plain text. Keep suggestions concise."""


def generate_suggested_reply(title: str, body: str, url: str, author: Optional[str] = None) -> str:
    prompt = craft_prompt(title, body, url, author)
    try:
        resp = get_client().chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You help draft concise GitHub discussion replies for REopt."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=350,
            temperature=0.2,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        log.exception("OpenAI call failed")
        return f"Failed to generate suggested reply automatically. Please review the discussion: {url}"


def send_email(subject: str, plain_text: str) -> None:
    if not SENDGRID_API_KEY:
        raise RuntimeError("SENDGRID_API_KEY is not configured")
    headers = {"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"}
    data = {
        "personalizations": [{"to": [{"email": REOPT_EMAIL}], "subject": subject}],
        "from": {"email": FROM_EMAIL},
        "content": [{"type": "text/plain", "value": plain_text}],
    }
    r = requests.post(SENDGRID_URL, headers=headers, json=data, timeout=30)
    if r.status_code >= 400:
        # Raise so RQ marks the job failed and retries it.
        raise RuntimeError(f"SendGrid error {r.status_code}: {r.text}")


def process_event(payload: Dict) -> None:
    """Entry point enqueued as "worker.process_event"."""
    kind = payload.get("type")
    title = payload.get("title") or ""
    body = payload.get("body") or ""
    url = payload.get("url") or ""
    author = payload.get("author")

    suggested = generate_suggested_reply(title, body, url, author)
    subject = f"[REopt Forum] {'Comment' if kind == 'comment' else 'Discussion'}: {title}"
    email_body = (
        f"Link: {url}\nAuthor: {author or 'unknown'}\n\n"
        f"Original content:\n{body}\n\n"
        f"Suggested reply and actions:\n{suggested}"
    )
    send_email(subject, email_body)
    log.info("Sent notification for %s %s", kind, payload.get("id"))


if __name__ == "__main__":
    # `python worker.py` starts an RQ worker using REDIS_URL (used by Render; avoids shell quoting).
    from redis import Redis
    from rq import Worker

    conn = Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"))
    Worker(["reopt"], connection=conn).work()
