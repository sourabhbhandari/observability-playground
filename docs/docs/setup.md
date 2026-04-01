# Quick Start

## Prerequisites

| Requirement | Minimum Version |
|---|---|
| Docker Desktop | 4.25+ |
| Docker Compose | v2.20+ |
| Python | 3.11+ |
| Make | any |

## 1. Clone & Configure

```bash
git clone https://github.com/your-org/observability-playground
cd observability-playground

# Review and edit .env if needed
cp .env .env.local   # optional – override defaults
```

## 2. Start the Stack

```bash
make up
```

This starts all services. The first run pulls ~2GB of images. Allow 60–90 seconds for all health checks to pass.

## 3. Verify Health

```bash
make status
```

Expected output:
```
Mimir:   OK
Loki:    OK
Tempo:   OK
Grafana: Ok
```

## 4. Install Python Utilities

```bash
make setup-python
```

## 5. Generate Some Data

```bash
# Create a burst of traces, logs, and metrics
make load

# Trigger a deliberate error (for alerting)
make simulate-error
```

## 6. Explore Grafana

Open **[http://localhost:3000](http://localhost:3000)** (admin / admin123) and:

1. **Explore → Mimir** – run PromQL queries
2. **Explore → Loki** – run LogQL queries
3. **Explore → Tempo** – search and inspect traces
4. **Dashboards** – pre-provisioned datasources are ready

## Common Commands

```bash
make up                  # start stack
make down                # stop (preserve data)
make reset               # stop + wipe all volumes
make logs                # tail all logs
make cardinality         # high-cardinality report
make log-analytics       # log health report
make metric-usage        # used vs unused metrics
make mcp-server          # start Grafana MCP server
make docs-serve          # serve this documentation
```

## Stopping the Stack

```bash
make down       # stop, keep data
make reset      # stop, delete all data
```
