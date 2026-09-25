"""
Authoritative Inventory Service for SOL POS & CRM.
Guarantees mathematical determinism, concurrency safety, non-negative inventory,
and immutable ledger tracking for every stock movement.
"""
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any, List
from fastapi import HTTPException
from services.audit_service import log_audit


def get_variant_inventory(conn: sqlite3.Connection, variant_id: int) -> Optional[Dict[str, Any]]:
    """
    Retrieves current stock and threshold for a given product variant from the authoritative inventory table.
    """
    cursor = conn.cursor()
    cursor.execute("""
    SELECT 
        inv.id AS inventory_id,
        inv.variant_id,
        inv.stock_quantity,
        inv.low_stock_threshold,
        inv.updated_at,
        pv.sku,
        pv.barcode,
        pv.size,
        pv.color,
        pv.selling_price,
        pv.cost_price,
        p.id AS product_id,
        p.name AS product_name,
        p.category
    FROM inventory inv
    JOIN product_variants pv ON inv.variant_id = pv.id
    JOIN products p ON pv.product_id = p.id
    WHERE inv.variant_id = ?
    """, (variant_id,))
    row = cursor.fetchone()
    if not row:
        return None

    data = dict(row)
    data["is_low_stock"] = data["stock_quantity"] <= data["low_stock_threshold"]
    data["is_out_of_stock"] = data["stock_quantity"] <= 0
    return data


def stock_in(
    conn: sqlite3.Connection,
    variant_id: int,
    quantity: int,
    unit_cost: Optional[float] = None,
    reference: Optional[str] = "PURCHASE",
    reason: Optional[str] = "Stock In / Merchandise Receipt",
    user_id: int = 1
) -> Dict[str, Any]:
    """
    Receives new stock into inventory.
    Atomically increments inventory and writes an immutable STOCK_IN transaction ledger entry.
    """
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="INVALID_QUANTITY: Received quantity must be at least 1.")

    cursor = conn.cursor()
    now = datetime.now().isoformat()

    # Verify variant exists
    cursor.execute("SELECT id, product_id, cost_price, sku FROM product_variants WHERE id = ?", (variant_id,))
    variant = cursor.fetchone()
    if not variant:
        raise HTTPException(status_code=404, detail=f"VARIANT_NOT_FOUND: Variant ID {variant_id} does not exist.")

    # Fetch stock before
    cursor.execute("SELECT stock_quantity FROM inventory WHERE variant_id = ?", (variant_id,))
    inv_row = cursor.fetchone()
    if not inv_row:
        # Create inventory row if missing
        cursor.execute("""
        INSERT INTO inventory (variant_id, stock_quantity, low_stock_threshold, updated_at)
        VALUES (?, 0, 5, ?)
        """, (variant_id, now))
        stock_before = 0
    else:
        stock_before = inv_row["stock_quantity"]

    stock_after = stock_before + quantity

    # Atomically update inventory
    cursor.execute("""
    UPDATE inventory 
    SET stock_quantity = stock_quantity + ?, updated_at = ?
    WHERE variant_id = ?
    """, (quantity, now, variant_id))

    # Update cost price on variant if provided and valid
    old_cost = variant["cost_price"]
    if unit_cost is not None and unit_cost >= 0:
        cursor.execute("UPDATE product_variants SET cost_price = ?, updated_at = ? WHERE id = ?", (unit_cost, now, variant_id))
        if unit_cost != old_cost:
            log_audit(conn, "VARIANT", variant_id, "COST_PRICE_UPDATE", {"cost_price": old_cost}, {"cost_price": unit_cost}, "Updated on stock-in", user_id)

    # Insert immutable inventory transaction
    cursor.execute("""
    INSERT INTO inventory_transactions (
        type, variant_id, quantity_change, stock_before, stock_after,
        reference_type, reference_id, user_id, reason, note, timestamp, created_at
    )
    VALUES ('STOCK_IN', ?, ?, ?, ?, 'STOCK_IN', ?, ?, ?, ?, ?, ?)
    """, (
        variant_id,
        quantity,
        stock_before,
        stock_after,
        reference or "PURCHASE",
        user_id,
        reason or "Merchandise Receipt",
        reason or "Merchandise Receipt",
        now,
        now
    ))

    log_audit(
        conn, "INVENTORY", variant_id, "STOCK_IN",
        {"stock_before": stock_before},
        {"stock_after": stock_after, "quantity_added": quantity},
        reason or "Stock In",
        user_id
    )

    return {
        "success": True,
        "variant_id": variant_id,
        "sku": variant["sku"],
        "stock_before": stock_before,
        "quantity_added": quantity,
        "stock_after": stock_after,
        "updated_at": now
    }


