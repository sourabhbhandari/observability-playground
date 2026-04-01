#!/usr/bin/env python3
"""
high_cardinality.py – Detect high-cardinality metrics in Mimir/Prometheus.

Usage:
    python high_cardinality.py                    # report on all metrics
    python high_cardinality.py --top 20           # top-20 by series count
    python high_cardinality.py --threshold 1000   # flag metrics over 1000 series
    python high_cardinality.py --label-analysis   # per-label cardinality breakdown
    python high_cardinality.py --export-csv out.csv
"""

from __future__ import annotations

import csv
import json
import sys
import time
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
import httpx
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from utils import CONFIG, log, mimir_get, mimir_instant_query, mimir_labels, mimir_label_values

console = Console()

# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class MetricCardinality:
    name: str
    series_count: int
    label_names: list[str]
    label_counts: dict[str, int] = field(default_factory=dict)  # label → unique values
    top_explosive_label: str | None = None
    cardinality_score: float = 0.0   # higher = more explosive


def fetch_all_metric_names() -> list[str]:
    data = mimir_get("/prometheus/api/v1/label/__name__/values")
    return sorted(data.get("data", []))


def series_count_for_metric(metric: str, timeout: int = 10) -> int:
    try:
        result = mimir_instant_query(f"count({{__name__='{metric}'}})")
        vecs = result.get("data", {}).get("result", [])
        if vecs:
            return int(float(vecs[0]["value"][1]))
        return 0
    except Exception:
        return 0


def total_series_count() -> int:
    try:
        r = mimir_instant_query("count({__name__=~'.+'})")
        vecs = r.get("data", {}).get("result", [])
        return int(float(vecs[0]["value"][1])) if vecs else 0
    except Exception:
        return 0


def label_cardinality(label: str) -> int:
    try:
        vals = mimir_label_values(label)
        return len(vals)
    except Exception:
        return 0


def label_cardinality_for_metric(metric: str, label: str) -> int:
    try:
        r = mimir_instant_query(f"count(count by ({label}) ({{{label}!='', __name__='{metric}'}})) or vector(0)")
        vecs = r.get("data", {}).get("result", [])
        return int(float(vecs[0]["value"][1])) if vecs else 0
    except Exception:
        return 0


def fetch_metric_labels(metric: str) -> list[str]:
    try:
        data = mimir_get("/prometheus/api/v1/series", {"match[]": f"{{{metric!r}}}"})
        series = data.get("data", [])
        if not series:
            return []
        return [k for k in series[0].keys() if k != "__name__"]
    except Exception:
        return []


def analyze_metric(metric: str, include_labels: bool = False) -> MetricCardinality:
    count = series_count_for_metric(metric)
    labels = fetch_metric_labels(metric) if include_labels else []

    label_counts: dict[str, int] = {}
    top_label = None
    top_count = 0

    if include_labels:
        for lbl in labels:
            n = label_cardinality_for_metric(metric, lbl)
            label_counts[lbl] = n
            if n > top_count:
                top_count = n
                top_label = lbl

    # Cardinality score = series / max(1, # labels)  (simple heuristic)
    score = count / max(1, len(labels)) if labels else float(count)

    return MetricCardinality(
        name=metric,
        series_count=count,
        label_names=labels,
        label_counts=label_counts,
        top_explosive_label=top_label,
        cardinality_score=score,
    )


def global_label_cardinality() -> list[tuple[str, int]]:
    """Return (label_name, unique_value_count) sorted desc."""
    labels = mimir_labels()
    results = []
    for lbl in labels:
        n = label_cardinality(lbl)
        results.append((lbl, n))
    return sorted(results, key=lambda x: x[1], reverse=True)


def render_top_metrics(metrics: list[MetricCardinality], threshold: int) -> None:
    table = Table(
        title="High-Cardinality Metrics",
        box=box.ROUNDED,
        show_lines=True,
        highlight=True,
    )
    table.add_column("Rank", style="bold cyan", justify="right")
    table.add_column("Metric Name", style="bold white")
    table.add_column("Series Count", justify="right")
    table.add_column("Status", justify="center")
    table.add_column("Top Explosive Label")
    table.add_column("Score", justify="right")

    for i, m in enumerate(metrics, 1):
        status = (
            "[bold red]CRITICAL[/bold red]" if m.series_count > threshold * 5 else
            "[bold yellow]HIGH[/bold yellow]"    if m.series_count > threshold     else
            "[green]OK[/green]"
        )
        table.add_row(
            str(i),
            m.name,
            f"{m.series_count:,}",
            status,
            m.top_explosive_label or "–",
            f"{m.cardinality_score:.1f}",
        )
    console.print(table)


