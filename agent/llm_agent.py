"""LLM tool-calling agent. Claude investigates via read-only tools and proposes purchases;
every proposal passes through PurchasingAgent.propose() (hard guardrails). Rejections are
returned to the model as tool errors so it can self-correct. Execution + validation stay in code."""
import json

SYSTEM = ("You are a purchasing agent for a quick-commerce buyer. Investigate stock risk with the tools, "
          "compare suppliers on price, lead time, reliability and MOQ, then call propose_purchase once per "
          "item that needs restocking. If a proposal is rejected, read the errors and fix it. "
          "Never invent suppliers. Finish with a one-line summary.")

TOOLS = [
    {"name": "get_low_stock_items", "description": "Items with less than 14 days of stock cover (incl. on-order).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_suppliers", "description": "All suppliers (price, lead_days, reliability, moq, approved) for a SKU.",
     "input_schema": {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]}},
    {"name": "get_budget", "description": "Remaining budget per category.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "propose_purchase", "description": "Propose a PO. Validated by hard guardrails; may be rejected.",
     "input_schema": {"type": "object", "properties": {
         "sku": {"type": "string"}, "supplier_id": {"type": "string"},
         "qty": {"type": "integer"}, "rationale": {"type": "string"}},
         "required": ["sku", "supplier_id", "qty", "rationale"]}},
]


def _dispatch(agent, call, results):
    n, a = call.name, call.input
    if n == "get_low_stock_items":
        out = agent.t_low_stock(); agent.log("investigate", f"low stock: {[i['sku'] for i in out]}")
    elif n == "get_suppliers":
        out = agent.t_suppliers(a["sku"]); agent.log("investigate", f"suppliers for {a['sku']}: {len(out)}")
    elif n == "get_budget":
        out = agent.erp.db["budget"]
    elif n == "propose_purchase":
        if any(r["decision"]["sku"] == a["sku"] for r in results):
            return {"error": ["already purchased/queued for this SKU"]}
        p = agent.propose(a["sku"], a["supplier_id"], int(a["qty"]), a["rationale"])
        if "error" in p:
            return p
        d = p["decision"]; agent.log("decide", d["explanation"], {k: v for k, v in d.items() if k != "supplier"})
        r = {"decision": d, "status": "pending_approval" if d["needs_approval"] else "executed"}
        if not d["needs_approval"]:
            r.update(agent.execute(d))
        results.append(r)
        out = {"status": r["status"], "validation_ok": r.get("validation", {}).get("ok")}
    else:
        out = {"error": [f"unknown tool {n}"]}
    return out


def run_llm(agent, client, model, max_turns=12):
    msgs = [{"role": "user", "content": "Review inventory and restock anything at risk."}]
    results = []
    for _ in range(max_turns):
        r = client.messages.create(model=model, max_tokens=1024, system=SYSTEM, tools=TOOLS, messages=msgs)
        msgs.append({"role": "assistant", "content": r.content})
        calls = [b for b in r.content if b.type == "tool_use"]
        if not calls:
            break
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": c.id, "content": json.dumps(_dispatch(agent, c, results))}
            for c in calls]})
    return results
