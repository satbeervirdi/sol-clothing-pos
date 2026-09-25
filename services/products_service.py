"""
Authoritative Products & Variants Service for SOL POS & CRM.
Enforces:
- Normalized Product -> Product Variant -> Inventory model
- Guaranteed unique SKUs and barcodes
- Single source of stock via inventory table
- Atomic product creation with opening stock ledger entries
- Zero fake/invented numbers
"""
import sqlite3
import io
import json
import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from PIL import Image
from fastapi import HTTPException

try:
    from google import genai
except ImportError:
    genai = None

from models import ProductCreate, ProductUpdate, VariantCreate, VariantUpdate
from services.audit_service import log_audit


def list_products(
    conn: sqlite3.Connection,
    search: Optional[str] = None,
    category: Optional[str] = None,
    low_stock_only: bool = False
) -> List[Dict[str, Any]]:
    """
    Lists all sellable product variants with authoritative stock from the inventory table.
    """
    cursor = conn.cursor()
    query = """
    SELECT 
        pv.id AS variant_id,
        pv.id AS id,
        p.id AS product_id,
        p.name,
        p.name AS product_name,
        pv.sku,
        pv.barcode,
        p.category,
        pv.size,
        pv.color,
        p.brand,
        pv.cost_price,
        pv.selling_price,
        pv.gst_rate,
        COALESCE(inv.stock_quantity, 0) AS stock_quantity,
        COALESCE(inv.stock_quantity, 0) AS available_stock,
        COALESCE(inv.low_stock_threshold, 5) AS low_stock_threshold,
        COALESCE(NULLIF(pv.image_url, ''), p.image_url, '') AS image_url,
        COALESCE(NULLIF(pv.image_url, ''), p.image_url, '') AS image,
        COALESCE((
            SELECT SUM(si.quantity - si.returned_quantity) 
            FROM sale_items si 
            JOIN sales s ON si.sale_id = s.id 
            WHERE (si.variant_id = pv.id OR (si.variant_id IS NULL AND si.sku = pv.sku)) 
              AND s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED')
        ), 0) AS units_sold
    FROM product_variants pv
    JOIN products p ON pv.product_id = p.id
    LEFT JOIN inventory inv ON inv.variant_id = pv.id
    WHERE 1=1
    """
    params = []

    if search:
        s = f"%{search.strip()}%"
        query += " AND (p.name LIKE ? OR pv.sku LIKE ? OR pv.barcode LIKE ? OR pv.color LIKE ? OR p.category LIKE ?)"
        params.extend([s, s, s, s, s])

    if category and category != "All":
        query += " AND p.category = ?"
        params.append(category)

    if low_stock_only:
        query += " AND COALESCE(inv.stock_quantity, 0) <= COALESCE(inv.low_stock_threshold, 5)"

    query += " ORDER BY p.name ASC, pv.size ASC"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]

    for r in rows:
        r["is_low_stock"] = r["stock_quantity"] <= r["low_stock_threshold"]
        r["is_out_of_stock"] = r["stock_quantity"] <= 0

    return rows


def get_categories(conn: sqlite3.Connection) -> List[str]:
    """Returns sorted distinct product categories."""
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != '' ORDER BY category ASC;")
    return [r[0] for r in cursor.fetchall()]


