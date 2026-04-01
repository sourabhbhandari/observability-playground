#!/usr/bin/env python3
"""
grafana_mcp.py – MCP server exposing Mimir, Loki, Tempo and Grafana to AI clients.

Implements the Model Context Protocol (MCP) so that Claude / other LLMs
can fetch metrics, logs, traces and dashboards directly from the playground.

Start with:
    python grafana_mcp.py
    # or via stdio (for Claude Desktop):
    python grafana_mcp.py --transport stdio

Tools exposed:
  query_metrics          – instant PromQL query against Mimir
  query_metrics_range    – range PromQL query (returns time-series)
  list_metrics           – list all metric names
  query_logs             – LogQL query against Loki
  list_log_labels        – list Loki label names and values
  search_traces          – search Tempo traces by tag
  get_trace              – fetch a single trace by ID
  list_dashboards        – list Grafana dashboards
  get_dashboard          – fetch a Grafana dashboard by UID
  list_datasources       – list Grafana datasources
  grafana_health         – check health of all services
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

import click
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolResult,
    GetPromptResult,
    ListToolsResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    TextContent,
    Tool,
)
from pydantic import BaseModel

from utils import (
    CONFIG,
    grafana_api,
    loki_label_values,
    loki_labels,
    loki_query_range,
    mimir_get,
    mimir_instant_query,
    mimir_labels,
    mimir_range_query,
    tempo_search,
    tempo_trace,
    ns_to_iso,
)


# ─────────────────────────────────────────────────────────────────────────────
#  MCP Server
# ─────────────────────────────────────────────────────────────────────────────

server = Server("grafana-observability-mcp")


# ─────────────────────────────────────────────────────────────────────────────
#  Tool definitions
# ─────────────────────────────────────────────────────────────────────────────

TOOLS: list[Tool] = [
    Tool(
        name="query_metrics",
        description=(
            "Execute an instant PromQL query against Grafana Mimir. "
            "Returns the current value(s) for the given expression. "
            "Example: query_metrics(query='up', time='now')"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "PromQL expression"},
                "time":  {"type": "string", "description": "RFC3339 timestamp or Unix seconds (default: now)"},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="query_metrics_range",
        description=(
            "Execute a range PromQL query against Grafana Mimir. "
            "Returns a time-series matrix. "
            "Example: query_metrics_range(query='rate(http_requests_total[5m])', start='1h', end='now', step='1m')"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "PromQL expression"},
                "start": {"type": "string", "description": "Start time: RFC3339, Unix seconds, or relative like '1h', '30m'"},
                "end":   {"type": "string", "description": "End time: RFC3339, Unix seconds, or 'now'"},
                "step":  {"type": "string", "description": "Query step, e.g. '1m', '5m', '1h'", "default": "1m"},
            },
            "required": ["query", "start"],
        },
    ),
    Tool(
        name="list_metrics",
        description="List all metric names stored in Mimir. Optionally filter by prefix or regex.",
        inputSchema={
            "type": "object",
            "properties": {
                "filter": {"type": "string", "description": "Substring or regex to filter metric names"},
                "limit":  {"type": "integer", "description": "Maximum names to return", "default": 200},
            },
        },
    ),
    Tool(
        name="query_logs",
        description=(
            "Execute a LogQL query against Grafana Loki. "
            "Supports log stream selectors and filter expressions. "
            "Example: query_logs(query='{service_name=\"api\"} |= \"error\"', hours=1)"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query":  {"type": "string", "description": "LogQL expression"},
                "hours":  {"type": "number", "description": "Look-back window in hours", "default": 1},
                "limit":  {"type": "integer", "description": "Max log lines", "default": 100},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="list_log_labels",
        description="List all label names in Loki, and optionally the values for a specific label.",
        inputSchema={
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "Label name to fetch values for (optional)"},
            },
        },
    ),
    Tool(
        name="search_traces",
        description=(
            "Search traces in Grafana Tempo. "
            "Filter by service name, operation, duration, etc. "
            "Example: search_traces(service='checkout', limit=10)"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "service":    {"type": "string", "description": "service.name tag filter"},
                "operation":  {"type": "string", "description": "span name filter"},
                "min_duration": {"type": "string", "description": "minimum duration e.g. '100ms', '1s'"},
                "limit":      {"type": "integer", "description": "Max traces", "default": 20},
            },
        },
    ),
    Tool(
        name="get_trace",
        description="Fetch a single trace by trace ID from Grafana Tempo.",
        inputSchema={
            "type": "object",
            "properties": {
                "trace_id": {"type": "string", "description": "Hex trace ID"},
            },
            "required": ["trace_id"],
        },
    ),
    Tool(
        name="list_dashboards",
        description="List all Grafana dashboards. Optionally filter by folder or title substring.",
        inputSchema={
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Filter by folder name"},
                "query":  {"type": "string", "description": "Title substring filter"},
                "limit":  {"type": "integer", "default": 50},
            },
        },
    ),
    Tool(
        name="get_dashboard",
        description="Fetch a Grafana dashboard by UID. Returns the full dashboard JSON.",
        inputSchema={
            "type": "object",
            "properties": {
                "uid": {"type": "string", "description": "Dashboard UID"},
            },
            "required": ["uid"],
        },
    ),
    Tool(
        name="list_datasources",
        description="List all configured Grafana datasources.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="grafana_health",
        description="Check the health / readiness of all observability stack services.",
        inputSchema={"type": "object", "properties": {}},
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_time(t: str | None) -> str:
    if not t or t.lower() == "now":
        return datetime.now(timezone.utc).isoformat()
    # Relative like "1h", "30m"
    if t.endswith("h") and t[:-1].isdigit():
        secs = int(t[:-1]) * 3600
        return datetime.fromtimestamp(time.time() - secs, tz=timezone.utc).isoformat()
    if t.endswith("m") and t[:-1].isdigit():
        secs = int(t[:-1]) * 60
        return datetime.fromtimestamp(time.time() - secs, tz=timezone.utc).isoformat()
    return t  # assume already ISO or unix


def _ok(data: Any) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data, indent=2, default=str))],
        isError=False,
    )


def _err(msg: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=f"Error: {msg}")],
        isError=True,
    )


def check_service_health(url: str, path: str = "/ready") -> dict:
    import httpx
    try:
        r = httpx.get(f"{url}{path}", timeout=5)
        return {"status": "ok" if r.status_code < 400 else "degraded", "code": r.status_code}
    except Exception as e:
        return {"status": "unreachable", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
#  Tool handlers
# ─────────────────────────────────────────────────────────────────────────────

@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> CallToolResult:
    try:
        match name:
            # ── Metrics ─────────────────────────────────────────────────────
            case "query_metrics":
                query = arguments["query"]
                t     = _resolve_time(arguments.get("time"))
                result = mimir_instant_query(query, t)
                vecs   = result.get("data", {}).get("result", [])
                return _ok({
                    "query":      query,
                    "resultType": result.get("data", {}).get("resultType"),
                    "results":    [
                        {
                            "labels": v.get("metric", {}),
                            "value":  v.get("value", [None, None])[1],
                            "timestamp": v.get("value", [None, None])[0],
                        }
                        for v in vecs
                    ],
                })

            case "query_metrics_range":
                query = arguments["query"]
                start = _resolve_time(arguments.get("start", "1h"))
                end   = _resolve_time(arguments.get("end", "now"))
                step  = arguments.get("step", "1m")
                result = mimir_range_query(query, start, end, step)
                matrix = result.get("data", {}).get("result", [])
                # Summarize to avoid huge payloads
                summary = []
                for series in matrix[:20]:
                    vals = series.get("values", [])
                    summary.append({
                        "labels":     series.get("metric", {}),
                        "data_points": len(vals),
                        "first":      vals[0] if vals else None,
                        "last":       vals[-1] if vals else None,
                    })
                return _ok({"query": query, "start": start, "end": end, "step": step, "series": summary})

            case "list_metrics":
                filter_str = arguments.get("filter", "")
                limit      = int(arguments.get("limit", 200))
                data = mimir_get("/prometheus/api/v1/label/__name__/values")
                names = data.get("data", [])
                if filter_str:
                    import re
                    try:
                        pat = re.compile(filter_str, re.I)
                        names = [n for n in names if pat.search(n)]
                    except Exception:
                        names = [n for n in names if filter_str.lower() in n.lower()]
                return _ok({"count": len(names), "metrics": names[:limit]})

            # ── Logs ────────────────────────────────────────────────────────
            case "query_logs":
                query   = arguments["query"]
                hours   = float(arguments.get("hours", 1))
                limit   = int(arguments.get("limit", 100))
                now_ns  = int(time.time() * 1e9)
                start_ns = now_ns - int(hours * 3600 * 1e9)
                resp    = loki_query_range(query, start_ns, now_ns, limit)
                lines   = []
                for stream in resp.get("data", {}).get("result", []):
                    labels = stream.get("stream", {})
                    for ts_ns, line in stream.get("values", [])[:limit]:
                        lines.append({
                            "timestamp": ns_to_iso(int(ts_ns)),
                            "labels": labels,
                            "line": line,
                        })
                lines.sort(key=lambda x: x["timestamp"], reverse=True)
                return _ok({"query": query, "total": len(lines), "logs": lines[:limit]})

            case "list_log_labels":
                label = arguments.get("label")
                if label:
                    vals = loki_label_values(label)
                    return _ok({"label": label, "values": vals, "count": len(vals)})
                else:
                    lbls = loki_labels()
                    return _ok({"labels": lbls, "count": len(lbls)})

            # ── Traces ──────────────────────────────────────────────────────
            case "search_traces":
                tags: dict[str, str] = {}
                if s := arguments.get("service"):
                    tags["service.name"] = s
                if op := arguments.get("operation"):
                    tags["name"] = op
                limit = int(arguments.get("limit", 20))
                result = tempo_search(tags, limit)
                return _ok(result)

            case "get_trace":
                trace_id = arguments["trace_id"]
                result = tempo_trace(trace_id)
                return _ok(result)

            # ── Grafana ──────────────────────────────────────────────────────
            case "list_dashboards":
                qs = "/api/search?type=dash-db&limit=500"
                if q := arguments.get("query"):
                    qs += f"&query={q}"
                results = grafana_api(qs)
                folder_filter = arguments.get("folder", "").lower()
                if folder_filter:
                    results = [r for r in results if folder_filter in r.get("folderTitle", "").lower()]
                limit = int(arguments.get("limit", 50))
                return _ok([
                    {"uid": r.get("uid"), "title": r.get("title"), "folder": r.get("folderTitle"), "url": r.get("url")}
                    for r in results[:limit]
                ])

            case "get_dashboard":
                uid    = arguments["uid"]
                result = grafana_api(f"/api/dashboards/uid/{uid}")
                db     = result.get("dashboard", {})
                # Summarize panels
                panels = [
                    {"title": p.get("title"), "type": p.get("type"), "targets_count": len(p.get("targets", []))}
                    for p in db.get("panels", [])
                ]
                return _ok({
                    "uid":         uid,
                    "title":       db.get("title"),
                    "description": db.get("description"),
                    "tags":        db.get("tags"),
                    "panels":      panels,
                })

            case "list_datasources":
                data = grafana_api("/api/datasources")
                return _ok([
                    {"uid": d.get("uid"), "name": d.get("name"), "type": d.get("type"), "url": d.get("url")}
                    for d in data
                ])

            case "grafana_health":
                services = {
                    "mimir":   check_service_health(CONFIG.mimir_url, "/ready"),
                    "loki":    check_service_health(CONFIG.loki_url,  "/ready"),
                    "tempo":   check_service_health(CONFIG.tempo_url, "/ready"),
                    "grafana": check_service_health(CONFIG.grafana_url, "/api/health"),
                }
                overall = "ok" if all(v["status"] == "ok" for v in services.values()) else "degraded"
                return _ok({"overall": overall, "services": services})

            case _:
                return _err(f"Unknown tool: {name}")

    except Exception as exc:
        return _err(str(exc))


# ─────────────────────────────────────────────────────────────────────────────
#  Prompts (pre-built investigation templates)
# ─────────────────────────────────────────────────────────────────────────────

@server.list_prompts()
async def handle_list_prompts() -> list[Prompt]:
    return [
        Prompt(
            name="investigate_service",
            description="Full observability investigation for a given service: metrics, logs, and traces.",
            arguments=[
                PromptArgument(name="service", description="Service name to investigate", required=True),
                PromptArgument(name="hours",   description="Look-back window in hours", required=False),
            ],
        ),
        Prompt(
            name="error_investigation",
            description="Investigate recent errors across metrics, logs, and traces.",
            arguments=[
                PromptArgument(name="hours", description="Look-back window", required=False),
            ],
        ),
    ]


@server.get_prompt()
async def handle_get_prompt(name: str, arguments: dict | None) -> GetPromptResult:
    args = arguments or {}
    hours = args.get("hours", "1")

    if name == "investigate_service":
        service = args.get("service", "<service>")
        messages = [
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=(
                        f"Investigate the service '{service}' over the last {hours} hour(s).\n\n"
                        "Please:\n"
                        f"1. Use query_metrics to check: rate(http_requests_total{{service='{service}'}}[5m]), "
                        f"   histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{{service='{service}'}}[5m]))\n"
                        f"2. Use query_logs with query='{{service_name=\"{service}\"}} |= \"error\"' to find recent errors\n"
                        f"3. Use search_traces with service='{service}' to find recent traces\n"
                        "4. Summarise findings and suggest next actions."
                    ),
                ),
            )
        ]
        return GetPromptResult(description=f"Investigate {service}", messages=messages)

    if name == "error_investigation":
        messages = [
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=(
                        f"Investigate errors across all services over the last {hours} hour(s).\n\n"
                        "Please:\n"
                        "1. Use query_metrics: sum by (service) (rate(http_requests_total{status=~'5..'}[5m]))\n"
                        "2. Use query_logs with query='{job!=\"\"} |= \"error\" | logfmt' for recent errors\n"
                        "3. Use search_traces to look for failed traces\n"
                        "4. Correlate findings across the three pillars and provide a root cause hypothesis."
                    ),
                ),
            )
        ]
        return GetPromptResult(description="Error investigation", messages=messages)

    raise ValueError(f"Unknown prompt: {name}")


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--transport", default="stdio", type=click.Choice(["stdio"]), help="MCP transport")
@click.option("--mimir-url",   default=None)
@click.option("--loki-url",    default=None)
@click.option("--tempo-url",   default=None)
@click.option("--grafana-url", default=None)
def main(transport: str, mimir_url: str | None, loki_url: str | None, tempo_url: str | None, grafana_url: str | None) -> None:
    """Start the Grafana MCP server."""
    if mimir_url:   CONFIG.mimir_url   = mimir_url
    if loki_url:    CONFIG.loki_url    = loki_url
    if tempo_url:   CONFIG.tempo_url   = tempo_url
    if grafana_url: CONFIG.grafana_url = grafana_url

    import asyncio

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
