"""
utils.py – Shared helpers for the Observability Playground Python tools.
"""

from __future__ import annotations

import os
import time
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generator
from urllib.parse import urlencode

import httpx
import structlog

# ─────────────────────────────────────────────────────────────────────────────
#  Logging setup
# ─────────────────────────────────────────────────────────────────────────────

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

log = structlog.get_logger()


# ─────────────────────────────────────────────────────────────────────────────
#  Endpoint defaults
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PlaygroundConfig:
    mimir_url: str   = field(default_factory=lambda: os.getenv("MIMIR_URL",    "http://localhost:9009"))
    loki_url: str    = field(default_factory=lambda: os.getenv("LOKI_URL",     "http://localhost:3100"))
    tempo_url: str   = field(default_factory=lambda: os.getenv("TEMPO_URL",    "http://localhost:3200"))
    grafana_url: str = field(default_factory=lambda: os.getenv("GRAFANA_URL",  "http://localhost:3000"))
    grafana_user: str     = field(default_factory=lambda: os.getenv("GF_SECURITY_ADMIN_USER",     "admin"))
    grafana_password: str = field(default_factory=lambda: os.getenv("GF_SECURITY_ADMIN_PASSWORD", "admin123"))


# Singleton config
CONFIG = PlaygroundConfig()


# ─────────────────────────────────────────────────────────────────────────────
#  HTTP helpers
# ─────────────────────────────────────────────────────────────────────────────

def mimir_get(path: str, params: dict | None = None, timeout: int = 30) -> dict:
    """Query Mimir HTTP API (Prometheus-compatible)."""
    url = f"{CONFIG.mimir_url}{path}"
    resp = httpx.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def mimir_range_query(query: str, start: str, end: str, step: str = "60s") -> dict:
    return mimir_get(
        "/prometheus/api/v1/query_range",
        {"query": query, "start": start, "end": end, "step": step},
    )


def mimir_instant_query(query: str, time_str: str | None = None) -> dict:
    params: dict[str, str] = {"query": query}
    if time_str:
        params["time"] = time_str
    return mimir_get("/prometheus/api/v1/query", params)


def mimir_labels() -> list[str]:
    data = mimir_get("/prometheus/api/v1/labels")
    return data.get("data", [])


def mimir_label_values(label: str) -> list[str]:
    data = mimir_get(f"/prometheus/api/v1/label/{label}/values")
    return data.get("data", [])


def mimir_series(match: str) -> list[dict]:
    data = mimir_get("/prometheus/api/v1/series", {"match[]": match})
    return data.get("data", [])


def mimir_metadata() -> dict[str, list[dict]]:
    data = mimir_get("/prometheus/api/v1/metadata")
    return data.get("data", {})


def loki_query_range(
    query: str,
    start_ns: int | None = None,
    end_ns: int | None = None,
    limit: int = 5000,
) -> dict:
    """Query Loki log stream."""
    now = int(time.time() * 1e9)
    params = {
        "query": query,
        "limit": limit,
        "start": start_ns or (now - 3600 * int(1e9)),
        "end":   end_ns   or now,
        "direction": "backward",
    }
    url = f"{CONFIG.loki_url}/loki/api/v1/query_range"
    resp = httpx.get(url, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def loki_labels() -> list[str]:
    resp = httpx.get(f"{CONFIG.loki_url}/loki/api/v1/labels", timeout=15)
    resp.raise_for_status()
    return resp.json().get("data", [])


def loki_label_values(label: str) -> list[str]:
    resp = httpx.get(f"{CONFIG.loki_url}/loki/api/v1/label/{label}/values", timeout=15)
    resp.raise_for_status()
    return resp.json().get("data", [])


def loki_stats(query: str, start_ns: int | None = None, end_ns: int | None = None) -> dict:
    now = int(time.time() * 1e9)
    params = {
        "query": query,
        "start": start_ns or (now - 3600 * int(1e9)),
        "end":   end_ns   or now,
    }
    resp = httpx.get(f"{CONFIG.loki_url}/loki/api/v1/index/stats", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def tempo_search(tags: dict | None = None, limit: int = 20) -> dict:
    params: dict[str, Any] = {"limit": limit}
    if tags:
        params.update({f"tags.{k}": v for k, v in tags.items()})
    resp = httpx.get(f"{CONFIG.tempo_url}/api/search", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def tempo_trace(trace_id: str) -> dict:
    resp = httpx.get(f"{CONFIG.tempo_url}/api/traces/{trace_id}", timeout=30)
    resp.raise_for_status()
    return resp.json()


def grafana_api(path: str, method: str = "GET", payload: dict | None = None) -> dict:
    """Call Grafana HTTP API with basic auth."""
    url = f"{CONFIG.grafana_url}{path}"
    auth = (CONFIG.grafana_user, CONFIG.grafana_password)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    resp = httpx.request(
        method, url, auth=auth, headers=headers,
        json=payload, timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
#  Time helpers
# ─────────────────────────────────────────────────────────────────────────────

def now_rfc3339() -> str:
    return datetime.now(timezone.utc).isoformat()


def unix_to_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def hours_ago_rfc3339(h: int) -> str:
    return datetime.fromtimestamp(time.time() - h * 3600, tz=timezone.utc).isoformat()


def ns_to_iso(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).isoformat()