def lookup_by_code(conn: sqlite3.Connection, code: str) -> Dict[str, Any]:
    """
    Rapid barcode, SKU, or QR code lookup for POS cashier.
    Queries normalized product_variants joined with products and inventory.
    """
    cursor = conn.cursor()
    clean_code = code.strip()

    cursor.execute("""
    SELECT 
        pv.id AS variant_id,
        pv.id AS id,
        p.id AS product_id,
        pv.sku,
        pv.barcode,
        p.name AS product_name,
        p.name,
        p.category,
        pv.size,
        pv.color,
        p.brand,
        pv.cost_price,
        pv.selling_price,
        pv.gst_rate,
        COALESCE(inv.stock_quantity, 0) AS stock_quantity,
        COALESCE(inv.stock_quantity, 0) AS available_stock,
        COALESCE(inv.low_stock_threshold, 5) AS low_stock_threshold,
        COALESCE(NULLIF(pv.image_url, ''), p.image_url, '') AS image,
        COALESCE(NULLIF(pv.image_url, ''), p.image_url, '') AS image_url
    FROM product_variants pv
    JOIN products p ON pv.product_id = p.id
    LEFT JOIN inventory inv ON inv.variant_id = pv.id
    WHERE pv.barcode = ? OR pv.sku = ? OR pv.qr_data = ?
    LIMIT 1;
    """, (clean_code, clean_code, clean_code))
    row = cursor.fetchone()

    if not row:
        # Check case-insensitive SKU match as fallback
        cursor.execute("""
        SELECT 
            pv.id AS variant_id,
            pv.id AS id,
            p.id AS product_id,
            pv.sku,
            pv.barcode,
            p.name AS product_name,
            p.name,
            p.category,
            pv.size,
            pv.color,
            p.brand,
            pv.cost_price,
            pv.selling_price,
            pv.gst_rate,
            COALESCE(inv.stock_quantity, 0) AS stock_quantity,
            COALESCE(inv.stock_quantity, 0) AS available_stock,
            COALESCE(inv.low_stock_threshold, 5) AS low_stock_threshold,
            COALESCE(NULLIF(pv.image_url, ''), p.image_url, '') AS image,
            COALESCE(NULLIF(pv.image_url, ''), p.image_url, '') AS image_url
        FROM product_variants pv
        JOIN products p ON pv.product_id = p.id
        LEFT JOIN inventory inv ON inv.variant_id = pv.id
        WHERE UPPER(pv.sku) = UPPER(?)
        LIMIT 1;
        """, (clean_code,))
        row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"PRODUCT_NOT_FOUND: No garment found matching barcode/SKU '{clean_code}'.")

    v = dict(row)
    v["is_low_stock"] = v["stock_quantity"] <= v["low_stock_threshold"]
    v["is_out_of_stock"] = v["stock_quantity"] <= 0
    return v


