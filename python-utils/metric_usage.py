#!/usr/bin/env python3
"""
metric_usage.py – Identify USED vs UNUSED metrics in Grafana dashboards/alerts.

Compares metrics actually queried in Grafana (dashboards + alert rules)
against all metrics stored in Mimir to surface dead weight.

Usage:
    python metric_usage.py                   # full used/unused report
    python metric_usage.py --unused-only     # list unused metrics
    python metric_usage.py --export-csv out.csv
"""

from __future__ import annotations

import csv
import json
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from utils import CONFIG, grafana_api, mimir_get, log

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
#  PromQL metric name extractor (simple regex approach)
# ─────────────────────────────────────────────────────────────────────────────

_METRIC_RE = re.compile(r"(?<![a-zA-Z0-9_])[a-zA-Z_:][a-zA-Z0-9_:]*(?=\s*(?:\{|[^a-zA-Z0-9_\(])|\s*$)")
_FUNCTIONS  = frozenset([
    "rate", "irate", "increase", "delta", "idelta", "changes",
    "resets", "sum", "min", "max", "avg", "count", "stddev", "stdvar",
    "topk", "bottomk", "quantile", "label_replace", "label_join",
    "vector", "scalar", "histogram_quantile", "absent", "absent_over_time",
    "predict_linear", "deriv", "sort", "sort_desc", "round", "ceil", "floor",
    "abs", "ln", "log2", "log10", "exp", "sqrt", "time", "minute", "hour",
    "day_of_month", "day_of_week", "days_in_month", "month", "year",
    "timestamp", "clamp", "clamp_max", "clamp_min", "last_over_time",
    "avg_over_time", "min_over_time", "max_over_time", "sum_over_time",
    "count_over_time", "quantile_over_time", "stddev_over_time",
    "stdvar_over_time", "first_over_time", "info", "group",
    "bool", "ignoring", "on", "without", "by", "or", "and", "unless",
    "offset", "for", "if", "else",
])


def extract_metrics_from_promql(expr: str) -> set[str]:
    """Extract metric names from a PromQL expression."""
    candidates = _METRIC_RE.findall(expr)
    return {c for c in candidates if c not in _FUNCTIONS and not c.startswith("__")}


# ─────────────────────────────────────────────────────────────────────────────
#  Grafana data fetchers
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GrafanaDashboard:
    uid: str
    title: str
    folder: str
    panels: list[str] = field(default_factory=list)      # raw PromQL exprs
    metrics_used: set[str] = field(default_factory=set)


@dataclass
class GrafanaAlertRule:
    uid: str
    title: str
    expr: str
    metrics_used: set[str] = field(default_factory=set)


def fetch_all_dashboards() -> list[GrafanaDashboard]:
    results: list[GrafanaDashboard] = []
    search = grafana_api("/api/search?type=dash-db&limit=500")

    for item in search:
        uid   = item.get("uid", "")
        title = item.get("title", "")
        folder = item.get("folderTitle", "General")

        try:
            detail = grafana_api(f"/api/dashboards/uid/{uid}")
        except Exception:
            continue

        dashboard = detail.get("dashboard", {})
        db = GrafanaDashboard(uid=uid, title=title, folder=folder)

        # Walk panels and rows
        for panel in _walk_panels(dashboard):
            for target in panel.get("targets", []):
                expr = target.get("expr", "") or target.get("query", "")
                if expr:
                    db.panels.append(expr)
                    db.metrics_used |= extract_metrics_from_promql(expr)

        results.append(db)

    return results


def _walk_panels(dashboard: dict) -> list[dict]:
    """Flatten nested panels/rows."""
    panels = []
    for p in dashboard.get("panels", []):
        if p.get("type") == "row":
            for sub in p.get("panels", []):
                panels.append(sub)
        else:
            panels.append(p)
    return panels


