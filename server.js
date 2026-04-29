import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL(".", import.meta.url));
const port = Number(process.env.PORT || 4173);
const model = process.env.OPENAI_MODEL || "gpt-4.1-mini";

const mimeTypes = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8"
};

const groceryItemSchema = {
  type: "object",
  additionalProperties: false,
  required: ["name", "quantity", "reason"],
  properties: {
    name: { type: "string" },
    quantity: { type: "string" },
    reason: { type: "string" }
  }
};

const groceryGroupSchema = {
  type: "object",
  additionalProperties: false,
  required: ["aisle", "items"],
  properties: {
    aisle: { type: "string" },
    items: {
      type: "array",
      minItems: 1,
      maxItems: 20,
      items: groceryItemSchema
    }
  }
};

const shoppingPlanSchema = {
  type: "object",
  additionalProperties: false,
  required: ["isRecipeRelated", "summary", "agentTrace", "groups", "substitutions", "optionalItems", "customerNotes"],
  properties: {
    isRecipeRelated: { type: "boolean" },
    summary: { type: "string" },
    agentTrace: {
      type: "array",
      minItems: 4,
      maxItems: 10,
      items: {
        type: "object",
        additionalProperties: false,
        required: ["stepId", "title", "detail"],
        properties: {
          stepId: {
            type: "string",
            enum: ["recipe", "context", "product", "inventory", "promotions", "builder", "final-response"]
          },
          title: { type: "string" },
          detail: { type: "string" }
        }
      }
    },
    groups: {
      type: "array",
      minItems: 1,
      maxItems: 12,
      items: groceryGroupSchema
    },
    substitutions: {
      type: "array",
      maxItems: 8,
      items: { type: "string" }
    },
    optionalItems: {
      type: "array",
      maxItems: 8,
      items: { type: "string" }
    },
    customerNotes: {
      type: "array",
      maxItems: 8,
      items: { type: "string" }
    }
  }
};

const orchestratorSchema = {
  type: "object",
  additionalProperties: false,
  required: ["isRecipeRelated", "intentSummary", "servings", "constraints", "meals", "traceDetail"],
  properties: {
    isRecipeRelated: { type: "boolean" },
    intentSummary: { type: "string" },
    servings: { type: "string" },
    constraints: { type: "array", maxItems: 10, items: { type: "string" } },
    meals: { type: "array", maxItems: 10, items: { type: "string" } },
    traceDetail: { type: "string" }
  }
};

const recipePlannerSchema = {
  type: "object",
  additionalProperties: false,
  required: ["recipes", "baseIngredients", "substitutions", "optionalItems", "customerNotes", "traceDetail"],
  properties: {
    recipes: {
      type: "array",
      minItems: 1,
      maxItems: 8,
      items: {
        type: "object",
        additionalProperties: false,
        required: ["name", "role", "ingredients"],
        properties: {
          name: { type: "string" },
          role: { type: "string" },
          ingredients: {
            type: "array",
            minItems: 1,
            maxItems: 20,
            items: groceryItemSchema
          }
        }
      }
    },
    baseIngredients: {
      type: "array",
      minItems: 1,
      maxItems: 50,
      items: groceryItemSchema
    },
    substitutions: { type: "array", maxItems: 8, items: { type: "string" } },
    optionalItems: { type: "array", maxItems: 8, items: { type: "string" } },
    customerNotes: { type: "array", maxItems: 8, items: { type: "string" } },
    traceDetail: { type: "string" }
  }
};

const groupedCartSchema = {
  type: "object",
  additionalProperties: false,
  required: ["groups", "traceDetail"],
  properties: {
    groups: {
      type: "array",
      minItems: 1,
      maxItems: 12,
      items: groceryGroupSchema
    },
    traceDetail: { type: "string" }
  }
};

