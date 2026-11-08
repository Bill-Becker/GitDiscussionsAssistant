"""RQ job: draft a suggested reply with OpenAI and email it to the REopt team via SendGrid."""
import logging
import os
from typing import Dict, List, Optional, Tuple

import requests
from openai import OpenAI

from guidance import build_system_prompt

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("worker")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "700"))
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


def craft_user_message(title: str, body: str, url: str, author: Optional[str] = None) -> str:
    """The discussion itself. Instructions live in guidance/ (see guidance.py)."""
    return (
        f"Discussion title: {title}\n"
        f"Link: {url}\n"
        f"Author: {author or 'unknown'}\n\n"
        f"Post:\n{body}"
    )


def generate_suggested_reply(
    title: str, body: str, url: str, author: Optional[str] = None
) -> Tuple[str, List[str]]:
    """Return (suggested reply text, names of guidance skills applied)."""
    system_prompt, skills = build_system_prompt(title, body)
    try:
        resp = get_client().chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": craft_user_message(title, body, url, author)},
            ],
            max_tokens=OPENAI_MAX_TOKENS,
            temperature=0.2,
        )
        return (resp.choices[0].message.content or "").strip(), skills
    except Exception:
        log.exception("OpenAI call failed")
        return f"Failed to generate suggested reply automatically. Please review the discussion: {url}", skills


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

    suggested, skills = generate_suggested_reply(title, body, url, author)
    subject = f"[REopt Forum] {'Comment' if kind == 'comment' else 'Discussion'}: {title}"
    email_body = (
        f"Link: {url}\nAuthor: {author or 'unknown'}\n\n"
        f"Original content:\n{body}\n\n"
        f"Suggested reply and actions:\n{suggested}\n\n"
        f"Guidance skills applied: {', '.join(skills) or 'none'}"
    )
    send_email(subject, email_body)
    log.info("Sent notification for %s %s", kind, payload.get("id"))


if __name__ == "__main__":
    # `python worker.py` starts an RQ worker using REDIS_URL (used by Render; avoids shell quoting).
    from redis import Redis
    from rq import Worker

    conn = Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"))
    Worker(["reopt"], connection=conn).work()
