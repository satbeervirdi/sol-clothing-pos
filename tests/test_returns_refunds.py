"""
Tests for Itemized Returns, Refunds, Inventory Restitution, and Sale Status Transitions.
"""
import pytest
from fastapi import HTTPException
from models import InvoiceCreate, InvoiceItemInput, SaleReturnRequest, SaleReturnItemInput
from services.sales_service import checkout, process_sale_return
from services.inventory_service import get_variant_inventory, get_inventory_ledger


def test_full_return_restores_inventory_and_updates_status(db_conn, sample_product_with_variants, sample_customer):
    v1 = sample_product_with_variants["variant_1"]
    cust_id = sample_customer["id"]
    initial_stock = v1["stock"]  # 10

    # 1. Complete a sale of 2 units of variant 1
    sale_inv = checkout(
        conn=db_conn,
        sale_data=InvoiceCreate(
            customer_id=cust_id,
            customer_name="Arjun Sharma",
            customer_phone="9876543210",
            payment_method="Cash",
            items=[
                InvoiceItemInput(
                    variant_id=v1["id"],
                    sku=v1["sku"],
                    product_name="SOL Heavyweight Oversized Tee",
                    quantity=2,
                    unit_price=1500.0
                )
            ]
        )
    )
    sale_id = sale_inv["id"]

    # Verify inventory was decremented by 2 (10 -> 8)
    inv_after_sale = get_variant_inventory(db_conn, v1["id"])
    assert inv_after_sale["stock_quantity"] == 8

    # Fetch sale item ID
    cursor = db_conn.cursor()
    cursor.execute("SELECT id, quantity FROM sale_items WHERE sale_id = ?;", (sale_id,))
    s_item = cursor.fetchone()
    sale_item_id = s_item["id"]

    # 2. Process complete return of all 2 units
    ret_res = process_sale_return(
        conn=db_conn,
        sale_id=sale_id,
        return_req=SaleReturnRequest(
            items=[
                SaleReturnItemInput(
                    sale_item_id=sale_item_id,
                    quantity=2,
                    restock_inventory=True
                )
            ],
            refund_method="Cash",
            reason="Size mismatch"
        )
    )

    assert ret_res["success"] is True
    assert ret_res["sale_status"] == "REFUNDED"
    assert ret_res["total_refund_amount"] > 0

    # 3. Verify inventory is fully restored to 10
    inv_after_ret = get_variant_inventory(db_conn, v1["id"])
    assert inv_after_ret["stock_quantity"] == 10

    # 4. Verify return ledger transaction was logged
    ledger = get_inventory_ledger(db_conn, variant_id=v1["id"])
    assert ledger[0]["type"] == "RETURN"
    assert ledger[0]["quantity_change"] == 2
    assert ledger[0]["stock_after"] == 10

    # 5. Verify customer total_spent is reconciled
    cursor.execute("SELECT total_spent, total_orders FROM customers WHERE id = ?;", (cust_id,))
    cust_row = cursor.fetchone()
    assert cust_row["total_spent"] == 0.0
    assert cust_row["total_orders"] == 0


