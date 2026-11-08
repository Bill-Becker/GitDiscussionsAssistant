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
| `SMEE_URL` | Local testing only: smee.io channel for the optional `smee` compose service |
| `TEAM_USERNAMES` | Comma-separated logins to ignore (bot accounts are always ignored) |

## Run locally

```sh
cp .env.example .env    # then edit
docker compose up --build -d
```

To receive real GitHub webhooks locally, create a channel at [smee.io](https://smee.io), use its URL as the webhook Payload URL, set `SMEE_URL` in `.env`, and enable the optional `smee` service, which forwards events to `web`:

```sh
docker compose --profile smee up --build -d
docker compose --profile smee down      # include the profile so smee is stopped too
```

Smee does not replay events missed while the client was down; use **Redeliver** in the webhook's Recent Deliveries. Containers read `.env` only when created: after editing it, run `docker compose up -d` (not `restart`), and check a value with `docker compose exec worker printenv REOPT_EMAIL`.

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

**Verified:**
- *NLR-managed laptop:* signed test event (`send_test_event.py`) → receiver → Redis → worker → NLR LiteLLM gateway (`gpt-5.4-mini`) → SendGrid → `nlr.gov` inbox (Junk).
- *Personal laptop, off NLR network:* real GitHub discussion → webhook → smee.io → receiver → Redis → worker → SendGrid → Gmail (Spam). Webhook signatures validate through smee. The LLM step used the fallback text because `litellm.nlr.gov` does not resolve outside NLR's network.

**Known constraints:**
- Netskope on NLR-managed laptops intercepts TLS on every network and blocks ngrok and smee.io, so GitHub cannot deliver webhooks to them; containers there also need the NREL CA chain in `certs/*.crt` (git-ignored; see Dockerfile).
- The LiteLLM gateway (`OPENAI_BASE_URL=https://litellm.nlr.gov`) is reachable only from NLR's network.
- Spam/Junk is caused by the sender, not the content: `FROM_EMAIL` is a Gmail address sent through SendGrid, which fails Gmail/Microsoft sender authentication (DMARC alignment). "Not spam" does not fix it. Any deployment needs a SendGrid-authenticated domain (DNS records) or an SMTP relay for the sending domain.

**Next steps — NLR testing:**
1. Keep developing on a non-NLR machine with smee; set `OPENAI_BASE_URL`/`OPENAI_API_KEY` to a public OpenAI-compatible endpoint to test real drafted replies (or accept the fallback text).
2. For testing inbox placement, create a Gmail filter "Never send to Spam" for the sender, or authenticate a personal domain in SendGrid and use it as `FROM_EMAIL`.
3. On NLR-managed laptops, test the LiteLLM step with `scripts/send_test_event.py` only.

**Next steps — NLR production:**
1. **Hosting (decides LLM access):** an NLR-hosted server can use the LiteLLM gateway; an external host (Render via `render.yaml`) needs a public OpenAI/Anthropic key and approval to send discussion content there.
2. **Inbound events:** webhooks need a public HTTPS endpoint, which an internal NLR server may not have. If not, replace the webhook with a poller that queries the GitHub API for new discussions/comments (outbound-only).
3. **Email:** ask NLR IT for SendGrid domain authentication of `nlr.gov` (or a subdomain), or for NLR's SMTP relay (requires adding SMTP support to `worker.py`). Set `FROM_EMAIL` to the approved address and `REOPT_EMAIL` to `REopt@nlr.gov`.
4. Set `TEAM_USERNAMES` to the real REopt team logins and replace the test webhook/smee URL with the production endpoint.

## Behavior notes

- Only `created` actions are processed; text must pass a simple keyword "looks like a question" filter.
- Event IDs are stored in the Redis set `processed_events` so GitHub redeliveries do not send duplicate emails.
- Jobs retry up to 3 times (10s / 60s / 5m) on failure, e.g. SendGrid errors. If OpenAI fails, the email still goes out with a fallback message.
- Discussion content is sent to OpenAI and SendGrid — keep that in mind for privacy policy.
