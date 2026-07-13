# aiops-platform

`aiops-platform` is an asynchronous FastAPI service that turns Datadog Monitor and Watchdog events into traceable Slack incidents and, when explicitly enabled, rule-based remediation through Kubernetes and GitHub.

## Architecture

```text
Datadog Monitor / Watchdog
            │ webhook
            ▼
 FastAPI API + validation + JSON request logging
            │
            ▼
 Incident service ─────────► Slack incident thread
            │                         ▲
            ▼                         │ verification updates
 AI signal analysis → root cause → rule engine
            │
            ├────────► Kubernetes action engine
            └────────► GitHub remediation pull request
```

## Folder structure

```text
app/
├── action_engine/     Kubernetes remediation execution
├── ai/                prompt construction and incident signal analysis
├── api/               routes, middleware, and exception handlers
├── config/            validated environment settings
├── connectors/        Datadog, Slack, GitHub integrations
├── decision_engine/   root-cause analysis and remediation rules
├── logging/           JSON logging and request context
├── models/            domain entities and remediation types
├── schemas/           OpenAPI request/response contracts
├── services/          application orchestration
└── verification/      post-action health checks
tests/                 isolated API and unit tests
```

## Installation

Requirements: Python 3.12 and optionally Docker with Docker Compose.

```powershell
cd aiops-platform
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

## Running locally

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://localhost:8000/docs` for Swagger UI and `http://localhost:8000/openapi.json` for the OpenAPI document.

Endpoints:

- `GET /health` — service health and version.
- `GET /version` — running version.
- `POST /webhooks/datadog` — authenticated Datadog event ingestion.

## Docker

The multi-stage image installs dependencies in a builder layer and runs a compact Python 3.12 runtime as an unprivileged user. It includes an HTTP healthcheck.

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Compose loads `.env`, exposes the configured port, mounts application source read-only for local iteration, restarts unless stopped, and runs an application healthcheck.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `DATADOG_WEBHOOK_TOKEN` | Required shared secret sent as `X-Datadog-Webhook-Token`. |
| `DATADOG_WEBHOOK_HMAC_SECRET` | Optional HMAC SHA-256 secret for `X-Datadog-Signature`. |
| `SLACK_BOT_TOKEN` | Bot token with `chat:write`. |
| `SLACK_INCIDENT_CHANNEL` | Slack channel ID where parent incident messages are posted. |
| `GITHUB_TOKEN` / `GITHUB_REPOSITORY` | Credentials and `owner/repository` for remediation PRs. |
| `KUBERNETES_IN_CLUSTER` | Uses in-cluster authentication when `true`; otherwise local kubeconfig. |
| `AUTO_REMEDIATION_ENABLED` | Enables action execution; defaults to `false`. |
| `REMEDIATION_WAIT_SECONDS` | Delay before a health verification. |
| `CORS_ALLOW_ORIGINS` | Comma-separated allowed origins, or `*`. |

Use a secret manager in deployed environments; never commit real secrets to `.env`.

## Datadog setup

Create a Datadog webhook integration targeting `https://<host>/webhooks/datadog`. Add `X-Datadog-Webhook-Token` with the configured shared secret. Include tags such as `namespace`, `service`, `cluster_name`, and `pod_name` so actions can identify their target resources.

## Slack setup

Create a Slack app, grant `chat:write`, install it to the workspace, and invite the bot into the incident channel. Configure its bot token and channel ID. The service creates an initial Block Kit message and posts remediation updates in its thread.

## GitHub setup

Use a fine-grained token restricted to the remediation repository with Contents read/write and Pull requests read/write permissions. The connector creates a branch, creates/updates the remediation report (the GitHub Contents API commits and pushes it), opens a PR, comments on it, and returns its URL.

## Kubernetes setup

Install a least-privilege service account with only the required verbs for pods, deployments, replicasets, logs, and deployment scales in intended namespaces. Set `KUBERNETES_IN_CLUSTER=true` in Kubernetes, or make a local kubeconfig available for development.

## Deployment

Build and deploy the container through your preferred orchestrator. Configure secrets outside the image, use HTTPS at the ingress, restrict CORS to known control-plane origins, and initially keep `AUTO_REMEDIATION_ENABLED=false`. Enable it only after testing rule outcomes in a non-production environment.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Webhook returns 401 | Verify the token/HMAC header and configured secret. |
| Webhook returns 503 | Confirm Slack token, channel membership, and Slack API availability. |
| Kubernetes action fails | Check kubeconfig/service-account permissions and resource tags. |
| GitHub PR fails | Verify repository name and token permissions. |
| Verification reports unhealthy | Inspect deployment status and Slack thread updates. |

## Development commands

```text
make run       Start local development server
make test      Run pytest suite
make lint      Run Ruff and syntax compilation
make docker    Build and run Compose service
make clean     Remove local Python test cache
```

## Future roadmap

- Persistent, multi-replica incident/thread storage.
- Queue-backed remediation workers and approval workflows.
- OpenTelemetry traces and metrics export.
- Policy-as-code authorization for remediation actions.
- Additional observability, ticketing, and infrastructure connectors.
