# MarketMate Python + OpenTelemetry

This is a Python version of the MarketMate multi-agent recipe shopping app. It keeps the same browser UI, but the backend is Python and each AI agent call is traced with OpenTelemetry.

## Run

```bash
cd python-marketmate
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
OPENAI_API_KEY=your_key python app.py
```

Open the app at:

```text
http://localhost:5273
```

## Tracing

By default, spans are printed to the console. To export to an OTLP collector:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
OTEL_SERVICE_NAME=marketmate-python \
OPENAI_API_KEY=your_key \
python app.py
```

Important spans:

- `http.post.recipe_plan`
- `agent.orchestrator_agent`
- `agent.recipe_planner_agent`
- `agent.product_search_agent`
- `agent.inventory_availability_agent`
- `agent.loyalty_promotions_agent`
- `agent.shopping_list_builder_agent`
- `agent.final_response_agent`
- `cart.response`
