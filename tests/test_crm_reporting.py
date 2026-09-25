"""
Tests for Customer CRM Metrics Reconciliation and 100% Database-Derived Reporting.
"""
import pytest
from services.customers_service import create_customer, search_customers, get_customer
from services.sales_service import checkout, cancel_sale
from services.reporting_service import get_analytics_dashboard
from models import CustomerCreate, InvoiceCreate, InvoiceItemInput


def test_customer_creation_and_search(db_conn):
    cust = create_customer(db_conn, CustomerCreate(
        name="Vikramaditya Rao",
        phone="9820011223",
        email="vikram@sol.luxury",
        city="Bengaluru"
    ))
    assert cust["id"] is not None
    assert cust["total_spent"] == 0.0
    assert cust["total_orders"] == 0

    # Search by partial phone
    results = search_customers(db_conn, "98200")
    assert len(results) >= 1
    assert results[0]["id"] == cust["id"]

    # Search by partial name
    results_name = search_customers(db_conn, "Vikram")
    assert len(results_name) >= 1
    assert results_name[0]["id"] == cust["id"]


def test_customer_spend_derived_strictly_from_completed_sales(db_conn, sample_product_with_variants, sample_customer):
    v1 = sample_product_with_variants["variant_1"]
    v2 = sample_product_with_variants["variant_2"]
    cust_id = sample_customer["id"]

    # Customer initially has 0 orders and 0 spent
    c_initial = get_customer(db_conn, cust_id)
    assert c_initial["total_spent"] == 0.0
    assert c_initial["total_orders"] == 0

    # Sale 1: Buy 1 unit of V1 (₹1500 + 5% tax = ₹1575)
    sale_1 = checkout(
        conn=db_conn,
        sale_data=InvoiceCreate(
            customer_id=cust_id,
            payment_method="Cash",
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

    c_after_s1 = get_customer(db_conn, cust_id)
    assert c_after_s1["total_orders"] == 1
    assert c_after_s1["total_spent"] == sale_1["grand_total"]

    # Sale 2: Buy 1 unit of V2 (₹1600 + 5% tax = ₹1680)
    sale_2 = checkout(
        conn=db_conn,
        sale_data=InvoiceCreate(
            customer_id=cust_id,
            payment_method="Card",
            items=[
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

    c_after_s2 = get_customer(db_conn, cust_id)
    assert c_after_s2["total_orders"] == 2
    assert c_after_s2["total_spent"] == round(sale_1["grand_total"] + sale_2["grand_total"], 2)

    # Cancel Sale 2
    cancel_sale(
        conn=db_conn,
        sale_id=sale_2["id"],
        reason="Customer changed mind at counter"
    )

    # Metrics should automatically roll back to reflect ONLY remaining completed sale 1
    c_after_cancel = get_customer(db_conn, cust_id)
    assert c_after_cancel["total_orders"] == 1
    assert c_after_cancel["total_spent"] == sale_1["grand_total"]


def test_reporting_dashboard_100_percent_derived(db_conn, sample_product_with_variants):
    v1 = sample_product_with_variants["variant_1"]

    # Checkout 3 units of V1
    sale = checkout(
        conn=db_conn,
        sale_data=InvoiceCreate(
            customer_name="Retail Buyer",
            items=[
                InvoiceItemInput(
                    variant_id=v1["id"],
                    sku=v1["sku"],
                    product_name="SOL Heavyweight Oversized Tee",
                    quantity=3,
                    unit_price=1500.0
                )
            ]
        )
    )

    report = get_analytics_dashboard(db_conn)
    kpis = report["kpi"]

    # 1. Total revenue & orders
    assert kpis["total_orders"] >= 1
    assert kpis["total_revenue"] >= sale["grand_total"]

    # 2. Inventory valuation
    # Remaining V1 stock = 10 - 3 = 7 units @ 1500 selling / 600 cost
    # Remaining V2 stock = 5 units @ 1600 selling / 650 cost
    # Expected retail val = (7 * 1500) + (5 * 1600) = 10500 + 8000 = 18500
    # Expected cost val = (7 * 600) + (5 * 650) = 4200 + 3250 = 7450
    assert kpis["inventory_retail_val"] == 18500.0
    assert kpis["inventory_cost_val"] == 7450.0

    # 3. Best selling products
    best_sellers = report["best_selling_products"]
    assert len(best_sellers) >= 1
    top_item = best_sellers[0]
    assert top_item["sku"] == v1["sku"]
    assert top_item["units_sold"] == 3
    assert top_item["total_revenue_generated"] == 4500.00


def test_dashboard_and_crm_after_partial_return(db_conn, sample_product_with_variants, sample_customer):
    from services.sales_service import process_sale_return
    from services.reporting_service import get_sold_products_breakdown
    from models import SaleReturnRequest, SaleReturnItemInput

    v1 = sample_product_with_variants["variant_1"]
    cust_id = sample_customer["id"]

    # Sell 2 units of V1 to customer
    sale = checkout(
        conn=db_conn,
        sale_data=InvoiceCreate(
            customer_id=cust_id,
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
    sale_id = sale["id"]

    # Fetch sale item id
    cursor = db_conn.cursor()
    cursor.execute("SELECT id FROM sale_items WHERE sale_id = ?;", (sale_id,))
    item_id = cursor.fetchone()["id"]

    # Dashboard before return
    d_before = get_analytics_dashboard(db_conn)
    initial_orders = d_before["kpi"]["total_orders"]
    initial_revenue = d_before["kpi"]["total_revenue"]

    # Return 1 of the 2 units
    ret = process_sale_return(
        conn=db_conn,
        sale_id=sale_id,
        return_req=SaleReturnRequest(
            items=[SaleReturnItemInput(sale_item_id=item_id, quantity=1, restock_inventory=True)],
            reason="Size mismatch"
        )
    )
    refund_amount = ret["total_refund_amount"]
    assert ret["sale_status"] == "PARTIALLY_REFUNDED"

    # Dashboard after return
    d_after = get_analytics_dashboard(db_conn)
    kpis = d_after["kpi"]

    # Order count MUST NOT drop to 0!
    assert kpis["total_orders"] == initial_orders
    # Revenue must decrease exactly by the refunded amount
    assert round(kpis["total_revenue"], 2) == round(initial_revenue - refund_amount, 2)

    # Best-seller units sold must be net: 2 - 1 = 1 unit
    best_sellers = {b["sku"]: b for b in d_after["best_selling_products"]}
    assert best_sellers[v1["sku"]]["units_sold"] == 1

    # Customer profile must retain the 1 active order and net spend
    cust = get_customer(db_conn, cust_id)
    assert cust["total_orders"] == 1
    assert cust["total_spent"] == round(sale["grand_total"] - refund_amount, 2)

    # Sold products breakdown must also show net sold units
    breakdown = get_sold_products_breakdown(db_conn)
    sold_dict = {p["sku"]: p for p in breakdown["sold_products"]}
    assert sold_dict[v1["sku"]]["units_sold"] == 1
