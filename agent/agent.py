"""Investigate -> Decide -> Act -> Validate loop for low-stock replenishment."""
from . import llm

SAFETY_DAYS = 7            # extra cover wanted on top of lead time
REORDER_TRIGGER_DAYS = 14  # investigate SKUs with less cover than this
APPROVAL_LIMIT = 1500      # POs above this need human approval


class PurchasingAgent:
    def __init__(self, erp):
        self.erp, self.trace = erp, []

    def log(self, step, msg, data=None):
        self.trace.append({"step": step, "msg": msg, "data": data})

    # ---- tools (read-only) ----
    def t_low_stock(self):
        out = []
        for sku, i in self.erp.db["inventory"].items():
            cover = (i["on_hand"] + i["on_order"]) / i["daily_sales"]
            if cover < REORDER_TRIGGER_DAYS:
                out.append({"sku": sku, **i, "days_of_cover": round(cover, 1)})
        return out

    def t_suppliers(self, sku):
        return [s for s in self.erp.db["suppliers"] if s["sku"] == sku]

    # ---- decide ----
    def score(self, s, cover, max_price):
        if s["lead_days"] > cover:  # would stock out before arrival
            return None
        price_pts = 1 - s["price"] / max_price
        return round(0.4 * s["reliability"] + 0.3 * (1 - s["lead_days"] / 30) + 0.3 * price_pts, 3)

    def decide(self, item):
        cover = item["days_of_cover"]
        all_s = self.t_suppliers(item["sku"])
        peers = [s for s in all_s if s["approved"]]
        excluded = [s["name"] for s in all_s if not s["approved"]]
        cap = int(item["daily_sales"] * item["shelf_life_days"]) if item.get("shelf_life_days") else None
        if cap:  # perishables: never order more than we can sell before expiry
            peers = [s for s in peers if s["moq"] <= cap]
        self.log("investigate", f"{item['sku']} ({item['name']}): {cover}d cover; {len(peers)} approved suppliers"
                 + (f"; excluded unapproved: {excluded}" if excluded else ""))
        max_price = max((s["price"] for s in peers), default=1)
        ranked = [{**s, "score": sc} for s in peers if (sc := self.score(s, cover, max_price)) is not None]
        if not ranked:
            return {"sku": item["sku"], "action": "skip",
                    "reason": "no approved supplier can deliver before stock-out (escalate to buyer)"}
        best = max(ranked, key=lambda s: s["score"])
        need = item["daily_sales"] * (best["lead_days"] + SAFETY_DAYS) - (item["on_hand"] + item["on_order"])
        qty = max(int(need), best["moq"])
        if cap:
            qty = min(qty, cap)
        total = round(qty * best["price"], 2)
        left = self.erp.db["budget"][item["category"]]
        d = {"sku": item["sku"], "action": "buy", "qty": qty, "supplier": best, "total": total,
             "days_of_cover": cover, "budget_left": left,
             "alternatives": [{"name": s["name"], "score": s["score"]} for s in ranked]}
        if total > left:
            d.update(action="skip", reason=f"${total} exceeds remaining {item['category']} budget ${left}")
        elif total > APPROVAL_LIMIT:
            d.update(needs_approval=True, reason=f"${total} exceeds ${APPROVAL_LIMIT} auto-approve limit")
        else:
            d.update(needs_approval=False, reason="within budget and auto-approve limit")
        d["explanation"] = llm.explain(d)
        return d

    # ---- guardrails for LLM-proposed purchases ----
    def propose(self, sku, supplier_id, qty, rationale):
        """Hard policy check. The LLM proposes; this code disposes. Errors go back to the model."""
        inv = self.erp.db["inventory"].get(sku)
        sup = next((x for x in self.t_suppliers(sku) if x["id"] == supplier_id), None)
        if not inv or not sup:
            return {"error": [f"unknown sku/supplier: {sku}/{supplier_id}"]}
        cover = round((inv["on_hand"] + inv["on_order"]) / inv["daily_sales"], 1)
        total, left, errs = round(qty * sup["price"], 2), self.erp.db["budget"][inv["category"]], []
        if not sup["approved"]: errs.append("supplier is not on the approved list")
        if sup["lead_days"] > cover: errs.append(f"lead time {sup['lead_days']}d exceeds {cover}d of stock cover")
        if qty < sup["moq"]: errs.append(f"qty below supplier MOQ {sup['moq']}")
        if total > left: errs.append(f"total ${total} exceeds remaining budget ${left}")
        if inv.get("shelf_life_days") and qty > inv["daily_sales"] * inv["shelf_life_days"]:
            errs.append(f"qty exceeds shelf-life cap {int(inv['daily_sales'] * inv['shelf_life_days'])}")
        if errs:
            self.log("guardrail", f"Rejected proposal {sku}/{supplier_id} x{qty}: {'; '.join(errs)}")
            return {"error": errs}
        d = {"sku": sku, "action": "buy", "qty": qty, "supplier": {**sup, "score": None}, "total": total,
             "days_of_cover": cover, "budget_left": left, "needs_approval": total > APPROVAL_LIMIT,
             "reason": "LLM proposal passed all guardrails", "explanation": rationale}
        return {"decision": d}

    # ---- act + validate ----
    def act(self, d):
        s = d["supplier"]
        po = self.erp.create_po(d["sku"], s["id"], d["qty"], s["price"], s["lead_days"])
        self.log("act", f"Created {po['po_id']} for {d['sku']}: {po['qty']} x ${po['unit_price']} = ${po['total']}", po)
        return po

    def validate(self, d, po, budget_before):
        inv = self.erp.db["inventory"][d["sku"]]
        budget_now = self.erp.db["budget"][inv["category"]]
        checks = {
            "po_recorded": any(p["po_id"] == po["po_id"] for p in self.erp.pos),
            "total_matches_qty_x_price": abs(po["total"] - po["qty"] * po["unit_price"]) < 0.01,
            "supplier_approved": d["supplier"]["approved"],
            "arrives_before_stockout": po["eta_days"] <= d["days_of_cover"],
            "budget_decremented": abs((budget_before - po["total"]) - budget_now) < 0.01,
            "no_negative_budget": budget_now >= 0,
            "cover_now_healthy": (inv["on_hand"] + inv["on_order"]) / inv["daily_sales"] >= SAFETY_DAYS,
        }
        ok = all(checks.values())
        self.log("validate", "All checks passed" if ok else "FAILED: " + ", ".join(k for k, v in checks.items() if not v), checks)
        return {"ok": ok, "checks": checks}

    def execute(self, d):
        cat = self.erp.db["inventory"][d["sku"]]["category"]
        before = self.erp.db["budget"][cat]
        po = self.act(d)
        return {"po": po, "validation": self.validate(d, po, before)}

    def run(self):
        """Auto-approved buys are executed; larger ones wait for human approval."""
        results = []
        for item in self.t_low_stock():
            d = self.decide(item)
            self.log("decide", d.get("explanation") or d["reason"], {k: v for k, v in d.items() if k != "supplier"})
            r = {"decision": d, "status": "skipped"}
            if d["action"] == "buy" and not d["needs_approval"]:
                r.update(status="executed", **self.execute(d))
            elif d["action"] == "buy":
                r["status"] = "pending_approval"
            results.append(r)
        return results
