from app.banking.account_store import AccountStore
from app.banking.payment_service import PaymentService


def test_successful_transfer_with_fee():
    store = AccountStore()
    service = PaymentService(store)

    result = service.transfer("alice", "bob", 50.0)

    assert result["status"] == "success"
    assert result["fee"] == 1.0
    assert store.get_balance("alice") == 49.0
    assert store.get_balance("bob") == 70.0


def test_transfer_should_fail_when_balance_cannot_cover_amount_plus_fee():
    store = AccountStore()
    service = PaymentService(store)

    before = store.snapshot()

    result = service.transfer("alice", "bob", 100.0)

    assert result["status"] == "declined"
    assert result["reason"] == "Insufficient funds"
    assert store.snapshot() == before


def test_same_account_transfer_should_be_declined_without_balance_change():
    store = AccountStore()
    service = PaymentService(store)

    before = store.snapshot()

    result = service.transfer("alice", "alice", 10.0)

    assert result["status"] == "declined"
    assert result["reason"] == "Cannot transfer to the same account"
    assert store.snapshot() == before