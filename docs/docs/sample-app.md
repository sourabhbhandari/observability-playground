# Sample App

The sample app (`sample-app/main.py`) is a FastAPI service fully instrumented with the OpenTelemetry Python SDK. It demonstrates best practices for all three pillars.

## How It Works

```
FastAPI App
  ├── OTel SDK (traces, metrics, logs)
  │     └── OTLP gRPC → OTel Collector :4319
  │                          ├── Mimir  (metrics)
  │                          ├── Loki   (logs)
  │                          └── Tempo  (traces)
  └── Prometheus scrape endpoint /metrics
```

## Instruments Created

### Metrics

| Instrument | Type | Description |
|---|---|---|
| `http_requests_total` | Counter | Total HTTP requests by method/path/status |
| `http_request_duration_seconds` | Histogram | Request latency |
| `business_orders_total` | Counter | Orders by product/region |
| `business_order_value_usd` | Histogram | Order values |
| `active_users` | UpDownCounter | Currently active users |
| `db_query_duration_seconds` | Histogram | Simulated DB query latency |

### Traces

Every API endpoint creates a root span. Nested spans simulate:
- Database queries (`db.SELECT`, `db.INSERT`)
- External HTTP calls (`payment-service`, `notification-service`)

### Logs

All Python `logging` calls are hooked into OTel and forwarded to Loki. Log lines include:

```
trace_id=<trace_id> span_id=<span_id>
```

enabling one-click navigation from logs to traces in Grafana.

## Endpoints

| Endpoint | What it emits |
|---|---|
| `POST /api/orders` | Full trace (DB + external), business metrics, info/error logs |
| `GET /api/simulate/error` | 500 error span + error log |
| `GET /api/simulate/slow?delay=3` | High-latency span |
| `GET /api/simulate/load?requests=20` | Burst of DB spans |

## Running Locally (outside Docker)

```bash
cd sample-app
pip install -r requirements.txt

# Point to your running OTel Collector
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4319
export OTEL_SERVICE_NAME=sample-app-local

python main.py
```

## Adding More Instrumentation

### Custom metric

```python
from opentelemetry import metrics
meter = metrics.get_meter("my-module")
my_counter = meter.create_counter("my_events_total")

# In your handler:
my_counter.add(1, {"event_type": "login", "user_tier": "premium"})
```

### Manual span

```python
from opentelemetry import trace
tracer = trace.get_tracer("my-module")

with tracer.start_as_current_span("my_operation") as span:
    span.set_attribute("my.key", "value")
    # ... do work ...
```

### Structured log with trace correlation

```python
import logging
log = logging.getLogger(__name__)
log.info("User logged in", extra={"user_id": uid, "method": "oauth"})
# trace_id and span_id are injected automatically by OTel
```
