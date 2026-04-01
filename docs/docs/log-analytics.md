# Log Analytics

`python-utils/log_analytics.py` analyzes log data stored in Loki to surface error trends, pattern clusters, and service health.

## Features

- **Service-level summary** – total lines, errors, warnings, error rate, health status
- **Error pattern clustering** – groups similar error messages by normalizing variable parts (numbers, UUIDs, IPs)
- **Label cardinality** – shows Loki label index size to detect over-labeling
- **JSON export** – machine-readable output for CI/CD pipelines

## Usage

```bash
cd python-utils

# Last hour, all services
python log_analytics.py

# Last 6 hours
python log_analytics.py --hours 6

# Single service
python log_analytics.py --service checkout-svc

# Show label cardinality
python log_analytics.py --labels

# Show top 30 error patterns
python log_analytics.py --top-errors 30

# Export to JSON
python log_analytics.py --export-json /tmp/logs.json
```

## Output

```
╭──────────────────────────────────────────╮
│  Observability Playground – Log Analytics │
│  Loki: http://localhost:3100  |  1h       │
╰──────────────────────────────────────────╯

┌──────────────┬───────┬────────┬──────┬──────┬────────────┬──────────┐
│ Service      │ Total │ Errors │ Warn │ Info │ Error Rate │ Health   │
├──────────────┼───────┼────────┼──────┼──────┼────────────┼──────────┤
│ checkout-svc │ 2,340 │    234 │   80 │ 2026 │      10.0% │ CRITICAL │
│ sample-app   │   892 │     18 │   22 │  852 │       2.0% │ HEALTHY  │
└──────────────┴───────┴────────┴──────┴──────┴────────────┴──────────┘
```

## Error Pattern Clustering

The tool normalizes log lines before grouping them:

| Raw log | Normalized pattern |
|---|---|
| `DB timeout after 5012ms on orders` | `DB timeout after <N>ms on orders` |
| `User 12345 not found` | `User <N> not found` |
| `Request f4a2-... failed` | `Request <UUID> failed` |

This groups thousands of unique error messages into actionable buckets.

## Recommendations from Output

When services exceed 5% error rate:

- Add structured context to error logs (stack trace, request ID, user ID)
- Set up Grafana alert rules on LogQL error rate queries
- Use log-based alerting in OnCall for P1 incidents
