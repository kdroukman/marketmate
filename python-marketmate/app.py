from __future__ import annotations

import json
import os
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parent
STATIC_ROOT = ROOT / "static"
PORT = int(os.getenv("PORT", "5273"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_URL = "https://api.openai.com/v1/responses"


try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
    from opentelemetry.trace import Status, StatusCode

    resource = Resource.create({
        "service.name": os.getenv("OTEL_SERVICE_NAME", "marketmate-python"),
        "service.version": "1.0.0",
    })
    provider = TracerProvider(resource=resource)

    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    else:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("marketmate.agents")
    OTEL_ENABLED = True
except ModuleNotFoundError:
    OTEL_ENABLED = False

    class _NoopSpan:
        def __enter__(self) -> "_NoopSpan":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def set_attribute(self, *_args: Any) -> None:
            return None

        def record_exception(self, *_args: Any) -> None:
            return None

        def set_status(self, *_args: Any) -> None:
            return None

    class _NoopTracer:
        def start_as_current_span(self, *_args: Any, **_kwargs: Any) -> _NoopSpan:
            return _NoopSpan()

    class StatusCode:
        ERROR = "ERROR"

    class Status:
        def __init__(self, *_args: Any) -> None:
            return None

    tracer = _NoopTracer()

try:
    from opentelemetry.util.genai.handler import get_telemetry_handler
    from opentelemetry.util.genai.types import (
        AgentInvocation,
        InputMessage,
        LLMInvocation,
        OutputMessage,
        Text,
        Workflow,
    )

    genai_handler = get_telemetry_handler()
    GENAI_ENABLED = True
except ModuleNotFoundError:
    genai_handler = None
    GENAI_ENABLED = False


GROCERY_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "quantity", "reason"],
    "properties": {
        "name": {"type": "string"},
        "quantity": {"type": "string"},
        "reason": {"type": "string"},
    },
}

GROCERY_GROUP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["aisle", "items"],
    "properties": {
        "aisle": {"type": "string"},
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": GROCERY_ITEM_SCHEMA,
        },
    },
}

ORCHESTRATOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["isRecipeRelated", "intentSummary", "servings", "constraints", "meals", "traceDetail"],
    "properties": {
        "isRecipeRelated": {"type": "boolean"},
        "intentSummary": {"type": "string"},
        "servings": {"type": "string"},
        "constraints": {"type": "array", "maxItems": 10, "items": {"type": "string"}},
        "meals": {"type": "array", "maxItems": 10, "items": {"type": "string"}},
        "traceDetail": {"type": "string"},
    },
}

RECIPE_PLANNER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["recipes", "baseIngredients", "substitutions", "optionalItems", "customerNotes", "traceDetail"],
    "properties": {
        "recipes": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "role", "ingredients"],
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "ingredients": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 20,
                        "items": GROCERY_ITEM_SCHEMA,
                    },
                },
            },
        },
        "baseIngredients": {
            "type": "array",
            "minItems": 1,
            "maxItems": 50,
            "items": GROCERY_ITEM_SCHEMA,
        },
        "substitutions": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
        "optionalItems": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
        "customerNotes": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
        "traceDetail": {"type": "string"},
    },
}

GROUPED_CART_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["groups", "traceDetail"],
    "properties": {
        "groups": {"type": "array", "minItems": 1, "maxItems": 12, "items": GROCERY_GROUP_SCHEMA},
        "traceDetail": {"type": "string"},
    },
}

REVIEW_AGENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["groups", "substitutions", "optionalItems", "customerNotes", "traceDetail"],
    "properties": {
        "groups": {"type": "array", "minItems": 1, "maxItems": 12, "items": GROCERY_GROUP_SCHEMA},
        "substitutions": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
        "optionalItems": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
        "customerNotes": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
        "traceDetail": {"type": "string"},
    },
}

FINAL_AGENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "customerNotes", "traceDetail"],
    "properties": {
        "summary": {"type": "string"},
        "customerNotes": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
        "traceDetail": {"type": "string"},
    },
}


class AppError(Exception):
    def __init__(self, message: str, status: int = 500) -> None:
        super().__init__(message)
        self.status = status


def output_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]

    parts: list[str] = []
    for output in payload.get("output", []):
        for content in output.get("content", []):
            if isinstance(content.get("text"), str):
                parts.append(content["text"])
            if isinstance(content.get("output_text"), str):
                parts.append(content["output_text"])
    return "\n".join(parts)


def run_curl_request(request_body: str, api_key: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "curl",
            "-sS",
            "--fail-with-body",
            OPENAI_URL,
            "-H",
            "content-type: application/json",
            "-H",
            f"authorization: Bearer {api_key}",
            "--data-binary",
            "@-",
        ],
        input=request_body,
        text=True,
        capture_output=True,
        check=False,
    )

    if completed.returncode == 0:
        return json.loads(completed.stdout)

    try:
        payload = json.loads(completed.stdout)
        raise AppError(payload.get("error", {}).get("message", completed.stderr), completed.returncode)
    except json.JSONDecodeError as error:
        raise AppError(completed.stderr or "The curl LLM request failed.") from error


