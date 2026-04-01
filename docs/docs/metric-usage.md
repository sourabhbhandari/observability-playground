# Metric Usage Analyzer

`python-utils/metric_usage.py` compares the metrics **stored in Mimir** against those **actually queried** in Grafana dashboards and alert rules, surfacing dead weight that wastes storage and compute.

## How It Works

1. Fetch all metric names from Mimir (`/prometheus/api/v1/label/__name__/values`)
2. Fetch all dashboards from Grafana API and extract PromQL expressions from panel targets
3. Fetch all unified alert rules from Grafana and extract PromQL expressions
4. Parse metric names from each PromQL expression using regex
5. Report intersection (used) and difference (unused)

## Usage

```bash
cd python-utils

# Full report
python metric_usage.py

# Unused metrics only
python metric_usage.py --unused-only

# Used metrics only
python metric_usage.py --used-only

# Show top 50 rows per table
python metric_usage.py --top 50

# Export full report to CSV
python metric_usage.py --export-csv /tmp/metric_usage.csv

# Custom URLs
python metric_usage.py --grafana-url http://my-grafana:3000 --mimir-url http://my-mimir:9009
```

## Example Output

```
╭────────────────────────────────────────────────────────╮
│  Metric Usage Summary                                   │
│  Total metrics stored:     342                          │
│  Used in dashboards/alerts: 87   (25.4%)                │
│  Unused metrics:           255   (74.6% of total)       │
╰────────────────────────────────────────────────────────╯
```

## Interpreting Results

| Status | Meaning |
|---|---|
| **Used** | Referenced in at least one dashboard panel or alert rule |
| **Unused** | Stored in Mimir but never queried by Grafana |

> Note: "unused in Grafana" doesn't mean unused everywhere – other systems (e.g. recording rules, external tools) may also query metrics. Use this as a starting point, not a ground truth.

## Reducing Unused Metrics

### Option 1 – Drop at the OTel Collector

```yaml
processors:
  filter/drop_unused:
    error_mode: ignore
    metrics:
      metric:
        - 'name == "go_gc_duration_seconds"'
        - 'name == "process_open_fds"'
        - 'IsMatch(name, "go_.*") == true'
```

### Option 2 – Relabel at the source

In your OTel SDK configuration or via a Prometheus `metric_relabel_configs`:

```yaml
metric_relabel_configs:
  - source_labels: [__name__]
    regex: "go_.*"
    action: drop
```

### Option 3 – Build dashboards for valuable metrics

Rather than dropping, create dashboards for your top business metrics so they show as "used".
