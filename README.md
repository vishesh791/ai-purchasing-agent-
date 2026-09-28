# AI Purchasing Agent

A full-stack agent that helps a buyer **replenish low-stock items**: it investigates inventory and suppliers,
decides what to buy and from whom, takes action (creates a PO), and validates the outcome.
Human approval is required above a spend threshold.

> Scenario implemented end-to-end: **low-stock replenishment**. Mock data, no external services required.

## Run
```bash
python server.py            # http://localhost:8000  (no dependencies)
python -m unittest discover -s tests -t .
```
Optional: `pip install anthropic` and set `ANTHROPIC_API_KEY` to have Claude write the rationale text.
Without a key, a template is used and everything still works.

## Flow
| Step | What happens | Code |
|---|---|---|
| Investigate | Find SKUs with < 14 days of cover; pull suppliers; drop unapproved ones | `agent.t_low_stock`, `t_suppliers` |
| Decide | Drop suppliers that can't arrive before stock-out; score the rest (reliability 0.4, lead time 0.3, price 0.3); size qty = demand over lead time + 7-day safety − stock, respecting MOQ; check budget | `agent.decide` |
| Act | Under $1,500 auto-create PO; above that, wait for buyer approve/reject | `agent.act`, `server.approve` |
| Validate | 7 post-conditions: PO recorded, total = qty × price, supplier approved, arrives before stock-out, budget decremented, budget ≥ 0, cover restored | `agent.validate` |

## Design choices (talking points)
- **Two modes, one guardrail layer.** With `ANTHROPIC_API_KEY`, Claude runs a tool-calling loop (investigate, compare, propose). Without a key, a deterministic policy makes the same decision. Both go through the same hard guardrails, so the LLM can propose but never overspend or pick an unapproved supplier.
- **Guardrail errors are fed back to the model** as tool errors so it self-corrects (tested with a scripted fake model in `tests/`).
- **Guardrails:** approved-supplier list, budget cap, approval threshold, infeasible cases escalate instead of buying.
- **Validation reads state back** from the ERP rather than trusting the action's return value.
- **Swappable backend:** `agent/data.py` (`ERP`) is the only thing to replace with a real DB/API.

## Agent modes
| Mode | When | Who decides | Who enforces rules |
|---|---|---|---|
| LLM | `ANTHROPIC_API_KEY` set | Claude via tools (`agent/llm_agent.py`) | `PurchasingAgent.propose()` |
| Policy | no key / LLM error | scoring code (`agent.decide`) | same checks |

Perishables: `SKU-301` Fresh Milk has a 7-day shelf life, so a cheaper supplier with a 500-unit MOQ is rejected
because it would overstock and spoil.

## Demo data outcomes
- `SKU-101` USB-C Hub → auto-bought from VoltEdge (cheaper BulkTech is too slow; ShadyDeals unapproved)
- `SKU-103` Monitor → $3,120 → waits for approval
- `SKU-104` Webcam → no supplier can beat the stock-out → escalated
- `SKU-201` Paper → auto-bought; `SKU-102` Mouse → healthy, ignored

## Interview prep: questions to be ready for
- **Why not let the LLM decide everything?** Money is involved; rules must be deterministic, testable and auditable. The LLM handles the fuzzy part (trade-offs, explanation).
- **What if the model hallucinates a supplier or qty?** `propose()` rejects it and returns the reason; the loop retries. Capped at 12 turns.
- **How would you add a new scenario (e.g. price-spike detection, negotiation)?** Add read tools + one guarded action tool; reuse the trace/validate pattern.
- **How do you know the action worked?** `validate()` re-reads ERP state and checks 7 post-conditions.
- **Scale/production?** Replace `ERP` with real APIs, persist state and traces, add auth, idempotency keys on PO creation, evals over historical orders.
- **Try live changes:** raise `APPROVAL_LIMIT`, change score weights, add a new guardrail (e.g. max spend per supplier).

## Layout
```
agent/{data,agent,llm_agent,llm}.py   server.py   static/index.html   tests/test_agent.py
```
## Limitations / next steps
Single-item POs, static demand (no forecast), in-memory state, no auth, no multi-currency or contract terms.
