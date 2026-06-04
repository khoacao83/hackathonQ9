class InventoryStore:
    def __init__(self):
        self.products = {}

    def add_product(self, product_id: str, quantity: int):
        self.products[product_id] = {
            "stock": quantity,
            "reserved": 0,
        }

    def get_stock(self, product_id: str) -> int:
        return self.products[product_id]["stock"]

    def get_reserved(self, product_id: str) -> int:
        return self.products[product_id]["reserved"]

    def get_available(self, product_id: str) -> int:
        product = self.products[product_id]

        # BUG:
        # Available stock should be stock - reserved.
        # Current implementation ignores reserved quantity.
        return product["stock"]

    def increase_reserved(self, product_id: str, quantity: int):
        self.products[product_id]["reserved"] += quantity

    def decrease_reserved(self, product_id: str, quantity: int):
        self.products[product_id]["reserved"] -= quantity

    def decrease_stock(self, product_id: str, quantity: int):
        self.products[product_id]["stock"] -= quantity