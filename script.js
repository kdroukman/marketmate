const defaultPrompt = `Make me a shopping list based on my weekly dinner planner -
Monday: Chicken Kiev, Tuesday: Steak, Wednesday: Any Fish recipe, Thursday: Vegetarian Dish, Friday: Pasta.
Include some side dishes and garnish options.`;

const workflow = [
  ["prompt", "User Prompt", "Captured weekly dinner planner and shopping intent."],
  ["orchestrator-plan", "AI Intake Agent", "Detected intent, extracted meals, and decomposed the request."],
  ["orchestrator", "Agentic Orchestrator", "Starting the specialist AI agent chain."],
  ["approval", "Customer Approval", "List is ready for review and confirmation."]
];

const checkoutFlow = [
  ["checkout", "Checkout Agent", "Submitted approved list to order management."],
  ["delivery", "Delivery Scheduler", "Reserved a delivery window for tomorrow evening."],
  ["notify", "Notification Agent", "Sent confirmation by email, SMS, and push."]
];

const promptInput = document.querySelector("#plannerPrompt");
const runButton = document.querySelector("#runWorkflow");
const resetButton = document.querySelector("#resetPrompt");
const approveButton = document.querySelector("#approveList");
const reviseButton = document.querySelector("#reviseList");
const approvalStatus = document.querySelector("#approvalStatus");
const shoppingList = document.querySelector("#shoppingList");
const traceList = document.querySelector("#traceList");
const traceCount = document.querySelector("#traceCount");
const itemCount = document.querySelector("#itemCount");
const summaryItems = document.querySelector("#summaryItems");
const progressFill = document.querySelector("#progressFill");

let running = false;
let tracePosition = 0;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function setProgress(done, total) {
  progressFill.style.width = `${Math.round((done / total) * 100)}%`;
  traceCount.textContent = `${done}/${total}`;
}

function resetWorkflow() {
  tracePosition = 0;
  document.querySelectorAll(".node").forEach((node) => {
    node.classList.remove("active", "complete");
  });
  traceList.innerHTML = "";
  setProgress(0, workflow.length);
  approvalStatus.textContent = "Pending";
  approvalStatus.className = "status-pill pending";
  approveButton.disabled = true;
  reviseButton.disabled = true;
}

function addTrace(step, title, detail, complete = false) {
  const item = document.createElement("li");
  item.className = complete ? "complete" : "";
  item.innerHTML = `<strong>${title}</strong><span>${detail}</span>`;
  traceList.appendChild(item);
  traceList.scrollTop = traceList.scrollHeight;
}

function activateStep(stepId, completed = true) {
  document.querySelectorAll(".node.active").forEach((node) => node.classList.remove("active"));
  const node = document.querySelector(`[data-step="${stepId}"]`);
  if (!node) return;
  node.classList.add("active");
  if (completed) node.classList.add("complete");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#039;");
}

function renderShoppingList(plan) {
  const groups = [...plan.groups];
  if (plan.substitutions.length) {
    groups.push({
      aisle: "Substitutions",
      items: plan.substitutions.map((item) => ({ name: item, quantity: "Optional", reason: "Backup option" }))
    });
  }
  if (plan.optionalItems.length) {
    groups.push({
      aisle: "Optional Items",
      items: plan.optionalItems.map((item) => ({ name: item, quantity: "Optional", reason: "Nice-to-have addition" }))
    });
  }

  const total = groups.reduce((sum, group) => sum + group.items.length, 0);
  itemCount.textContent = `${total} items`;
  summaryItems.textContent = total;
  shoppingList.classList.remove("empty");
  shoppingList.innerHTML = groups.map((group) => `
    <div class="aisle-group">
      <div class="aisle-name">${escapeHtml(group.aisle)}</div>
      <ul class="item-list">
        ${group.items.map((item) => `
          <li>
            <strong>${escapeHtml(item.name)}</strong>
            <span>${escapeHtml(item.quantity)}</span>
            <small>${escapeHtml(item.reason)}</small>
          </li>
        `).join("")}
      </ul>
    </div>
  `).join("") + `
    <div class="customer-notes">
      <strong>${escapeHtml(plan.summary)}</strong>
      ${plan.customerNotes.map((note) => `<p>${escapeHtml(note)}</p>`).join("")}
    </div>
  `;
}

