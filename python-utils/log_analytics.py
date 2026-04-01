#!/usr/bin/env python3
"""
log_analytics.py – Analyze logs in Grafana Loki.

Features:
  • Log volume over time (per service, per level)
  • Error rate trends
  • Top error patterns (log clustering)
  • Label cardinality analysis
  • Slowest services from structured log fields

Usage:
    python log_analytics.py                          # last 1h summary
    python log_analytics.py --hours 6                # last 6h
    python log_analytics.py --service payment-svc    # filter by service
    python log_analytics.py --top-errors 20          # top-20 error patterns
    python log_analytics.py --export-json out.json
"""

from __future__ import annotations

import json
import re
import time
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from utils import CONFIG, loki_query_range, loki_labels, loki_label_values, loki_stats, ns_to_iso

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
#  Data models
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LogPattern:
    signature: str           # normalized pattern (numbers/UUIDs stripped)
    count: int
    examples: list[str]
    level: str
    first_seen: str
    last_seen: str


@dataclass
class ServiceLogStats:
    service: str
    total_lines: int
    error_count: int
    warn_count: int
    info_count: int
    error_rate: float         # errors / total
    top_patterns: list[LogPattern] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

_NUM_RE   = re.compile(r"\b\d+\b")
_UUID_RE  = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_HEX_RE   = re.compile(r"\b[0-9a-f]{6,}\b", re.I)
_IP_RE    = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")
_PATH_RE  = re.compile(r"/[^\s\"']+")


def normalize_log_line(line: str) -> str:
    """Strip variable parts to create a log pattern fingerprint."""
    line = _UUID_RE.sub("<UUID>", line)
    line = _IP_RE.sub("<IP>", line)
    line = _HEX_RE.sub("<HEX>", line)
    line = _NUM_RE.sub("<N>", line)
    line = _PATH_RE.sub("<PATH>", line)
    return " ".join(line.split())


def parse_log_entries(loki_response: dict) -> list[dict]:
    """Flatten Loki query_range response into a list of {ts, line, labels}."""
    entries = []
    for stream in loki_response.get("data", {}).get("result", []):
        labels = stream.get("stream", {})
        for ts_ns, line in stream.get("values", []):
            entries.append({
                "ts_ns": int(ts_ns),
                "ts":    ns_to_iso(int(ts_ns)),
                "line":  line,
                "labels": labels,
                "level": _extract_level(line, labels),
            })
    return entries


def _extract_level(line: str, labels: dict) -> str:
    # Try from labels first
    for key in ("level", "severity", "loglevel"):
        v = labels.get(key, "").lower()
        if v:
            return v
    # Fall back to scanning line
    lower = line.lower()
    for lvl in ("error", "fatal", "critical", "warn", "warning", "info", "debug", "trace"):
        if lvl in lower:
            return lvl
    return "unknown"


def cluster_patterns(entries: list[dict], min_count: int = 2) -> list[LogPattern]:
    """Group log lines by normalized pattern."""
    pattern_map: dict[str, list[dict]] = defaultdict(list)

    for e in entries:
        sig = normalize_log_line(e["line"])
        pattern_map[sig].append(e)

    patterns: list[LogPattern] = []
    for sig, items in pattern_map.items():
        if len(items) < min_count:
            continue
        items_sorted = sorted(items, key=lambda x: x["ts_ns"])
        patterns.append(LogPattern(
            signature=sig[:200],
            count=len(items),
            examples=[i["line"][:300] for i in items[:3]],
            level=items[0]["level"],
            first_seen=items_sorted[0]["ts"],
            last_seen=items_sorted[-1]["ts"],
        ))

    return sorted(patterns, key=lambda p: p.count, reverse=True)


def fetch_logs_for_service(service: str, start_ns: int, end_ns: int, limit: int = 5000) -> list[dict]:
    query = f'{{service_name="{service}"}}'
    resp = loki_query_range(query, start_ns, end_ns, limit)
    return parse_log_entries(resp)