def create_product(conn: sqlite3.Connection, p: ProductCreate, user_id: int = 1) -> Dict[str, Any]:
    """
    Atomic product creation (Section 4 & 5):
    1. Validates SKU is unique
    2. Inserts or attaches to parent product style
    3. Creates product_variant with size, color, selling_price, cost_price
    4. Creates inventory record
    5. Writes OPENING_STOCK immutable inventory_transactions record if initial stock > 0
    6. Logs audit record
    """
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    clean_sku = p.sku.strip()
    clean_barcode = p.barcode.strip() if p.barcode and p.barcode.strip() else clean_sku

    # Check for SKU collision in product_variants
    cursor.execute("SELECT id FROM product_variants WHERE sku = ?;", (clean_sku,))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail=f"DUPLICATE_SKU: SKU '{clean_sku}' already exists.")

    # Check for barcode collision in product_variants
    cursor.execute("SELECT id FROM product_variants WHERE barcode = ?;", (clean_barcode,))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail=f"DUPLICATE_BARCODE: Barcode '{clean_barcode}' already exists.")

    # Check if parent product already exists (by name and category), else create
    cursor.execute("SELECT id FROM products WHERE name = ? AND category = ?;", (p.name.strip(), p.category.strip()))
    prod_row = cursor.fetchone()

    if prod_row:
        product_id = prod_row["id"]
        # Update image if empty
        if p.image_url:
            cursor.execute("UPDATE products SET image_url = ? WHERE id = ? AND (image_url IS NULL OR image_url = '');", (p.image_url, product_id))
    else:
        cursor.execute("""
        INSERT INTO products (
            sku, barcode, name, category, size, color, brand,
            cost_price, selling_price, stock_quantity, low_stock_threshold,
            image_url, qr_data, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?);
        """, (
            clean_sku,
            clean_barcode,
            p.name.strip(),
            p.category.strip(),
            p.size.strip(),
            p.color.strip(),
            p.brand.strip() if p.brand else "SOL",
            p.cost_price,
            p.selling_price,
            p.low_stock_threshold,
            p.image_url or "",
            p.qr_data or clean_sku,
            now,
            now
        ))
        product_id = cursor.lastrowid

    # Create Product Variant
    cursor.execute("""
    INSERT INTO product_variants (
        product_id, sku, barcode, size, color, cost_price, selling_price,
        gst_rate, image_url, qr_data, created_at, updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, 5.0, ?, ?, ?, ?);
    """, (
        product_id,
        clean_sku,
        clean_barcode,
        p.size.strip(),
        p.color.strip(),
        p.cost_price,
        p.selling_price,
        p.image_url or "",
        p.qr_data or clean_sku,
        now,
        now
    ))
    variant_id = cursor.lastrowid

    # Create Inventory Record
    cursor.execute("""
    INSERT INTO inventory (variant_id, stock_quantity, low_stock_threshold, updated_at)
    VALUES (?, ?, ?, ?);
    """, (variant_id, p.stock_quantity, p.low_stock_threshold, now))

    # If initial stock > 0, write immutable opening stock ledger transaction (Section 7)
    if p.stock_quantity > 0:
        cursor.execute("""
        INSERT INTO inventory_transactions (
            type, variant_id, quantity_change, stock_before, stock_after,
            reference_type, reference_id, user_id, reason, note, timestamp, created_at
        )
        VALUES ('OPENING_STOCK', ?, ?, 0, ?, 'INITIAL', 'OPENING_STOCK', ?, 'Initial product creation', 'Initial product creation', ?, ?);
        """, (
            variant_id,
            p.stock_quantity,
            p.stock_quantity,
            user_id,
            now,
            now
        ))

    log_audit(conn, "PRODUCT", product_id, "CREATE", None, {
        "variant_id": variant_id,
        "name": p.name,
        "sku": clean_sku,
        "stock": p.stock_quantity,
        "selling_price": p.selling_price
    }, "New product registered", user_id)

    return lookup_by_code(conn, clean_sku)