function showError(message) {
  shoppingList.className = "shopping-list empty";
  shoppingList.textContent = message;
  itemCount.textContent = "Needs setup";
  summaryItems.textContent = "0";
  approvalStatus.textContent = "Pending";
  approvalStatus.className = "status-pill pending";
  approveButton.disabled = true;
  reviseButton.disabled = false;
}

async function fetchShoppingPlan(prompt) {
  const response = await fetch("/api/recipe-plan", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ prompt })
  });

  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "The recipe planning request failed.");
  }

  return payload;
}

async function runWorkflow() {
  if (running) return;
  running = true;
  runButton.disabled = true;
  resetWorkflow();
  shoppingList.className = "shopping-list empty";
  shoppingList.textContent = "MarketMate is building your cart...";
  itemCount.textContent = "Working";
  summaryItems.textContent = "0";

  for (const [stepId, title, detail] of workflow.slice(0, 3)) {
    tracePosition += 1;
    activateStep(stepId);
    addTrace(stepId, title, detail, true);
    setProgress(tracePosition, workflow.length);
    await sleep(260);
  }

  try {
    const plan = await fetchShoppingPlan(promptInput.value);
    const planTrace = plan.agentTrace.length ? plan.agentTrace : workflow.slice(3, -1).map(([stepId, title, detail]) => ({ stepId, title, detail }));
    const totalSteps = 3 + planTrace.length + 1;

    for (const { stepId, title, detail } of planTrace) {
      tracePosition += 1;
      activateStep(stepId);
      addTrace(stepId, title, detail, true);
      setProgress(tracePosition, totalSteps);
      await sleep(120);
    }

    tracePosition += 1;
    activateStep("approval");
    addTrace("approval", "Customer Approval", plan.isRecipeRelated ? "Agent-generated shopping cart is ready for review." : "Prompt was not recipe-related.", true);
    setProgress(tracePosition, totalSteps);

    if (!plan.isRecipeRelated) {
      showError(plan.summary || "Please enter a prompt related to recipes, meals, groceries, or ingredients.");
      runButton.disabled = false;
      running = false;
      return;
    }

    renderShoppingList(plan);
  } catch (error) {
    addTrace("final-response", "LLM Request Failed", error.message, true);
    showError(error.message);
    runButton.disabled = false;
    running = false;
    return;
  }

  approvalStatus.textContent = "Ready";
  approvalStatus.className = "status-pill ready";
  approveButton.disabled = false;
  reviseButton.disabled = false;
  runButton.disabled = false;
  running = false;
}

async function approveList() {
  if (running) return;
  running = true;
  approveButton.disabled = true;
  reviseButton.disabled = true;
  approvalStatus.textContent = "Approved";
  approvalStatus.className = "status-pill approved";

  const total = workflow.length + checkoutFlow.length;
  for (const [stepId, title, detail] of checkoutFlow) {
    tracePosition += 1;
    activateStep(stepId);
    addTrace(stepId, title, detail, true);
    setProgress(tracePosition, total);
    await sleep(300);
  }

  addTrace("complete", "Order Confirmed", "Checkout, delivery scheduling, and notification workflow completed.", true);
  document.querySelectorAll(".node.active").forEach((node) => node.classList.remove("active"));
  running = false;
}

resetButton.addEventListener("click", () => {
  promptInput.value = defaultPrompt;
  resetWorkflow();
  shoppingList.className = "shopping-list empty";
  shoppingList.textContent = "Tell MarketMate what you want to cook and your shopping list will appear here.";
  itemCount.textContent = "0 items";
  summaryItems.textContent = "0";
});

runButton.addEventListener("click", runWorkflow);
approveButton.addEventListener("click", approveList);
reviseButton.addEventListener("click", () => {
  approvalStatus.textContent = "Pending";
  approvalStatus.className = "status-pill pending";
  approveButton.disabled = true;
  reviseButton.disabled = true;
  promptInput.focus();
});

resetWorkflow();