def test_partial_return_handles_itemized_quantities(db_conn, sample_product_with_variants, sample_customer):
    v1 = sample_product_with_variants["variant_1"]
    v2 = sample_product_with_variants["variant_2"]
    cust_id = sample_customer["id"]

    # Purchase 2 units of V1 and 1 unit of V2
    sale_inv = checkout(
        conn=db_conn,
        sale_data=InvoiceCreate(
            customer_id=cust_id,
            customer_name="Arjun Sharma",
            customer_phone="9876543210",
            payment_method="UPI",
            items=[
                InvoiceItemInput(
                    variant_id=v1["id"],
                    sku=v1["sku"],
                    product_name="SOL Tee M",
                    quantity=2,
                    unit_price=1500.0
                ),
                InvoiceItemInput(
                    variant_id=v2["id"],
                    sku=v2["sku"],
                    product_name="SOL Tee L",
                    quantity=1,
                    unit_price=1600.0
                )
            ]
        )
    )
    sale_id = sale_inv["id"]

    cursor = db_conn.cursor()
    cursor.execute("SELECT id, variant_id, quantity FROM sale_items WHERE sale_id = ? AND variant_id = ?;", (sale_id, v1["id"]))
    v1_item = cursor.fetchone()

    # Return only 1 of the 2 units of V1
    ret_res = process_sale_return(
        conn=db_conn,
        sale_id=sale_id,
        return_req=SaleReturnRequest(
            items=[
                SaleReturnItemInput(
                    sale_item_id=v1_item["id"],
                    quantity=1,
                    restock_inventory=True
                )
            ],
            refund_method="UPI",
            reason="Customer wanted 1 less"
        )
    )

    assert ret_res["sale_status"] == "PARTIALLY_REFUNDED"
    # Inventory for V1 should have restored 1 unit (10 - 2 + 1 = 9)
    inv_v1 = get_variant_inventory(db_conn, v1["id"])
    assert inv_v1["stock_quantity"] == 9

    # Inventory for V2 should remain unchanged at 4 (5 - 1 = 4)
    inv_v2 = get_variant_inventory(db_conn, v2["id"])
    assert inv_v2["stock_quantity"] == 4


def test_excess_return_rejected(db_conn, sample_product_with_variants):
    v1 = sample_product_with_variants["variant_1"]

    sale_inv = checkout(
        conn=db_conn,
        sale_data=InvoiceCreate(
            customer_name="Walk-in Guest",
            items=[
                InvoiceItemInput(
                    variant_id=v1["id"],
                    sku=v1["sku"],
                    product_name="SOL Tee M",
                    quantity=1,
                    unit_price=1500.0
                )
            ]
        )
    )
    sale_id = sale_inv["id"]

    cursor = db_conn.cursor()
    cursor.execute("SELECT id FROM sale_items WHERE sale_id = ?;", (sale_id,))
    sale_item_id = cursor.fetchone()["id"]

    # Try to return 2 units when only 1 was bought
    with pytest.raises(HTTPException) as exc_info:
        process_sale_return(
            conn=db_conn,
            sale_id=sale_id,
            return_req=SaleReturnRequest(
                items=[SaleReturnItemInput(sale_item_id=sale_item_id, quantity=2)],
                reason="Wrong size"
            )
        )
    assert exc_info.value.status_code == 400
    assert "EXCESS_RETURN_QUANTITY" in exc_info.value.detail


def test_return_without_restock_does_not_increment_inventory(db_conn, sample_product_with_variants):
    v1 = sample_product_with_variants["variant_1"]

    sale_inv = checkout(
        conn=db_conn,
        sale_data=InvoiceCreate(
            items=[
                InvoiceItemInput(
                    variant_id=v1["id"],
                    sku=v1["sku"],
                    product_name="SOL Tee M",
                    quantity=1,
                    unit_price=1500.0
                )
            ]
        )
    )
    sale_id = sale_inv["id"]

    cursor = db_conn.cursor()
    cursor.execute("SELECT id FROM sale_items WHERE sale_id = ?;", (sale_id,))
    sale_item_id = cursor.fetchone()["id"]

    # Return damaged item with restock_inventory=False
    ret_res = process_sale_return(
        conn=db_conn,
        sale_id=sale_id,
        return_req=SaleReturnRequest(
            items=[
                SaleReturnItemInput(
                    sale_item_id=sale_item_id,
                    quantity=1,
                    restock_inventory=False
                )
            ],
            reason="Item torn / scrap"
        )
    )
    assert ret_res["sale_status"] == "REFUNDED"

    # Stock should remain at 9 (NOT incremented back to 10)
    inv = get_variant_inventory(db_conn, v1["id"])
    assert inv["stock_quantity"] == 9


