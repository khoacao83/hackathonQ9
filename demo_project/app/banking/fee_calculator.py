def calculate_transfer_fee(amount: float) -> float:
    if amount <= 0:
        raise ValueError("Transfer amount must be positive")

    fee = amount * 0.01

    if fee < 1.0:
        return 1.0

    return round(fee, 2)