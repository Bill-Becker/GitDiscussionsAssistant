import hashlib
import hmac
import json
import os

import fakeredis
import pytest

os.environ["GITHUB_WEBHOOK_SECRET"] = "test-secret"
os.environ["TEAM_USERNAMES"] = "teammate"

import app as app_module  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from rq import Queue  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    fake = fakeredis.FakeRedis()
    monkeypatch.setattr(app_module, "redis_conn", fake)
    monkeypatch.setattr(app_module, "q", Queue("reopt", connection=fake))
    return TestClient(app_module.app)


def post(client, event, payload, secret="test-secret"):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/webhook", content=body, headers={
        "X-Hub-Signature-256": sig, "X-GitHub-Event": event, "Content-Type": "application/json",
    })


def comment_payload(login="someone", body="How do I set up a PV run?", cid=1):
    return {
        "action": "created",
        "discussion": {"title": "PV question", "html_url": "https://github.com/x/y/discussions/1"},
        "comment": {"id": cid, "body": body, "html_url": "https://github.com/x/y/discussions/1#c",
                    "user": {"login": login, "type": "User"}},
    }


def test_bad_signature_rejected(client):
    assert post(client, "discussion_comment", comment_payload(), secret="wrong").status_code == 401


def test_comment_enqueued_once(client):
    assert post(client, "discussion_comment", comment_payload()).json() == {"status": "accepted"}
    assert app_module.q.count == 1
    assert post(client, "discussion_comment", comment_payload()).json() == {"status": "already_processed"}
    assert app_module.q.count == 1


def test_team_member_skipped(client):
    r = post(client, "discussion_comment", comment_payload(login="Teammate"))
    assert r.json() == {"status": "skipped_author"}


def test_non_question_ignored(client):
    r = post(client, "discussion_comment", comment_payload(body="Thanks!"))
    assert r.json() == {"status": "not_a_question"}


def test_discussion_enqueued(client):
    payload = {"action": "created", "discussion": {
        "id": 7, "title": "Help", "body": "Why does my run fail?", "html_url": "u",
        "user": {"login": "someone", "type": "User"}}}
    assert post(client, "discussion", payload).json() == {"status": "accepted"}


def test_ping(client):
    assert post(client, "ping", {"zen": "hi"}).json() == {"status": "pong"}
