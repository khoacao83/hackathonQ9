class ReservationService:
    def __init__(self, inventory_store):
        self.inventory_store = inventory_store

    def reserve(self, product_id: str, quantity: int):
        available = self.inventory_store.get_available(product_id)

        if available < quantity:
            return {
                "status": "failed",
                "reason": "Insufficient inventory",
            }

        self.inventory_store.increase_reserved(product_id, quantity)

        return {
            "status": "reserved",
            "product_id": product_id,
            "quantity": quantity,
        }

    def release(self, product_id: str, quantity: int):
        # BUG:
        # No validation. It can reduce reserved below zero.
        self.inventory_store.decrease_reserved(product_id, quantity)

        return {
            "status": "released",
            "product_id": product_id,
            "quantity": quantity,
        }

    def commit(self, product_id: str, quantity: int):
        # BUG:
        # It decreases stock but does not decrease reserved.
        # After a successful order, reserved quantity remains stuck.
        self.inventory_store.decrease_stock(product_id, quantity)

        return {
            "status": "committed",
            "product_id": product_id,
            "quantity": quantity,
        }