import unittest
from agent.data import ERP
from agent.agent import PurchasingAgent


class T(unittest.TestCase):
    def setUp(self):
        self.erp = ERP()
        self.res = {r["decision"]["sku"]: r for r in PurchasingAgent(self.erp).run()}

    def test_healthy_stock_not_ordered(self):
        self.assertNotIn("SKU-102", self.res)

    def test_unapproved_supplier_never_chosen(self):
        self.assertNotEqual(self.res["SKU-101"]["decision"]["supplier"]["id"], "SUP-C")

    def test_small_order_auto_executes_and_validates(self):
        r = self.res["SKU-201"]
        self.assertEqual(r["status"], "executed")
        self.assertTrue(r["validation"]["ok"])

    def test_large_order_waits_for_approval(self):
        self.assertEqual(self.res["SKU-103"]["status"], "pending_approval")
        self.assertNotIn("SKU-103", [p["sku"] for p in self.erp.pos])

    def test_infeasible_delivery_is_escalated_not_bought(self):
        self.assertEqual(self.res["SKU-104"]["status"], "skipped")

    def test_budget_never_negative(self):
        self.assertTrue(all(v >= 0 for v in self.erp.db["budget"].values()))


class B:
    def __init__(self, **k): self.__dict__.update(k)


def tu(i, name, inp): return B(type="tool_use", id=i, name=name, input=inp)


class FakeClaude:
    """Scripted model: first proposes an UNAPPROVED supplier, gets rejected, then self-corrects."""
    def __init__(self):
        self.n, self.messages = 0, self
        self.script = [
            [tu("1", "get_low_stock_items", {})],
            [tu("2", "propose_purchase", {"sku": "SKU-101", "supplier_id": "SUP-C", "qty": 50, "rationale": "cheapest"})],
            [tu("3", "propose_purchase", {"sku": "SKU-101", "supplier_id": "SUP-A", "qty": 50, "rationale": "reliable+fast"})],
            [B(type="text", text="done")]]

    def create(self, **kw):
        self.n += 1
        return B(content=self.script[self.n - 1])


class LLMLoop(unittest.TestCase):
    def test_guardrail_rejects_then_model_recovers(self):
        from agent.llm_agent import run_llm
        erp = ERP(); a = PurchasingAgent(erp)
        res = run_llm(a, FakeClaude(), "fake")
        self.assertEqual(res[0]["decision"]["supplier"]["id"], "SUP-A")
        self.assertTrue(res[0]["validation"]["ok"])
        self.assertTrue(any(t["step"] == "guardrail" for t in a.trace))

    def test_shelf_life_cap_blocks_overstock(self):
        a = PurchasingAgent(ERP())
        self.assertIn("error", a.propose("SKU-301", "SUP-I", 500, "cheap"))


class Perishable(unittest.TestCase):
    def test_policy_never_picks_supplier_whose_moq_exceeds_shelf_life(self):
        r = {x["decision"]["sku"]: x for x in PurchasingAgent(ERP()).run()}
        self.assertEqual(r["SKU-301"]["decision"]["supplier"]["id"], "SUP-H")


if __name__ == "__main__":
    unittest.main()
