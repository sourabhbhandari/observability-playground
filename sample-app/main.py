#!/usr/bin/env python3
"""
main.py – OTel-instrumented sample FastAPI application.

Demonstrates:
  • Metrics   → pushed via OTLP to OTel Collector → Mimir
  • Logs      → pushed via OTLP to OTel Collector → Loki
  • Traces    → pushed via OTLP to OTel Collector → Tempo
  • Prometheus scrape endpoint (/metrics) as an alternative

Environment variables:
  OTEL_SERVICE_NAME              (default: sample-app)
  OTEL_EXPORTER_OTLP_ENDPOINT   (default: http://localhost:4319)
  OTEL_EXPORTER_OTLP_PROTOCOL   grpc | http/protobuf (default: grpc)
"""

from __future__ import annotations

import logging
import os
import random
import time
import asyncio
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

# ─── OpenTelemetry ──────────────────────────────────────────────────────────
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor

# Prometheus exporter (for /metrics scrape endpoint)
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST


# ─────────────────────────────────────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────────────────────────────────────

SERVICE  = os.getenv("OTEL_SERVICE_NAME", "sample-app")
VERSION  = os.getenv("SERVICE_VERSION",   "1.0.0")
ENV      = os.getenv("DEPLOYMENT_ENV",    "playground")
ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4319")

RESOURCE = Resource.create({
    SERVICE_NAME:    SERVICE,
    SERVICE_VERSION: VERSION,
    "deployment.environment": ENV,
    "host.name":     os.getenv("HOSTNAME", "localhost"),
})

OTLP_GRPC_OPTS = {"endpoint": ENDPOINT, "insecure": True}

# ─────────────────────────────────────────────────────────────────────────────
#  OTel: Traces
# ─────────────────────────────────────────────────────────────────────────────

tracer_provider = TracerProvider(resource=RESOURCE)
tracer_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(**OTLP_GRPC_OPTS))
)
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  OTel: Metrics
# ─────────────────────────────────────────────────────────────────────────────

prom_reader     = PrometheusMetricReader()
otlp_reader     = PeriodicExportingMetricReader(
    OTLPMetricExporter(**OTLP_GRPC_OPTS),
    export_interval_millis=15_000,
)
meter_provider  = MeterProvider(resource=RESOURCE, metric_readers=[otlp_reader, prom_reader])
metrics.set_meter_provider(meter_provider)
meter           = metrics.get_meter(__name__, version=VERSION)

# ── Custom instruments ──────────────────────────────────────────────────────
http_requests_total = meter.create_counter(
    "http_requests_total",
    unit="1",
    description="Total HTTP requests processed by this service",
)
http_request_duration = meter.create_histogram(
    "http_request_duration_seconds",
    unit="s",
    description="HTTP request latency in seconds",
)
business_orders_total = meter.create_counter(
    "business_orders_total",
    unit="1",
    description="Total business orders processed",
)
business_order_value = meter.create_histogram(
    "business_order_value_usd",
    unit="USD",
    description="Value of business orders in USD",
)
active_users_gauge = meter.create_up_down_counter(
    "active_users",
    unit="1",
    description="Currently active users",
)
db_query_duration = meter.create_histogram(
    "db_query_duration_seconds",
    unit="s",
    description="Database query latency",
)

# ─────────────────────────────────────────────────────────────────────────────
#  OTel: Logs
# ─────────────────────────────────────────────────────────────────────────────

logger_provider = LoggerProvider(resource=RESOURCE)
logger_provider.add_log_record_processor(
    BatchLogRecordProcessor(OTLPLogExporter(**OTLP_GRPC_OPTS))
)

# Hook standard Python logging → OTel
otel_log_handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s trace_id=%(otelTraceID)s span_id=%(otelSpanID)s",
    handlers=[logging.StreamHandler(), otel_log_handler],
)
LoggingInstrumentor().instrument(set_logging_format=True)
HTTPXClientInstrumentor().instrument()

log = logging.getLogger(SERVICE)

