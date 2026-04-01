# Grafana MCP Server

`python-utils/grafana_mcp.py` is a **Model Context Protocol (MCP)** server that exposes your entire observability stack to AI assistants (Claude, etc.).

## Starting the Server

```bash
cd python-utils
python grafana_mcp.py
```

For Claude Desktop integration, add to `~/.config/claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "grafana-observability": {
      "command": "python3",
      "args": ["/path/to/python-utils/grafana_mcp.py"],
      "env": {
        "MIMIR_URL":   "http://localhost:9009",
        "LOKI_URL":    "http://localhost:3100",
        "TEMPO_URL":   "http://localhost:3200",
        "GRAFANA_URL": "http://localhost:3000"
      }
    }
  }
}
```

## Available Tools

### Metrics (Mimir)

| Tool | Description | Example |
|---|---|---|
| `query_metrics` | Instant PromQL query | `query_metrics(query="up")` |
| `query_metrics_range` | Range PromQL query | `query_metrics_range(query="rate(...)", start="1h")` |
| `list_metrics` | List metric names | `list_metrics(filter="http_")` |

### Logs (Loki)

| Tool | Description | Example |
|---|---|---|
| `query_logs` | LogQL query | `query_logs(query='{app="api"} \|= "error"', hours=1)` |
| `list_log_labels` | List label names/values | `list_log_labels(label="service_name")` |

### Traces (Tempo)

| Tool | Description | Example |
|---|---|---|
| `search_traces` | Search traces by tag | `search_traces(service="checkout")` |
| `get_trace` | Fetch a trace by ID | `get_trace(trace_id="abc123")` |

### Grafana

| Tool | Description |
|---|---|
| `list_dashboards` | List all dashboards |
| `get_dashboard` | Fetch dashboard by UID |
| `list_datasources` | List datasources |
| `grafana_health` | Health of all services |

## Built-in Prompts

The MCP server also ships two investigation prompt templates:

### `investigate_service`
Guides the AI to investigate a specific service across metrics, logs, and traces.

```
Use the "investigate_service" prompt with service="checkout" hours="2"
```

### `error_investigation`
Guides the AI to find and correlate errors across the full stack.

```
Use the "error_investigation" prompt with hours="1"
```

## Example AI Conversation

> **You:** What is the error rate for the sample-app service over the last 30 minutes?
>
> **Claude (using MCP):** *(calls `query_metrics` with `sum(rate(http_requests_total{service="sample-app",status=~"5.."}[5m])) / sum(rate(http_requests_total{service="sample-app"}[5m]))`)*
>
> The error rate for sample-app over the last 30 minutes is **2.3%**. Let me also check the logs…
>
> *(calls `query_logs` with `{service_name="sample-app"} |= "error"`, hours=0.5)*
>
> I found 47 error log lines, primarily `DB timeout on orders`. The most recent trace ID is `abc123ef`. Let me fetch that trace to see what happened…