def create_variant(conn: sqlite3.Connection, v: "VariantCreate", user_id: int = 1) -> Dict[str, Any]:
    """
    Creates an additional variant for an existing parent product.
    Creates variant, authoritative inventory record, and opening stock ledger transaction if initial_stock > 0.
    """
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    clean_sku = v.sku.strip()
    clean_barcode = v.barcode.strip() if v.barcode and v.barcode.strip() else clean_sku

    # Check parent product exists
    cursor.execute("SELECT id, name FROM products WHERE id = ?;", (v.product_id,))
    prod = cursor.fetchone()
    if not prod:
        raise HTTPException(status_code=404, detail=f"Product with id {v.product_id} not found.")

    # Check SKU collision
    cursor.execute("SELECT id FROM product_variants WHERE sku = ?;", (clean_sku,))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail=f"DUPLICATE_SKU: SKU '{clean_sku}' already exists.")

    # Check Barcode collision
    cursor.execute("SELECT id FROM product_variants WHERE barcode = ?;", (clean_barcode,))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail=f"DUPLICATE_BARCODE: Barcode '{clean_barcode}' already exists.")

    cursor.execute("""
    INSERT INTO product_variants (
        product_id, sku, barcode, size, color, cost_price, selling_price,
        gst_rate, image_url, qr_data, created_at, updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        v.product_id,
        clean_sku,
        clean_barcode,
        v.size.strip(),
        v.color.strip(),
        v.cost_price,
        v.selling_price,
        v.gst_rate,
        v.image_url or "",
        v.qr_data or clean_sku,
        now,
        now
    ))
    variant_id = cursor.lastrowid

    # Create Inventory Record
    cursor.execute("""
    INSERT INTO inventory (variant_id, stock_quantity, low_stock_threshold, updated_at)
    VALUES (?, ?, ?, ?);
    """, (variant_id, v.initial_stock, v.low_stock_threshold, now))

    if v.initial_stock > 0:
        cursor.execute("""
        INSERT INTO inventory_transactions (
            type, variant_id, quantity_change, stock_before, stock_after,
            reference_type, reference_id, user_id, reason, note, timestamp, created_at
        )
        VALUES ('OPENING_STOCK', ?, ?, 0, ?, 'INITIAL', 'OPENING_STOCK', ?, 'Initial variant creation', 'Initial variant creation', ?, ?);
        """, (
            variant_id,
            v.initial_stock,
            v.initial_stock,
            user_id,
            now,
            now
        ))

    log_audit(conn, "VARIANT", variant_id, "CREATE", None, {
        "product_id": v.product_id,
        "sku": clean_sku,
        "stock": v.initial_stock,
        "selling_price": v.selling_price
    }, "New variant registered", user_id)

    return lookup_by_code(conn, clean_sku)


def get_variant(conn: sqlite3.Connection, variant_id: int) -> Dict[str, Any]:
    """
    Retrieves a single sellable product variant by its primary key variant_id.
    """
    cursor = conn.cursor()
    cursor.execute("""
    SELECT 
        pv.id AS variant_id,
        pv.id AS id,
        p.id AS product_id,
        p.name,
        p.name AS product_name,
        pv.sku,
        pv.barcode,
        p.category,
        pv.size,
        pv.color,
        p.brand,
        pv.cost_price,
        pv.selling_price,
        pv.gst_rate,
        COALESCE(inv.stock_quantity, 0) AS stock_quantity,
        COALESCE(inv.stock_quantity, 0) AS available_stock,
        COALESCE(inv.low_stock_threshold, 5) AS low_stock_threshold,
        COALESCE(NULLIF(pv.image_url, ''), p.image_url, '') AS image_url,
        COALESCE(NULLIF(pv.image_url, ''), p.image_url, '') AS image,
        COALESCE((
            SELECT SUM(si.quantity - si.returned_quantity) 
            FROM sale_items si 
            JOIN sales s ON si.sale_id = s.id 
            WHERE (si.variant_id = pv.id OR (si.variant_id IS NULL AND si.sku = pv.sku)) 
              AND s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED')
        ), 0) AS units_sold
    FROM product_variants pv
    JOIN products p ON pv.product_id = p.id
    LEFT JOIN inventory inv ON inv.variant_id = pv.id
    WHERE pv.id = ?;
    """, (variant_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"VARIANT_NOT_FOUND: Variant with ID {variant_id} not found.")

    v = dict(row)
    v["is_low_stock"] = v["stock_quantity"] <= v["low_stock_threshold"]
    v["is_out_of_stock"] = v["stock_quantity"] <= 0
    return v


def update_variant(conn: sqlite3.Connection, variant_id: int, v: VariantUpdate, user_id: int = 1) -> Dict[str, Any]:
    """
    Updates a specific product variant and synchronizes parent product metadata (name, category, brand).
    """
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    cursor.execute("""
    SELECT pv.*, p.name AS product_name, p.category, p.brand 
    FROM product_variants pv 
    JOIN products p ON pv.product_id = p.id 
    WHERE pv.id = ?;
    """, (variant_id,))
    existing = cursor.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail=f"VARIANT_NOT_FOUND: Variant with ID {variant_id} not found.")

    old_state = dict(existing)
    product_id = existing["product_id"]

    # SKU update & collision check
    if v.sku is not None:
        clean_sku = v.sku.strip()
        if clean_sku != existing["sku"]:
            cursor.execute("SELECT id FROM product_variants WHERE sku = ? AND id != ?;", (clean_sku, variant_id))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail=f"DUPLICATE_SKU: SKU '{clean_sku}' already in use.")
            cursor.execute("UPDATE product_variants SET sku = ? WHERE id = ?;", (clean_sku, variant_id))

    # Barcode update & collision check
    if v.barcode is not None:
        clean_bc = v.barcode.strip()
        if clean_bc and clean_bc != existing["barcode"]:
            cursor.execute("SELECT id FROM product_variants WHERE barcode = ? AND id != ?;", (clean_bc, variant_id))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail=f"DUPLICATE_BARCODE: Barcode '{clean_bc}' already in use.")
            cursor.execute("UPDATE product_variants SET barcode = ? WHERE id = ?;", (clean_bc, variant_id))

    # Direct variant fields
    var_updates = []
    var_params = []
    for col, val in [("size", v.size), ("color", v.color), ("cost_price", v.cost_price), 
                     ("selling_price", v.selling_price), ("gst_rate", v.gst_rate), ("image_url", v.image_url)]:
        if val is not None:
            var_updates.append(f"{col} = ?")
            var_params.append(val.strip() if isinstance(val, str) else val)

    if var_updates:
        var_updates.append("updated_at = ?")
        var_params.append(now)
        var_params.append(variant_id)
        cursor.execute(f"UPDATE product_variants SET {', '.join(var_updates)} WHERE id = ?;", var_params)

    # Low stock threshold
    if v.low_stock_threshold is not None:
        cursor.execute("UPDATE inventory SET low_stock_threshold = ?, updated_at = ? WHERE variant_id = ?;", (v.low_stock_threshold, now, variant_id))

    # Update parent product fields if provided (name, category, brand)
    prod_updates = []
    prod_params = []
    for col, val in [("name", v.name), ("category", v.category), ("brand", v.brand)]:
        if val is not None:
            prod_updates.append(f"{col} = ?")
            prod_params.append(val.strip() if isinstance(val, str) else val)

    if prod_updates:
        prod_updates.append("updated_at = ?")
        prod_params.append(now)
        prod_params.append(product_id)
        cursor.execute(f"UPDATE products SET {', '.join(prod_updates)} WHERE id = ?;", prod_params)

    log_audit(conn, "VARIANT", variant_id, "UPDATE", old_state, v.model_dump(exclude_unset=True), "Variant updated", user_id)
    return get_variant(conn, variant_id)


def delete_variant(conn: sqlite3.Connection, variant_id: int, user_id: int = 1) -> Dict[str, Any]:
    """
    Safely deletes a single product variant and its inventory records.
    Blocks deletion if completed sales history references the variant (Section 13).
    If this was the parent product's last variant, removes the parent product as well.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM product_variants WHERE id = ?;", (variant_id,))
    var_row = cursor.fetchone()
    if not var_row:
        raise HTTPException(status_code=404, detail=f"VARIANT_NOT_FOUND: Variant with ID {variant_id} not found.")

    sku = var_row["sku"]
    product_id = var_row["product_id"]

    cursor.execute("""
    SELECT COUNT(*) 
    FROM sale_items 
    WHERE variant_id = ? OR sku = ?;
    """, (variant_id, sku))
    sales_count = cursor.fetchone()[0]

    if sales_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"CANNOT_DELETE_VARIANT: Variant '{sku}' (ID {variant_id}) has {sales_count} historical sales records. Retail POS rules prohibit deleting sold variants."
        )

    cursor.execute("DELETE FROM inventory_transactions WHERE variant_id = ?;", (variant_id,))
    cursor.execute("DELETE FROM inventory WHERE variant_id = ?;", (variant_id,))
    cursor.execute("DELETE FROM product_variants WHERE id = ?;", (variant_id,))

    # If parent product has no remaining variants, delete parent product as well
    cursor.execute("SELECT COUNT(*) FROM product_variants WHERE product_id = ?;", (product_id,))
    remaining_variants = cursor.fetchone()[0]
    deleted_parent = False
    if remaining_variants == 0:
        cursor.execute("DELETE FROM products WHERE id = ?;", (product_id,))
        deleted_parent = True

    log_audit(conn, "VARIANT", variant_id, "DELETE", {"sku": sku, "deleted_parent": deleted_parent}, None, "Variant deleted", user_id)
    return {"success": True, "deleted_variant_id": variant_id, "deleted_parent": deleted_parent}


