# ─────────────────────────────────────────────
#  Observability Playground – Makefile
# ─────────────────────────────────────────────
.DEFAULT_GOAL := help
SHELL         := /bin/bash

COMPOSE       := docker compose
PYTHON        := python3
UTILS_DIR     := python-utils
DOCS_DIR      := docs

.PHONY: help up down restart logs status ps \
        mimir-up loki-up tempo-up grafana-up oncall-up \
        cardinality log-analytics metric-usage mcp-server \
        sample-app-logs docs-serve docs-build \
        clean reset setup-python

# ─── Colours ──────────────────────────────────
CYAN  := \033[1;36m
RESET := \033[0m

help: ## Show this help
	@echo ""
	@echo "  $(CYAN)Observability Playground$(RESET)"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  $(CYAN)%-22s$(RESET) %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""

# ─── Stack management ─────────────────────────
up: ## Start full observability stack
	@echo "Starting stack…"
	$(COMPOSE) up -d --build
	@echo ""
	@echo "  Grafana:      http://localhost:3000   (admin / admin123)"
	@echo "  Mimir:        http://localhost:9009"
	@echo "  Loki:         http://localhost:3100"
	@echo "  Tempo:        http://localhost:3200"
	@echo "  OnCall:       http://localhost:8080"
	@echo "  Sample App:   http://localhost:8000"
	@echo "  MinIO:        http://localhost:9001   (minioadmin / minioadmin123)"
	@echo "  OTel Metrics: http://localhost:9464/metrics"
	@echo ""

down: ## Stop and remove containers (volumes preserved)
	$(COMPOSE) down

reset: ## Stop and remove containers AND volumes (data loss!)
	@read -p "This will delete all data. Continue? [y/N]: " ans && [ "$$ans" = "y" ]
	$(COMPOSE) down -v

restart: ## Restart all services
	$(COMPOSE) restart

logs: ## Follow logs for all services
	$(COMPOSE) logs -f --tail=100

status: ## Show service health status
	$(COMPOSE) ps
	@echo ""
	@echo "Health:"
	@curl -sf http://localhost:9009/ready  && echo "  Mimir:   OK" || echo "  Mimir:   NOT READY"
	@curl -sf http://localhost:3100/ready  && echo "  Loki:    OK" || echo "  Loki:    NOT READY"
	@curl -sf http://localhost:3200/ready  && echo "  Tempo:   OK" || echo "  Tempo:   NOT READY"
	@curl -sf http://localhost:3000/api/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('  Grafana: ' + d.get('database','OK'))"

ps: ## Alias for docker compose ps
	$(COMPOSE) ps

# ─── Individual service logs ──────────────────
mimir-logs: ## Follow Mimir logs
	$(COMPOSE) logs -f mimir

loki-logs: ## Follow Loki logs
	$(COMPOSE) logs -f loki

tempo-logs: ## Follow Tempo logs
	$(COMPOSE) logs -f tempo

grafana-logs: ## Follow Grafana logs
	$(COMPOSE) logs -f grafana

oncall-logs: ## Follow OnCall logs
	$(COMPOSE) logs -f oncall-engine oncall-celery

sample-app-logs: ## Follow sample app logs
	$(COMPOSE) logs -f sample-app

otel-logs: ## Follow OTel Collector logs
	$(COMPOSE) logs -f otel-collector

# ─── Python setup ─────────────────────────────
setup-python: ## Install Python utility dependencies
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r $(UTILS_DIR)/requirements.txt

# ─── Observability utilities ──────────────────
cardinality: ## Run high-cardinality metric analyzer
	cd $(UTILS_DIR) && $(PYTHON) high_cardinality.py --top 50 --threshold 500

cardinality-labels: ## Run cardinality analyzer with label breakdown
	cd $(UTILS_DIR) && $(PYTHON) high_cardinality.py --top 30 --label-analysis --include-labels

log-analytics: ## Run log analytics (last 1h)
	cd $(UTILS_DIR) && $(PYTHON) log_analytics.py --hours 1

log-analytics-6h: ## Run log analytics (last 6h)
	cd $(UTILS_DIR) && $(PYTHON) log_analytics.py --hours 6

metric-usage: ## Report used vs unused metrics
	cd $(UTILS_DIR) && $(PYTHON) metric_usage.py

metric-usage-export: ## Export metric usage report to CSV
	cd $(UTILS_DIR) && $(PYTHON) metric_usage.py --export-csv /tmp/metric_usage.csv
	@echo "Report saved to /tmp/metric_usage.csv"

mcp-server: ## Start Grafana MCP server (stdio transport)
	cd $(UTILS_DIR) && $(PYTHON) grafana_mcp.py --transport stdio

# ─── Load generation ─────────────────────────
load: ## Generate synthetic load via sample-app API
	@echo "Generating load…"
	@for i in $$(seq 1 20); do \
		curl -sf http://localhost:8000/api/simulate/load?requests=10 > /dev/null; \
		curl -sf -X POST http://localhost:8000/api/orders \
			-H "Content-Type: application/json" \
			-d '{"product_id":"p001","quantity":2,"region":"us-east"}' > /dev/null; \
		sleep 0.5; \
	done
	@echo "Load generation complete."

simulate-error: ## Trigger a simulated error in sample-app
	curl -sf http://localhost:8000/api/simulate/error || true

simulate-slow: ## Trigger a 3-second slow request
	curl -sf "http://localhost:8000/api/simulate/slow?delay=3"

# ─── Documentation ───────────────────────────
docs-serve: ## Serve MkDocs documentation locally
	cd $(DOCS_DIR) && mkdocs serve -a 0.0.0.0:8001

docs-build: ## Build MkDocs static site
	cd $(DOCS_DIR) && mkdocs build

docs-install: ## Install MkDocs dependencies
	pip install mkdocs mkdocs-material mkdocs-mermaid2-plugin

# ─── Cleanup ─────────────────────────────────
clean: ## Remove generated files (CSVs, JSONs)
	find . -name "*.csv" -newer $(MAKEFILE_LIST) -delete
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