def adjust_stock(
    conn: sqlite3.Connection,
    variant_id: int,
    quantity_change: int,
    reason: str = "CORRECTION",
    note: str = "",
    user_id: int = 1
) -> Dict[str, Any]:
    """
    Performs an authorized manual stock adjustment.
    Enforces non-negative inventory constraints and concurrency-safe updates.
    """
    if quantity_change == 0:
        raise HTTPException(status_code=400, detail="INVALID_QUANTITY: Adjustment quantity change cannot be 0.")

    cursor = conn.cursor()
    now = datetime.now().isoformat()

    cursor.execute("SELECT id, sku FROM product_variants WHERE id = ?", (variant_id,))
    variant = cursor.fetchone()
    if not variant:
        raise HTTPException(status_code=404, detail=f"VARIANT_NOT_FOUND: Variant ID {variant_id} does not exist.")

    cursor.execute("SELECT stock_quantity FROM inventory WHERE variant_id = ?", (variant_id,))
    inv_row = cursor.fetchone()
    if not inv_row:
        raise HTTPException(status_code=404, detail=f"INVENTORY_NOT_FOUND: No inventory record for variant ID {variant_id}.")

    stock_before = inv_row["stock_quantity"]

    # Prevent negative stock
    if quantity_change < 0:
        abs_qty = abs(quantity_change)
        cursor.execute("""
        UPDATE inventory 
        SET stock_quantity = stock_quantity - ?, updated_at = ?
        WHERE variant_id = ? AND stock_quantity >= ?
        """, (abs_qty, now, variant_id, abs_qty))

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=400,
                detail=f"INSUFFICIENT_STOCK: Current stock is {stock_before}. Cannot reduce by {abs_qty}."
            )

        reason_lower = (reason or "").lower()
        if "damage" in reason_lower:
            tx_type = "DAMAGE"
        elif "loss" in reason_lower:
            tx_type = "LOSS"
        else:
            tx_type = "ADJUSTMENT_OUT"
    else:
        cursor.execute("""
        UPDATE inventory 
        SET stock_quantity = stock_quantity + ?, updated_at = ?
        WHERE variant_id = ?
        """, (quantity_change, now, variant_id))
        tx_type = "ADJUSTMENT_IN"

    stock_after = stock_before + quantity_change
    full_reason = f"{reason}: {note}".strip(": ") if note else reason

    cursor.execute("""
    INSERT INTO inventory_transactions (
        type, variant_id, quantity_change, stock_before, stock_after,
        reference_type, reference_id, user_id, reason, note, timestamp, created_at
    )
    VALUES (?, ?, ?, ?, ?, 'MANUAL_ADJUST', 'ADJUST', ?, ?, ?, ?, ?)
    """, (
        tx_type,
        variant_id,
        quantity_change,
        stock_before,
        stock_after,
        user_id,
        full_reason,
        full_reason,
        now,
        now
    ))

    log_audit(
        conn, "INVENTORY", variant_id, "MANUAL_ADJUST",
        {"stock_before": stock_before},
        {"stock_after": stock_after, "delta": quantity_change},
        full_reason,
        user_id
    )

    return {
        "success": True,
        "variant_id": variant_id,
        "sku": variant["sku"],
        "stock_before": stock_before,
        "quantity_change": quantity_change,
        "stock_after": stock_after,
        "type": tx_type,
        "reason": full_reason,
        "updated_at": now
    }


def get_inventory_ledger(
    conn: sqlite3.Connection,
    variant_id: Optional[int] = None,
    tx_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Retrieves the auditable inventory movement ledger with variant and product details.
    """
    cursor = conn.cursor()
    query = """
    SELECT 
        it.id,
        it.type,
        it.variant_id,
        it.quantity_change,
        it.stock_before,
        it.stock_after,
        it.reference_type,
        it.reference_id,
        it.reason,
        it.user_id,
        it.created_at,
        pv.sku,
        pv.barcode,
        pv.size,
        pv.color,
        p.name AS product_name,
        p.category
    FROM inventory_transactions it
    JOIN product_variants pv ON it.variant_id = pv.id
    JOIN products p ON pv.product_id = p.id
    WHERE 1=1
    """
    params = []

    if variant_id:
        query += " AND it.variant_id = ?"
        params.append(variant_id)

    if tx_type:
        query += " AND it.type = ?"
        params.append(tx_type.upper())

    query += " ORDER BY it.id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor.execute(query, params)
    return [dict(r) for r in cursor.fetchall()]


def reconcile_inventory(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Audits the current stock in inventory against the sum of all transaction logs.
    Reconciles parent product cached stock_quantity from variants.
    Returns status and list of any discrepancies.
    """
    cursor = conn.cursor()

    # Re-sync parent product stock_quantity to variant sums
    cursor.execute("""
    UPDATE products 
    SET stock_quantity = (
        SELECT COALESCE(SUM(inv.stock_quantity), 0)
        FROM product_variants pv
        JOIN inventory inv ON pv.id = inv.variant_id
        WHERE pv.product_id = products.id
    )
    WHERE id IN (SELECT DISTINCT product_id FROM product_variants WHERE product_id IS NOT NULL);
    """)

    cursor.execute("""
    SELECT 
        pv.id AS variant_id,
        pv.sku,
        p.name AS product_name,
        pv.size,
        pv.color,
        COALESCE(inv.stock_quantity, 0) AS current_stock,
        COALESCE((SELECT SUM(it.quantity_change) FROM inventory_transactions it WHERE it.variant_id = pv.id), 0) AS ledger_stock
    FROM product_variants pv
    JOIN products p ON pv.product_id = p.id
    LEFT JOIN inventory inv ON inv.variant_id = pv.id
    ORDER BY p.name ASC, pv.size ASC
    """)
    rows = cursor.fetchall()

    discrepancies = []
    total_variants = len(rows)
    total_matched = 0

    for r in rows:
        diff = r["current_stock"] - r["ledger_stock"]
        if diff != 0:
            discrepancies.append({
                "variant_id": r["variant_id"],
                "sku": r["sku"],
                "product_name": r["product_name"],
                "size": r["size"],
                "color": r["color"],
                "current_stock": r["current_stock"],
                "ledger_stock": r["ledger_stock"],
                "discrepancy": diff
            })
        else:
            total_matched += 1

    return {
        "status": "RECONCILED" if len(discrepancies) == 0 else "DISCREPANCIES_FOUND",
        "total_variants": total_variants,
        "matched_variants": total_matched,
        "discrepancy_count": len(discrepancies),
        "discrepancies": discrepancies
    }
