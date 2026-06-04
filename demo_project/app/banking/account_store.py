class AccountStore:
    def __init__(self):
        self.accounts = {
            "alice": 100.0,
            "bob": 20.0,
            "charlie": 0.0,
        }

    def get_balance(self, account_id: str) -> float:
        if account_id not in self.accounts:
            raise ValueError(f"Account not found: {account_id}")
        return self.accounts[account_id]

    def debit(self, account_id: str, amount: float) -> None:
        if account_id not in self.accounts:
            raise ValueError(f"Account not found: {account_id}")
        self.accounts[account_id] -= amount

    def credit(self, account_id: str, amount: float) -> None:
        if account_id not in self.accounts:
            raise ValueError(f"Account not found: {account_id}")
        self.accounts[account_id] += amount

    def snapshot(self) -> dict:
        return dict(self.accounts)