def test_proportional_refund_math_with_tax_and_discount(db_conn, sample_product_with_variants, sample_customer):
    v1 = sample_product_with_variants["variant_1"]
    v2 = sample_product_with_variants["variant_2"]
    cust_id = sample_customer["id"]

    # Purchase 2 units of V1 (₹1500 each) and 1 unit of V2 (₹1600) = Subtotal ₹4600
    # Apply ₹600 discount -> Taxable ₹4000
    # 5% GST = ₹200 -> Grand Total = ₹4200
    # Ratio = 4200 / 4600 = 21/23
    sale_inv = checkout(
        conn=db_conn,
        sale_data=InvoiceCreate(
            customer_id=cust_id,
            discount_type="fixed",
            discount_val=600.0,
            payment_method="UPI",
            items=[
                InvoiceItemInput(
                    variant_id=v1["id"],
                    sku=v1["sku"],
                    product_name="SOL Tee M",
                    quantity=2,
                    unit_price=1500.0
                ),
                InvoiceItemInput(
                    variant_id=v2["id"],
                    sku=v2["sku"],
                    product_name="SOL Tee L",
                    quantity=1,
                    unit_price=1600.0
                )
            ]
        )
    )
    sale_id = sale_inv["id"]
    assert sale_inv["grand_total"] == 4200.0

    cursor = db_conn.cursor()
    cursor.execute("SELECT id, variant_id, quantity, line_total FROM sale_items WHERE sale_id = ? ORDER BY id ASC;", (sale_id,))
    items = cursor.fetchall()
    v1_item = items[0]
    v2_item = items[1]

    # Return 1 unit of V1 (out of 2):
    # Proportional price: line_total=3000, 1 unit line_share=1500.
    # 1500 * (4200 / 4600) = 1369.5652... rounded = 1369.57
    ret1 = process_sale_return(
        conn=db_conn,
        sale_id=sale_id,
        return_req=SaleReturnRequest(
            items=[SaleReturnItemInput(sale_item_id=v1_item["id"], quantity=1, restock_inventory=True)],
            reason="Partial return 1"
        )
    )
    assert ret1["sale_status"] == "PARTIALLY_REFUNDED"
    assert ret1["total_refund_amount"] == 1369.57

    # Verify customer net spend is retained: 4200 - 1369.57 = 2830.43 and order count is 1
    cursor.execute("SELECT total_spent, total_orders FROM customers WHERE id = ?;", (cust_id,))
    c_row = cursor.fetchone()
    assert c_row["total_orders"] == 1
    assert c_row["total_spent"] == 2830.43

    # Now return the remaining items (1 unit of V1 and 1 unit of V2)
    # The final return must reconcile penny-perfect to 4200 - 1369.57 = 2830.43!
    ret2 = process_sale_return(
        conn=db_conn,
        sale_id=sale_id,
        return_req=SaleReturnRequest(
            items=[
                SaleReturnItemInput(sale_item_id=v1_item["id"], quantity=1, restock_inventory=True),
                SaleReturnItemInput(sale_item_id=v2_item["id"], quantity=1, restock_inventory=True)
            ],
            reason="Final complete return"
        )
    )
    assert ret2["sale_status"] == "REFUNDED"
    assert ret2["total_refund_amount"] == 2830.43

    # Total refunds sum to exactly 1369.57 + 2830.43 = 4200.00 (penny-perfect!)
    cursor.execute("SELECT SUM(total_refund_amount) FROM sale_returns WHERE sale_id = ?;", (sale_id,))
    total_refunded = cursor.fetchone()[0]
    assert round(total_refunded, 2) == 4200.00

    # Customer spend is now cleanly 0.00 and order count is 0
    cursor.execute("SELECT total_spent, total_orders FROM customers WHERE id = ?;", (cust_id,))
    c_final = cursor.fetchone()
    assert c_final["total_spent"] == 0.00
    assert c_final["total_orders"] == 0
