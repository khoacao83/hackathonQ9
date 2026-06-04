class OrderService:
    def __init__(self, reservation_service, payment_gateway):
        self.reservation_service = reservation_service
        self.payment_gateway = payment_gateway

    def place_order(self, customer_id: str, product_id: str, quantity: int, unit_price: int):
        reservation = self.reservation_service.reserve(product_id, quantity)

        if reservation["status"] != "reserved":
            return {
                "status": "declined",
                "reason": reservation["reason"],
            }

        payment = self.payment_gateway.charge(
            customer_id=customer_id,
            amount=quantity * unit_price,
        )

        if payment["status"] != "paid":
            # BUG:
            # Payment failed but reservation is not released.
            # This causes reserved stock to remain stuck.
            return {
                "status": "declined",
                "reason": "Payment failed",
            }

        commit = self.reservation_service.commit(product_id, quantity)

        return {
            "status": "confirmed",
            "reservation": reservation,
            "payment": payment,
            "commit": commit,
        }