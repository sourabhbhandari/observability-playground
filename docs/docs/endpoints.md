# Endpoints Reference

All endpoints are accessible on `localhost` when using Docker Desktop.

## Service Endpoints

### Grafana Mimir (Metrics)

| Endpoint | Method | Description |
|---|---|---|
| `http://localhost:9009/ready` | GET | Readiness probe |
| `http://localhost:9009/metrics` | GET | Mimir self-metrics (Prometheus) |
| `http://localhost:9009/prometheus/api/v1/query` | GET | Instant PromQL query |
| `http://localhost:9009/prometheus/api/v1/query_range` | GET | Range PromQL query |
| `http://localhost:9009/prometheus/api/v1/labels` | GET | List all label names |
| `http://localhost:9009/prometheus/api/v1/label/__name__/values` | GET | List all metric names |
| `http://localhost:9009/prometheus/api/v1/series` | GET | Find series by match |
| `http://localhost:9009/prometheus/api/v1/metadata` | GET | Metric metadata |
| `http://localhost:9009/api/v1/push` | POST | Remote-write metrics |
| `http://localhost:9009/alertmanager/` | GET | Alertmanager UI |

### Grafana Loki (Logs)

| Endpoint | Method | Description |
|---|---|---|
| `http://localhost:3100/ready` | GET | Readiness probe |
| `http://localhost:3100/loki/api/v1/query_range` | GET | LogQL range query |
| `http://localhost:3100/loki/api/v1/query` | GET | LogQL instant query |
| `http://localhost:3100/loki/api/v1/labels` | GET | List label names |
| `http://localhost:3100/loki/api/v1/label/{name}/values` | GET | Label values |
| `http://localhost:3100/loki/api/v1/push` | POST | Push log streams |
| `http://localhost:3100/loki/api/v1/index/stats` | GET | Index stats |
| `http://localhost:3100/metrics` | GET | Loki self-metrics |

### Grafana Tempo (Traces)

| Endpoint | Method | Description |
|---|---|---|
| `http://localhost:3200/ready` | GET | Readiness probe |
| `http://localhost:3200/api/search` | GET | Search traces |
| `http://localhost:3200/api/traces/{traceID}` | GET | Get trace by ID |
| `http://localhost:3200/api/search/tags` | GET | List searchable tags |
| `http://localhost:3200/metrics` | GET | Tempo self-metrics |
| `http://localhost:4317` | gRPC | OTLP gRPC (direct to Tempo) |
| `http://localhost:4318` | HTTP | OTLP HTTP (direct to Tempo) |
| `http://localhost:9411` | HTTP | Zipkin ingestion |
| `http://localhost:14268` | HTTP | Jaeger Thrift |

### Grafana (Dashboard)

| Endpoint | Method | Description |
|---|---|---|
| `http://localhost:3000` | GET | Grafana UI |
| `http://localhost:3000/api/health` | GET | API health |
| `http://localhost:3000/api/datasources` | GET | List datasources |
| `http://localhost:3000/api/search` | GET | Search dashboards |
| `http://localhost:3000/api/dashboards/uid/{uid}` | GET | Get dashboard |
| `http://localhost:3000/api/ruler/grafana/api/v1/rules` | GET | Alert rules |
| `http://localhost:3000/api/annotations` | GET/POST | Annotations |

### Grafana OnCall (Incidents)

| Endpoint | Method | Description |
|---|---|---|
| `http://localhost:8080` | GET | OnCall UI |
| `http://localhost:8080/health/` | GET | Health |
| `http://localhost:8080/api/v1/integrations/` | GET | List integrations |
| `http://localhost:8080/api/v1/alert_groups/` | GET | Alert groups |
| `http://localhost:8080/api/v1/schedules/` | GET | On-call schedules |
| `http://localhost:8080/integrations/v1/{TOKEN}/` | POST | Trigger alert |

### OTel Collector

| Endpoint | Protocol | Description |
|---|---|---|
| `http://localhost:4319` | gRPC | OTLP gRPC ingestion |
| `http://localhost:4320` | HTTP | OTLP HTTP ingestion |
| `http://localhost:8888/metrics` | HTTP | Collector self-metrics |
| `http://localhost:9464/metrics` | HTTP | Prometheus exporter |
| `http://localhost:13133/` | HTTP | Health check |
| `http://localhost:55679/debug/tracez` | HTTP | zPages trace browser |
| `http://localhost:55679/debug/pipelinez` | HTTP | Pipeline diagnostics |

### Sample App

| Endpoint | Method | Description |
|---|---|---|
| `http://localhost:8000/api/health` | GET | Health check |
| `http://localhost:8000/api/info` | GET | Config info |
| `http://localhost:8000/api/products` | GET | List products |
| `http://localhost:8000/api/orders` | POST | Create order (generates telemetry) |
| `http://localhost:8000/api/users` | GET | List users |
| `http://localhost:8000/api/simulate/error` | GET | Trigger 500 error |
| `http://localhost:8000/api/simulate/slow` | GET | Trigger slow request |
| `http://localhost:8000/api/simulate/load` | GET | Generate load burst |
| `http://localhost:8000/metrics` | GET | Prometheus scrape |

### MinIO (Object Storage)

| Endpoint | Description |
|---|---|
| `http://localhost:9001` | MinIO Console UI (minioadmin / minioadmin123) |
| `http://localhost:9000` | S3-compatible API |

## Default Credentials

| Service | Username | Password |
|---|---|---|
| Grafana | `admin` | `admin123` |
| MinIO | `minioadmin` | `minioadmin123` |
| PostgreSQL | `oncall` | `oncall123` |
| RabbitMQ | `rabbitmq` | `rabbitmq123` |

> All credentials are configurable via the `.env` file.
