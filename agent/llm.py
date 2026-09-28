"""Optional LLM layer. The DECISION is made by deterministic policy code (auditable);
the LLM only explains it in buyer-friendly language. Falls back to a template offline."""
import os, json


def explain(decision: dict) -> str:
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            msg = anthropic.Anthropic().messages.create(
                model=os.getenv("MODEL", "claude-sonnet-4-5"), max_tokens=250,
                messages=[{"role": "user", "content":
                           "You assist a procurement buyer. In 2-3 sentences, justify this purchasing decision "
                           "using only these facts:\n" + json.dumps(decision)}])
            return msg.content[0].text
        except Exception as e:  # never let the LLM break the pipeline
            return _template(decision) + f" (LLM unavailable: {type(e).__name__})"
    return _template(decision)


def _template(d):
    if d["action"] == "skip":
        return f"No purchase: {d['reason']}."
    s = d["supplier"]
    return (f"Buy {d['qty']} units from {s['name']} at ${s['price']:.2f} (score {s['score']}). "
            f"Stock runs out in {d['days_of_cover']:.1f} days and delivery takes {s['lead_days']}; "
            f"{d['reason']}.")
