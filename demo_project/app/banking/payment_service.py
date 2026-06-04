from app.banking.account_store import AccountStore
from app.banking.fee_calculator import calculate_transfer_fee


class PaymentService:
    def __init__(self, store: AccountStore):
        self.store = store

    def transfer(self, from_account: str, to_account: str, amount: float) -> dict:
        if from_account == to_account:
            return {
                "status": "declined",
                "reason": "Cannot transfer to the same account",
            }

        fee = calculate_transfer_fee(amount)
        sender_balance = self.store.get_balance(from_account)

        if sender_balance < amount + fee:
            return {
                "status": "declined",
                "reason": "Insufficient funds",
            }

        self.store.debit(from_account, amount + fee)
        self.store.credit(to_account, amount)

        return {
            "status": "success",
            "amount": amount,
            "fee": fee,
            "total_debited": amount + fee,
        }