def fetch_all_services() -> list[str]:
    try:
        return loki_label_values("service_name")
    except Exception:
        try:
            return loki_label_values("app")
        except Exception:
            return []


def fetch_log_volume_by_level(service: str | None, start_ns: int, end_ns: int) -> dict[str, int]:
    """Count log lines by level using LogQL metric query."""
    base = f'{{service_name="{service}"}}' if service else '{job!=""}'
    results: dict[str, int] = defaultdict(int)
    for level in ("error", "warn", "info", "debug"):
        try:
            q = f'sum(count_over_time({base} |~ "(?i){level}"[1h]))'
            resp = loki_query_range(q, start_ns, end_ns, limit=1)
            for stream in resp.get("data", {}).get("result", []):
                for _, val in stream.get("values", []):
                    results[level] += int(float(val))
        except Exception:
            pass
    return dict(results)


def analyze_service(service: str, start_ns: int, end_ns: int) -> ServiceLogStats:
    entries = fetch_logs_for_service(service, start_ns, end_ns)
    total = len(entries)
    errors = sum(1 for e in entries if e["level"] in ("error", "fatal", "critical"))
    warns  = sum(1 for e in entries if e["level"] in ("warn", "warning"))
    infos  = sum(1 for e in entries if e["level"] == "info")

    error_entries = [e for e in entries if e["level"] in ("error", "fatal", "critical")]
    patterns = cluster_patterns(error_entries)

    return ServiceLogStats(
        service=service,
        total_lines=total,
        error_count=errors,
        warn_count=warns,
        info_count=infos,
        error_rate=errors / max(1, total),
        top_patterns=patterns[:10],
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Rendering
# ─────────────────────────────────────────────────────────────────────────────

def render_service_summary(stats: list[ServiceLogStats]) -> None:
    table = Table(title="Log Analytics – Service Summary", box=box.ROUNDED, highlight=True)
    table.add_column("Service", style="bold cyan")
    table.add_column("Total Lines", justify="right")
    table.add_column("Errors", justify="right", style="red")
    table.add_column("Warnings", justify="right", style="yellow")
    table.add_column("Info", justify="right", style="green")
    table.add_column("Error Rate", justify="right")
    table.add_column("Health", justify="center")

    for s in stats:
        rate_pct = s.error_rate * 100
        health = (
            "[bold red]CRITICAL[/bold red]"  if rate_pct > 10 else
            "[bold yellow]DEGRADED[/bold yellow]"  if rate_pct > 2  else
            "[bold green]HEALTHY[/bold green]"
        )
        table.add_row(
            s.service,
            f"{s.total_lines:,}",
            f"{s.error_count:,}",
            f"{s.warn_count:,}",
            f"{s.info_count:,}",
            f"{rate_pct:.2f}%",
            health,
        )
    console.print(table)


def render_top_errors(patterns: list[LogPattern], top_n: int = 15) -> None:
    table = Table(title="Top Error Patterns", box=box.ROUNDED, highlight=True, show_lines=True)
    table.add_column("Rank", justify="right", style="cyan")
    table.add_column("Count", justify="right", style="red bold")
    table.add_column("Level", style="yellow")
    table.add_column("Pattern (truncated)", style="white")
    table.add_column("Last Seen")

    for i, p in enumerate(patterns[:top_n], 1):
        table.add_row(
            str(i),
            f"{p.count:,}",
            p.level.upper(),
            p.signature[:120],
            p.last_seen,
        )
    console.print(table)


def render_loki_labels(top_n: int = 20) -> None:
    labels = loki_labels()
    table = Table(title="Loki Label Index", box=box.SIMPLE_HEAVY)
    table.add_column("Label", style="cyan")
    table.add_column("# Unique Values", justify="right")

    rows = []
    for lbl in labels:
        try:
            vals = loki_label_values(lbl)
            rows.append((lbl, len(vals)))
        except Exception:
            rows.append((lbl, 0))

    for lbl, n in sorted(rows, key=lambda x: x[1], reverse=True)[:top_n]:
        risk = (
            "[bold red]HIGH[/bold red]"    if n > 1000 else
            "[bold yellow]MED[/bold yellow]" if n > 100  else
            "[green]LOW[/green]"
        )
        table.add_row(f"{lbl}  {risk}", str(n))
    console.print(table)


# ─────────────────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--hours",       default=1,    show_default=True, help="Look-back window in hours")
@click.option("--service",     default=None, help="Limit analysis to one service_name label")
@click.option("--top-errors",  default=15,   show_default=True, help="Top N error patterns to display")
@click.option("--labels",      is_flag=True, help="Show Loki label cardinality")
@click.option("--export-json", "export_json", default=None, help="Export results to JSON file")
@click.option("--loki-url",    default=None, help="Override Loki URL")
def main(
    hours: int,
    service: str | None,
    top_errors: int,
    labels: bool,
    export_json: str | None,
    loki_url: str | None,
) -> None:
    """Analyze logs stored in Grafana Loki."""

    if loki_url:
        CONFIG.loki_url = loki_url

    now_ns   = int(time.time() * 1e9)
    start_ns = now_ns - hours * 3600 * int(1e9)

    console.print(Panel.fit(
        f"[bold cyan]Observability Playground – Log Analytics[/bold cyan]\n"
        f"Loki: [white]{CONFIG.loki_url}[/white]  |  Window: [white]last {hours}h[/white]",
        border_style="cyan",
    ))

    # ── Label cardinality ─────────────────────────────────────────────────────
    if labels:
        render_loki_labels()

    # ── Select services ───────────────────────────────────────────────────────
    if service:
        services = [service]
    else:
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as prog:
            prog.add_task("Discovering services …")
            services = fetch_all_services()
        if not services:
            console.print("[yellow]No services found – pushing data with service_name label?[/yellow]")
            return

    console.print(f"\n[bold]Analyzing {len(services)} service(s):[/bold] {', '.join(services[:10])}\n")

    # ── Per-service analysis ──────────────────────────────────────────────────
    all_stats: list[ServiceLogStats] = []
    all_error_patterns: list[LogPattern] = []

    with Progress(SpinnerColumn(), TextColumn("{task.description}")) as prog:
        task = prog.add_task("Analyzing logs …", total=len(services))
        for svc in services:
            s = analyze_service(svc, start_ns, now_ns)
            all_stats.append(s)
            all_error_patterns.extend(s.top_patterns)
            prog.advance(task)

    all_stats.sort(key=lambda x: x.error_rate, reverse=True)

    render_service_summary(all_stats)

    # ── Top error patterns across all services ────────────────────────────────
    all_error_patterns.sort(key=lambda p: p.count, reverse=True)
    render_top_errors(all_error_patterns, top_errors)

    # ── Recommendations ───────────────────────────────────────────────────────
    high_error_svcs = [s for s in all_stats if s.error_rate > 0.05]
    if high_error_svcs:
        svc_names = ", ".join(s.service for s in high_error_svcs[:5])
        console.print(Panel(
            f"[bold red]Services with error rate > 5%:[/bold red] {svc_names}\n\n"
            "[yellow]Recommendations:[/yellow]\n"
            "  • Add structured error context (stack trace, request_id, user_id)\n"
            "  • Set up Grafana alert rules on error_rate > threshold\n"
            "  • Use LogQL metric queries to track trends over time\n"
            "  • Integrate with Grafana OnCall for automated alerting",
            title="[bold red]Action Required[/bold red]",
            border_style="red",
        ))

    # ── Export ────────────────────────────────────────────────────────────────
    if export_json:
        out = {
            "window_hours": hours,
            "services": [
                {
                    "service": s.service,
                    "total_lines": s.total_lines,
                    "error_count": s.error_count,
                    "error_rate": s.error_rate,
                    "top_patterns": [
                        {"pattern": p.signature, "count": p.count, "level": p.level}
                        for p in s.top_patterns[:5]
                    ],
                }
                for s in all_stats
            ],
        }
        Path(export_json).write_text(json.dumps(out, indent=2))
        console.print(f"[green]Exported to {export_json}[/green]")


if __name__ == "__main__":
    main()
