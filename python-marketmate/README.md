# MarketMate Python + OpenAI Agents SDK

This is a Python version of the MarketMate multi-agent recipe shopping app. It keeps the same browser UI, but the backend uses the OpenAI Agents SDK for the demo workflow.

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

## Splunk AI Agent Monitoring

The app is designed to run with Splunk's zero-code instrumentation for OpenAI Agents SDK apps. Run it with `opentelemetry-instrument` so the instrumentation package can capture agents, LLM calls, tool calls, tokens, metrics, traces, logs, and evaluation events:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
OTEL_SERVICE_NAME=marketmate-python \
OPENAI_API_KEY=your_key \
/path/to/.venv/bin/opentelemetry-instrument python app.py
```

Key packages:

- `openai-agents`
- `splunk-otel-instrumentation-openai-agents`
- `splunk-otel-genai-emitters-splunk`
- `splunk-otel-genai-evals-deepeval`

The EC2 CloudFormation template installs the Splunk Distribution of the OpenTelemetry Collector and sets:

```text
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=marketmate
OTEL_INSTRUMENTATION_GENAI_EMITTERS=span_metric_event,splunk
OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true
OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT_MODE=SPAN_AND_EVENT
OTEL_INSTRUMENTATION_GENAI_EVALS_RESULTS_AGGREGATION=true
OTEL_INSTRUMENTATION_GENAI_EMITTERS_EVALUATION=replace-category:SplunkEvaluationResults
OTEL_INSTRUMENTATION_GENAI_EVALS_SEPARATE_PROCESS=false
DEEPEVAL_FILE_SYSTEM=READ_ONLY
```

The app's workflow uses OpenAI Agents SDK `Agent` and `Runner` calls, and function tools for customer context, recipe search, product catalog search, inventory review, and promotions. The application code no longer creates Splunk GenAI telemetry objects directly.

Splunk Observability telemetry and Splunk Cloud evaluation events use separate tokens:

- Splunk Observability Cloud: access token + realm `us1`
- Splunk Cloud Platform evals/logs: HEC token + HEC endpoint