def post_to_openai(request_body: str, api_key: str) -> dict[str, Any]:
    with tracer.start_as_current_span("openai.responses") as span:
        span.set_attribute("gen_ai.system", "openai")
        span.set_attribute("gen_ai.request.model", MODEL)
        span.set_attribute("http.method", "POST")
        span.set_attribute("url.full", OPENAI_URL)

        request = urllib.request.Request(
            OPENAI_URL,
            data=request_body.encode("utf-8"),
            method="POST",
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {api_key}",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                span.set_attribute("http.response.status_code", response.status)
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            span.set_attribute("http.response.status_code", error.code)
            body = error.read().decode("utf-8")
            try:
                payload = json.loads(body)
                raise AppError(payload.get("error", {}).get("message", "The LLM request failed."), error.code)
            except json.JSONDecodeError as json_error:
                raise AppError(body or "The LLM request failed.", error.code) from json_error
        except (urllib.error.URLError, ssl.SSLError) as error:
            span.record_exception(error)
            span.set_attribute("openai.transport_fallback", "curl")
            return run_curl_request(request_body, api_key)


def clipped_text(value: Any, limit: int = 10_000) -> str:
    text = value if isinstance(value, str) else json.dumps(value, indent=2)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated]"


def genai_input_message(role: str, content: Any) -> Any:
    return InputMessage(role=role, parts=[Text(content=clipped_text(content))])


def call_agent(name: str, title: str, instructions: str, input_data: Any, schema: dict[str, Any]) -> tuple[dict[str, Any], int]:
    started_at = time.monotonic()

    with tracer.start_as_current_span(f"agent.{name}") as span:
        span.set_attribute("agent.name", title)
        span.set_attribute("gen_ai.request.model", MODEL)
        input_text = input_data if isinstance(input_data, str) else json.dumps(input_data, indent=2)
        genai_agent = None
        genai_llm = None

        request_body = json.dumps({
            "model": MODEL,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": instructions}]},
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": input_text}],
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": name,
                    "strict": True,
                    "schema": schema,
                }
            },
        })

        if GENAI_ENABLED and genai_handler:
            input_messages = [
                genai_input_message("system", instructions),
                genai_input_message("user", input_text),
            ]
            genai_agent = AgentInvocation(
                name=title,
                agent_type=name.replace("_agent", ""),
                model=MODEL,
                system_instructions=instructions,
                input_messages=input_messages,
            )
            genai_handler.start_agent(genai_agent)

            genai_llm = LLMInvocation(
                request_model=MODEL,
                operation="responses",
                input_messages=input_messages,
            )
            genai_llm.provider = "openai"
            genai_llm.framework = "native-http"
            genai_handler.start_llm(genai_llm)

        try:
            payload = post_to_openai(request_body, os.environ["OPENAI_API_KEY"])
            text = output_text(payload)
            if not text:
                raise AppError(f"{title} did not return parseable output text.")

            parsed = json.loads(text)
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            span.set_attribute("agent.duration_ms", elapsed_ms)
            span.set_attribute("agent.trace_detail", parsed.get("traceDetail", ""))

            if genai_llm is not None:
                genai_llm.output_messages = [
                    OutputMessage(
                        role="assistant",
                        parts=[Text(content=clipped_text(text))],
                        finish_reason="stop",
                    )
                ]
            if genai_agent is not None:
                genai_agent.output_result = clipped_text(parsed)

            return parsed, elapsed_ms
        finally:
            if GENAI_ENABLED and genai_handler:
                if genai_llm is not None:
                    genai_handler.stop_llm(genai_llm)
                if genai_agent is not None:
                    genai_handler.stop_agent(genai_agent)


def trace_event(step_id: str, title: str, detail: str, duration_ms: int | None = None) -> dict[str, str]:
    suffix = f" ({round(duration_ms / 1000, 1)}s)" if duration_ms is not None else ""
    return {"stepId": step_id, "title": title, "detail": f"{detail}{suffix}"}


