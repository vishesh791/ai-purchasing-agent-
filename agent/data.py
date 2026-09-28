"""Mock datasets + in-memory 'ERP'. Swap for a real DB/API without touching the agent."""
import copy

SEED = {
    "budget": {"Electronics": 20000, "Office": 3000, "Grocery": 3000},
    "inventory": {  # on_hand, on_order, daily_sales, category
        "SKU-101": {"name": "USB-C Hub", "category": "Electronics", "on_hand": 100, "on_order": 0, "daily_sales": 12},
        "SKU-102": {"name": "Wireless Mouse", "category": "Electronics", "on_hand": 300, "on_order": 0, "daily_sales": 8},
        "SKU-103": {"name": "27in Monitor", "category": "Electronics", "on_hand": 60, "on_order": 0, "daily_sales": 6},
        "SKU-104": {"name": "Webcam", "category": "Electronics", "on_hand": 10, "on_order": 0, "daily_sales": 5},
        "SKU-301": {"name": "Fresh Milk 1L", "category": "Grocery", "on_hand": 100, "on_order": 0, "daily_sales": 40, "shelf_life_days": 7},
        "SKU-201": {"name": "A4 Paper (case)", "category": "Office", "on_hand": 15, "on_order": 0, "daily_sales": 5},
    },
    "suppliers": [
        {"id": "SUP-A", "name": "VoltEdge", "sku": "SKU-101", "price": 14.0, "lead_days": 5, "reliability": 0.97, "moq": 50, "approved": True},
        {"id": "SUP-B", "name": "BulkTech", "sku": "SKU-101", "price": 11.5, "lead_days": 14, "reliability": 0.88, "moq": 200, "approved": True},
        {"id": "SUP-C", "name": "ShadyDeals", "sku": "SKU-101", "price": 9.0, "lead_days": 3, "reliability": 0.60, "moq": 10, "approved": False},
        {"id": "SUP-A", "name": "VoltEdge", "sku": "SKU-103", "price": 130.0, "lead_days": 7, "reliability": 0.96, "moq": 10, "approved": True},
        {"id": "SUP-D", "name": "ScreenCo", "sku": "SKU-103", "price": 118.0, "lead_days": 10, "reliability": 0.93, "moq": 20, "approved": True},
        {"id": "SUP-G", "name": "CamWorld", "sku": "SKU-104", "price": 35.0, "lead_days": 6, "reliability": 0.94, "moq": 20, "approved": True},
        {"id": "SUP-H", "name": "DairyFresh", "sku": "SKU-301", "price": 1.10, "lead_days": 1, "reliability": 0.96, "moq": 100, "approved": True},
        {"id": "SUP-I", "name": "FarmCo", "sku": "SKU-301", "price": 0.95, "lead_days": 2, "reliability": 0.90, "moq": 500, "approved": True},
        {"id": "SUP-E", "name": "PaperPlus", "sku": "SKU-201", "price": 22.0, "lead_days": 2, "reliability": 0.99, "moq": 10, "approved": True},
        {"id": "SUP-F", "name": "OfficeDirect", "sku": "SKU-201", "price": 19.5, "lead_days": 4, "reliability": 0.95, "moq": 20, "approved": True},
    ],
}


class ERP:
    def __init__(self):
        self.db = copy.deepcopy(SEED)
        self.pos = []

    def create_po(self, sku, supplier_id, qty, unit_price, lead_days):
        po = {"po_id": f"PO-{len(self.pos)+1:04d}", "sku": sku, "supplier_id": supplier_id, "qty": qty,
              "unit_price": unit_price, "total": round(qty * unit_price, 2), "eta_days": lead_days, "status": "SENT"}
        self.pos.append(po)
        self.db["inventory"][sku]["on_order"] += qty
        cat = self.db["inventory"][sku]["category"]
        self.db["budget"][cat] = round(self.db["budget"][cat] - po["total"], 2)
        return po
