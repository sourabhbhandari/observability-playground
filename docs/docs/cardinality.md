# High Cardinality Analyzer

`python-utils/high_cardinality.py` helps you find metrics that have too many active time series — the most common source of high costs and degraded query performance.

## What is High Cardinality?

A metric has **high cardinality** when it has too many unique label combinations. For example:

```promql
http_requests_total{user_id="u-001234", ...}   # BAD: user_id explodes series
http_requests_total{method="GET", status="200"} # GOOD: bounded label values
```

## Usage

```bash
cd python-utils

# Basic report – top 50 metrics by series count
python high_cardinality.py

# Flag metrics over 1,000 series
python high_cardinality.py --threshold 1000

# Include per-metric label breakdown (slower)
python high_cardinality.py --include-labels --label-analysis

# Export to CSV
python high_cardinality.py --export-csv cardinality.csv

# Custom Mimir URL
python high_cardinality.py --mimir-url http://my-mimir:9009
```

## Output Example

```
╭─────────────────────────────────────────────╮
│  Observability Playground – Cardinality      │
│  Mimir: http://localhost:9009                │
╰─────────────────────────────────────────────╯

Total active series: 12,847
Unique metric names: 342

┌──────┬────────────────────────────────┬──────────────┬──────────┬──────────────────┐
│ Rank │ Metric Name                    │ Series Count │ Status   │ Top Label        │
├──────┼────────────────────────────────┼──────────────┼──────────┼──────────────────┤
│    1 │ http_requests_total            │       2,400  │ HIGH     │ path             │
│    2 │ db_query_duration_seconds_...  │         450  │ OK       │ db.table         │
└──────┴────────────────────────────────┴──────────────┴──────────┴──────────────────┘
```

## Remediation Tips

| Problem | Remedy |
|---|---|
| Label contains user ID / request ID | Drop the label in OTel Collector with a `transform` processor |
| Too many URL paths | Use `url.template` instead of `url.full` |
| Unbounded enum labels | Add an allowlist filter |
| Too many metric names | Drop unused metrics at the collector |

### OTel Collector Drop Rule Example

```yaml
# config/otel-collector/otel-collector.yaml
processors:
  transform/drop_high_cardinality:
    metric_statements:
      - context: datapoint
        statements:
          - delete_key(attributes, "user.id")
          - delete_key(attributes, "request.id")
          - delete_key(attributes, "session.id")
```
