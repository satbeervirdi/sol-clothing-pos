"""
Authoritative Customer CRM Service for SOL POS & CRM.
Enforces:
- All customer metrics (Total Orders, Total Spent, Last Visit) are derived strictly from completed sales
- Zero fake/demo/unsupported loyalty numbers
- Clean tier evaluation and CRM search
"""
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import HTTPException

from models import CustomerCreate, CustomerUpdate
from services.audit_service import log_audit


def calculate_tier(total_spent: float) -> str:
    """Calculates customer loyalty tier deterministically based on real completed spending."""
    if total_spent >= 30000.0:
        return "Platinum"
    elif total_spent >= 15000.0:
        return "Gold"
    elif total_spent >= 5000.0:
        return "Silver"
    return "Bronze"


def get_tier_discount(tier: str) -> float:
    """Standard tier discount policy."""
    discounts = {
        "Platinum": 15.0,
        "Gold": 10.0,
        "Silver": 5.0,
        "Bronze": 0.0
    }
    return discounts.get(tier, 0.0)


def list_customers(conn: sqlite3.Connection, search: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Lists customers with metrics derived directly from real completed sales records (Section 15).
    """
    cursor = conn.cursor()
    query = """
    SELECT 
        c.id,
        c.name,
        c.phone,
        c.email,
        c.city,
        c.notes,
        c.loyalty_points,
        c.created_at,
        COALESCE((SELECT COUNT(*) FROM sales s WHERE s.customer_id = c.id AND s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED')), 0) AS total_orders,
        COALESCE((SELECT ROUND(SUM(
            s.grand_total - COALESCE((SELECT SUM(sr.total_refund_amount) FROM sale_returns sr WHERE sr.sale_id = s.id), 0.0)
        ), 2) FROM sales s WHERE s.customer_id = c.id AND s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED')), 0.0) AS total_spent,
        COALESCE((SELECT MAX(s.created_at) FROM sales s WHERE s.customer_id = c.id AND s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED')), c.last_visit) AS last_visit
    FROM customers c
    WHERE 1=1
    """
    params = []

    if search:
        s = f"%{search.strip()}%"
        query += " AND (c.name LIKE ? OR c.phone LIKE ? OR c.email LIKE ? OR c.city LIKE ?)"
        params.extend([s, s, s, s])

    query += " ORDER BY total_spent DESC, last_visit DESC"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]

    for r in rows:
        r["tier"] = calculate_tier(r["total_spent"])
        r["suggested_discount"] = get_tier_discount(r["tier"])

    return rows


def search_customers(conn: sqlite3.Connection, term: str) -> List[Dict[str, Any]]:
    """
    Rapid customer lookup for billing POS screen.
    """
    cursor = conn.cursor()
    clean_term = term.strip()
    s = f"%{clean_term}%"

    cursor.execute("""
    SELECT 
        c.id,
        c.name,
        c.phone,
        c.email,
        c.city,
        c.loyalty_points,
        COALESCE((SELECT COUNT(*) FROM sales s WHERE s.customer_id = c.id AND s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED')), 0) AS total_orders,
        COALESCE((SELECT ROUND(SUM(
            s.grand_total - COALESCE((SELECT SUM(sr.total_refund_amount) FROM sale_returns sr WHERE sr.sale_id = s.id), 0.0)
        ), 2) FROM sales s WHERE s.customer_id = c.id AND s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED')), 0.0) AS total_spent,
        COALESCE((SELECT MAX(s.created_at) FROM sales s WHERE s.customer_id = c.id AND s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED')), c.last_visit) AS last_visit
    FROM customers c
    WHERE c.phone LIKE ? OR c.name LIKE ? OR c.email LIKE ?
    ORDER BY (c.phone = ?) DESC, total_spent DESC
    LIMIT 10
    """, (s, s, s, clean_term))

    rows = [dict(r) for r in cursor.fetchall()]
    for r in rows:
        r["tier"] = calculate_tier(r["total_spent"])
        r["suggested_discount"] = get_tier_discount(r["tier"])

    return rows


def get_customer(conn: sqlite3.Connection, customer_id: int) -> Dict[str, Any]:
    """
    Retrieves full customer CRM profile with authenticated purchase history.
    """
    cursor = conn.cursor()
    cursor.execute("""
    SELECT 
        c.id,
        c.name,
        c.phone,
        c.email,
        c.city,
        c.notes,
        c.loyalty_points,
        c.created_at,
        COALESCE((SELECT COUNT(*) FROM sales s WHERE s.customer_id = c.id AND s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED')), 0) AS total_orders,
        COALESCE((SELECT ROUND(SUM(
            s.grand_total - COALESCE((SELECT SUM(sr.total_refund_amount) FROM sale_returns sr WHERE sr.sale_id = s.id), 0.0)
        ), 2) FROM sales s WHERE s.customer_id = c.id AND s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED')), 0.0) AS total_spent,
        COALESCE((SELECT MAX(s.created_at) FROM sales s WHERE s.customer_id = c.id AND s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED')), c.last_visit) AS last_visit
    FROM customers c
    WHERE c.id = ?
    """, (customer_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="CUSTOMER_NOT_FOUND: Customer not found.")

    cust = dict(row)
    cust["tier"] = calculate_tier(cust["total_spent"])
    cust["suggested_discount"] = get_tier_discount(cust["tier"])

    # Load purchase history from completed sales
    cursor.execute("""
    SELECT id, invoice_number, grand_total, payment_method, sale_status, created_at 
    FROM sales 
    WHERE customer_id = ? 
    ORDER BY created_at DESC
    """, (customer_id,))
    sales = [dict(s) for s in cursor.fetchall()]

    for s in sales:
        cursor.execute("""
        SELECT product_name, size, color, quantity, unit_price, line_total 
        FROM sale_items 
        WHERE sale_id = ?
        """, (s["id"],))
        s["items"] = [dict(it) for it in cursor.fetchall()]

    cust["purchase_history"] = sales
    return cust


def create_customer(conn: sqlite3.Connection, c: CustomerCreate, user_id: int = 1) -> Dict[str, Any]:
    """Creates a new customer with verified unique phone and initialized metrics."""
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    clean_phone = c.phone.strip()

    cursor.execute("SELECT id FROM customers WHERE phone = ?;", (clean_phone,))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail=f"DUPLICATE_PHONE: Customer with phone '{clean_phone}' already exists.")

    cursor.execute("""
    INSERT INTO customers (
        name, phone, email, city, notes, loyalty_points, tier, total_spent, total_orders, last_visit, created_at
    )
    VALUES (?, ?, ?, ?, ?, 0, 'Bronze', 0.0, 0, ?, ?);
    """, (
        c.name.strip(),
        clean_phone,
        c.email.strip() if c.email else "",
        c.city.strip() if c.city else "",
        c.notes.strip() if c.notes else "",
        now,
        now
    ))
    cid = cursor.lastrowid
    log_audit(conn, "CUSTOMER", cid, "CREATE", None, {"name": c.name, "phone": clean_phone}, "Customer registered", user_id)

    return get_customer(conn, cid)


def update_customer(conn: sqlite3.Connection, customer_id: int, c: CustomerUpdate, user_id: int = 1) -> Dict[str, Any]:
    """Updates customer demographic or contact details."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers WHERE id = ?;", (customer_id,))
    existing = cursor.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="CUSTOMER_NOT_FOUND: Customer not found.")

    updates = []
    params = []
    fields = [("name", c.name), ("phone", c.phone), ("email", c.email), ("city", c.city), ("notes", c.notes)]
    for col, val in fields:
        if val is not None:
            updates.append(f"{col} = ?")
            params.append(val.strip() if isinstance(val, str) else val)

    if updates:
        params.append(customer_id)
        cursor.execute(f"UPDATE customers SET {', '.join(updates)} WHERE id = ?;", params)
        log_audit(conn, "CUSTOMER", customer_id, "UPDATE", dict(existing), c.model_dump(exclude_unset=True), "Customer details updated", user_id)

    return get_customer(conn, customer_id)
