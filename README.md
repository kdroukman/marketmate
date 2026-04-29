# MarketMate

MarketMate is a Python recipe-shopping demo with a customer-facing shopping UI, a multi-agent OpenAI workflow, and OpenTelemetry instrumentation.

## Local Python App

```bash
cd python-marketmate
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
OPENAI_API_KEY=your_key python app.py
```

Open:

```text
http://localhost:5273
```

## AWS

See [infra/deploy.md](infra/deploy.md) for CloudFormation deployment instructions.

Do not commit API keys or AWS credentials.