# ─────────────────────────────────────────────────────────────────────────────
#  Simulated back-end helpers
# ─────────────────────────────────────────────────────────────────────────────

PRODUCTS = {
    "p001": {"name": "Widget A", "price": 9.99,  "stock": 150},
    "p002": {"name": "Gadget B", "price": 49.99, "stock": 32},
    "p003": {"name": "Thing C",  "price": 2.50,  "stock": 500},
    "p004": {"name": "Doohickey", "price": 199.99, "stock": 5},
}


def _simulate_db_query(table: str, op: str = "SELECT") -> dict:
    """Simulate a DB call with tracing and latency."""
    with tracer.start_as_current_span(
        f"db.{op.lower()} {table}",
        attributes={"db.system": "postgresql", "db.operation": op, "db.sql.table": table},
    ) as span:
        latency = random.uniform(0.002, 0.08)
        time.sleep(latency)
        db_query_duration.record(latency, {"db.table": table, "db.op": op})

        if random.random() < 0.05:   # 5% chance of DB error
            span.set_attribute("error", True)
            raise RuntimeError(f"DB timeout on {table}")
        return {"rows": random.randint(1, 100), "latency_ms": latency * 1000}


def _simulate_external_call(service: str) -> dict:
    with tracer.start_as_current_span(
        f"http.call {service}",
        attributes={"http.method": "GET", "peer.service": service},
    ) as span:
        latency = random.uniform(0.01, 0.3)
        time.sleep(latency)
        if random.random() < 0.03:
            span.set_attribute("error", True)
            raise RuntimeError(f"Timeout calling {service}")
        return {"status": "ok", "latency_ms": latency * 1000}


# ─────────────────────────────────────────────────────────────────────────────
#  Background traffic simulator
# ─────────────────────────────────────────────────────────────────────────────

async def traffic_simulator() -> None:
    """Generate synthetic traffic to populate metrics/logs/traces."""
    endpoints = ["/api/products", "/api/orders", "/api/users", "/api/health"]
    clients   = ["mobile", "web", "partner", "internal"]
    regions   = ["us-east", "eu-west", "ap-south"]

    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        while True:
            try:
                ep = random.choice(endpoints)
                await client.get(ep, headers={
                    "x-client-type": random.choice(clients),
                    "x-region":      random.choice(regions),
                })
            except Exception:
                pass
            await asyncio.sleep(random.uniform(0.5, 2.0))


# ─────────────────────────────────────────────────────────────────────────────
#  App lifecycle
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting sample-app", extra={"service": SERVICE, "env": ENV})
    active_users_gauge.add(random.randint(5, 20), {"region": "us-east"})

    sim_task = asyncio.create_task(traffic_simulator())
    yield

    sim_task.cancel()
    log.info("Shutting down sample-app")
    tracer_provider.shutdown()
    meter_provider.shutdown()
    logger_provider.shutdown()


app = FastAPI(
    title="Observability Playground – Sample App",
    description="OTel-instrumented app producing metrics, logs, and traces",
    version=VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FastAPIInstrumentor().instrument_app(app)


# ─────────────────────────────────────────────────────────────────────────────
#  Middleware: record HTTP metrics on every request
# ─────────────────────────────────────────────────────────────────────────────

@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response: Response = await call_next(request)
    duration = time.perf_counter() - start

    labels = {
        "method":  request.method,
        "path":    request.url.path,
        "status":  str(response.status_code),
        "service": SERVICE,
    }
    http_requests_total.add(1, labels)
    http_request_duration.record(duration, labels)

    return response


# ─────────────────────────────────────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": SERVICE, "version": VERSION}


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus scrape endpoint."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/products")
async def list_products():
    with tracer.start_as_current_span("list_products") as span:
        span.set_attribute("products.count", len(PRODUCTS))
        log.info("Listing products", extra={"count": len(PRODUCTS)})
        try:
            _simulate_db_query("products")
        except RuntimeError as e:
            log.error("DB error fetching products: %s", e)
            raise HTTPException(status_code=503, detail=str(e))
        return {"products": list(PRODUCTS.values())}


