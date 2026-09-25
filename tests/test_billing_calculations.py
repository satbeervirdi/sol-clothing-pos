"""
Tests for Exact Billing Calculations, Decimal Precision, GST, and Discount Math.
"""
import pytest
from decimal import Decimal
from fastapi import HTTPException
from services.sales_service import calculate_bill_totals


def test_exact_line_total_math():
    items = [
        {"product_name": "Shirt", "quantity": 2, "unit_price": 1299.50, "discount_amount": 100.00},
        {"product_name": "Trousers", "quantity": 1, "unit_price": 2499.00, "discount_amount": 0.00}
    ]
    # Line 1: (2 * 1299.50) - 100 = 2599.00 - 100 = 2499.00
    # Line 2: (1 * 2499.00) = 2499.00
    # Subtotal: 2499.00 + 2499.00 = 4998.00
    result = calculate_bill_totals(items, discount_type="fixed", discount_val=0.0, tax_rate=0.0)

    assert result["subtotal"] == 4998.00
    assert result["items"][0]["line_total"] == 2499.00
    assert result["items"][1]["line_total"] == 2499.00
    assert result["grand_total"] == 4998.00


def test_gst_calculation_precision():
    # Test fractional paise GST calculation
    # Subtotal = 1499.00
    # Taxable amount = 1499.00
    # GST at 5% = 1499 * 0.05 = 74.95
    # Grand Total = 1499 + 74.95 = 1573.95
    items = [{"product_name": "SOL Signature Tee", "quantity": 1, "unit_price": 1499.00}]
    result = calculate_bill_totals(items, discount_type="fixed", discount_val=0.0, tax_rate=5.0)

    assert result["subtotal"] == 1499.00
    assert result["discount_amount"] == 0.0
    assert result["taxable_amount"] == 1499.00
    assert result["tax_rate"] == 5.0
    assert result["tax_amount"] == 74.95
    assert result["grand_total"] == 1573.95


def test_bill_percentage_discount():
    # Cart: 2 items @ 1500 each = 3000.00
    # 10% storewide discount = 300.00
    # Taxable = 2700.00
    # 5% GST = 135.00
    # Grand Total = 2835.00
    items = [
        {"product_name": "Item A", "quantity": 2, "unit_price": 1500.00}
    ]
    result = calculate_bill_totals(items, discount_type="percent", discount_val=10.0, tax_rate=5.0)

    assert result["subtotal"] == 3000.00
    assert result["discount_amount"] == 300.00
    assert result["taxable_amount"] == 2700.00
    assert result["tax_amount"] == 135.00
    assert result["grand_total"] == 2835.00


def test_bill_fixed_discount():
    # Cart: 1 item @ 2500.00
    # Flat ₹500 off coupon
    # Taxable = 2000.00
    # 12% GST = 240.00
    # Grand Total = 2240.00
    items = [{"product_name": "Blazer", "quantity": 1, "unit_price": 2500.00}]
    result = calculate_bill_totals(items, discount_type="fixed", discount_val=500.0, tax_rate=12.0)

    assert result["subtotal"] == 2500.00
    assert result["discount_amount"] == 500.00
    assert result["taxable_amount"] == 2000.00
    assert result["tax_amount"] == 240.00
    assert result["grand_total"] == 2240.00


def test_discount_cannot_exceed_subtotal():
    # Subtotal = 800.00, Fixed discount = 1500.00
    # Max discount allowed = 800.00
    # Taxable = 0.00, Tax = 0.00, Grand Total = 0.00
    items = [{"product_name": "Cap", "quantity": 1, "unit_price": 800.00}]
    result = calculate_bill_totals(items, discount_type="fixed", discount_val=1500.0, tax_rate=5.0)

    assert result["discount_amount"] == 800.00
    assert result["taxable_amount"] == 0.00
    assert result["tax_amount"] == 0.00
    assert result["grand_total"] == 0.00


def test_invalid_billing_inputs():
    # Zero or negative quantity
    with pytest.raises(HTTPException) as exc1:
        calculate_bill_totals([{"product_name": "Shirt", "quantity": 0, "unit_price": 500.0}])
    assert exc1.value.status_code == 400

    # Discount percent > 100%
    with pytest.raises(HTTPException) as exc2:
        calculate_bill_totals(
            [{"product_name": "Shirt", "quantity": 1, "unit_price": 500.0}],
            discount_type="percent",
            discount_val=150.0
        )
    assert exc2.value.status_code == 400

    # Negative discount
    with pytest.raises(HTTPException) as exc3:
        calculate_bill_totals(
            [{"product_name": "Shirt", "quantity": 1, "unit_price": 500.0}],
            discount_type="fixed",
            discount_val=-50.0
        )
    assert exc3.value.status_code == 400


def test_api_calculate_endpoint(client):
    payload = {
        "items": [
            {
                "product_name": "SOL Signature Polo",
                "quantity": 2,
                "unit_price": 1800.0,
                "discount_amount": 0.0
            }
        ],
        "discount_type": "percent",
        "discount_val": 10.0,
        "tax_rate": 5.0
    }
    resp = client.post("/api/sales/calculate", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["subtotal"] == 3600.00
    assert data["discount_amount"] == 360.00
    assert data["taxable_amount"] == 3240.00
    assert data["tax_amount"] == 162.00
    assert data["grand_total"] == 3402.00


def test_mixed_gst_rates_in_single_cart():
    # Item 1: Apparel with 5% GST (MRP/Selling 2000.00)
    # Item 2: Luxury Leather Belt with 18% GST (MRP/Selling 1000.00)
    # Subtotal = 3000.00
    # Store discount: 10% (= 300.00)
    # Item 1 share: 2000 - 200 = 1800 taxable @ 5% GST = 90.00
    # Item 2 share: 1000 - 100 = 900 taxable @ 18% GST = 162.00
    # Total Tax = 252.00
    # Grand Total = (3000 - 300) + 252 = 2952.00
    items = [
        {"product_name": "Silk Shirt", "quantity": 1, "unit_price": 2000.0, "gst_rate": 5.0},
        {"product_name": "Leather Belt", "quantity": 1, "unit_price": 1000.0, "gst_rate": 18.0}
    ]
    result = calculate_bill_totals(items, discount_type="percent", discount_val=10.0)

    assert result["subtotal"] == 3000.00
    assert result["discount_amount"] == 300.00
    assert result["taxable_amount"] == 2700.00
    assert result["tax_amount"] == 252.00
    assert result["grand_total"] == 2952.00