def update_product(conn: sqlite3.Connection, product_id: int, p: ProductUpdate, user_id: int = 1) -> Dict[str, Any]:
    """Updates parent product details and synchronizes variants."""
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    cursor.execute("SELECT * FROM products WHERE id = ?;", (product_id,))
    existing = cursor.fetchone()
    if not existing:
        # Check if product_id is actually a variant_id for backward compatibility
        cursor.execute("SELECT product_id FROM product_variants WHERE id = ?;", (product_id,))
        vr = cursor.fetchone()
        if vr and vr["product_id"]:
            product_id = vr["product_id"]
            cursor.execute("SELECT * FROM products WHERE id = ?;", (product_id,))
            existing = cursor.fetchone()

    if not existing:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND: Product not found.")

    old_state = dict(existing)
    updates = []
    params = []

    fields = [
        ("name", p.name),
        ("category", p.category),
        ("brand", p.brand),
        ("image_url", p.image_url)
    ]

    for col, val in fields:
        if val is not None:
            updates.append(f"{col} = ?")
            params.append(val.strip() if isinstance(val, str) else val)

    if updates:
        updates.append("updated_at = ?")
        params.append(now)
        params.append(product_id)
        cursor.execute(f"UPDATE products SET {', '.join(updates)} WHERE id = ?;", params)

    # If selling price or cost price updated, update the variants of this product
    if p.selling_price is not None:
        cursor.execute("UPDATE product_variants SET selling_price = ?, updated_at = ? WHERE product_id = ?;", (p.selling_price, now, product_id))
    if p.cost_price is not None:
        cursor.execute("UPDATE product_variants SET cost_price = ?, updated_at = ? WHERE product_id = ?;", (p.cost_price, now, product_id))
    if p.low_stock_threshold is not None:
        cursor.execute("""
        UPDATE inventory 
        SET low_stock_threshold = ?, updated_at = ?
        WHERE variant_id IN (SELECT id FROM product_variants WHERE product_id = ?);
        """, (p.low_stock_threshold, now, product_id))

    log_audit(conn, "PRODUCT", product_id, "UPDATE", old_state, p.model_dump(exclude_unset=True), "Product updated", user_id)

    cursor.execute("SELECT * FROM products WHERE id = ?;", (product_id,))
    return dict(cursor.fetchone())


