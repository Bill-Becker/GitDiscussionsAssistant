"""Send a correctly signed fake GitHub webhook to the receiver, exactly as GitHub would.

Usage:
    python scripts/send_test_event.py                       # discussion_comment to localhost
    python scripts/send_test_event.py --event ping          # just check signature + connectivity
    python scripts/send_test_event.py --event discussion --title "Run failed" --body "Why does my run fail?"
    python scripts/send_test_event.py --event discussion --title "Battery sizing" --body-file post.md
    python scripts/send_test_event.py --url https://<host>/webhook --secret <secret>

The secret is read from GITHUB_WEBHOOK_SECRET in .env unless --secret is given.
Each run uses a fresh event id, so the receiver's duplicate check won't skip it.
"""
import argparse
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_env_secret(env_path: Path) -> str:
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("GITHUB_WEBHOOK_SECRET="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def build_payload(event: str, title: str, body: str, author: str) -> dict:
    event_id = int(time.time() * 1000)
    discussion_url = "https://github.com/example/test-repo/discussions/1"
    user = {"login": author, "type": "User"}
    if event == "ping":
        return {"zen": "Test ping", "hook_id": 0}
    if event == "discussion":
        return {
            "action": "created",
            "discussion": {"id": event_id, "title": title,
                           "body": body, "html_url": discussion_url, "user": user},
        }
    return {
        "action": "created",
        "discussion": {"title": title, "html_url": discussion_url},
        "comment": {"id": event_id, "body": body, "html_url": f"{discussion_url}#discussioncomment-{event_id}",
                    "user": user},
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://localhost:8000/webhook")
    p.add_argument("--event", choices=["discussion_comment", "discussion", "ping"], default="discussion_comment")
    p.add_argument("--title", default="Test discussion from send_test_event.py",
                   help="discussion title (for a comment, the title of the discussion it belongs to)")
    p.add_argument("--body", default="How do I add a battery to my REopt run? I keep getting an error.",
                   help="text of the post or comment, as the user would write it")
    p.add_argument("--body-file", default=None, help="read the body from a text/Markdown file instead of --body")
    p.add_argument("--author", default="test-user", help="GitHub login of the poster")
    p.add_argument("--secret", default=None, help="defaults to GITHUB_WEBHOOK_SECRET in .env")
    args = p.parse_args()
    if args.body_file:
        args.body = Path(args.body_file).read_text(encoding="utf-8")

    secret = args.secret or os.getenv("GITHUB_WEBHOOK_SECRET") or read_env_secret(ROOT / ".env")
    if not secret:
        raise SystemExit("No secret found: set GITHUB_WEBHOOK_SECRET in .env or pass --secret")

    # Compact JSON like GitHub sends; relays such as smee.io re-serialize compactly, so spaces would break the signature.
    data = json.dumps(build_payload(args.event, args.title, args.body, args.author),
                      separators=(",", ":")).encode()
    sig = "sha256=" + hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()
    req = urllib.request.Request(args.url, data=data, method="POST", headers={
        "Content-Type": "application/json",
        "X-GitHub-Event": args.event,
        "X-Hub-Signature-256": sig,
        "User-Agent": "GitHub-Hookshot/test",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print(resp.status, resp.read().decode())
    except urllib.error.HTTPError as e:
        print(e.code, e.read().decode())
    except urllib.error.URLError as e:
        raise SystemExit(f"Could not reach {args.url}: {e.reason} (is the service running?)")


if __name__ == "__main__":
    main()
