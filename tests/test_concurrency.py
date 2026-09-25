"""
Tests for Concurrency Safety: Atomic Conditional Stock Decrements and Sequential Invoice Sequences.
"""
import concurrent.futures
from models import InvoiceCreate, InvoiceItemInput


def test_concurrent_checkout_prevents_overselling(client, db_conn, sample_product_with_variants):
    v1 = sample_product_with_variants["variant_1"]

    # Set stock of variant 1 to exactly 1
    cursor = db_conn.cursor()
    cursor.execute("UPDATE inventory SET stock_quantity = 1 WHERE variant_id = ?;", (v1["id"],))
    db_conn.commit()

    payload = {
        "customer_name": "Concurrent Buyer",
        "customer_phone": "9999988888",
        "payment_method": "Cash",
        "items": [
            {
                "variant_id": v1["id"],
                "sku": v1["sku"],
                "product_name": "Exclusive Tee",
                "quantity": 1,
                "unit_price": 1500.0
            }
        ]
    }

    results = []
    # Launch 5 concurrent checkout requests for the same single available unit
    def attempt_checkout():
        return client.post("/api/sales/checkout", json=payload)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(attempt_checkout) for _ in range(5)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    success_responses = [r for r in results if r.status_code == 200]
    failed_responses = [r for r in results if r.status_code in (400, 409)]

    # Exactly ONE checkout must succeed
    assert len(success_responses) == 1
    # Exactly FOUR checkouts must fail due to stock depletion
    assert len(failed_responses) == 4

    for fr in failed_responses:
        assert "INSUFFICIENT_STOCK" in fr.json().get("detail", "")

    # Authoritative inventory table must have exactly 0 stock, NEVER negative
    cursor.execute("SELECT stock_quantity FROM inventory WHERE variant_id = ?;", (v1["id"],))
    final_stock = cursor.fetchone()[0]
    assert final_stock == 0


def test_collision_free_sequential_invoice_numbering(client, db_conn, sample_product_with_variants):
    v1 = sample_product_with_variants["variant_1"]

    # Provide plenty of stock
    cursor = db_conn.cursor()
    cursor.execute("UPDATE inventory SET stock_quantity = 50 WHERE variant_id = ?;", (v1["id"],))
    db_conn.commit()

    num_concurrent_orders = 8

    def make_order(idx):
        payload = {
            "customer_name": f"Shopper {idx}",
            "customer_phone": f"900000000{idx}",
            "payment_method": "UPI",
            "items": [
                {
                    "variant_id": v1["id"],
                    "sku": v1["sku"],
                    "product_name": "Tee",
                    "quantity": 1,
                    "unit_price": 1500.0
                }
            ]
        }
        return client.post("/api/sales/checkout", json=payload)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_concurrent_orders) as executor:
        futures = [executor.submit(make_order, i) for i in range(num_concurrent_orders)]
        responses = [f.result() for f in concurrent.futures.as_completed(futures)]

    # All should succeed
    for r in responses:
        assert r.status_code == 200

    invoice_numbers = [r.json()["invoice_number"] for r in responses]
    # Every invoice number must be strictly unique
    assert len(set(invoice_numbers)) == num_concurrent_orders
    # Every invoice number must adhere to prefix format
    for inv in invoice_numbers:
        assert inv.startswith("SOL-")


def test_year_rollover_sequence(db_conn):
    from services.sales_service import get_next_invoice_number

    # Generate sequence for 2026
    inv_2026_1 = get_next_invoice_number(db_conn, "2026")
    inv_2026_2 = get_next_invoice_number(db_conn, "2026")
    assert inv_2026_1 == "SOL-2026-000001"
    assert inv_2026_2 == "SOL-2026-000002"

    # Year rolls over to 2027: sequence starts fresh from 000001
    inv_2027_1 = get_next_invoice_number(db_conn, "2027")
    inv_2027_2 = get_next_invoice_number(db_conn, "2027")
    assert inv_2027_1 == "SOL-2027-000001"
    assert inv_2027_2 == "SOL-2027-000002"

    # 2026 continues cleanly where it left off
    inv_2026_3 = get_next_invoice_number(db_conn, "2026")
    assert inv_2026_3 == "SOL-2026-000003"
