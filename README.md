# Observability Playground

A **batteries-included** local observability stack for learning, prototyping, and testing instrumentation strategies. It runs in Docker Compose and wires **metrics** (Grafana Mimir), **logs** (Grafana Loki), **traces** (Grafana Tempo), **dashboards** (Grafana), **incident management** (Grafana OnCall), an **OpenTelemetry Collector**, and a **sample FastAPI app** with MinIO as S3-compatible backend storage.

## What’s in the stack

| Component | Role | Default URL / port |
|-----------|------|--------------------|
| Grafana | Dashboards & alerting | http://localhost:3000 |
| Grafana Mimir | Metrics (Prometheus-compatible) | http://localhost:9009 |
| Grafana Loki | Log aggregation | http://localhost:3100 |
| Grafana Tempo | Distributed tracing | http://localhost:3200 |
| Grafana OnCall | On-call / incidents | http://localhost:8080 |
| Sample app | OTel-instrumented API | http://localhost:8000 |
| MinIO | Object storage (S3 API + console) | http://localhost:9000 / http://localhost:9001 |
| OTel Collector | Telemetry ingestion | OTLP (see `docker-compose.yml`) |

Default Grafana login: **admin** / **admin123**. MinIO console (if using defaults): **minioadmin** / **minioadmin123**.

## Prerequisites

- **Docker** and **Docker Compose** (`docker compose`)
- **Python 3** (optional, for `python-utils` scripts and docs tooling)
- **curl** (used by `make status` and some targets)

## Quick start

```bash
cd observability-playground
make up
```

Then open [http://localhost:3000](http://localhost:3000).

To stop the stack without deleting volumes:

```bash
make down
```

## Makefile commands

The default target prints a short help screen. From the repo root:

```bash
make          # same as: make help
make help     # list targets with one-line descriptions
```

### Stack lifecycle

| Target | Description |
|--------|-------------|
| `up` | Start the full stack (`docker compose up -d --build`) and print service URLs |
| `down` | Stop and remove containers (volumes kept) |
| `restart` | Restart all services |
| `reset` | **Destructive:** prompts, then removes containers **and** volumes |
| `logs` | Follow logs for all services (`--tail=100`) |
| `status` | `docker compose ps` plus quick health checks (Mimir, Loki, Tempo, Grafana) |
| `ps` | Alias for `docker compose ps` |

### Per-service logs

| Target | Description |
|--------|-------------|
| `mimir-logs` | Follow Mimir logs |
| `loki-logs` | Follow Loki logs |
| `tempo-logs` | Follow Tempo logs |
| `grafana-logs` | Follow Grafana logs |
| `oncall-logs` | Follow OnCall engine + Celery logs |
| `sample-app-logs` | Follow sample app logs |
| `otel-logs` | Follow OTel Collector logs |

### Python utilities (`python-utils/`)

| Target | Description |
|--------|-------------|
| `setup-python` | `pip install -r python-utils/requirements.txt` |
| `cardinality` | High-cardinality metric analyzer (`--top 50 --threshold 500`) |
| `cardinality-labels` | Same tool with label breakdown |
| `log-analytics` | Log analytics for the last 1 hour |
| `log-analytics-6h` | Log analytics for the last 6 hours |
| `metric-usage` | Report used vs unused metrics |
| `metric-usage-export` | Export metric usage CSV to `/tmp/metric_usage.csv` |
| `mcp-server` | Start Grafana MCP server (stdio transport) |

Run these with the stack up and dependencies installed as needed.

### Load and demos (sample app)

| Target | Description |
|--------|-------------|
| `load` | Generate synthetic load via the sample-app HTTP API |
| `simulate-error` | Trigger a simulated error |
| `simulate-slow` | Trigger a ~3s slow request |

### Documentation (MkDocs in `docs/`)

| Target | Description |
|--------|-------------|
| `docs-serve` | Serve docs at `0.0.0.0:8001` |
| `docs-build` | Build static site under `docs/site` |
| `docs-install` | `pip install mkdocs mkdocs-material mkdocs-mermaid2-plugin` |

### Cleanup

| Target | Description |
|--------|-------------|
| `clean` | Remove newer `*.csv`, `*.pyc`, and `__pycache__` dirs (see Makefile for exact rules) |

## Help

- **Makefile:** `make help` shows every target that has a `##` description in the [Makefile](Makefile).
- **Longer docs:** after `docs-install`, run `make docs-serve` and open the served URL, or read the MkDocs sources under `docs/docs/`.

## Project layout (high level)

- `docker-compose.yml` — full observability stack
- `Makefile` — convenience targets for stack, utilities, and docs
- `python-utils/` — cardinality, log analytics, metric usage, Grafana MCP helper
- `docs/` — MkDocs project and built site (`docs/site/` when built)
