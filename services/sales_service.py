"""
Authoritative Billing & Sales Service for SOL POS & CRM.
Enforces:
- Exact monetary precision using Python Decimal with standard financial ROUND_HALF_UP
- Single authoritative calculation on the backend
- Atomic database transactions for checkout, returns, and cancellations
- Concurrency-safe conditional inventory decrements (no overselling)
- Collision-free sequential invoice numbering (SOL-YYYY-XXXXXX)
- Complete returns and refunds with inventory ledger restitution
"""
import sqlite3
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import HTTPException

from models import InvoiceCreate, SaleReturnRequest, BillCalculationRequest
from services.audit_service import log_audit


def to_decimal(val: Any) -> Decimal:
    """Safely converts input to a 2-decimal rounded Decimal."""
    if val is None or val == "":
        return Decimal("0.00")
    try:
        return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def calculate_bill_totals(
    items: List[Dict[str, Any]],
    discount_type: str = "fixed",
    discount_val: float = 0.0,
    tax_rate: float = 5.0
) -> Dict[str, Any]:
    """
    Authoritative financial calculation engine.
    Calculates line totals, subtotal, discount, taxable amount, tax, and grand total.
    Supports both bill-level and item-level GST rates according to statutory rules.
    """
    processed_items = []
    subtotal = Decimal("0.00")

    for it in items:
        qty = Decimal(str(it.get("quantity", 1)))
        if qty <= Decimal("0"):
            raise HTTPException(status_code=400, detail=f"INVALID_QUANTITY: Quantity for '{it.get('product_name', 'Item')}' must be at least 1.")

        unit_price = to_decimal(it.get("unit_price", 0.0))
        if unit_price < Decimal("0.00"):
            raise HTTPException(status_code=400, detail=f"INVALID_PRICE: Unit price for '{it.get('product_name', 'Item')}' cannot be negative.")

        item_raw = (qty * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        item_disc = min(item_raw, to_decimal(it.get("discount_amount", 0.0)))
        line_total = max(Decimal("0.00"), item_raw - item_disc)

        subtotal += line_total
        processed_items.append({
            **it,
            "unit_price": float(unit_price),
            "quantity": int(qty),
            "discount_amount": float(item_disc),
            "line_total": float(line_total)
        })

    # Bill-level discount
    disc_val_dec = to_decimal(discount_val)
    if discount_type.lower() == "percent":
        if disc_val_dec < Decimal("0.00") or disc_val_dec > Decimal("100.00"):
            raise HTTPException(status_code=400, detail="INVALID_DISCOUNT: Discount percentage must be between 0% and 100%.")
        calc_discount = (subtotal * disc_val_dec / Decimal("100.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        if disc_val_dec < Decimal("0.00"):
            raise HTTPException(status_code=400, detail="INVALID_DISCOUNT: Discount amount cannot be negative.")
        calc_discount = disc_val_dec

    discount_amount = min(subtotal, max(Decimal("0.00"), calc_discount))
    taxable_amount = max(Decimal("0.00"), subtotal - discount_amount)

    tax_rate_dec = to_decimal(tax_rate)
    if tax_rate_dec < Decimal("0.00"):
        raise HTTPException(status_code=400, detail="INVALID_TAX_RATE: Tax rate cannot be negative.")

    # Check if items define custom/mixed gst_rates
    all_same_rate = all(to_decimal(it.get("gst_rate") if it.get("gst_rate") is not None else tax_rate_dec) == tax_rate_dec for it in processed_items)

    if not all_same_rate:
        total_tax_calc = Decimal("0.00")
        for it_dict in processed_items:
            it_lt = to_decimal(it_dict["line_total"])
            if subtotal > Decimal("0.00"):
                it_taxable = (it_lt * taxable_amount / subtotal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                it_taxable = Decimal("0.00")

            it_rate = to_decimal(it_dict.get("gst_rate") if it_dict.get("gst_rate") is not None else tax_rate_dec)
            if it_rate < Decimal("0.00"):
                raise HTTPException(status_code=400, detail="INVALID_TAX_RATE: Tax rate cannot be negative.")
            it_tax = (it_taxable * it_rate / Decimal("100.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            it_dict["tax_rate"] = float(it_rate)
            it_dict["tax_amount"] = float(it_tax)
            total_tax_calc += it_tax
        tax_amount = total_tax_calc
    else:
        tax_amount = (taxable_amount * tax_rate_dec / Decimal("100.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        running_item_tax = Decimal("0.00")
        for idx, it_dict in enumerate(processed_items):
            it_lt = to_decimal(it_dict["line_total"])
            if idx == len(processed_items) - 1:
                it_tax = tax_amount - running_item_tax
            else:
                it_taxable = (it_lt * taxable_amount / subtotal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if subtotal > 0 else Decimal("0.00")
                it_tax = (it_taxable * tax_rate_dec / Decimal("100.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                running_item_tax += it_tax
            it_dict["tax_rate"] = float(tax_rate_dec)
            it_dict["tax_amount"] = float(it_tax)

    grand_total = (taxable_amount + tax_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "items": processed_items,
        "subtotal": float(subtotal),
        "discount_type": discount_type,
        "discount_val": float(disc_val_dec),
        "discount_amount": float(discount_amount),
        "taxable_amount": float(taxable_amount),
        "tax_rate": float(tax_rate_dec),
        "tax_amount": float(tax_amount),
        "grand_total": float(grand_total)
    }


def get_next_invoice_number(conn: sqlite3.Connection, current_year: Optional[str] = None) -> str:
    """
    Collision-free sequential invoice number generation (Section 30).
    Uses atomic SQLite upsert RETURNING on invoice_sequences partitioned by year.
    Format: SOL-YYYY-XXXXXX (e.g. SOL-2026-000001)
    """
    cursor = conn.cursor()
    year = current_year or datetime.now().strftime("%Y")
    cursor.execute("""
    INSERT INTO invoice_sequences (year, last_sequence)
    VALUES (?, 1)
    ON CONFLICT(year) DO UPDATE SET last_sequence = last_sequence + 1
    RETURNING last_sequence;
    """, (year,))
    seq_num = cursor.fetchone()[0]
    return f"SOL-{year}-{seq_num:06d}"


def checkout(
    conn: sqlite3.Connection,
    sale_data: InvoiceCreate,
    user_id: int = 1
) -> Dict[str, Any]:
    """
    Atomic retail POS checkout operation:
    1. Validate cart items and positive quantities
    2. Concurrency-safe atomic conditional stock decrement
    3. Authoritative backend financial recalculation with Decimal precision
    4. Collision-free sequential invoice numbering
    5. Customer CRM resolution and metric updates
    6. Insert sales, sale_items, payments, and inventory_transactions
    7. Commit transaction
    """
    if not sale_data.items or len(sale_data.items) == 0:
        raise HTTPException(status_code=400, detail="CART_EMPTY: Cannot complete sale with empty cart.")

    cursor = conn.cursor()
    now = datetime.now().isoformat()

    # Fetch store settings for default tax rate
    cursor.execute("SELECT default_tax_rate, currency_symbol FROM settings WHERE id = 1;")
    s_row = cursor.fetchone()
    default_tax = s_row["default_tax_rate"] if s_row else 5.0
    active_tax_rate = sale_data.tax_rate if sale_data.tax_rate is not None else default_tax

    # Step 1: Pre-resolve items & verify catalog details
    resolved_items = []
    for raw_it in sale_data.items:
        it = raw_it.model_dump()
        v_id = it.get("variant_id")
        sku = (it.get("sku") or "").strip()
        p_id = it.get("product_id")

        # Resolve variant if not explicitly given
        if not v_id and sku and sku != "CUSTOM":
            cursor.execute("SELECT id, product_id, selling_price, cost_price, sku, barcode FROM product_variants WHERE sku = ?;", (sku,))
            vr = cursor.fetchone()
            if vr:
                v_id = vr["id"]
                p_id = vr["product_id"] if not p_id else p_id
                it["variant_id"] = v_id
                it["product_id"] = p_id

        original_price = float(it.get("unit_price", 0.0))
        cost_price = 0.0
        price_override = 0
        override_reason = ""

        if v_id:
            cursor.execute("""
            SELECT pv.id, pv.product_id, pv.selling_price, pv.cost_price, pv.sku, pv.barcode, p.name, pv.size, pv.color, pv.gst_rate
            FROM product_variants pv
            JOIN products p ON pv.product_id = p.id
            WHERE pv.id = ?;
            """, (v_id,))
            vr = cursor.fetchone()
            if vr:
                p_id = vr["product_id"]
                catalog_price = float(vr["selling_price"])
                cost_price = float(vr["cost_price"])
                original_price = catalog_price
                it["product_id"] = p_id
                it["sku"] = vr["sku"]
                it["barcode"] = vr["barcode"] or vr["sku"]
                if it.get("gst_rate") is None and vr["gst_rate"] is not None:
                    it["gst_rate"] = float(vr["gst_rate"])
                if not it.get("size"):
                    it["size"] = vr["size"]
                if not it.get("color"):
                    it["color"] = vr["color"]
                if not it.get("product_name") or it.get("product_name") == "Custom":
                    it["product_name"] = vr["name"]

                # Price Authority check (Section 29)
                current_unit_price = float(it.get("unit_price", catalog_price))
                if round(current_unit_price, 2) != round(catalog_price, 2):
                    price_override = 1
                    override_reason = f"Cashier price adjustment from ₹{catalog_price:.2f} to ₹{current_unit_price:.2f}"
            else:
                raise HTTPException(status_code=404, detail=f"VARIANT_NOT_FOUND: Variant ID {v_id} does not exist.")

        it["original_price"] = original_price
        it["cost_price"] = cost_price
        it["price_override"] = price_override
        it["override_reason"] = override_reason
        resolved_items.append(it)

    # Step 2: Atomic Concurrency-Safe Stock Decrement (Section 26)
    # Uses conditional stock update to prevent overselling
    deducted_variants = []
    for it in resolved_items:
        v_id = it.get("variant_id")
        qty = it["quantity"]

        if v_id:
            cursor.execute("""
            UPDATE inventory 
            SET stock_quantity = stock_quantity - ?, updated_at = ?
            WHERE variant_id = ? AND stock_quantity >= ?;
            """, (qty, now, v_id, qty))

            if cursor.rowcount == 0:
                # Query current stock to report exact shortage
                cursor.execute("SELECT stock_quantity FROM inventory WHERE variant_id = ?;", (v_id,))
                cur_row = cursor.fetchone()
                current_stock = cur_row["stock_quantity"] if cur_row else 0
                raise HTTPException(
                    status_code=400,
                    detail=f"INSUFFICIENT_STOCK: Only {current_stock} units available for '{it.get('product_name')}' ({it.get('size')}/{it.get('color')}). Requested: {qty}."
                )

            cursor.execute("SELECT stock_quantity FROM inventory WHERE variant_id = ?;", (v_id,))
            new_stock = cursor.fetchone()["stock_quantity"]
            deducted_variants.append({
                "variant_id": v_id,
                "quantity": qty,
                "stock_before": new_stock + qty,
                "stock_after": new_stock
            })

    # Step 3: Authoritative Backend Calculation (Section 9 & 10)
    bill_calc = calculate_bill_totals(
        resolved_items,
        discount_type=sale_data.discount_type,
        discount_val=sale_data.discount_val,
        tax_rate=active_tax_rate
    )
    grand_total_dec = to_decimal(bill_calc["grand_total"])

    # Cash change calculation
    tendered = to_decimal(sale_data.cash_tendered or 0.0)
    if sale_data.payment_method.lower() == "cash" and tendered > Decimal("0.00"):
        change_returned = max(Decimal("0.00"), tendered - grand_total_dec)
    else:
        tendered = grand_total_dec
        change_returned = Decimal("0.00")

    # Step 4: Sequential Invoice Number Generation (Section 30)
    inv_number = get_next_invoice_number(conn)

    # Step 5: Customer CRM Resolution (Section 15)
    customer_id = sale_data.customer_id
    cust_phone = (sale_data.customer_phone or "").strip()
    cust_name = (sale_data.customer_name or "Walk-in Guest").strip()
    cust_email = (sale_data.customer_email or "").strip()

    if cust_phone:
        cursor.execute("SELECT id, name, email FROM customers WHERE phone = ?;", (cust_phone,))
        cust_row = cursor.fetchone()
        if cust_row:
            customer_id = cust_row["id"]
            if cust_name and cust_name != "Walk-in Guest":
                cursor.execute("UPDATE customers SET name = ?, email = COALESCE(NULLIF(?, ''), email) WHERE id = ?;", (cust_name, cust_email, customer_id))
        else:
            cursor.execute("""
            INSERT INTO customers (name, phone, email, city, notes, loyalty_points, tier, total_spent, total_orders, last_visit, created_at)
            VALUES (?, ?, ?, '', 'Created at checkout', 0, 'Bronze', 0.0, 0, ?, ?);
            """, (cust_name, cust_phone, cust_email, now, now))
            customer_id = cursor.lastrowid

    # Step 6: Create Sale record
    cursor.execute("""
    INSERT INTO sales (
        invoice_number, customer_id, customer_name, customer_phone, customer_email,
        subtotal, discount_type, discount_val, discount_amount, tax_rate, tax_amount,
        grand_total, payment_method, payment_status, sale_status, cash_tendered, change_returned,
        notes, created_by, created_at, updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Paid', 'COMPLETED', ?, ?, ?, ?, ?, ?);
    """, (
        inv_number,
        customer_id,
        cust_name,
        cust_phone,
        cust_email,
        bill_calc["subtotal"],
        bill_calc["discount_type"],
        bill_calc["discount_val"],
        bill_calc["discount_amount"],
        bill_calc["tax_rate"],
        bill_calc["tax_amount"],
        bill_calc["grand_total"],
        sale_data.payment_method,
        float(tendered),
        float(change_returned),
        sale_data.notes or "",
        user_id,
        now,
        now
    ))
    sale_id = cursor.lastrowid

    # Dual-write to legacy invoices table for backward compatibility
    cursor.execute("""
    INSERT INTO invoices (
        id, invoice_number, customer_id, customer_name, customer_phone,
        subtotal, discount_type, discount_val, discount_amount, tax_rate, tax_amount,
        grand_total, payment_method, payment_status, cash_tendered, change_returned, notes, created_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Paid', ?, ?, ?, ?);
    """, (
        sale_id, inv_number, customer_id, cust_name, cust_phone,
        bill_calc["subtotal"], bill_calc["discount_type"], bill_calc["discount_val"],
        bill_calc["discount_amount"], bill_calc["tax_rate"], bill_calc["tax_amount"],
        bill_calc["grand_total"], sale_data.payment_method, float(tendered), float(change_returned),
        sale_data.notes or "", now
    ))

    # Step 7: Create Sale Items & Inventory Transactions
    saved_items = []
    for it in bill_calc["items"]:
        cursor.execute("""
        INSERT INTO sale_items (
            sale_id, product_id, variant_id, sku, product_name, size, color,
            original_price, unit_price, price_override, override_reason,
            quantity, returned_quantity, discount_amount, line_total, cost_price
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?);
        """, (
            sale_id,
            it.get("product_id"),
            it.get("variant_id"),
            it.get("sku") or "",
            it["product_name"],
            it.get("size") or "",
            it.get("color") or "",
            it.get("original_price", it["unit_price"]),
            it["unit_price"],
            it.get("price_override", 0),
            it.get("override_reason", ""),
            it["quantity"],
            it.get("discount_amount", 0.0),
            it["line_total"],
            it.get("cost_price", 0.0)
        ))
        item_id = cursor.lastrowid

        # Dual-write into legacy invoice_items
        cursor.execute("""
        INSERT INTO invoice_items (
            id, invoice_id, product_id, sku, product_name, size, color,
            unit_price, quantity, discount_amount, line_total, cost_price
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            item_id, sale_id, it.get("product_id"), it.get("sku") or "",
            it["product_name"], it.get("size") or "", it.get("color") or "",
            it["unit_price"], it["quantity"], it.get("discount_amount", 0.0),
            it["line_total"], it.get("cost_price", 0.0)
        ))

        saved_items.append({**it, "id": item_id, "sale_id": sale_id})

    # Step 8: Insert Inventory Transaction Ledger entries
    for dv in deducted_variants:
        cursor.execute("""
        INSERT INTO inventory_transactions (
            type, variant_id, quantity_change, stock_before, stock_after,
            reference_type, reference_id, user_id, reason, note, timestamp, created_at
        )
        VALUES ('SALE', ?, ?, ?, ?, 'SALE', ?, ?, ?, ?, ?, ?);
        """, (
            dv["variant_id"],
            -dv["quantity"],
            dv["stock_before"],
            dv["stock_after"],
            inv_number,
            user_id,
            f"Sold on {inv_number}",
            f"Sold on {inv_number}",
            now,
            now
        ))

    # Step 9: Insert Payment record
    cursor.execute("""
    INSERT INTO payments (
        sale_id, payment_method, amount, status, transaction_ref,
        cash_tendered, change_returned, created_at
    )
    VALUES (?, ?, ?, 'Completed', '', ?, ?, ?);
    """, (sale_id, sale_data.payment_method, bill_calc["grand_total"], float(tendered), float(change_returned), now))

    # Step 10: Update Customer Metrics transactionally (Section 15)
    if customer_id:
        cursor.execute("""
        SELECT 
            COUNT(*) AS total_orders,
            COALESCE(SUM(
                s.grand_total - COALESCE((SELECT SUM(sr.total_refund_amount) FROM sale_returns sr WHERE sr.sale_id = s.id), 0.0)
            ), 0.0) AS total_spent
        FROM sales s 
        WHERE s.customer_id = ? AND s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED');
        """, (customer_id,))
        crm_metrics = cursor.fetchone()
        tot_orders = crm_metrics["total_orders"]
        tot_spent = round(crm_metrics["total_spent"], 2)

        tier = "Bronze"
        if tot_spent >= 30000:
            tier = "Platinum"
        elif tot_spent >= 15000:
            tier = "Gold"
        elif tot_spent >= 5000:
            tier = "Silver"

        earned_points = int(bill_calc["grand_total"] // 100)
        cursor.execute("""
        UPDATE customers 
        SET total_spent = ?, total_orders = ?, tier = ?,
            loyalty_points = loyalty_points + ?, last_visit = ?
        WHERE id = ?;
        """, (tot_spent, tot_orders, tier, earned_points, now, customer_id))

    # Log audit record
    log_audit(conn, "SALE", sale_id, "CHECKOUT", None, {
        "invoice_number": inv_number,
        "grand_total": bill_calc["grand_total"],
        "items_count": len(saved_items)
    }, "Sale completed", user_id)

    return {
        "id": sale_id,
        "invoice_id": sale_id,
        "invoice_number": inv_number,
        "customer_id": customer_id,
        "customer_name": cust_name,
        "customer_phone": cust_phone,
        "customer_email": cust_email,
        "subtotal": bill_calc["subtotal"],
        "discount_type": bill_calc["discount_type"],
        "discount_val": bill_calc["discount_val"],
        "discount_amount": bill_calc["discount_amount"],
        "taxable_amount": bill_calc["taxable_amount"],
        "tax_rate": bill_calc["tax_rate"],
        "tax_amount": bill_calc["tax_amount"],
        "grand_total": bill_calc["grand_total"],
        "payment_method": sale_data.payment_method,
        "payment_status": "Paid",
        "sale_status": "COMPLETED",
        "cash_tendered": float(tendered),
        "change_returned": float(change_returned),
        "notes": sale_data.notes or "",
        "items": saved_items,
        "created_at": now
    }


def process_sale_return(
    conn: sqlite3.Connection,
    sale_id: int,
    return_req: SaleReturnRequest,
    user_id: int = 1
) -> Dict[str, Any]:
    """
    Processes an itemized return and refund (Section 14):
    1. Validates sale is eligible (COMPLETED or PARTIALLY_REFUNDED)
    2. Validates return quantity does not exceed original purchased quantity
    3. Restocks inventory and writes RETURN transaction ledger entry
    4. Records refund payment record and updates sale status
    5. Deducts refunded amount from customer CRM total_spent
    """
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    cursor.execute("SELECT * FROM sales WHERE id = ?;", (sale_id,))
    sale = cursor.fetchone()
    if not sale:
        raise HTTPException(status_code=404, detail="SALE_NOT_FOUND: Sale record does not exist.")

    if sale["sale_status"] not in ("COMPLETED", "PARTIALLY_REFUNDED"):
        raise HTTPException(
            status_code=400,
            detail=f"SALE_NOT_RETURNABLE: Sale is already '{sale['sale_status']}'. Cannot process returns."
        )

    # Sequence for return receipt
    year = datetime.now().strftime("%Y")
    cursor.execute("SELECT COUNT(*) FROM sale_returns WHERE return_number LIKE ?;", (f"RET-{year}-%",))
    ret_seq = cursor.fetchone()[0] + 1
    return_number = f"RET-{year}-{ret_seq:05d}"

    sale_subtotal = to_decimal(sale["subtotal"])
    sale_grand_total = to_decimal(sale["grand_total"])
    ratio = (sale_grand_total / sale_subtotal) if sale_subtotal > Decimal("0.00") else Decimal("1.00")

    total_refund = Decimal("0.00")
    return_items_to_save = []

    for r_it in return_req.items:
        cursor.execute("SELECT * FROM sale_items WHERE id = ? AND sale_id = ?;", (r_it.sale_item_id, sale_id))
        s_item = cursor.fetchone()
        if not s_item:
            raise HTTPException(status_code=404, detail=f"ITEM_NOT_FOUND: Sale item ID {r_it.sale_item_id} not found in this sale.")

        max_returnable = s_item["quantity"] - s_item["returned_quantity"]
        if r_it.quantity > max_returnable:
            raise HTTPException(
                status_code=400,
                detail=f"EXCESS_RETURN_QUANTITY: Cannot return {r_it.quantity} of '{s_item['product_name']}'. Only {max_returnable} returnable."
            )

        # Pro-rata refund value for this line item based on net effective price paid (including tax & discounts)
        line_tot = to_decimal(s_item["line_total"])
        effective_line_paid = (line_tot * ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        unit_effective = (effective_line_paid / Decimal(str(s_item["quantity"]))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        item_refund = (unit_effective * Decimal(str(r_it.quantity))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_refund += item_refund

        # Update returned quantity on sale_item
        cursor.execute("""
        UPDATE sale_items 
        SET returned_quantity = returned_quantity + ?
        WHERE id = ?;
        """, (r_it.quantity, r_it.sale_item_id))

        # Restock inventory if requested
        v_id = s_item["variant_id"]
        if r_it.restock_inventory and v_id:
            cursor.execute("SELECT stock_quantity FROM inventory WHERE variant_id = ?;", (v_id,))
            inv_row = cursor.fetchone()
            stock_before = inv_row["stock_quantity"] if inv_row else 0
            stock_after = stock_before + r_it.quantity

            cursor.execute("""
            UPDATE inventory 
            SET stock_quantity = stock_quantity + ?, updated_at = ?
            WHERE variant_id = ?;
            """, (r_it.quantity, now, v_id))

            cursor.execute("""
            INSERT INTO inventory_transactions (
                type, variant_id, quantity_change, stock_before, stock_after,
                reference_type, reference_id, user_id, reason, note, timestamp, created_at
            )
            VALUES ('RETURN', ?, ?, ?, ?, 'RETURN', ?, ?, ?, ?, ?, ?);
            """, (
                v_id,
                r_it.quantity,
                stock_before,
                stock_after,
                return_number,
                user_id,
                f"Customer return: {return_req.reason}",
                f"Customer return: {return_req.reason}",
                now,
                now
            ))

        return_items_to_save.append({
            "sale_item_id": r_it.sale_item_id,
            "variant_id": v_id,
            "quantity": r_it.quantity,
            "refund_amount": float(item_refund),
            "restock_inventory": 1 if r_it.restock_inventory else 0
        })

    # Check whether all sale items have been returned
    cursor.execute("SELECT SUM(quantity) as total_qty, SUM(returned_quantity) as total_ret FROM sale_items WHERE sale_id = ?;", (sale_id,))
    qty_check = cursor.fetchone()
    is_fully_refunded = (qty_check["total_qty"] == qty_check["total_ret"])
    new_sale_status = "REFUNDED" if is_fully_refunded else "PARTIALLY_REFUNDED"

    # Perfect penny reconciliation if all items in sale are now returned
    if is_fully_refunded and len(return_items_to_save) > 0:
        cursor.execute("SELECT COALESCE(SUM(total_refund_amount), 0.0) FROM sale_returns WHERE sale_id = ?;", (sale_id,))
        prior_refunds = to_decimal(cursor.fetchone()[0])
        exact_remaining = sale_grand_total - prior_refunds
        diff = exact_remaining - total_refund
        if diff != Decimal("0.00"):
            total_refund = exact_remaining
            return_items_to_save[-1]["refund_amount"] = float(to_decimal(return_items_to_save[-1]["refund_amount"]) + diff)

    # Save Return master
    cursor.execute("""
    INSERT INTO sale_returns (
        return_number, sale_id, customer_id, total_refund_amount,
        refund_method, reason, user_id, created_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        return_number,
        sale_id,
        sale["customer_id"],
        float(total_refund),
        return_req.refund_method,
        return_req.reason,
        user_id,
        now
    ))
    return_id = cursor.lastrowid

    # Save return items
    for rit in return_items_to_save:
        cursor.execute("""
        INSERT INTO sale_return_items (
            return_id, sale_item_id, variant_id, quantity, refund_amount, restock_inventory, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """, (return_id, rit["sale_item_id"], rit["variant_id"], rit["quantity"], rit["refund_amount"], rit["restock_inventory"], now))

    # Record negative refund payment entry
    cursor.execute("""
    INSERT INTO payments (
        sale_id, payment_method, amount, status, transaction_ref, created_at
    )
    VALUES (?, ?, ?, 'Refunded', ?, ?);
    """, (sale_id, return_req.refund_method, -float(total_refund), return_number, now))

    cursor.execute("UPDATE sales SET sale_status = ?, updated_at = ? WHERE id = ?;", (new_sale_status, now, sale_id))

    # Reconcile customer spent and order count using net revenue
    if sale["customer_id"]:
        cursor.execute("""
        SELECT 
            COUNT(*) AS total_orders,
            COALESCE(SUM(
                s.grand_total - COALESCE((SELECT SUM(sr.total_refund_amount) FROM sale_returns sr WHERE sr.sale_id = s.id), 0.0)
            ), 0.0) AS total_spent
        FROM sales s 
        WHERE s.customer_id = ? AND s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED');
        """, (sale["customer_id"],))
        c_stats = cursor.fetchone()
        c_orders = c_stats["total_orders"]
        c_spent = round(c_stats["total_spent"], 2)

        tier = "Bronze"
        if c_spent >= 30000:
            tier = "Platinum"
        elif c_spent >= 15000:
            tier = "Gold"
        elif c_spent >= 5000:
            tier = "Silver"

        cursor.execute("UPDATE customers SET total_orders = ?, total_spent = ?, tier = ? WHERE id = ?;", (c_orders, c_spent, tier, sale["customer_id"]))

    log_audit(conn, "SALE", sale_id, "RETURN", {"status": sale["sale_status"]}, {"status": new_sale_status, "refund_amount": float(total_refund)}, return_req.reason, user_id)

    return {
        "success": True,
        "return_id": return_id,
        "return_number": return_number,
        "sale_id": sale_id,
        "sale_status": new_sale_status,
        "total_refund_amount": float(total_refund),
        "refund_method": return_req.refund_method,
        "items_returned": len(return_items_to_save),
        "created_at": now
    }


def cancel_sale(
    conn: sqlite3.Connection,
    sale_id: int,
    reason: str,
    user_id: int = 1
) -> Dict[str, Any]:
    """
    Cancels a sale in its entirety, restores all stock to inventory with audit logs,
    and updates sale/payment status to CANCELLED.
    """
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    cursor.execute("SELECT * FROM sales WHERE id = ?;", (sale_id,))
    sale = cursor.fetchone()
    if not sale:
        raise HTTPException(status_code=404, detail="SALE_NOT_FOUND: Sale record does not exist.")

    if sale["sale_status"] == "CANCELLED":
        raise HTTPException(status_code=400, detail="SALE_ALREADY_CANCELLED: This sale has already been cancelled.")

    # Restock all non-returned items
    cursor.execute("SELECT * FROM sale_items WHERE sale_id = ?;", (sale_id,))
    items = cursor.fetchall()

    for itm in items:
        rem_qty = itm["quantity"] - itm["returned_quantity"]
        v_id = itm["variant_id"]
        if rem_qty > 0 and v_id:
            cursor.execute("SELECT stock_quantity FROM inventory WHERE variant_id = ?;", (v_id,))
            inv_row = cursor.fetchone()
            stock_before = inv_row["stock_quantity"] if inv_row else 0
            stock_after = stock_before + rem_qty

            cursor.execute("UPDATE inventory SET stock_quantity = stock_quantity + ?, updated_at = ? WHERE variant_id = ?;", (rem_qty, now, v_id))
            cursor.execute("""
            INSERT INTO inventory_transactions (
                type, variant_id, quantity_change, stock_before, stock_after,
                reference_type, reference_id, user_id, reason, note, timestamp, created_at
            )
            VALUES ('RETURN', ?, ?, ?, ?, 'CANCELLATION', ?, ?, ?, ?, ?, ?);
            """, (
                v_id,
                rem_qty,
                stock_before,
                stock_after,
                sale["invoice_number"],
                user_id,
                f"Sale cancelled: {reason}",
                f"Sale cancelled: {reason}",
                now,
                now
            ))

    cursor.execute("UPDATE sales SET sale_status = 'CANCELLED', payment_status = 'Cancelled', updated_at = ? WHERE id = ?;", (now, sale_id))
    cursor.execute("UPDATE invoices SET payment_status = 'Cancelled' WHERE id = ?;", (sale_id,))
    cursor.execute("UPDATE payments SET status = 'Cancelled' WHERE sale_id = ?;", (sale_id,))

    # Reconcile customer total spent using net revenue
    if sale["customer_id"]:
        cursor.execute("""
        SELECT 
            COUNT(*) AS total_orders,
            COALESCE(SUM(
                s.grand_total - COALESCE((SELECT SUM(sr.total_refund_amount) FROM sale_returns sr WHERE sr.sale_id = s.id), 0.0)
            ), 0.0) AS total_spent
        FROM sales s 
        WHERE s.customer_id = ? AND s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED');
        """, (sale["customer_id"],))
        c_stats = cursor.fetchone()
        c_orders = c_stats["total_orders"]
        c_spent = round(c_stats["total_spent"], 2)

        tier = "Bronze"
        if c_spent >= 30000:
            tier = "Platinum"
        elif c_spent >= 15000:
            tier = "Gold"
        elif c_spent >= 5000:
            tier = "Silver"

        cursor.execute("UPDATE customers SET total_orders = ?, total_spent = ?, tier = ? WHERE id = ?;", (c_orders, c_spent, tier, sale["customer_id"]))

    log_audit(conn, "SALE", sale_id, "CANCEL", {"status": sale["sale_status"]}, {"status": "CANCELLED"}, reason, user_id)

    return {
        "success": True,
        "sale_id": sale_id,
        "invoice_number": sale["invoice_number"],
        "sale_status": "CANCELLED",
        "reason": reason,
        "cancelled_at": now
    }


def get_sale_details(conn: sqlite3.Connection, sale_id: Any) -> Optional[Dict[str, Any]]:
    """Retrieves full sale document with items, payments, returns, and delivery logs."""
    cursor = conn.cursor()
    if isinstance(sale_id, int) or (isinstance(sale_id, str) and sale_id.isdigit()):
        cursor.execute("SELECT * FROM sales WHERE id = ?;", (int(sale_id),))
    else:
        cursor.execute("SELECT * FROM sales WHERE invoice_number = ?;", (str(sale_id),))
    row = cursor.fetchone()
    if not row:
        return None

    sale = dict(row)
    s_id = sale["id"]
    cursor.execute("SELECT * FROM sale_items WHERE sale_id = ?;", (s_id,))
    sale["items"] = [dict(it) for it in cursor.fetchall()]

    cursor.execute("SELECT * FROM payments WHERE sale_id = ?;", (s_id,))
    sale["payments"] = [dict(p) for p in cursor.fetchall()]

    cursor.execute("SELECT * FROM sale_returns WHERE sale_id = ?;", (s_id,))
    sale["returns"] = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM invoice_delivery_logs WHERE sale_id = ?;", (s_id,))
    sale["delivery_logs"] = [dict(d) for d in cursor.fetchall()]

    cursor.execute("SELECT * FROM settings WHERE id = 1;")
    s_row = cursor.fetchone()
    sale["settings"] = dict(s_row) if s_row else {}

    return sale