const reviewAgentSchema = {
  type: "object",
  additionalProperties: false,
  required: ["groups", "substitutions", "optionalItems", "customerNotes", "traceDetail"],
  properties: {
    groups: {
      type: "array",
      minItems: 1,
      maxItems: 12,
      items: groceryGroupSchema
    },
    substitutions: { type: "array", maxItems: 8, items: { type: "string" } },
    optionalItems: { type: "array", maxItems: 8, items: { type: "string" } },
    customerNotes: { type: "array", maxItems: 8, items: { type: "string" } },
    traceDetail: { type: "string" }
  }
};

const finalAgentSchema = {
  type: "object",
  additionalProperties: false,
  required: ["summary", "customerNotes", "traceDetail"],
  properties: {
    summary: { type: "string" },
    customerNotes: { type: "array", maxItems: 8, items: { type: "string" } },
    traceDetail: { type: "string" }
  }
};

function sendJson(response, status, payload) {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(payload));
}

async function readJson(request) {
  let body = "";
  for await (const chunk of request) {
    body += chunk;
    if (body.length > 50_000) {
      throw new Error("Request body is too large.");
    }
  }
  return JSON.parse(body || "{}");
}

function extractOutputText(payload) {
  if (typeof payload.output_text === "string") return payload.output_text;

  const parts = [];
  for (const output of payload.output || []) {
    for (const content of output.content || []) {
      if (typeof content.text === "string") parts.push(content.text);
      if (typeof content.output_text === "string") parts.push(content.output_text);
    }
  }
  return parts.join("\n");
}

function runCurlRequest(requestBody, apiKey) {
  return new Promise((resolve, reject) => {
    const child = spawn("curl", [
      "-sS",
      "--fail-with-body",
      "https://api.openai.com/v1/responses",
      "-H",
      "content-type: application/json",
      "-H",
      `authorization: Bearer ${apiKey}`,
      "--data-binary",
      "@-"
    ], { stdio: ["pipe", "pipe", "pipe"] });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });

    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });

    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) {
        resolve(JSON.parse(stdout));
        return;
      }

      try {
        const payload = JSON.parse(stdout);
        const apiError = new Error(payload.error?.message || stderr || "The curl LLM request failed.");
        apiError.status = payload.error?.status || 500;
        reject(apiError);
      } catch {
        reject(new Error(stderr || "The curl LLM request failed."));
      }
    });

    child.stdin.end(requestBody);
  });
}