def fetch_alert_rules() -> list[GrafanaAlertRule]:
    rules: list[GrafanaAlertRule] = []
    try:
        data = grafana_api("/api/ruler/grafana/api/v1/rules")
    except Exception:
        try:
            data = grafana_api("/api/alerts")
        except Exception:
            return []

    # Unified alerting (ruler API returns namespace → group → rules)
    if isinstance(data, dict):
        for namespace, groups in data.items():
            for group in groups:
                for rule in group.get("rules", []):
                    expr = (
                        rule.get("grafana_alert", {}).get("data", [{}])[0]
                        .get("model", {}).get("expr", "")
                    )
                    title = rule.get("grafana_alert", {}).get("title", "")
                    uid   = rule.get("grafana_alert", {}).get("uid", "")
                    if expr:
                        ar = GrafanaAlertRule(uid=uid, title=title, expr=expr)
                        ar.metrics_used = extract_metrics_from_promql(expr)
                        rules.append(ar)
    return rules


def fetch_all_stored_metrics() -> list[str]:
    data = mimir_get("/prometheus/api/v1/label/__name__/values")
    return data.get("data", [])


# ─────────────────────────────────────────────────────────────────────────────
#  Analysis
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class UsageReport:
    total_stored: int
    used_metrics: set[str]
    unused_metrics: set[str]
    dashboard_metric_map: dict[str, list[str]]   # metric → [dashboard titles]
    alert_metric_map: dict[str, list[str]]        # metric → [alert titles]


