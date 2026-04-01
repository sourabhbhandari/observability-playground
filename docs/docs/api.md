# API Reference

The `api-collection/observability.http` file contains a complete API collection compatible with:

- **VS Code REST Client** extension (`humao.rest-client`)
- **JetBrains HTTP Client** (IntelliJ, PyCharm, etc.)
- **curl** (copy individual blocks)

## Load the Collection

### VS Code REST Client
1. Install the **REST Client** extension
2. Open `api-collection/observability.http`
3. Click **Send Request** above any `###` block

### curl Examples

#### Mimir – Instant PromQL Query
```bash
curl "http://localhost:9009/prometheus/api/v1/query?query=up"
```

#### Loki – Query Logs
```bash
curl -G "http://localhost:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={service_name="sample-app"} |= "error"' \
  --data-urlencode 'limit=50'
```

#### Loki – Push a Log Line
```bash
curl -X POST http://localhost:3100/loki/api/v1/push \
  -H "Content-Type: application/json" \
  -d '{
    "streams": [{
      "stream": {"service_name": "test", "level": "info"},
      "values": [["'$(date +%s%N)'", "Hello from curl!"]]
    }]
  }'
```

#### Tempo – Search Traces
```bash
curl "http://localhost:3200/api/search?limit=10"
```

#### Grafana – List Dashboards
```bash
curl -u admin:admin123 "http://localhost:3000/api/search?type=dash-db"
```

#### Sample App – Create Order (generates full telemetry)
```bash
curl -X POST http://localhost:8000/api/orders \
  -H "Content-Type: application/json" \
  -d '{"product_id": "p001", "quantity": 2, "region": "us-east"}'
```

#### OTel Collector – Push a Trace via OTLP HTTP
```bash
# Using grpcurl (brew install grpcurl)
grpcurl -plaintext \
  -proto opentelemetry/proto/collector/trace/v1/trace_service.proto \
  localhost:4319 \
  opentelemetry.proto.collector.trace.v1.TraceService/Export
```

## PromQL Quick Reference

```promql
# Request rate (5m)
rate(http_requests_total[5m])

# Error rate by service
sum by (service) (rate(http_requests_total{status=~"5.."}[5m]))
  /
sum by (service) (rate(http_requests_total[5m]))

# p99 latency
histogram_quantile(0.99,
  sum by (le, service) (rate(http_request_duration_seconds_bucket[5m]))
)

# Apdex score (target=300ms, tolerating=1.2s)
(
  sum(rate(http_request_duration_seconds_bucket{le="0.3"}[5m]))
  + sum(rate(http_request_duration_seconds_bucket{le="1.2"}[5m]))
) / 2
/ sum(rate(http_request_duration_seconds_count[5m]))

# Active series count
count({__name__!=""})

# Top-10 metrics by series
topk(10, count by (__name__) ({__name__!=""}))
```

## LogQL Quick Reference

```logql
# All logs from a service
{service_name="sample-app"}

# Filter to errors
{service_name="sample-app"} |= "error"

# Regex filter
{service_name="sample-app"} |~ "timeout|connection refused"

# Parse JSON and filter
{service_name="sample-app"} | json | level="error"

# Log rate by service
sum by (service_name) (rate({service_name!=""}[5m]))

# Error rate (%)
sum(rate({service_name="sample-app"} |= "error" [5m]))
  /
sum(rate({service_name="sample-app"}[5m]))
```

## TraceQL Quick Reference

```traceql
# Traces from a service
{.service.name = "sample-app"}

# Traces with errors
{status = error}

# Slow traces (>1s)
{duration > 1s}

# Combine
{.service.name = "sample-app" && status = error && duration > 500ms}
```
