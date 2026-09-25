"""
Authoritative Reporting & Analytics Service for SOL POS & CRM.
Enforces:
- 100% database-derived analytics (Section 17)
- Zero hardcoded numbers or random values
- Best sellers computed strictly from completed sale_items (Section 16)
- Clear distinction between Retail Value and Cost Value (Section 18)
- Real customer spending & revenue calculations
"""
import sqlite3
from datetime import datetime
from typing import Dict, Any, List


def get_analytics_dashboard(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Computes real-time executive dashboard KPIs from authoritative database records.
    Accounts for COMPLETED and PARTIALLY_REFUNDED sales with net refunds subtracted.
    """
    cursor = conn.cursor()
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 1. Total Completed & Partially Refunded Sales Stats (Net Revenue)
    cursor.execute("""
    SELECT 
        COUNT(*) AS total_orders,
        COALESCE(SUM(
            grand_total - COALESCE((SELECT SUM(sr.total_refund_amount) FROM sale_returns sr WHERE sr.sale_id = sales.id), 0.0)
        ), 0.0) AS total_revenue
    FROM sales
    WHERE sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED');
    """)
    sales_stats = cursor.fetchone()

    # 2. Today's Net Sales
    cursor.execute("""
    SELECT 
        COUNT(*) AS today_orders,
        COALESCE(SUM(
            grand_total - COALESCE((SELECT SUM(sr.total_refund_amount) FROM sale_returns sr WHERE sr.sale_id = sales.id), 0.0)
        ), 0.0) AS today_revenue
    FROM sales
    WHERE sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED') AND created_at LIKE ?;
    """, (f"{today_str}%",))
    today_stats = cursor.fetchone()

    # 3. Authoritative Inventory Valuation (Section 18)
    cursor.execute("""
    SELECT 
        COUNT(DISTINCT p.id) AS total_products,
        COALESCE(SUM(inv.stock_quantity), 0) AS total_stock_units,
        COALESCE(SUM(inv.stock_quantity * pv.cost_price), 0.0) AS inventory_cost_val,
        COALESCE(SUM(inv.stock_quantity * pv.selling_price), 0.0) AS inventory_retail_val,
        COALESCE(SUM(CASE WHEN inv.stock_quantity <= inv.low_stock_threshold THEN 1 ELSE 0 END), 0) AS low_stock_count
    FROM inventory inv
    JOIN product_variants pv ON inv.variant_id = pv.id
    JOIN products p ON pv.product_id = p.id;
    """)
    inv_stats = cursor.fetchone()

    # 4. Total Customers Count
    cursor.execute("SELECT COUNT(*) FROM customers;")
    total_customers = cursor.fetchone()[0]

    # 5. Real Gross Profit from Net Completed / Partially Refunded Sales
    cursor.execute("""
    SELECT 
        COALESCE(SUM((si.quantity - si.returned_quantity) * (si.line_total / si.quantity)), 0.0) AS total_revenue,
        COALESCE(SUM((si.quantity - si.returned_quantity) * si.cost_price), 0.0) AS total_cogs
    FROM sale_items si
    JOIN sales s ON si.sale_id = s.id
    WHERE s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED') AND (si.quantity - si.returned_quantity) > 0;
    """)
    margin_row = cursor.fetchone()
    gross_profit = max(0.0, margin_row["total_revenue"] - margin_row["total_cogs"])

    # 6. Best-Selling Products (Section 16: Computed strictly from net sold units)
    cursor.execute("""
    SELECT 
        si.product_name,
        si.sku,
        si.size,
        si.color,
        p.category,
        COALESCE(inv.stock_quantity, 0) AS current_stock,
        pv.selling_price AS current_price,
        SUM(si.quantity - si.returned_quantity) AS units_sold,
        ROUND(SUM((si.quantity - si.returned_quantity) * (si.line_total / si.quantity)), 2) AS total_revenue_generated
    FROM sale_items si
    JOIN sales s ON si.sale_id = s.id
    LEFT JOIN product_variants pv ON si.variant_id = pv.id
    LEFT JOIN products p ON pv.product_id = p.id
    LEFT JOIN inventory inv ON inv.variant_id = pv.id
    WHERE s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED')
    GROUP BY si.product_name, si.sku, si.size, si.color
    HAVING units_sold > 0
    ORDER BY units_sold DESC, total_revenue_generated DESC
    LIMIT 10;
    """)
    best_sellers = [dict(b) for b in cursor.fetchall()]

    # 7. Category Share from Real Sales
    cursor.execute("""
    SELECT 
        COALESCE(p.category, 'General') AS category,
        SUM(si.quantity - si.returned_quantity) AS total_units,
        ROUND(SUM((si.quantity - si.returned_quantity) * (si.line_total / si.quantity)), 2) AS total_sales
    FROM sale_items si
    JOIN sales s ON si.sale_id = s.id
    LEFT JOIN product_variants pv ON si.variant_id = pv.id
    LEFT JOIN products p ON (si.product_id = p.id OR pv.product_id = p.id)
    WHERE s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED')
    GROUP BY p.category
    HAVING total_units > 0
    ORDER BY total_sales DESC;
    """)
    category_breakdown = [dict(c) for c in cursor.fetchall()]

    # 8. Low Stock Alerts
    cursor.execute("""
    SELECT 
        pv.id,
        p.name,
        pv.sku,
        p.category,
        pv.size,
        pv.color,
        inv.stock_quantity,
        inv.low_stock_threshold,
        pv.cost_price,
        pv.selling_price
    FROM inventory inv
    JOIN product_variants pv ON inv.variant_id = pv.id
    JOIN products p ON pv.product_id = p.id
    WHERE inv.stock_quantity <= inv.low_stock_threshold
    ORDER BY inv.stock_quantity ASC
    LIMIT 10;
    """)
    low_stock_alerts = [dict(l) for l in cursor.fetchall()]

    # 9. Top VIP Customers (Strictly from real net completed sales)
    cursor.execute("""
    SELECT 
        c.id,
        c.name,
        c.phone,
        c.tier,
        COALESCE((SELECT ROUND(SUM(
            s.grand_total - COALESCE((SELECT SUM(sr.total_refund_amount) FROM sale_returns sr WHERE sr.sale_id = s.id), 0.0)
        ), 2) FROM sales s WHERE s.customer_id = c.id AND s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED')), 0.0) AS total_spent,
        COALESCE((SELECT COUNT(*) FROM sales s WHERE s.customer_id = c.id AND s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED')), 0) AS total_orders,
        c.loyalty_points,
        c.last_visit
    FROM customers c
    ORDER BY total_spent DESC
    LIMIT 5;
    """)
    top_customers = [dict(tc) for tc in cursor.fetchall()]

    return {
        "kpi": {
            "total_revenue": round(sales_stats["total_revenue"], 2),
            "total_orders": sales_stats["total_orders"],
            "today_revenue": round(today_stats["today_revenue"], 2),
            "today_orders": today_stats["today_orders"],
            "total_stock_units": inv_stats["total_stock_units"],
            "total_products": inv_stats["total_products"],
            "inventory_cost_val": round(inv_stats["inventory_cost_val"], 2),
            "inventory_retail_val": round(inv_stats["inventory_retail_val"], 2),
            "low_stock_count": inv_stats["low_stock_count"],
            "total_customers": total_customers,
            "gross_profit": round(gross_profit, 2)
        },
        "best_selling_products": best_sellers,
        "category_breakdown": category_breakdown,
        "low_stock_alerts": low_stock_alerts,
        "top_customers": top_customers
    }


def get_sold_products_breakdown(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Returns breakdown of sold garments, today's metrics, and recent sales invoices.
    Accounts for COMPLETED and PARTIALLY_REFUNDED sales.
    """
    cursor = conn.cursor()
    today_str = datetime.now().strftime("%Y-%m-%d")

    cursor.execute("""
    SELECT 
        COALESCE(SUM(si.quantity - si.returned_quantity), 0) AS total_units_sold,
        COALESCE(SUM((si.quantity - si.returned_quantity) * (si.line_total / si.quantity)), 0.0) AS total_revenue
    FROM sale_items si
    JOIN sales s ON si.sale_id = s.id
    WHERE s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED');
    """)
    totals = cursor.fetchone()

    cursor.execute("""
    SELECT 
        COALESCE(SUM(si.quantity - si.returned_quantity), 0) AS today_units_sold,
        COALESCE(SUM((si.quantity - si.returned_quantity) * (si.line_total / si.quantity)), 0.0) AS today_revenue
    FROM sale_items si
    JOIN sales s ON si.sale_id = s.id
    WHERE s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED') AND s.created_at LIKE ?;
    """, (f"{today_str}%",))
    today_totals = cursor.fetchone()

    cursor.execute("""
    SELECT 
        si.product_name,
        si.sku,
        si.size,
        si.color,
        si.unit_price,
        SUM(si.quantity - si.returned_quantity) AS units_sold,
        ROUND(SUM((si.quantity - si.returned_quantity) * (si.line_total / si.quantity)), 2) AS total_revenue,
        MAX(s.created_at) AS last_sold_at,
        COALESCE(inv.stock_quantity, 0) AS current_stock,
        p.category,
        COALESCE(NULLIF(pv.image_url, ''), p.image_url, '') AS image_url
    FROM sale_items si
    JOIN sales s ON si.sale_id = s.id
    LEFT JOIN product_variants pv ON si.variant_id = pv.id
    LEFT JOIN inventory inv ON inv.variant_id = pv.id
    LEFT JOIN products p ON (si.product_id = p.id OR pv.product_id = p.id)
    WHERE s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED')
    GROUP BY si.product_name, si.sku, si.size, si.color
    HAVING units_sold > 0
    ORDER BY units_sold DESC, total_revenue DESC;
    """)
    sold_items = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
    SELECT 
        s.id, s.invoice_number, s.customer_name, s.customer_phone, 
        s.grand_total, s.payment_method, s.payment_status, s.sale_status, s.created_at,
        COUNT(si.id) as item_count,
        COALESCE(SUM(si.quantity - si.returned_quantity), 0) as total_units
    FROM sales s
    LEFT JOIN sale_items si ON s.id = si.sale_id
    GROUP BY s.id
    ORDER BY s.created_at DESC
    LIMIT 50;
    """)
    recent_sales = [dict(r) for r in cursor.fetchall()]

    return {
        "today_units_sold": today_totals["today_units_sold"] if today_totals else 0,
        "today_revenue": round(today_totals["today_revenue"], 2) if today_totals else 0.0,
        "total_units_sold": totals["total_units_sold"] if totals else 0,
        "total_revenue": round(totals["total_revenue"], 2) if totals else 0.0,
        "sold_products": sold_items,
        "recent_sales": recent_sales
    }