def build_usage_report(
    dashboards: list[GrafanaDashboard],
    alerts: list[GrafanaAlertRule],
    stored: list[str],
) -> UsageReport:
    all_used: set[str] = set()
    db_map:   dict[str, list[str]] = defaultdict(list)
    al_map:   dict[str, list[str]] = defaultdict(list)

    for db in dashboards:
        for m in db.metrics_used:
            all_used.add(m)
            db_map[m].append(db.title)

    for ar in alerts:
        for m in ar.metrics_used:
            all_used.add(m)
            al_map[m].append(ar.title)

    stored_set = set(stored)
    used_intersection = all_used & stored_set
    unused = stored_set - all_used

    return UsageReport(
        total_stored=len(stored_set),
        used_metrics=used_intersection,
        unused_metrics=unused,
        dashboard_metric_map=dict(db_map),
        alert_metric_map=dict(al_map),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Rendering
# ─────────────────────────────────────────────────────────────────────────────

def render_summary(report: UsageReport) -> None:
    total   = report.total_stored
    used    = len(report.used_metrics)
    unused  = len(report.unused_metrics)
    pct     = (unused / max(1, total)) * 100

    console.print(Panel(
        f"[bold]Total metrics stored in Mimir:[/bold] [yellow]{total:,}[/yellow]\n"
        f"[bold]Metrics used in dashboards/alerts:[/bold] [green]{used:,}[/green]\n"
        f"[bold]Unused metrics:[/bold] [red]{unused:,}[/red] ([red]{pct:.1f}%[/red] of total)\n\n"
        f"[dim]Unused = never referenced in any Grafana dashboard panel or alert rule[/dim]",
        title="[bold cyan]Metric Usage Summary[/bold cyan]",
        border_style="cyan",
    ))


def render_used_metrics(report: UsageReport, top_n: int = 30) -> None:
    table = Table(title=f"Used Metrics (top {top_n} by dashboard refs)", box=box.ROUNDED)
    table.add_column("Metric", style="bold green")
    table.add_column("Dashboard Refs", justify="right")
    table.add_column("Alert Refs", justify="right")
    table.add_column("Dashboards")

    rows = [
        (m, len(report.dashboard_metric_map.get(m, [])), len(report.alert_metric_map.get(m, [])))
        for m in report.used_metrics
    ]
    rows.sort(key=lambda x: x[1] + x[2], reverse=True)

    for m, db_refs, al_refs in rows[:top_n]:
        dbs = ", ".join(report.dashboard_metric_map.get(m, [])[:3])
        table.add_row(m, str(db_refs), str(al_refs), dbs[:80])
    console.print(table)


def render_unused_metrics(report: UsageReport, top_n: int = 50) -> None:
    table = Table(title=f"Unused Metrics (sample of {top_n})", box=box.ROUNDED)
    table.add_column("Metric Name", style="bold red")
    table.add_column("Tip")

    sorted_unused = sorted(report.unused_metrics)[:top_n]
    for m in sorted_unused:
        tip = "consider dropping" if "_total" in m or "_bucket" in m else "review"
        table.add_row(m, tip)
    console.print(table)


def export_to_csv(report: UsageReport, path: str) -> None:
    out = Path(path)
    with out.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric_name", "status", "dashboard_refs", "alert_refs", "dashboards"])
        for m in sorted(report.used_metrics):
            db_refs = report.dashboard_metric_map.get(m, [])
            al_refs = report.alert_metric_map.get(m, [])
            writer.writerow([m, "used", len(db_refs), len(al_refs), "|".join(db_refs[:5])])
        for m in sorted(report.unused_metrics):
            writer.writerow([m, "unused", 0, 0, ""])
    console.print(f"[green]Exported to {out}[/green]")


# ─────────────────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--unused-only",  is_flag=True, help="Show only unused metrics")
@click.option("--used-only",    is_flag=True, help="Show only used metrics")
@click.option("--top",          default=30,   show_default=True, help="Rows per table")
@click.option("--export-csv",   "export_csv", default=None, help="Export full report to CSV")
@click.option("--grafana-url",  default=None, help="Override Grafana URL")
@click.option("--mimir-url",    default=None, help="Override Mimir URL")
def main(
    unused_only: bool,
    used_only: bool,
    top: int,
    export_csv: str | None,
    grafana_url: str | None,
    mimir_url: str | None,
) -> None:
    """Report on which Mimir metrics are used vs unused in Grafana."""

    if grafana_url:
        CONFIG.grafana_url = grafana_url
    if mimir_url:
        CONFIG.mimir_url = mimir_url

    console.print(Panel.fit(
        f"[bold cyan]Observability Playground – Metric Usage Analyzer[/bold cyan]\n"
        f"Grafana: [white]{CONFIG.grafana_url}[/white]  |  Mimir: [white]{CONFIG.mimir_url}[/white]",
        border_style="cyan",
    ))

    with Progress(SpinnerColumn(), TextColumn("{task.description}")) as prog:
        t1 = prog.add_task("Fetching Grafana dashboards …")
        dashboards = fetch_all_dashboards()
        prog.update(t1, completed=True, description=f"Found {len(dashboards)} dashboards")

        t2 = prog.add_task("Fetching Grafana alert rules …")
        alerts = fetch_alert_rules()
        prog.update(t2, completed=True, description=f"Found {len(alerts)} alert rules")

        t3 = prog.add_task("Fetching stored metrics from Mimir …")
        stored = fetch_all_stored_metrics()
        prog.update(t3, completed=True, description=f"Found {len(stored):,} stored metrics")

    report = build_usage_report(dashboards, alerts, stored)

    render_summary(report)

    if not unused_only:
        render_used_metrics(report, top)

    if not used_only:
        render_unused_metrics(report, top)

    if export_csv:
        export_to_csv(report, export_csv)

    # Recommendations
    pct = len(report.unused_metrics) / max(1, report.total_stored) * 100
    if pct > 20:
        console.print(Panel(
            f"[bold yellow]{pct:.1f}% of metrics are never used in dashboards or alerts.[/bold yellow]\n\n"
            "[cyan]Recommendations:[/cyan]\n"
            "  • Add drop rules in OTel Collector for unused metrics\n"
            "  • Use Mimir's metric-level relabelling to discard noisy exporters\n"
            "  • Build dashboards to cover high-value business metrics\n"
            "  • Run this report regularly and track the unused % over time",
            title="[bold yellow]Optimization Opportunity[/bold yellow]",
            border_style="yellow",
        ))


if __name__ == "__main__":
    main()