@app.get("/api/products/{product_id}")
async def get_product(product_id: str):
    with tracer.start_as_current_span("get_product") as span:
        span.set_attribute("product.id", product_id)
        if product_id not in PRODUCTS:
            log.warning("Product not found: %s", product_id)
            raise HTTPException(status_code=404, detail="Product not found")
        log.info("Fetched product %s", product_id)
        return PRODUCTS[product_id]


@app.post("/api/orders")
async def create_order(request: Request):
    with tracer.start_as_current_span("create_order") as span:
        body = await request.json()
        product_id = body.get("product_id", "p001")
        quantity   = int(body.get("quantity", 1))
        region     = body.get("region", "us-east")

        span.set_attribute("order.product_id", product_id)
        span.set_attribute("order.quantity",   quantity)
        span.set_attribute("order.region",     region)

        product = PRODUCTS.get(product_id)
        if not product:
            log.error("Order rejected – unknown product %s", product_id)
            raise HTTPException(status_code=400, detail="Unknown product")

        value = product["price"] * quantity

        try:
            _simulate_db_query("orders", "INSERT")
            _simulate_external_call("payment-service")
            _simulate_external_call("notification-service")
        except RuntimeError as e:
            log.error("Order processing failed: %s", e, extra={"product_id": product_id})
            raise HTTPException(status_code=503, detail=str(e))

        business_orders_total.add(1, {"product": product_id, "region": region, "status": "success"})
        business_order_value.record(value, {"product": product_id, "region": region})

        log.info(
            "Order created successfully",
            extra={"product_id": product_id, "quantity": quantity, "value_usd": value, "region": region},
        )
        return {"order_id": f"ORD-{int(time.time() * 1000)}", "total": value, "status": "confirmed"}


@app.get("/api/users")
async def list_users():
    with tracer.start_as_current_span("list_users") as span:
        count = random.randint(50, 200)
        span.set_attribute("users.count", count)
        _simulate_db_query("users")
        active_users_gauge.add(random.randint(-5, 10), {"region": "us-east"})
        log.info("Listed users", extra={"count": count})
        return {"users_count": count}


@app.get("/api/simulate/error")
async def simulate_error():
    """Deliberately trigger an error for testing alerts."""
    with tracer.start_as_current_span("simulate_error") as span:
        span.set_attribute("error", True)
        log.error("Simulated error triggered by test endpoint")
        raise HTTPException(status_code=500, detail="Simulated internal error")


@app.get("/api/simulate/slow")
async def simulate_slow(delay: float = 2.0):
    """Deliberately introduce latency for testing latency alerts."""
    with tracer.start_as_current_span("simulate_slow") as span:
        span.set_attribute("simulated.delay_s", delay)
        log.warning("Slow endpoint triggered with delay=%.2fs", delay)
        await asyncio.sleep(min(delay, 30.0))
        return {"message": f"Slept for {delay}s", "status": "ok"}


@app.get("/api/simulate/load")
async def simulate_load(requests: int = 10):
    """Generate a burst of synthetic spans/metrics."""
    with tracer.start_as_current_span("simulate_load") as span:
        span.set_attribute("load.requests", requests)
        results = []
        for i in range(min(requests, 100)):
            try:
                db = _simulate_db_query(random.choice(["users", "orders", "products"]))
                results.append({"i": i, "ok": True})
            except RuntimeError:
                results.append({"i": i, "ok": False})
        log.info("Load simulation completed", extra={"requests": requests})
        return {"completed": len(results), "results": results[:5]}


@app.get("/api/info")
async def app_info():
    return {
        "service": SERVICE,
        "version": VERSION,
        "environment": ENV,
        "otel_endpoint": ENDPOINT,
        "endpoints": {
            "metrics_push":  f"{ENDPOINT} (OTLP gRPC)",
            "traces_push":   f"{ENDPOINT} (OTLP gRPC)",
            "logs_push":     f"{ENDPOINT} (OTLP gRPC)",
            "metrics_scrape": "http://localhost:8000/metrics (Prometheus)",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
