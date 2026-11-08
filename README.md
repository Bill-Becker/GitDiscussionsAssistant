# REopt Discussion Notifier

GitHub webhook → FastAPI receiver → Redis/RQ queue → worker (OpenAI drafts a suggested reply) → email to the REopt team via SendGrid.

```
GitHub (discussion / discussion_comment)
   └─▶ app.py  /webhook   validates X-Hub-Signature-256, filters, dedupes, enqueues
         └─▶ Redis queue "reopt"
               └─▶ worker.py  process_event → OpenAI → SendGrid email
```

## Files

| File | Purpose |
|---|---|
| `app.py` | Webhook receiver (`POST /webhook`, `GET /healthz`) |
| `worker.py` | RQ job: generate suggested reply, send email |
| `docker-compose.yml` | Local stack: redis + web + worker |
| `.env.example` | Environment variable template |
| `tests/` | Receiver tests (fakeredis, no network) |

## Configuration

Copy `.env.example` to `.env` and fill in values:

| Variable | Description |
|---|---|
| `GITHUB_WEBHOOK_SECRET` | Required. Same secret as in the GitHub webhook settings. Requests are rejected if unset. |
| `OPENAI_API_KEY` | OpenAI API key |
| `OPENAI_MODEL` | Defaults to `gpt-4o-mini` |
| `SENDGRID_API_KEY` | SendGrid API key |
| `FROM_EMAIL` | Verified SendGrid sender, e.g. `reopt-notify@nlr.gov` |
| `REOPT_EMAIL` | Recipient, e.g. `REopt@nlr.gov` |
| `REDIS_URL` | Set automatically in docker-compose |
| `TEAM_USERNAMES` | Comma-separated logins to ignore (bot accounts are always ignored) |

## Run locally

```sh
cp .env.example .env    # then edit
docker compose up --build
ngrok http 8000         # expose to GitHub for testing
```

Note: the RQ worker requires a Unix-like OS (it forks), so run it via Docker or WSL on Windows.

### Test without a tunnel

On NLR-managed laptops, Netskope blocks ngrok. Instead, send a correctly signed fake event:

```sh
python scripts/send_test_event.py --event ping      # expect: 200 {"status":"pong"}
python scripts/send_test_event.py                   # fake discussion comment -> email
python scripts/send_test_event.py --event discussion --body "Why does my run fail?"
```

It reads `GITHUB_WEBHOOK_SECRET` from `.env`. Use `--url https://<host>/webhook --secret <secret>` to target a deployment.

## Tests

```sh
pip install -r requirements-dev.txt
pytest -q
```

## GitHub webhook setup

Repository → Settings → Webhooks → Add webhook:

- **Payload URL:** `https://<your-host>/webhook`
- **Content type:** `application/json`
- **Secret:** value of `GITHUB_WEBHOOK_SECRET`
- **Events:** "Let me select individual events" → check **Discussions** and **Discussion comments**

Save, then check "Recent Deliveries" — the initial ping should return `{"status": "pong"}`.

## Deployment

- **Render (configured in `render.yaml`):**
  1. Push this project to a GitHub repo (`.env` is git-ignored).
  2. Render dashboard → **New → Blueprint** → select the repo. It creates `reopt-webhook` (web, free), `reopt-worker` (background worker, Starter plan — workers have no free tier) and `reopt-redis` (Key Value, free).
  3. Fill in the prompted secrets (`OPENAI_API_KEY`, `SENDGRID_API_KEY`, `FROM_EMAIL`, `REOPT_EMAIL`, `TEAM_USERNAMES`).
  4. Copy the auto-generated `GITHUB_WEBHOOK_SECRET` from the `reopt-webhook` Environment tab into the GitHub webhook.
  5. Payload URL: `https://reopt-webhook-<id>.onrender.com/webhook` (shown on the service page).

  Free web services sleep after ~15 min idle; the first webhook after a sleep can exceed GitHub's 10 s timeout and show as failed in Recent Deliveries. Upgrade the web service to Starter for production.
- **Railway:** same shape — web service, worker with command `python worker.py`, and a Redis plugin.
- **Google Cloud Run:** deploy the container as the web service; run the worker as a separate always-on service; Redis via Memorystore or a hosted provider.
- **AWS:** ECS/Fargate for web + worker, ElastiCache for Redis (or swap RQ for SQS).

GitHub needs a stable public HTTPS endpoint.

## Status and next steps (2026-11-08)

**Working locally (verified):** signed test event → receiver → Redis queue → worker → NLR LiteLLM gateway (`gpt-5.4-mini`) → SendGrid → delivered to an `nlr.gov` inbox (landed in Junk).

**NLR network constraints found:**
- Netskope on NLR-managed laptops intercepts TLS on every network (VPN or not). It blocks ngrok and smee.io event streams, so GitHub cannot deliver webhooks to a laptop. Use `scripts/send_test_event.py` locally.
- Containers need the NREL CA chain to reach SendGrid through Netskope: export it into `certs/*.crt` (git-ignored; see Dockerfile). Not needed off NLR-managed machines.
- The LLM key is for NLR's LiteLLM gateway (`OPENAI_BASE_URL=https://litellm.nlr.gov`), likely reachable only from NLR's network.
- `nlr.gov` mail is Microsoft 365; mail from a Gmail sender via SendGrid goes to Junk.

**Open decisions:**
1. Hosting: an NLR server (can reach the LiteLLM gateway) vs. Render (`render.yaml`, needs a public OpenAI/Anthropic key).
2. Email: an `nlr.gov`-authenticated SendGrid sender, or NLR's SMTP relay (would need SMTP support in `worker.py`).
3. Delivery: webhooks need a public endpoint; alternative is a poller that queries the GitHub API for new discussions/comments (outbound-only, works on NLR's network).

## Behavior notes

- Only `created` actions are processed; text must pass a simple keyword "looks like a question" filter.
- Event IDs are stored in the Redis set `processed_events` so GitHub redeliveries do not send duplicate emails.
- Jobs retry up to 3 times (10s / 60s / 5m) on failure, e.g. SendGrid errors. If OpenAI fails, the email still goes out with a fallback message.
- Discussion content is sent to OpenAI and SendGrid — keep that in mind for privacy policy.
