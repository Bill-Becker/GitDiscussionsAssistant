"""GitHub webhook receiver: validates signatures and enqueues discussion events to RQ."""
import hashlib
import hmac
import json
import logging
import os

from fastapi import FastAPI, Header, HTTPException, Request
from redis import Redis
from rq import Queue, Retry

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("webhook")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
GITHUB_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
TEAM_USERNAMES = {
    u.strip().lower() for u in os.getenv("TEAM_USERNAMES", "").split(",") if u.strip()
}
PROCESSED_KEY = "processed_events"

redis_conn = Redis.from_url(REDIS_URL)
q = Queue("reopt", connection=redis_conn)

app = FastAPI()


def verify_signature(body: bytes, signature_header: str) -> bool:
    # Fail closed: an unset secret would otherwise let anyone trigger LLM calls and emails.
    if not GITHUB_SECRET:
        log.error("GITHUB_WEBHOOK_SECRET is not set; rejecting request")
        return False
    mac = hmac.new(GITHUB_SECRET.encode(), msg=body, digestmod=hashlib.sha256)
    expected = "sha256=" + mac.hexdigest()
    return hmac.compare_digest(expected, signature_header or "")


def looks_like_question(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    keywords = ["?", "how", "why", "when", "what", "where", "help", "error", "issue",
                "request", "could", "should", "would"]
    return any(k in t for k in keywords)


def should_skip_author(user: dict) -> bool:
    login = (user.get("login") or "").lower()
    return login in TEAM_USERNAMES or user.get("type") == "Bot"


def skip(status: str, event: str, detail: str = "") -> dict:
    log.info("Skipped %s event: %s %s", event or "unknown", status, detail)
    return {"status": status}


def enqueue_once(key: str, job: dict) -> bool:
    """Atomically mark an event as seen and enqueue it. Returns False if already seen."""
    if redis_conn.sadd(PROCESSED_KEY, key) == 0:
        return False
    q.enqueue("worker.process_event", job, retry=Retry(max=3, interval=[10, 60, 300]))
    return True


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(
    request: Request,
    x_hub_signature_256: str = Header(None),
    x_github_event: str = Header(None),
):
    body = await request.body()
    if not verify_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = (x_github_event or "").lower()
    if event == "ping":
        return {"status": "pong"}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if payload.get("action") != "created":
        return skip("ignored", event, f"action={payload.get('action')}")

    discussion = payload.get("discussion") or {}
    title = discussion.get("title", "")

    if event == "discussion":
        if should_skip_author(discussion.get("user") or {}):
            return skip("skipped_author", event, (discussion.get("user") or {}).get("login", ""))
        body_text = discussion.get("body") or ""
        if not looks_like_question(body_text):
            return skip("not_a_question", event, f"discussion={discussion.get('id')}")
        job = {
            "type": "discussion",
            "id": discussion.get("id"),
            "title": title,
            "body": body_text,
            "url": discussion.get("html_url"),
            "author": (discussion.get("user") or {}).get("login"),
        }
        key = f"discussion:{job['id']}"

    elif event == "discussion_comment":
        comment = payload.get("comment") or {}
        user = comment.get("user") or {}
        if should_skip_author(user):
            return skip("skipped_author", event, user.get("login", ""))
        body_text = comment.get("body") or ""
        if not looks_like_question(body_text):
            return skip("not_a_question", event, f"comment={comment.get('id')}")
        job = {
            "type": "comment",
            "id": comment.get("id"),
            "title": title,
            "body": body_text,
            "url": comment.get("html_url") or discussion.get("html_url"),
            "author": user.get("login"),
        }
        key = f"comment:{job['id']}"

    else:
        return skip("ignored", event, "unhandled event type")

    if not enqueue_once(key, job):
        return skip("already_processed", event, key)
    log.info("Enqueued %s", key)
    return {"status": "accepted"}
