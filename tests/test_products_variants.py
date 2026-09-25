"""
Tests for Product & Variant Management and Stock Triggers.
"""
import pytest
from fastapi import HTTPException
from services.products_service import (
    create_product,
    list_products,
    lookup_by_code,
    update_product,
    delete_product
)
from services.inventory_service import stock_in
from models import ProductCreate, VariantCreate, StockInRequest


def test_create_product_with_default_variant(db_conn):
    prod_in = ProductCreate(
        name="Classic Crewneck Sweatshirt",
        sku="SOL-CREW-01",
        barcode="8901111222333",
        category="Sweatshirts",
        size="L",
        color="Heather Grey",
        brand="SOL",
        selling_price=2499.0,
        cost_price=950.0,
        stock_quantity=0,
        low_stock_threshold=4
    )
    prod = create_product(db_conn, prod_in)
    assert prod["product_id"] is not None
    assert prod["name"] == "Classic Crewneck Sweatshirt"
    assert prod["stock_quantity"] == 0

    # Verify variant was created
    cursor = db_conn.cursor()
    cursor.execute("SELECT * FROM product_variants WHERE product_id = ?;", (prod["product_id"],))
    variants = cursor.fetchall()
    assert len(variants) == 1
    assert variants[0]["sku"] == "SOL-CREW-01"

    # Verify inventory record was created
    cursor.execute("SELECT * FROM inventory WHERE variant_id = ?;", (variants[0]["id"],))
    inv = cursor.fetchone()
    assert inv is not None
    assert inv["stock_quantity"] == 0


def test_create_product_with_multiple_variants(db_conn):
    from services.products_service import create_variant
    from models import VariantCreate

    prod_in = ProductCreate(
        name="SOL Tailored Linen Trousers",
        sku="SOL-TRSR-LIN-30",
        category="Trousers",
        size="30",
        color="Sand",
        selling_price=3200.0,
        cost_price=1200.0
    )
    prod = create_product(db_conn, prod_in)
    product_id = prod["product_id"]
    assert product_id is not None

    create_variant(db_conn, VariantCreate(
        product_id=product_id,
        sku="SOL-TRSR-LIN-32",
        size="32",
        color="Sand",
        selling_price=3200.0,
        cost_price=1200.0
    ))
    create_variant(db_conn, VariantCreate(
        product_id=product_id,
        sku="SOL-TRSR-LIN-34",
        size="34",
        color="Sand",
        selling_price=3200.0,
        cost_price=1200.0
    ))

    cursor = db_conn.cursor()
    cursor.execute("SELECT * FROM product_variants WHERE product_id = ? ORDER BY size ASC;", (product_id,))
    variants = cursor.fetchall()
    assert len(variants) == 3
    assert [v["size"] for v in variants] == ["30", "32", "34"]

    # Each variant must have an inventory row
    for v in variants:
        cursor.execute("SELECT * FROM inventory WHERE variant_id = ?;", (v["id"],))
        assert cursor.fetchone() is not None


def test_get_by_barcode_or_sku(db_conn, sample_product_with_variants):
    v1 = sample_product_with_variants["variant_1"]

    # Lookup by variant SKU
    item = lookup_by_code(db_conn, v1["sku"])
    assert item is not None
    assert item["variant_id"] == v1["id"]
    assert item["stock_quantity"] == 10

    # Lookup by barcode
    item_bc = lookup_by_code(db_conn, "8901234567891")
    assert item_bc is not None
    assert item_bc["variant_id"] == v1["id"]


def test_duplicate_sku_rejection(db_conn, sample_product_with_variants):
    v1 = sample_product_with_variants["variant_1"]
    
    # Attempt to create product with existing SKU
    dup_prod = ProductCreate(
        name="Duplicate Style",
        sku=v1["sku"],
        category="T-Shirts",
        selling_price=1000.0
    )
    with pytest.raises(HTTPException) as exc_info:
        create_product(db_conn, dup_prod)
    assert exc_info.value.status_code == 400
    assert "already exists" in exc_info.value.detail