def non_recipe_plan(orchestrator: dict[str, Any]) -> dict[str, Any]:
    return {
        "isRecipeRelated": False,
        "summary": orchestrator.get("intentSummary") or "MarketMate is focused on recipe, meal-planning, and grocery prompts.",
        "agentTrace": [
            trace_event("context", "Orchestrator Agent", orchestrator.get("traceDetail", "Checked whether the prompt belongs in the recipe shopping workflow.")),
            trace_event("recipe", "Recipe Planner Agent", "Skipped recipe planning because the prompt was outside the supported food domain."),
            trace_event("builder", "Shopping List Builder Agent", "Created a minimal guidance card instead of a grocery cart."),
            trace_event("final-response", "Final Response Agent", "Asked for a recipe, meal plan, ingredient, or grocery-related request."),
        ],
        "groups": [
            {
                "aisle": "Recipe prompt needed",
                "items": [
                    {
                        "name": "Meal, recipe, ingredient, or grocery request",
                        "quantity": "1 prompt",
                        "reason": "MarketMate only builds shopping carts for cooking-related requests.",
                    }
                ],
            }
        ],
        "substitutions": [],
        "optionalItems": [],
        "customerNotes": ["Try asking for a dinner plan, a recipe shopping list, substitutions, or ingredients for a cuisine or event."],
    }


def create_shopping_plan(prompt: str) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        raise AppError("OPENAI_API_KEY is not set. Start the app with OPENAI_API_KEY=your_key python app.py.", 503)

    with tracer.start_as_current_span("cart.response") as span:
        span.set_attribute("recipe.prompt_length", len(prompt))
        genai_workflow = None
        if GENAI_ENABLED and genai_handler:
            genai_workflow = Workflow(
                name="marketmate_recipe_shopping_workflow",
                workflow_type="multi_agent_recipe_cart",
                input_messages=[genai_input_message("user", prompt)],
            )
            genai_handler.start_workflow(genai_workflow)

        agent_trace: list[dict[str, str]] = []

        try:
            orchestrator, duration = call_agent(
                "orchestrator_agent",
                "Orchestrator Agent",
                "You are the Orchestrator Agent for a recipe shopping app. Decide whether the user prompt is recipe, meal-planning, grocery, ingredient, cooking, entertaining menu, or substitution related. Extract the user's cooking intent, likely servings, constraints, and requested meals. Do not create the shopping cart. Prepare structured context for specialist agents.",
                prompt,
                ORCHESTRATOR_SCHEMA,
            )
            agent_trace.append(trace_event("context", "Orchestrator Agent", orchestrator["traceDetail"], duration))

            if not orchestrator["isRecipeRelated"]:
                span.set_attribute("recipe.related", False)
                result = non_recipe_plan(orchestrator)
                if genai_workflow is not None:
                    genai_workflow.final_output = clipped_text(result)
                return result

            recipe_plan, duration = call_agent(
                "recipe_planner_agent",
                "Recipe Planner Agent",
                "You are the Recipe Planner Agent. Choose practical recipes or meal components that satisfy the orchestrator context. Return base ingredients with quantities and reasons. Include sides, garnishes, dessert, and substitutions when relevant. Do not group by supermarket aisle; a later agent owns catalog mapping and cart grouping.",
                {"userPrompt": prompt, "orchestrator": orchestrator},
                RECIPE_PLANNER_SCHEMA,
            )
            agent_trace.append(trace_event("recipe", "Recipe Planner Agent", recipe_plan["traceDetail"], duration))

            product_cart, duration = call_agent(
                "product_search_agent",
                "Product Search Agent",
                "You are the Product Search Agent. Map the recipe planner's ingredients into supermarket-style grocery products. Normalize duplicate ingredients, use customer-friendly product names, and group them by common supermarket aisle. Keep quantities practical for the stated servings.",
                {"userPrompt": prompt, "orchestrator": orchestrator, "recipePlan": recipe_plan},
                GROUPED_CART_SCHEMA,
            )
            agent_trace.append(trace_event("product", "Product Search Agent", product_cart["traceDetail"], duration))

            inventory_review, duration = call_agent(
                "inventory_availability_agent",
                "Inventory & Availability Agent",
                "You are the Inventory & Availability Agent. Review the grouped cart for likely stock, freshness, and substitution issues. Keep the cart grouped by aisle, preserve useful items, and add clear substitution notes. Do not claim live inventory access; describe reasonable availability assumptions.",
                {"userPrompt": prompt, "orchestrator": orchestrator, "recipePlan": recipe_plan, "productCart": product_cart},
                REVIEW_AGENT_SCHEMA,
            )
            agent_trace.append(trace_event("inventory", "Inventory & Availability Agent", inventory_review["traceDetail"], duration))

            promotion_review, duration = call_agent(
                "loyalty_promotions_agent",
                "Loyalty & Promotions Agent",
                "You are the Loyalty & Promotions Agent. Review the cart for sensible savings, bulk-buy, pantry-staple, and optional add-on opportunities. Keep the grouped cart intact unless a small practical adjustment improves the customer experience. Add concise customer notes and optional items. Do not invent exact coupons or live prices.",
                {"userPrompt": prompt, "orchestrator": orchestrator, "recipePlan": recipe_plan, "inventoryReview": inventory_review},
                REVIEW_AGENT_SCHEMA,
            )
            agent_trace.append(trace_event("promotions", "Loyalty & Promotions Agent", promotion_review["traceDetail"], duration))

            built_cart, duration = call_agent(
                "shopping_list_builder_agent",
                "Shopping List Builder Agent",
                "You are the Shopping List Builder Agent. Finalize the cart for a customer-facing grocery app. Deduplicate items, keep aisle grouping tidy, and ensure each product has a clear quantity and shopping reason. Preserve substitution, optional item, and note guidance from upstream agents.",
                {"userPrompt": prompt, "orchestrator": orchestrator, "recipePlan": recipe_plan, "promotionReview": promotion_review},
                REVIEW_AGENT_SCHEMA,
            )
            agent_trace.append(trace_event("builder", "Shopping List Builder Agent", built_cart["traceDetail"], duration))

            final_response, duration = call_agent(
                "final_response_agent",
                "Final Response Agent",
                "You are the Final Response Agent for MarketMate. Write a concise customer-facing summary and helpful notes for the completed cart. Do not change the cart. Explain the plan in polished shopping-app language.",
                {"userPrompt": prompt, "orchestrator": orchestrator, "builtCart": built_cart},
                FINAL_AGENT_SCHEMA,
            )
            agent_trace.append(trace_event("final-response", "Final Response Agent", final_response["traceDetail"], duration))

            item_count = sum(len(group["items"]) for group in built_cart["groups"])
            span.set_attribute("recipe.related", True)
            span.set_attribute("cart.item_count", item_count)
            span.set_attribute("cart.group_count", len(built_cart["groups"]))

            result = {
                "isRecipeRelated": True,
                "summary": final_response["summary"],
                "agentTrace": agent_trace,
                "groups": built_cart["groups"],
                "substitutions": built_cart["substitutions"],
                "optionalItems": built_cart["optionalItems"],
                "customerNotes": (built_cart["customerNotes"] + final_response["customerNotes"])[:8],
            }
            if genai_workflow is not None:
                genai_workflow.final_output = clipped_text(result)
            return result
        finally:
            if GENAI_ENABLED and genai_handler and genai_workflow is not None:
                genai_handler.stop_workflow(genai_workflow)


