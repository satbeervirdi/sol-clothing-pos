"""
Tests for Authoritative Inventory, Ledger Immutability, Stock In, and Adjustments.
"""
import pytest
from fastapi import HTTPException
from services.inventory_service import (
    stock_in,
    adjust_stock,
    get_variant_inventory,
    get_inventory_ledger,
    reconcile_inventory
)


def test_stock_in_increases_inventory_and_logs_ledger(db_conn, sample_product_with_variants):
    v1 = sample_product_with_variants["variant_1"]
    initial_stock = v1["stock"]  # 10

    # Stock-in 15 more units
    result = stock_in(
        conn=db_conn,
        variant_id=v1["id"],
        quantity=15,
        unit_cost=620.0,
        reference="PO-2026-001",
        reason="Vendor Shipment",
        user_id=1
    )

    assert result["stock_after"] == initial_stock + 15
    assert result["stock_before"] == initial_stock

    # Verify inventory table directly
    inv = get_variant_inventory(db_conn, v1["id"])
    assert inv["stock_quantity"] == 25

    # Verify ledger entry
    ledger = get_inventory_ledger(db_conn, variant_id=v1["id"])
    latest_tx = ledger[0]
    assert latest_tx["type"] == "STOCK_IN"
    assert latest_tx["quantity_change"] == 15
    assert latest_tx["stock_before"] == 10
    assert latest_tx["stock_after"] == 25
    assert latest_tx["reason"] == "Vendor Shipment"


def test_stock_adjustment_positive_and_negative(db_conn, sample_product_with_variants):
    v2 = sample_product_with_variants["variant_2"]
    initial_stock = v2["stock"]  # 5

    # Positive adjustment: found 2 extra units during count
    adj_pos = adjust_stock(
        conn=db_conn,
        variant_id=v2["id"],
        quantity_change=2,
        reason="AUDIT_FOUND",
        note="Physical audit found extra units"
    )
    assert adj_pos["stock_after"] == 7

    # Negative adjustment: 1 damaged item written off
    adj_neg = adjust_stock(
        conn=db_conn,
        variant_id=v2["id"],
        quantity_change=-1,
        reason="DAMAGED",
        note="Water damage on garment"
    )
    assert adj_neg["stock_after"] == 6

    # Verify ledger contains both adjustments
    ledger = get_inventory_ledger(db_conn, variant_id=v2["id"])
    assert len(ledger) >= 2
    assert ledger[0]["type"] == "DAMAGE"
    assert ledger[0]["quantity_change"] == -1
    assert ledger[0]["stock_after"] == 6
    assert ledger[1]["type"] == "ADJUSTMENT_IN"
    assert ledger[1]["quantity_change"] == 2
    assert ledger[1]["stock_after"] == 7


def test_negative_stock_prevention(db_conn, sample_product_with_variants):
    v2 = sample_product_with_variants["variant_2"]
    current_stock = v2["stock"]  # 5

    # Attempt to reduce stock by more than available (e.g. -10 when only 5 exist)
    with pytest.raises(HTTPException) as exc_info:
        adjust_stock(
            conn=db_conn,
            variant_id=v2["id"],
            quantity_change=-10,
            reason="DEFECTIVE_BATCH"
        )
    assert exc_info.value.status_code == 400
    assert "INSUFFICIENT_STOCK" in exc_info.value.detail

    # Confirm stock was untouched
    inv = get_variant_inventory(db_conn, v2["id"])
    assert inv["stock_quantity"] == current_stock


def test_zero_quantity_stock_in_or_adjustment_rejection(db_conn, sample_product_with_variants):
    v1 = sample_product_with_variants["variant_1"]

    with pytest.raises(HTTPException) as exc_info:
        stock_in(db_conn, variant_id=v1["id"], quantity=0)
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException) as exc_info:
        adjust_stock(db_conn, variant_id=v1["id"], quantity_change=0)
    assert exc_info.value.status_code == 400


def test_inventory_ledger_continuity(db_conn, sample_product_with_variants):
    v1 = sample_product_with_variants["variant_1"]

    # Execute a sequence of operations
    stock_in(db_conn, variant_id=v1["id"], quantity=5)     # 10 -> 15
    adjust_stock(db_conn, variant_id=v1["id"], quantity_change=-3)  # 15 -> 12
    stock_in(db_conn, variant_id=v1["id"], quantity=8)     # 12 -> 20
    adjust_stock(db_conn, variant_id=v1["id"], quantity_change=-5)  # 20 -> 15

    ledger = get_inventory_ledger(db_conn, variant_id=v1["id"])
    # Ledger is returned sorted descending by timestamp/id
    # Reverse to check chronological order
    chronological = list(reversed(ledger))

    for i in range(len(chronological)):
        tx = chronological[i]
        assert tx["stock_after"] == tx["stock_before"] + tx["quantity_change"]
        if i > 0:
            assert tx["stock_before"] == chronological[i - 1]["stock_after"]


def test_reconcile_inventory_fixes_discrepancy(db_conn, sample_product_with_variants):
    prod_id = sample_product_with_variants["product_id"]
    
    # Deliberately desynchronize products.stock_quantity to simulate legacy stock drift
    cursor = db_conn.cursor()
    cursor.execute("UPDATE products SET stock_quantity = 999 WHERE id = ?;", (prod_id,))
    db_conn.commit()

    # Run reconciliation
    res = reconcile_inventory(db_conn)
    assert res["status"] == "RECONCILED"

    # Verify products.stock_quantity is now reconciled to exact sum of variants (10 + 5 = 15)
    cursor.execute("SELECT stock_quantity FROM products WHERE id = ?;", (prod_id,))
    assert cursor.fetchone()[0] == 15
