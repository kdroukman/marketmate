from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parent
STATIC_ROOT = ROOT / "static"
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "5273"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
app_logger = logging.getLogger("marketmate")
app_logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))


try:
    from agents import Agent, ModelSettings, RunConfig, Runner, function_tool

    AGENTS_SDK_ENABLED = True
except ModuleNotFoundError:
    def function_tool(func: Any) -> Any:
        return func

    Agent = None
    ModelSettings = None
    RunConfig = None
    Runner = None
    AGENTS_SDK_ENABLED = False


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


def clipped_text(value: Any, limit: int = 10_000) -> str:
    text = value if isinstance(value, str) else json.dumps(value, indent=2)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated]"


def parse_agent_json(raw_output: Any, title: str) -> dict[str, Any]:
    if isinstance(raw_output, dict):
        return raw_output

    text = raw_output if isinstance(raw_output, str) else json.dumps(raw_output)
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise AppError(f"{title} returned non-JSON output: {text[:300]}") from error


def schema_instruction(name: str, schema: dict[str, Any]) -> str:
    return (
        "\n\nReturn only valid JSON. Do not wrap it in markdown. "
        f"The JSON must satisfy this schema named {name}:\n{json.dumps(schema, indent=2)}"
    )


@function_tool
def customer_context_lookup(request: str) -> str:
    """Look up a customer's broad grocery preferences for a recipe planning request."""
    return json.dumps({
        "profile": "demo shopper",
        "preferences": ["clear quantities", "practical supermarket products", "reasonable substitutions"],
        "assumptions": ["budget-aware", "weeknight-friendly", "no live customer database access in demo mode"],
        "request": request[:800],
    })


@function_tool
def recipe_search(query: str) -> str:
    """Search demo recipe content and return meal-planning hints."""
    return json.dumps({
        "source": "demo recipe knowledge base",
        "matches": [
            "pair mains with a vegetable side and a starch when appropriate",
            "include garnishes and pantry staples only when useful",
            "prefer ingredients that are easy to find in a mainstream grocery store",
        ],
        "query": query[:1200],
    })


@function_tool
def product_catalog_search(ingredients: str) -> str:
    """Map recipe ingredients to supermarket-style product names and aisles."""
    return json.dumps({
        "catalog": "demo product catalog",
        "aisles": ["Produce", "Meat & Seafood", "Dairy", "Pantry", "Bakery", "Frozen", "Herbs & Spices"],
        "rules": [
            "dedupe overlapping ingredients",
            "use familiar product names",
            "keep quantities practical for one shopping trip",
        ],
        "ingredients": ingredients[:1200],
    })


@function_tool
def store_inventory_check(cart: str) -> str:
    """Review a demo cart for likely availability and substitution options."""
    return json.dumps({
        "store": "demo local store",
        "availability": "assumed available unless specialty or seasonal",
        "substitution_rules": [
            "offer frozen or canned substitutes for hard-to-find produce",
            "suggest similar proteins for seafood or meat constraints",
            "avoid claiming live stock counts",
        ],
        "cart": cart[:1200],
    })


@function_tool
def promotions_search(cart: str) -> str:
    """Find demo loyalty and savings suggestions for a grocery cart."""
    return json.dumps({
        "loyalty_program": "MarketMate demo rewards",
        "promotion_rules": [
            "suggest pantry-size buys only when useful",
            "surface optional add-ons rather than fake coupon values",
            "avoid exact prices or live offers",
        ],
        "cart": cart[:1200],
    })