class MarketMateHandler(BaseHTTPRequestHandler):
    server_version = "MarketMatePython/1.0"

    def do_POST(self) -> None:
        with tracer.start_as_current_span("http.post.recipe_plan") as span:
            span.set_attribute("http.request.method", "POST")
            span.set_attribute("url.path", self.path)

            try:
                if self.path != "/api/recipe-plan":
                    self.send_error(404)
                    return

                length = int(self.headers.get("content-length", "0"))
                if length > 50_000:
                    raise AppError("Request body is too large.", 413)

                body = self.rfile.read(length).decode("utf-8")
                payload = json.loads(body or "{}")
                prompt = payload.get("prompt", "")

                if not isinstance(prompt, str) or len(prompt.strip()) < 3:
                    raise AppError("Please enter a recipe or meal-planning prompt.", 400)

                result = create_shopping_plan(prompt.strip())
                self.send_json(200, result)
            except AppError as error:
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR))
                self.send_json(error.status, {"error": str(error)})
            except Exception as error:
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR))
                self.send_json(500, {"error": str(error) or "Unexpected server error."})

    def do_GET(self) -> None:
        with tracer.start_as_current_span("http.get.static") as span:
            span.set_attribute("http.request.method", "GET")
            span.set_attribute("url.path", self.path)
            parsed = urllib.parse.urlparse(self.path)
            relative = "index.html" if parsed.path == "/" else parsed.path.lstrip("/")
            file_path = (STATIC_ROOT / urllib.parse.unquote(relative)).resolve()

            if not str(file_path).startswith(str(STATIC_ROOT.resolve())):
                self.send_error(403)
                return

            if not file_path.exists() or not file_path.is_file():
                self.send_error(404)
                return

            content = file_path.read_bytes()
            self.send_response(200)
            self.send_header("content-type", self.guess_type(file_path))
            self.send_header("content-length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        content = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def guess_type(self, file_path: Path) -> str:
        return {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
        }.get(file_path.suffix, "application/octet-stream")


def main() -> None:
    print(f"MarketMate Python running at http://localhost:{PORT}")
    print(f"LLM model: {MODEL}")
    print(f"OpenTelemetry: {'enabled' if OTEL_ENABLED else 'not installed; install requirements.txt to enable'}")
    print(f"Splunk GenAI telemetry: {'enabled' if GENAI_ENABLED else 'not installed; install requirements.txt to enable'}")
    ThreadingHTTPServer(("127.0.0.1", PORT), MarketMateHandler).serve_forever()


if __name__ == "__main__":
    main()
