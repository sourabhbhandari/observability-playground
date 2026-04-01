# Python Utilities

All utilities live in `python-utils/` and share a common `utils.py` with HTTP client helpers.

## Installation

```bash
make setup-python
# or manually:
pip install -r python-utils/requirements.txt
```

## Configuration

Set environment variables or let the utilities use their defaults:

```bash
export MIMIR_URL=http://localhost:9009
export LOKI_URL=http://localhost:3100
export TEMPO_URL=http://localhost:3200
export GRAFANA_URL=http://localhost:3000
export GF_SECURITY_ADMIN_USER=admin
export GF_SECURITY_ADMIN_PASSWORD=admin123
```

## Available Tools

| Script | Purpose |
|---|---|
| `high_cardinality.py` | Find metrics with too many active series |
| `log_analytics.py` | Analyze log volume, errors, and patterns |
| `metric_usage.py` | Identify used vs unused metrics |
| `grafana_mcp.py` | MCP server for AI assistants |
| `utils.py` | Shared HTTP helpers (imported by other scripts) |

## Quick Examples

```bash
cd python-utils

# Top 50 metrics by series count
python high_cardinality.py --top 50

# Log analytics for last 6 hours
python log_analytics.py --hours 6

# Metric usage report + export
python metric_usage.py --export-csv /tmp/usage.csv

# Start MCP server
python grafana_mcp.py
```