def render_label_analysis(label_data: list[tuple[str, int]], top_n: int = 30) -> None:
    table = Table(
        title="Global Label Cardinality (top values = high cardinality risk)",
        box=box.ROUNDED,
        highlight=True,
    )
    table.add_column("Label Name", style="bold cyan")
    table.add_column("Unique Values", justify="right")
    table.add_column("Risk", justify="center")

    for lbl, count in label_data[:top_n]:
        risk = (
            "[bold red]CRITICAL[/bold red]" if count > 10_000 else
            "[bold yellow]HIGH[/bold yellow]"    if count > 1_000  else
            "[green]LOW[/green]"
        )
        table.add_row(lbl, f"{count:,}", risk)
    console.print(table)


def export_to_csv(metrics: list[MetricCardinality], path: str) -> None:
    out = Path(path)
    with out.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric_name", "series_count", "label_names", "top_explosive_label", "cardinality_score"])
        for m in metrics:
            writer.writerow([
                m.name,
                m.series_count,
                "|".join(m.label_names),
                m.top_explosive_label or "",
                f"{m.cardinality_score:.2f}",
            ])
    console.print(f"[green]Exported {len(metrics)} metrics to {out}[/green]")


# ─────────────────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--top", default=50, show_default=True, help="Show top N metrics by series count")
@click.option("--threshold", default=500, show_default=True, help="Series count threshold to flag as HIGH")
@click.option("--label-analysis", is_flag=True, help="Show per-label global cardinality analysis")
@click.option("--export-csv", "export_csv", default=None, help="Export results to CSV file")
@click.option("--mimir-url", default=None, help="Override Mimir URL")
@click.option("--include-labels", is_flag=True, help="Fetch per-metric label breakdowns (slower)")
def main(
    top: int,
    threshold: int,
    label_analysis: bool,
    export_csv: str | None,
    mimir_url: str | None,
    include_labels: bool,
) -> None:
    """Detect high-cardinality metrics in the Mimir / Prometheus backend."""

    if mimir_url:
        CONFIG.mimir_url = mimir_url

    console.print(Panel.fit(
        f"[bold cyan]Observability Playground – Cardinality Analyzer[/bold cyan]\n"
        f"Mimir: [white]{CONFIG.mimir_url}[/white]",
        border_style="cyan",
    ))

    # ── Total series ──────────────────────────────────────────────────────────
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as prog:
        prog.add_task("Counting total series …")
        total = total_series_count()

    console.print(f"\n[bold]Total active series:[/bold] [yellow]{total:,}[/yellow]\n")

    # ── Fetch all metric names ────────────────────────────────────────────────
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as prog:
        prog.add_task("Fetching metric names …")
        metric_names = fetch_all_metric_names()

    console.print(f"[bold]Unique metric names:[/bold] [yellow]{len(metric_names):,}[/yellow]\n")

    # ── Analyze per-metric ────────────────────────────────────────────────────
    results: list[MetricCardinality] = []
    with Progress(SpinnerColumn(), TextColumn("{task.description}")) as prog:
        task = prog.add_task(f"Analyzing top-{top} metrics …", total=min(top, len(metric_names)))

        # Quick series count via batch query for speed
        batch_query = "topk({}, count by (__name__)({{{}}})[:5m])".format(
            top, "__name__!=''"
        )
        try:
            r = mimir_instant_query(
                f"topk({top}, count by (__name__) ({{__name__!=''}}))"
            )
            vecs = r.get("data", {}).get("result", [])
            top_metrics = [(v["metric"]["__name__"], int(float(v["value"][1]))) for v in vecs]
        except Exception:
            top_metrics = [(m, 0) for m in metric_names[:top]]

        for name, count in sorted(top_metrics, key=lambda x: x[1], reverse=True):
            m = MetricCardinality(name=name, series_count=count, label_names=[])
            if include_labels:
                m = analyze_metric(name, include_labels=True)
            results.append(m)
            prog.advance(task)

    # Sort by series count
    results.sort(key=lambda x: x.series_count, reverse=True)

    # ── Render results ────────────────────────────────────────────────────────
    render_top_metrics(results, threshold)

    # ── Label analysis ────────────────────────────────────────────────────────
    if label_analysis:
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as prog:
            prog.add_task("Analyzing label cardinality …")
            lbl_data = global_label_cardinality()
        render_label_analysis(lbl_data)

    # ── Recommendations ───────────────────────────────────────────────────────
    high = [m for m in results if m.series_count > threshold]
    if high:
        console.print(Panel(
            f"[bold red]{len(high)} metrics exceed the threshold of {threshold:,} series.[/bold red]\n\n"
            "[yellow]Recommendations:[/yellow]\n"
            "  • Drop or relabel high-cardinality labels (e.g. user_id, request_id)\n"
            "  • Use recording rules to pre-aggregate before storing\n"
            "  • Apply OTel Collector 'filter' or 'transform' processors to reduce labels\n"
            "  • Use Mimir's 'max_global_series_per_user' limit as a guardrail",
            title="[bold red]Action Required[/bold red]",
            border_style="red",
        ))
    else:
        console.print("[bold green]All metrics are within the acceptable cardinality threshold.[/bold green]")

    # ── Export ────────────────────────────────────────────────────────────────
    if export_csv:
        export_to_csv(results, export_csv)


if __name__ == "__main__":
    main()
