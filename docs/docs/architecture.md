# Architecture

## Data Flow

```mermaid
graph TB
    subgraph Apps["Applications"]
        SA["Sample App\nFastAPI + OTel SDK"]
    end

    subgraph Collector["OTel Collector (contrib)"]
        R["Receivers\nOTLP gRPC/HTTP\nPrometheus"]
        P["Processors\nMemory Limiter\nBatch\nFilter\nSampler"]
        E["Exporters\nPrometheus Remote Write\nLoki\nOTLP/Tempo"]
        R --> P --> E
    end

    subgraph Storage["Telemetry Backends"]
        Mimir["Grafana Mimir\nMetrics TSDB\nS3 blocks"]
        Loki["Grafana Loki\nLog chunks\nS3 index"]
        Tempo["Grafana Tempo\nTrace blocks\nS3 storage"]
    end

    subgraph Viz["Visualization"]
        Grafana["Grafana\nDashboards\nAlert Rules\nExplore"]
        OnCall["Grafana OnCall\nRouting\nEscalation\nOn-call schedules"]
    end

    subgraph ObjectStore["Object Storage"]
        MinIO["MinIO\nmimir-blocks\nloki-chunks\ntempo-traces"]
    end

    subgraph PyTools["Python Utilities"]
        HC["high_cardinality.py"]
        LA["log_analytics.py"]
        MU["metric_usage.py"]
        MCP["grafana_mcp.py\nMCP Server"]
    end

    SA -->|OTLP gRPC| Collector
    E -->|remote_write| Mimir
    E -->|push| Loki
    E -->|OTLP gRPC| Tempo
    Mimir --> Grafana
    Loki  --> Grafana
    Tempo --> Grafana
    Grafana -->|webhook| OnCall
    Mimir --> MinIO
    Loki  --> MinIO
    Tempo --> MinIO
    HC  -->|PromQL API| Mimir
    LA  -->|LogQL API| Loki
    MU  -->|Grafana API + PromQL| Grafana
    MCP -->|REST APIs| Mimir
    MCP -->|REST APIs| Loki
    MCP -->|REST APIs| Tempo
    MCP -->|REST API| Grafana
```

## Storage Architecture

All three backends (Mimir, Loki, Tempo) use **MinIO** (S3-compatible) as their object store. This gives you a production-realistic setup without cloud dependencies.

| Backend | Bucket | Contents |
|---|---|---|
| Mimir | `mimir-blocks` | TSDB blocks, ruler rules, alertmanager config |
| Loki | `loki-chunks` | Log chunks and index |
| Tempo | `tempo-traces` | Trace blocks |

## Correlation

The stack is wired for **three-pillars correlation**:

- **Traces → Logs**: Tempo datasource configured with `tracesToLogsV2` linking `traceId` to Loki queries
- **Traces → Metrics**: Tempo datasource with `tracesToMetrics` linking to span metric recording rules
- **Logs → Traces**: Loki datasource configured with `derivedFields` extracting `trace_id` from log lines
- **Metrics with Exemplars**: Mimir datasource configured with `exemplarTraceIdDestinations` pointing to Tempo

## Network

All services share a single `observability` bridge network. Ports are exposed to `localhost` for Docker Desktop access:

```
localhost → docker bridge → container
```

## Single-Binary Mode

Mimir, Loki, and Tempo each run in **single-binary mode** (`target: all`) for simplicity. In production you would split these into separate microservices (compactor, ingester, querier, etc.) deployed independently.