def test_stock_trigger_synchronization(db_conn, sample_product_with_variants):
    prod_id = sample_product_with_variants["product_id"]
    v1 = sample_product_with_variants["variant_1"]
    v2 = sample_product_with_variants["variant_2"]

    # Total initial stock should be 10 + 5 = 15
    cursor = db_conn.cursor()
    cursor.execute("SELECT stock_quantity FROM products WHERE id = ?;", (prod_id,))
    assert cursor.fetchone()[0] == 15

    # Stock-in 10 more to variant 2
    stock_in(
        conn=db_conn,
        variant_id=v2["id"],
        quantity=10,
        unit_cost=650.0,
        reason="Restock pass"
    )

    # Trigger should have updated parent product stock_quantity to 10 + 15 = 25
    cursor.execute("SELECT stock_quantity FROM products WHERE id = ?;", (prod_id,))
    assert cursor.fetchone()[0] == 25


def test_variant_update_and_delete_isolation(db_conn):
    from services.products_service import get_variant, update_variant, delete_variant
    from models import VariantUpdate

    # Create Product 1 (has variant 1)
    p1 = create_product(db_conn, ProductCreate(
        name="SOL Linen Shirt",
        sku="SOL-LIN-01",
        category="Shirts",
        size="M",
        color="White",
        selling_price=1999.0
    ))

    # Create Product 2 (has variant 2)
    p2 = create_product(db_conn, ProductCreate(
        name="SOL Cotton Chinos",
        sku="SOL-CHIN-01",
        category="Trousers",
        size="32",
        color="Khaki",
        selling_price=2499.0
    ))

    v1_id = p1["variant_id"]
    v2_id = p2["variant_id"]
    prod1_id = p1["product_id"]
    prod2_id = p2["product_id"]

    # Verify that updating variant 2 does NOT alter product 1 or variant 1
    updated_v2 = update_variant(db_conn, v2_id, VariantUpdate(
        selling_price=2799.0,
        color="Dark Khaki"
    ))
    assert updated_v2["selling_price"] == 2799.0
    assert updated_v2["color"] == "Dark Khaki"

    # Variant 1 and Product 1 remain unchanged
    v1_check = get_variant(db_conn, v1_id)
    assert v1_check["selling_price"] == 1999.0
    assert v1_check["color"] == "White"

    # Delete variant 2
    del_res = delete_variant(db_conn, v2_id)
    assert del_res["success"] is True

    # Variant 2 is gone
    with pytest.raises(HTTPException) as exc:
        get_variant(db_conn, v2_id)
    assert exc.value.status_code == 404

    # Product 1 and Variant 1 are still completely intact
    v1_intact = get_variant(db_conn, v1_id)
    assert v1_intact["name"] == "SOL Linen Shirt"


def test_empty_or_whitespace_barcode_falls_back_to_sku(db_conn):
    p = create_product(db_conn, ProductCreate(
        name="SOL Silk Scarf",
        sku="SOL-SCARF-01",
        barcode="   ",  # whitespace only
        category="Accessories",
        size="Free Size",
        color="Red",
        selling_price=999.0
    ))
    assert p["barcode"] == "SOL-SCARF-01"

    # Creating another with barcode="" also succeeds without duplicate barcode error
    p2 = create_product(db_conn, ProductCreate(
        name="SOL Wool Scarf",
        sku="SOL-SCARF-02",
        barcode="",  # empty string
        category="Accessories",
        size="Free Size",
        color="Blue",
        selling_price=1199.0
    ))
    assert p2["barcode"] == "SOL-SCARF-02"


def test_delete_variant_blocked_if_historical_sales(db_conn, sample_product_with_variants):
    from services.sales_service import checkout
    from services.products_service import delete_variant
    from models import InvoiceCreate, InvoiceItemInput

    v1 = sample_product_with_variants["variant_1"]

    # Sell 1 unit of variant 1
    checkout(
        conn=db_conn,
        sale_data=InvoiceCreate(
            customer_name="Historical Customer",
            items=[
                InvoiceItemInput(
                    variant_id=v1["id"],
                    sku=v1["sku"],
                    product_name="SOL Tee",
                    quantity=1,
                    unit_price=1500.0
                )
            ]
        )
    )

    # Deleting variant 1 must be strictly blocked
    with pytest.raises(HTTPException) as exc:
        delete_variant(db_conn, v1["id"])
    assert exc.value.status_code == 400
    assert "CANNOT_DELETE_VARIANT" in exc.value.detail