def delete_product(conn: sqlite3.Connection, product_id: int, user_id: int = 1) -> Dict[str, Any]:
    """
    Safely deletes a product and its variants.
    Blocks deletion if completed sales history references the product (Section 13).
    """
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM products WHERE id = ?;", (product_id,))
    existing = cursor.fetchone()
    if not existing:
        # Check if product_id is actually a variant_id
        cursor.execute("SELECT id FROM product_variants WHERE id = ?;", (product_id,))
        if cursor.fetchone():
            return delete_variant(conn, product_id, user_id)
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND: Product not found.")

    cursor.execute("""
    SELECT COUNT(*) 
    FROM sale_items si
    WHERE si.product_id = ? OR si.variant_id IN (SELECT id FROM product_variants WHERE product_id = ?);
    """, (product_id, product_id))
    sales_count = cursor.fetchone()[0]

    if sales_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"CANNOT_DELETE_PRODUCT: Product ID {product_id} has {sales_count} historical sales records. Retail POS rules prohibit deleting sold products."
        )

    cursor.execute("SELECT id FROM product_variants WHERE product_id = ?;", (product_id,))
    var_ids = [r[0] for r in cursor.fetchall()]

    for vid in var_ids:
        cursor.execute("DELETE FROM inventory_transactions WHERE variant_id = ?;", (vid,))
        cursor.execute("DELETE FROM inventory WHERE variant_id = ?;", (vid,))
        cursor.execute("DELETE FROM product_variants WHERE id = ?;", (vid,))

    cursor.execute("DELETE FROM products WHERE id = ?;", (product_id,))
    log_audit(conn, "PRODUCT", product_id, "DELETE", {"deleted_variants": var_ids}, None, "Product deleted", user_id)

    return {"success": True, "deleted_id": product_id}


