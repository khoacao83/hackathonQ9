from app.inventory.inventory_store import InventoryStore
from app.inventory.reservation_service import ReservationService
from app.inventory.payment_gateway import PaymentGateway
from app.inventory.order_service import OrderService


def test_should_not_oversell_when_multiple_orders_reserve_same_product():
    store = InventoryStore()
    store.add_product("iphone-15", 5)

    reservation_service = ReservationService(store)

    first = reservation_service.reserve("iphone-15", 3)
    second = reservation_service.reserve("iphone-15", 3)

    assert first["status"] == "reserved"

    # This should fail because only 2 units should be available after first reservation.
    assert second["status"] == "failed"
    assert second["reason"] == "Insufficient inventory"

    assert store.get_stock("iphone-15") == 5
    assert store.get_reserved("iphone-15") == 3
    assert store.get_available("iphone-15") == 2


def test_should_release_reserved_stock_when_payment_fails():
    store = InventoryStore()
    store.add_product("macbook-pro", 10)

    reservation_service = ReservationService(store)
    payment_gateway = PaymentGateway(should_succeed=False)
    order_service = OrderService(reservation_service, payment_gateway)

    result = order_service.place_order(
        customer_id="customer-001",
        product_id="macbook-pro",
        quantity=4,
        unit_price=2000,
    )

    assert result["status"] == "declined"
    assert result["reason"] == "Payment failed"

    # Reservation should be released after payment failure.
    assert store.get_stock("macbook-pro") == 10
    assert store.get_reserved("macbook-pro") == 0
    assert store.get_available("macbook-pro") == 10


def test_should_commit_order_and_clear_reserved_stock_when_payment_succeeds():
    store = InventoryStore()
    store.add_product("airpods-pro", 8)

    reservation_service = ReservationService(store)
    payment_gateway = PaymentGateway(should_succeed=True)
    order_service = OrderService(reservation_service, payment_gateway)

    result = order_service.place_order(
        customer_id="customer-002",
        product_id="airpods-pro",
        quantity=3,
        unit_price=250,
    )

    assert result["status"] == "confirmed"

    # Stock should decrease by 3.
    assert store.get_stock("airpods-pro") == 5

    # Reserved should be cleared after commit.
    assert store.get_reserved("airpods-pro") == 0

    # Available should match remaining stock.
    assert store.get_available("airpods-pro") == 5


def test_release_should_not_make_reserved_quantity_negative():
    store = InventoryStore()
    store.add_product("ipad-air", 5)

    reservation_service = ReservationService(store)

    reservation_service.release("ipad-air", 2)

    # Reserved should never become negative.
    assert store.get_reserved("ipad-air") == 0
    assert store.get_available("ipad-air") == 5