async function postToOpenAI(requestBody, apiKey) {
  try {
    const apiResponse = await fetch("https://api.openai.com/v1/responses", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${apiKey}`
      },
      body: requestBody
    });

    const payload = await apiResponse.json();

    if (!apiResponse.ok) {
      const apiError = new Error(payload.error?.message || "The LLM request failed.");
      apiError.status = apiResponse.status;
      throw apiError;
    }

    return payload;
  } catch (error) {
    if (error.cause?.code === "UNABLE_TO_GET_ISSUER_CERT_LOCALLY") {
      return runCurlRequest(requestBody, apiKey);
    }

    throw error;
  }
}

async function callAgent({ name, instructions, input, schema }) {
  const startedAt = Date.now();
  const requestBody = JSON.stringify({
    model,
    input: [
      {
        role: "system",
        content: [{ type: "input_text", text: instructions }]
      },
      {
        role: "user",
        content: [{ type: "input_text", text: typeof input === "string" ? input : JSON.stringify(input, null, 2) }]
      }
    ],
    text: {
      format: {
        type: "json_schema",
        name,
        strict: true,
        schema
      }
    }
  });

  const payload = await postToOpenAI(requestBody, process.env.OPENAI_API_KEY);
  const outputText = extractOutputText(payload);
  if (!outputText) {
    throw new Error(`${name} did not return parseable output text.`);
  }

  return {
    output: JSON.parse(outputText),
    durationMs: Date.now() - startedAt
  };
}

function trace(stepId, title, detail, durationMs) {
  return {
    stepId,
    title,
    detail: durationMs ? `${detail} (${Math.round(durationMs / 100) / 10}s)` : detail
  };
}

function nonRecipePlan(orchestrator) {
  return {
    isRecipeRelated: false,
    summary: orchestrator.intentSummary || "MarketMate is focused on recipe, meal-planning, and grocery prompts.",
    agentTrace: [
      trace("context", "Orchestrator Agent", orchestrator.traceDetail || "Checked whether the prompt belongs in the recipe shopping workflow."),
      trace("recipe", "Recipe Planner Agent", "Skipped recipe planning because the prompt was outside the supported food domain."),
      trace("builder", "Shopping List Builder Agent", "Created a minimal guidance card instead of a grocery cart."),
      trace("final-response", "Final Response Agent", "Asked for a recipe, meal plan, ingredient, or grocery-related request.")
    ],
    groups: [
      {
        aisle: "Recipe prompt needed",
        items: [
          {
            name: "Meal, recipe, ingredient, or grocery request",
            quantity: "1 prompt",
            reason: "MarketMate only builds shopping carts for cooking-related requests."
          }
        ]
      }
    ],
    substitutions: [],
    optionalItems: [],
    customerNotes: ["Try asking for a dinner plan, a recipe shopping list, substitutions, or ingredients for a cuisine or event."]
  };
}

async function createShoppingPlan(prompt) {
  if (!process.env.OPENAI_API_KEY) {
    const setupError = new Error("OPENAI_API_KEY is not set. Start the app with OPENAI_API_KEY=your_key npm run dev.");
    setupError.status = 503;
    throw setupError;
  }

  const agentTrace = [];
  const orchestratorRun = await callAgent({
    name: "orchestrator_agent",
    instructions: [
      "You are the Orchestrator Agent for a recipe shopping app.",
      "Decide whether the user prompt is recipe, meal-planning, grocery, ingredient, cooking, entertaining menu, or substitution related.",
      "Extract the user's cooking intent, likely servings, constraints, and requested meals.",
      "Do not create the shopping cart. Prepare structured context for specialist agents."
    ].join(" "),
    input: prompt,
    schema: orchestratorSchema
  });
  const orchestrator = orchestratorRun.output;
  agentTrace.push(trace("context", "Orchestrator Agent", orchestrator.traceDetail, orchestratorRun.durationMs));

  if (!orchestrator.isRecipeRelated) {
    return nonRecipePlan(orchestrator);
  }

  const recipeRun = await callAgent({
    name: "recipe_planner_agent",
    instructions: [
      "You are the Recipe Planner Agent.",
      "Choose practical recipes or meal components that satisfy the orchestrator context.",
      "Return base ingredients with quantities and reasons. Include sides, garnishes, dessert, and substitutions when relevant.",
      "Do not group by supermarket aisle; a later agent owns catalog mapping and cart grouping."
    ].join(" "),
    input: { userPrompt: prompt, orchestrator },
    schema: recipePlannerSchema
  });
  const recipePlan = recipeRun.output;
  agentTrace.push(trace("recipe", "Recipe Planner Agent", recipePlan.traceDetail, recipeRun.durationMs));

  const productRun = await callAgent({
    name: "product_search_agent",
    instructions: [
      "You are the Product Search Agent.",
      "Map the recipe planner's ingredients into supermarket-style grocery products.",
      "Normalize duplicate ingredients, use customer-friendly product names, and group them by common supermarket aisle.",
      "Keep quantities practical for the stated servings."
    ].join(" "),
    input: { userPrompt: prompt, orchestrator, recipePlan },
    schema: groupedCartSchema
  });
  const productCart = productRun.output;
  agentTrace.push(trace("product", "Product Search Agent", productCart.traceDetail, productRun.durationMs));

  const inventoryRun = await callAgent({
    name: "inventory_availability_agent",
    instructions: [
      "You are the Inventory & Availability Agent.",
      "Review the grouped cart for likely stock, freshness, and substitution issues.",
      "Keep the cart grouped by aisle, preserve useful items, and add clear substitution notes.",
      "Do not claim live inventory access; describe reasonable availability assumptions."
    ].join(" "),
    input: { userPrompt: prompt, orchestrator, recipePlan, productCart },
    schema: reviewAgentSchema
  });
  const inventoryReview = inventoryRun.output;
  agentTrace.push(trace("inventory", "Inventory & Availability Agent", inventoryReview.traceDetail, inventoryRun.durationMs));

  const promotionRun = await callAgent({
    name: "loyalty_promotions_agent",
    instructions: [
      "You are the Loyalty & Promotions Agent.",
      "Review the cart for sensible savings, bulk-buy, pantry-staple, and optional add-on opportunities.",
      "Keep the grouped cart intact unless a small practical adjustment improves the customer experience.",
      "Add concise customer notes and optional items. Do not invent exact coupons or live prices."
    ].join(" "),
    input: { userPrompt: prompt, orchestrator, recipePlan, inventoryReview },
    schema: reviewAgentSchema
  });
  const promotionReview = promotionRun.output;
  agentTrace.push(trace("promotions", "Loyalty & Promotions Agent", promotionReview.traceDetail, promotionRun.durationMs));

  const builderRun = await callAgent({
    name: "shopping_list_builder_agent",
    instructions: [
      "You are the Shopping List Builder Agent.",
      "Finalize the cart for a customer-facing grocery app.",
      "Deduplicate items, keep aisle grouping tidy, and ensure each product has a clear quantity and shopping reason.",
      "Preserve substitution, optional item, and note guidance from upstream agents."
    ].join(" "),
    input: { userPrompt: prompt, orchestrator, recipePlan, promotionReview },
    schema: reviewAgentSchema
  });
  const builtCart = builderRun.output;
  agentTrace.push(trace("builder", "Shopping List Builder Agent", builtCart.traceDetail, builderRun.durationMs));

  const finalRun = await callAgent({
    name: "final_response_agent",
    instructions: [
      "You are the Final Response Agent for MarketMate.",
      "Write a concise customer-facing summary and helpful notes for the completed cart.",
      "Do not change the cart. Explain the plan in polished shopping-app language."
    ].join(" "),
    input: { userPrompt: prompt, orchestrator, builtCart },
    schema: finalAgentSchema
  });
  const finalResponse = finalRun.output;
  agentTrace.push(trace("final-response", "Final Response Agent", finalResponse.traceDetail, finalRun.durationMs));

  return {
    isRecipeRelated: true,
    summary: finalResponse.summary,
    agentTrace,
    groups: builtCart.groups,
    substitutions: builtCart.substitutions,
    optionalItems: builtCart.optionalItems,
    customerNotes: [...builtCart.customerNotes, ...finalResponse.customerNotes].slice(0, 8)
  };
}

async function serveStatic(request, response) {
  const requestedPath = new URL(request.url, `http://${request.headers.host}`).pathname;
  const relativePath = requestedPath === "/" ? "index.html" : decodeURIComponent(requestedPath.slice(1));
  const normalizedPath = normalize(relativePath);

  if (normalizedPath.startsWith("..")) {
    response.writeHead(403);
    response.end("Forbidden");
    return;
  }

  const filePath = join(root, normalizedPath);
  const content = await readFile(filePath);
  response.writeHead(200, { "content-type": mimeTypes[extname(filePath)] || "application/octet-stream" });
  response.end(content);
}

const server = createServer(async (request, response) => {
  try {
    if (request.method === "POST" && request.url === "/api/recipe-plan") {
      const { prompt } = await readJson(request);
      if (typeof prompt !== "string" || prompt.trim().length < 3) {
        sendJson(response, 400, { error: "Please enter a recipe or meal-planning prompt." });
        return;
      }

      const plan = await createShoppingPlan(prompt.trim());
      sendJson(response, 200, plan);
      return;
    }

    if (request.method === "GET") {
      await serveStatic(request, response);
      return;
    }

    response.writeHead(405);
    response.end("Method not allowed");
  } catch (error) {
    if (error.code === "ENOENT") {
      response.writeHead(404);
      response.end("Not found");
      return;
    }

    sendJson(response, error.status || 500, { error: error.message || "Unexpected server error." });
  }
});

server.listen(port, () => {
  console.log(`Shopping assistant running at http://localhost:${port}`);
  console.log(`LLM model: ${model}`);
});