def analyze_garment_visual(image_bytes: bytes, filename: str = "garment.jpg") -> Dict[str, Any]:
    """
    Visual garment classification.
    Uses Gemini Vision if configured, else robust PIL-based palette classification.
    No fake or random numbers.
    """
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if genai and gemini_key and not gemini_key.startswith("_KEY_EXPOSED"):
        try:
            client = genai.Client()
            prompt = (
                "You are an expert high-fashion merchandiser for the clothing brand 'SOL • Soul of Lifestyle'. "
                "Analyze this garment photo and output a JSON object with these exact keys:\n"
                "- 'detected_name': A luxury apparel name (e.g. 'SOL Oversized Graphic Tee', 'SOL Structured Oxford Shirt')\n"
                "- 'category': One of ['Shirts', 'T-Shirts', 'Denim & Jeans', 'Jackets', 'Trousers', 'Dresses', 'Ethnic Wear', 'Accessories']\n"
                "- 'color': Dominant stylish color name (e.g. 'Jet Black', 'Crisp White', 'Indigo Blue', 'Oatmeal Beige')\n"
                "- 'suggested_selling_price': Standard retail price in INR (e.g. 1499.0, 1999.0)\n"
                "- 'suggested_cost_price': Standard wholesale cost in INR (e.g. 600.0, 800.0)\n"
                "- 'suggested_sizes': Array of common sizes for this garment (e.g. ['S', 'M', 'L', 'XL'])\n"
                "Return ONLY raw JSON, without markdown formatting or code blocks."
            )
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    genai.types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    prompt
                ]
            )
            text = resp.text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text.strip())
            data["analysis_source"] = "gemini_vision"
            return data
        except Exception:
            pass

    # PIL-based classification
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        small = img.resize((32, 32), Image.Resampling.BOX)
        pixels = list(small.getdata())
        avg_r = sum(p[0] for p in pixels) // len(pixels)
        avg_g = sum(p[1] for p in pixels) // len(pixels)
        avg_b = sum(p[2] for p in pixels) // len(pixels)

        brightness = (avg_r * 299 + avg_g * 587 + avg_b * 114) // 1000
        if brightness < 45:
            color = "Jet Black"
        elif brightness > 215:
            color = "Crisp White"
        elif avg_r > avg_g + 25 and avg_r > avg_b + 25:
            color = "Crimson Red" if brightness < 120 else "Rose Peach"
        elif avg_b > avg_r + 20 and avg_b > avg_g:
            color = "Navy Blue" if brightness < 100 else "Sky Blue"
        elif avg_g > avg_r + 10 and avg_g > avg_b + 10:
            color = "Olive Drab" if brightness < 110 else "Sage Green"
        elif avg_r > 130 and avg_g > 110 and avg_b < 100:
            color = "Khaki Sand" if brightness > 150 else "Camel Tan"
        else:
            color = "Heather Grey" if brightness > 110 else "Charcoal"

        w, h = img.size
        ratio = h / w
        if ratio > 1.4:
            category = "Dresses"
            name = f"SOL Elegance {color} Dress"
            sizes = ["XS", "S", "M", "L"]
        elif ratio > 1.15:
            category = "Shirts"
            name = f"SOL Premium {color} Shirt"
            sizes = ["S", "M", "L", "XL"]
        elif ratio < 0.8:
            category = "Accessories"
            name = f"SOL Signature {color} Essential"
            sizes = ["Free Size"]
        else:
            category = "T-Shirts"
            name = f"SOL Heavyweight {color} Tee"
            sizes = ["S", "M", "L", "XL"]

        return {
            "detected_name": name,
            "category": category,
            "color": color,
            "suggested_sizes": sizes,
            "analysis_source": "smart_classifier"
        }
    except Exception:
        return {
            "detected_name": "SOL Garment Style",
            "category": "Shirts",
            "color": "Standard",
            "suggested_sizes": ["S", "M", "L", "XL"],
            "analysis_source": "fallback"
        }