def call_agent(
    name: str,
    title: str,
    instructions: str,
    input_data: Any,
    schema: dict[str, Any],
    tools: list[Any] | None = None,
) -> tuple[dict[str, Any], int]:
    if not AGENTS_SDK_ENABLED or Agent is None or Runner is None or RunConfig is None or ModelSettings is None:
        raise AppError("OpenAI Agents SDK is not installed. Run: pip install -r requirements.txt", 503)

    started_at = time.monotonic()
    app_logger.info("agent.start name=%s title=%s model=%s", name, title, MODEL)
    input_text = input_data if isinstance(input_data, str) else json.dumps(input_data, indent=2)
    agent_tools = tools or []
    tool_names = [getattr(tool, "name", getattr(tool, "__name__", "tool")) for tool in agent_tools]
    tool_instruction = ""
    if tool_names:
        tool_instruction = f"\n\nBefore producing the final JSON, call the relevant tool from this list exactly once: {', '.join(tool_names)}."

    agent = Agent(
        name=title,
        instructions=instructions + tool_instruction + schema_instruction(name, schema),
        model=MODEL,
        tools=agent_tools,
        model_settings=ModelSettings(tool_choice="auto" if agent_tools else "none"),
    )
    result = Runner.run_sync(
        agent,
        input_text,
        run_config=RunConfig(
            workflow_name="MarketMate recipe shopping workflow",
            trace_include_sensitive_data=True,
            trace_metadata={"environment": os.getenv("ENVIRONMENT_NAME", "marketmate")},
        ),
    )
    parsed = parse_agent_json(result.final_output, title)
    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    app_logger.info("agent.complete name=%s title=%s duration_ms=%s", name, title, elapsed_ms)
    return parsed, elapsed_ms


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

    app_logger.info("workflow.start prompt_length=%s", len(prompt))
    agent_trace: list[dict[str, str]] = []

    orchestrator, duration = call_agent(
        "orchestrator_agent",
        "Orchestrator Agent",
        "You are the Orchestrator Agent for a recipe shopping app. Decide whether the user prompt is recipe, meal-planning, grocery, ingredient, cooking, entertaining menu, or substitution related. Extract the user's cooking intent, likely servings, constraints, and requested meals. Do not create the shopping cart. Prepare structured context for specialist agents.",
        prompt,
        ORCHESTRATOR_SCHEMA,
        [customer_context_lookup],
    )
    agent_trace.append(trace_event("context", "Orchestrator Agent", orchestrator["traceDetail"], duration))

    if not orchestrator["isRecipeRelated"]:
        return non_recipe_plan(orchestrator)

    recipe_plan, duration = call_agent(
        "recipe_planner_agent",
        "Recipe Planner Agent",
        "You are the Recipe Planner Agent. Choose practical recipes or meal components that satisfy the orchestrator context. Return base ingredients with quantities and reasons. Include sides, garnishes, dessert, and substitutions when relevant. Do not group by supermarket aisle; a later agent owns catalog mapping and cart grouping.",
        {"userPrompt": prompt, "orchestrator": orchestrator},
        RECIPE_PLANNER_SCHEMA,
        [recipe_search],
    )
    agent_trace.append(trace_event("recipe", "Recipe Planner Agent", recipe_plan["traceDetail"], duration))

    product_cart, duration = call_agent(
        "product_search_agent",
        "Product Search Agent",
        "You are the Product Search Agent. Map the recipe planner's ingredients into supermarket-style grocery products. Normalize duplicate ingredients, use customer-friendly product names, and group them by common supermarket aisle. Keep quantities practical for the stated servings.",
        {"userPrompt": prompt, "orchestrator": orchestrator, "recipePlan": recipe_plan},
        GROUPED_CART_SCHEMA,
        [product_catalog_search],
    )
    agent_trace.append(trace_event("product", "Product Search Agent", product_cart["traceDetail"], duration))

    inventory_review, duration = call_agent(
        "inventory_availability_agent",
        "Inventory & Availability Agent",
        "You are the Inventory & Availability Agent. Review the grouped cart for likely stock, freshness, and substitution issues. Keep the cart grouped by aisle, preserve useful items, and add clear substitution notes. Do not claim live inventory access; describe reasonable availability assumptions.",
        {"userPrompt": prompt, "orchestrator": orchestrator, "recipePlan": recipe_plan, "productCart": product_cart},
        REVIEW_AGENT_SCHEMA,
        [store_inventory_check],
    )
    agent_trace.append(trace_event("inventory", "Inventory & Availability Agent", inventory_review["traceDetail"], duration))

    promotion_review, duration = call_agent(
        "loyalty_promotions_agent",
        "Loyalty & Promotions Agent",
        "You are the Loyalty & Promotions Agent. Review the cart for sensible savings, bulk-buy, pantry-staple, and optional add-on opportunities. Keep the grouped cart intact unless a small practical adjustment improves the customer experience. Add concise customer notes and optional items. Do not invent exact coupons or live prices.",
        {"userPrompt": prompt, "orchestrator": orchestrator, "recipePlan": recipe_plan, "inventoryReview": inventory_review},
        REVIEW_AGENT_SCHEMA,
        [promotions_search],
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
    result = {
        "isRecipeRelated": True,
        "summary": final_response["summary"],
        "agentTrace": agent_trace,
        "groups": built_cart["groups"],
        "substitutions": built_cart["substitutions"],
        "optionalItems": built_cart["optionalItems"],
        "customerNotes": (built_cart["customerNotes"] + final_response["customerNotes"])[:8],
    }
    app_logger.info(
        "workflow.complete recipe_related=true cart_item_count=%s cart_group_count=%s",
        item_count,
        len(built_cart["groups"]),
    )
    return result


class MarketMateHandler(BaseHTTPRequestHandler):
    server_version = "MarketMatePython/1.0"

    def do_POST(self) -> None:
        request_started_at = time.monotonic()
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
            app_logger.info(
                "http.request method=POST path=%s status=200 duration_ms=%s",
                self.path,
                int((time.monotonic() - request_started_at) * 1000),
            )
        except AppError as error:
            self.send_json(error.status, {"error": str(error)})
            app_logger.warning(
                "http.request method=POST path=%s status=%s error=%s",
                self.path,
                error.status,
                error,
            )
        except Exception as error:
            self.send_json(500, {"error": str(error) or "Unexpected server error."})
            app_logger.exception("http.request method=POST path=%s status=500", self.path)

    def do_GET(self) -> None:
        request_started_at = time.monotonic()
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
        app_logger.info(
            "http.request method=GET path=%s status=200 duration_ms=%s",
            self.path,
            int((time.monotonic() - request_started_at) * 1000),
        )

    def log_message(self, format: str, *args: Any) -> None:
        app_logger.info("http.server client=%s message=%s", self.client_address[0], format % args)

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
    app_logger.info("MarketMate Python running at http://%s:%s", HOST, PORT)
    app_logger.info("LLM model: %s", MODEL)
    app_logger.info("OpenAI Agents SDK: %s", "enabled" if AGENTS_SDK_ENABLED else "not installed; install requirements.txt to enable")
    ThreadingHTTPServer((HOST, PORT), MarketMateHandler).serve_forever()


if __name__ == "__main__":
    main()
