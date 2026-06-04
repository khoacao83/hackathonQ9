class PaymentGateway:
    def __init__(self, should_succeed: bool = True):
        self.should_succeed = should_succeed

    def charge(self, customer_id: str, amount: int):
        if self.should_succeed:
            return {
                "status": "paid",
                "customer_id": customer_id,
                "amount": amount,
            }

        return {
            "status": "failed",
            "customer_id": customer_id,
            "amount": amount,
            "reason": "Payment declined",
        }