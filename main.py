"""
SOL • Soul of Lifestyle POS & CRM - Main Application Server
High-concurrency, normalized retail operating system with:
- Authoritative backend pricing and Decimal precision billing
- Concurrency-safe atomic conditional stock decrement
- Immutable inventory transaction ledger
- Verified customer CRM metrics derived from completed sales
- Zero fake/demo/mock numbers
"""
import os
import io
import csv
import json
import sqlite3
import base64
import uuid
import time
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, StreamingResponse

from database import get_db, get_db_transaction, init_db, DB_PATH
from models import (
    ProductCreate, ProductUpdate, VariantCreate, VariantUpdate,
    StockInRequest, StockAdjustRequest,
    CustomerCreate, CustomerUpdate,
    InvoiceCreate, BillCalculationRequest, SaleReturnRequest, SaleCancelRequest,
    DeliveryRetryRequest, SettingsUpdate, EmailRequest, ImageAnalysisRequest
)
from services import (
    products_service,
    inventory_service,
    sales_service,
    customers_service,
    invoice_service,
    notification_service,
    reporting_service,
    audit_service
)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="SOL • Soul of Lifestyle POS & CRM", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------- Products & Variants API -----------------

@app.get("/api/products")
def list_products(
    search: Optional[str] = None,
    category: Optional[str] = None,
    low_stock_only: bool = False
):
    conn = get_db()
    try:
        return products_service.list_products(conn, search, category, low_stock_only)
    finally:
        conn.close()


@app.get("/api/products/categories")
def get_categories():
    conn = get_db()
    try:
        return products_service.get_categories(conn)
    finally:
        conn.close()


@app.get("/api/products/lookup/{code}")
def lookup_product_by_scan(code: str):
    conn = get_db()
    try:
        return products_service.lookup_by_code(conn, code)
    finally:
        conn.close()


@app.post("/api/products")
def create_product(p: ProductCreate):
    with get_db_transaction() as conn:
        return products_service.create_product(conn, p)


@app.post("/api/variants")
def create_variant_endpoint(v: VariantCreate):
    with get_db_transaction() as conn:
        return products_service.create_variant(conn, v)


@app.post("/api/products/{product_id}/variants")
def create_product_variant_endpoint(product_id: int, v: VariantCreate):
    with get_db_transaction() as conn:
        v.product_id = product_id
        return products_service.create_variant(conn, v)


@app.get("/api/variants/{variant_id}")
def get_variant_endpoint(variant_id: int):
    conn = get_db()
    try:
        return products_service.get_variant(conn, variant_id)
    finally:
        conn.close()


@app.put("/api/variants/{variant_id}")
def update_variant_endpoint(variant_id: int, v: VariantUpdate):
    with get_db_transaction() as conn:
        return products_service.update_variant(conn, variant_id, v)


@app.delete("/api/variants/{variant_id}")
def delete_variant_endpoint(variant_id: int):
    with get_db_transaction() as conn:
        return products_service.delete_variant(conn, variant_id)


@app.post("/api/variants/{variant_id}/adjust-stock")
def adjust_variant_stock(variant_id: int, adj: StockAdjustRequest):
    with get_db_transaction() as conn:
        return inventory_service.adjust_stock(
            conn, variant_id, adj.quantity_change, adj.reason, adj.note or ""
        )


@app.put("/api/products/{product_id}")
def update_product(product_id: int, p: ProductUpdate):
    with get_db_transaction() as conn:
        return products_service.update_product(conn, product_id, p)


@app.delete("/api/products/{product_id}")
def delete_product(product_id: int):
    with get_db_transaction() as conn:
        return products_service.delete_product(conn, product_id)


@app.post("/api/products/upload-and-analyze")
async def upload_and_analyze_garment(req: ImageAnalysisRequest):
    try:
        raw_b64 = req.image_data
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]

        image_bytes = base64.b64decode(raw_b64)

        # Optimize and save image with PIL
        from PIL import Image as PILImage
        img = PILImage.open(io.BytesIO(image_bytes))
        if img.mode in ("RGBA", "P"):
            background = PILImage.new("RGB", img.size, (255, 255, 255))
            if img.mode == "RGBA":
                background.paste(img, mask=img.split()[3])
            else:
                background.paste(img)
            img = background
        else:
            img = img.convert("RGB")

        max_dim = 1200
        if img.width > max_dim or img.height > max_dim:
            img.thumbnail((max_dim, max_dim), PILImage.Resampling.LANCZOS)

        file_hash = uuid.uuid4().hex[:6]
        filename = f"prod_{int(time.time())}_{file_hash}.jpg"
        upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "uploads", "products")
        os.makedirs(upload_dir, exist_ok=True)
        save_path = os.path.join(upload_dir, filename)
        img.save(save_path, "JPEG", quality=88, optimize=True)

        rel_url = f"/static/uploads/products/{filename}"
        analysis = products_service.analyze_garment_visual(image_bytes, filename)

        cat_clean = analysis.get("category", "GEN")[:3].upper().replace(" ", "").replace("-", "")
        col_clean = analysis.get("color", "STD")[:3].upper().replace(" ", "").replace("-", "")
        
        # Clean sequential / deterministic SKU format instead of random numbers
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM product_variants WHERE sku LIKE ?;", (f"SOL-{cat_clean}-{col_clean}-%",))
        var_count = cur.fetchone()[0] + 1
        conn.close()

        sku = f"SOL-{cat_clean}-{col_clean}-{var_count:03d}"
        barcode = sku.replace("-", "")

        return {
            "success": True,
            "image_url": rel_url,
            "detected_name": analysis.get("detected_name", "SOL Garment"),
            "category": analysis.get("category", "General"),
            "color": analysis.get("color", "Standard"),
            "suggested_sizes": analysis.get("suggested_sizes", ["S", "M", "L", "XL"]),
            "sku_suggestion": sku,
            "barcode_suggestion": barcode,
            "analysis_source": analysis.get("analysis_source", "smart_classifier")
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Image upload/analysis failed: {str(e)}")


# ----------------- Authoritative Inventory API -----------------

@app.post("/api/inventory/stock-in")
def receive_stock(req: StockInRequest):
    with get_db_transaction() as conn:
        return inventory_service.stock_in(
            conn, req.variant_id, req.quantity, req.unit_cost, req.reference, req.reason
        )


@app.post("/api/inventory/adjust")
def adjust_inventory(req: StockAdjustRequest):
    if not req.variant_id:
        raise HTTPException(status_code=400, detail="variant_id is required.")
    with get_db_transaction() as conn:
        return inventory_service.adjust_stock(
            conn, req.variant_id, req.quantity_change, req.reason, req.note or ""
        )


@app.post("/api/products/{product_id}/adjust-stock")
def legacy_adjust_stock(product_id: int, adj: StockAdjustRequest):
    """
    Backward-compatible stock adjustment endpoint.
    Resolves variant from product_id and records immutable inventory transaction.
    """
    with get_db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM product_variants WHERE product_id = ? LIMIT 1;", (product_id,))
        vr = cursor.fetchone()
        if not vr:
            # Check if product_id is already a variant_id
            cursor.execute("SELECT id FROM product_variants WHERE id = ?;", (product_id,))
            vr = cursor.fetchone()

        if not vr:
            raise HTTPException(status_code=404, detail="Product variant not found.")

        variant_id = vr["id"]
        return inventory_service.adjust_stock(
            conn, variant_id, adj.quantity_change, adj.reason, adj.note or ""
        )


@app.get("/api/inventory/transactions")
def get_inventory_transactions(
    variant_id: Optional[int] = None,
    tx_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    conn = get_db()
    try:
        return inventory_service.get_inventory_ledger(conn, variant_id, tx_type, limit, offset)
    finally:
        conn.close()


@app.get("/api/inventory/reconcile")
@app.get("/api/audit/reconcile")
def reconcile_inventory_data():
    conn = get_db()
    try:
        inv_recon = inventory_service.reconcile_inventory(conn)

        # Sales vs Sale Items reconciliation
        cursor = conn.cursor()
        cursor.execute("""
        SELECT 
            s.id, s.invoice_number, s.subtotal, s.grand_total,
            COALESCE(SUM(si.line_total), 0.0) AS calc_subtotal
        FROM sales s
        LEFT JOIN sale_items si ON s.id = si.sale_id
        GROUP BY s.id;
        """)
        sales_discrepancies = []
        for r in cursor.fetchall():
            if round(r["subtotal"] - r["calc_subtotal"], 2) != 0:
                sales_discrepancies.append(dict(r))

        # Customers spending reconciliation
        cursor.execute("""
        SELECT 
            c.id, c.name, c.phone, c.total_spent AS stored_spent,
            COALESCE((SELECT ROUND(SUM(
                s.grand_total - COALESCE((SELECT SUM(sr.total_refund_amount) FROM sale_returns sr WHERE sr.sale_id = s.id), 0.0)
            ), 2) FROM sales s WHERE s.customer_id = c.id AND s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED')), 0.0) AS real_spent
        FROM customers c;
        """)
        crm_discrepancies = []
        for r in cursor.fetchall():
            if round(r["stored_spent"] - r["real_spent"], 2) != 0:
                crm_discrepancies.append(dict(r))

        return {
            "status": "HEALTHY" if (inv_recon["discrepancy_count"] == 0 and len(sales_discrepancies) == 0 and len(crm_discrepancies) == 0) else "DISCREPANCIES_DETECTED",
            "inventory_reconciliation": inv_recon,
            "sales_vs_items_discrepancies": sales_discrepancies,
            "customer_metrics_discrepancies": crm_discrepancies
        }
    finally:
        conn.close()


# ----------------- Customers CRM API -----------------

@app.get("/api/customers/search")
def search_customers(q: str = Query(...)):
    conn = get_db()
    try:
        return customers_service.search_customers(conn, q)
    finally:
        conn.close()


@app.get("/api/customers")
def list_customers(search: Optional[str] = None):
    conn = get_db()
    try:
        return customers_service.list_customers(conn, search)
    finally:
        conn.close()


@app.get("/api/customers/{customer_id}")
def get_customer(customer_id: int):
    conn = get_db()
    try:
        return customers_service.get_customer(conn, customer_id)
    finally:
        conn.close()


@app.post("/api/customers")
def create_customer(c: CustomerCreate):
    with get_db_transaction() as conn:
        return customers_service.create_customer(conn, c)


@app.put("/api/customers/{customer_id}")
def update_customer(customer_id: int, c: CustomerUpdate):
    with get_db_transaction() as conn:
        return customers_service.update_customer(conn, customer_id, c)


# ----------------- Invoices & Sales Billing API -----------------

@app.post("/api/sales/calculate")
def preview_calculate_bill(req: BillCalculationRequest):
    """
    Authoritative bill preview calculation endpoint.
    Frontend calls this to get backend-computed taxes, discounts, and totals without saving.
    """
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT default_tax_rate FROM settings WHERE id = 1;")
        s_row = cursor.fetchone()
        tax_rate = req.tax_rate if req.tax_rate is not None else (s_row["default_tax_rate"] if s_row else 5.0)

        items_dict = [it.model_dump() for it in req.items]
        return sales_service.calculate_bill_totals(
            items_dict,
            discount_type=req.discount_type,
            discount_val=req.discount_val,
            tax_rate=tax_rate
        )
    finally:
        conn.close()


@app.post("/api/invoices")
@app.post("/api/sales/checkout")
def create_invoice(inv: InvoiceCreate, background_tasks: BackgroundTasks):
    """
    Atomic Checkout Operation:
    - Concurrency-safe atomic conditional stock decrement
    - Authoritative Decimal monetary calculation
    - Collision-free sequential invoice numbering
    - Single transaction commit
    - Non-blocking WhatsApp and Email delivery dispatch
    """
    with get_db_transaction() as conn:
        created_sale = sales_service.checkout(conn, inv, user_id=1)

    # Non-blocking post-sale delivery
    cust_phone = created_sale.get("customer_phone", "")
    cust_name = created_sale.get("customer_name", "Walk-in Guest")
    inv_number = created_sale["invoice_number"]
    grand_total = created_sale["grand_total"]

    whatsapp_status = "NOT_PROVIDED"
    whatsapp_url = ""
    email_status = "NOT_PROVIDED"

    if cust_phone:
        whatsapp_url = notification_service.build_whatsapp_link(
            cust_phone, cust_name, inv_number, grand_total
        )
        whatsapp_status = "SENT"
        try:
            conn_log = get_db()
            conn_log.execute("""
            INSERT INTO invoice_delivery_logs (sale_id, channel, recipient, status, error_message, sent_at)
            VALUES (?, 'WHATSAPP', ?, 'SENT', '', datetime('now'));
            """, (created_sale["id"], cust_phone))
            conn_log.commit()
            conn_log.close()
        except Exception:
            pass

    cust_email = created_sale.get("customer_email", "")
    if cust_email:
        conn_set = get_db()
        cursor_set = conn_set.cursor()
        cursor_set.execute("SELECT gmail_sender, gmail_app_password FROM settings WHERE id = 1;")
        s_row = cursor_set.fetchone()
        conn_set.close()

        if s_row and s_row["gmail_sender"] and s_row["gmail_app_password"]:
            pdf_buf = invoice_service.generate_invoice_pdf_buffer(created_sale, created_sale.get("settings", {}))
            background_tasks.add_task(
                notification_service.dispatch_invoice_email_task,
                s_row["gmail_sender"],
                s_row["gmail_app_password"],
                cust_email,
                inv_number,
                pdf_buf.getvalue(),
                created_sale["id"]
            )
            email_status = "SENT"
        else:
            email_status = "PENDING_SMTP_CONFIG"

        try:
            conn_log = get_db()
            conn_log.execute("""
            INSERT INTO invoice_delivery_logs (sale_id, channel, recipient, status, error_message, sent_at)
            VALUES (?, 'EMAIL', ?, ?, '', datetime('now'));
            """, (created_sale["id"], cust_email, email_status))
            conn_log.commit()
            conn_log.close()
        except Exception:
            pass

    # Check Google Sheets Webhook
    conn_sheets = get_db()
    cur_sh = conn_sheets.cursor()
    cur_sh.execute("SELECT google_sheets_webhook_url FROM settings WHERE id = 1;")
    sh_row = cur_sh.fetchone()
    conn_sheets.close()
    if sh_row and sh_row["google_sheets_webhook_url"]:
        background_tasks.add_task(
            notification_service.sync_invoice_to_google_sheets,
            created_sale,
            sh_row["google_sheets_webhook_url"]
        )

    created_sale["whatsapp_status"] = whatsapp_status
    created_sale["whatsapp_url"] = whatsapp_url
    created_sale["email_status"] = email_status
    return created_sale


@app.post("/api/sales/{sale_id}/return")
def return_sale(sale_id: int, req: SaleReturnRequest):
    with get_db_transaction() as conn:
        return sales_service.process_sale_return(conn, sale_id, req, user_id=1)


@app.post("/api/sales/{sale_id}/cancel")
def cancel_sale(sale_id: int, req: SaleCancelRequest):
    with get_db_transaction() as conn:
        return sales_service.cancel_sale(conn, sale_id, req.reason, user_id=1)


@app.get("/api/invoices")
@app.get("/api/sales")
def list_sales(limit: int = 50, search: Optional[str] = None):
    conn = get_db()
    try:
        cursor = conn.cursor()
        query = "SELECT * FROM sales WHERE 1=1"
        params = []
        if search:
            s = f"%{search.strip()}%"
            query += " AND (invoice_number LIKE ? OR customer_name LIKE ? OR customer_phone LIKE ?)"
            params.extend([s, s, s])
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        sales = [dict(r) for r in cursor.fetchall()]

        for s in sales:
            cursor.execute("SELECT COUNT(*) as item_count, COALESCE(SUM(quantity), 0) as total_qty FROM sale_items WHERE sale_id = ?;", (s["id"],))
            stats = cursor.fetchone()
            s["item_count"] = stats["item_count"]
            s["total_qty"] = stats["total_qty"]

        return sales
    finally:
        conn.close()


@app.get("/api/invoices/{invoice_id}")
@app.get("/api/sales/{invoice_id}")
def get_sale(invoice_id: str):
    conn = get_db()
    try:
        sale = sales_service.get_sale_details(conn, invoice_id)
        if not sale:
            raise HTTPException(status_code=404, detail="Invoice / Sale not found.")
        return sale
    finally:
        conn.close()


@app.get("/api/invoices/{invoice_id}/pdf")
@app.get("/api/sales/{sale_id}/pdf")
def get_sale_invoice_pdf(invoice_id: str):
    conn = get_db()
    try:
        sale = sales_service.get_sale_details(conn, invoice_id)
        if not sale:
            raise HTTPException(status_code=404, detail="Invoice not found.")

        cursor = conn.cursor()
        cursor.execute("SELECT * FROM settings WHERE id = 1;")
        settings = dict(cursor.fetchone())

        buf = invoice_service.generate_invoice_pdf_buffer(sale, settings)
        filename = f"{sale.get('invoice_number', 'SOL-INV')}.pdf"
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename={filename}"}
        )
    finally:
        conn.close()


@app.post("/api/invoices/{invoice_id}/retry-delivery")
def retry_invoice_delivery(invoice_id: str, req: DeliveryRetryRequest, background_tasks: BackgroundTasks):
    conn = get_db()
    try:
        sale = sales_service.get_sale_details(conn, invoice_id)
        if not sale:
            raise HTTPException(status_code=404, detail="Invoice not found.")

        if req.channel.upper() == "WHATSAPP":
            phone = sale.get("customer_phone")
            if not phone:
                raise HTTPException(status_code=400, detail="No customer phone attached to invoice.")
            wa_url = notification_service.build_whatsapp_link(
                phone, sale.get("customer_name", "Guest"), sale["invoice_number"], sale["grand_total"]
            )
            with conn:
                conn.execute("""
                INSERT INTO invoice_delivery_logs (sale_id, channel, recipient, status, sent_at)
                VALUES (?, 'WHATSAPP', ?, 'SENT', datetime('now'));
                """, (invoice_id, phone))
            return {"status": "SUCCESS", "channel": "WHATSAPP", "url": wa_url}

        elif req.channel.upper() == "EMAIL":
            email = sale.get("customer_email")
            if not email:
                raise HTTPException(status_code=400, detail="No customer email attached to invoice.")
            cursor = conn.cursor()
            cursor.execute("SELECT gmail_sender, gmail_app_password FROM settings WHERE id = 1;")
            s = cursor.fetchone()
            if not s or not s["gmail_sender"] or not s["gmail_app_password"]:
                raise HTTPException(status_code=400, detail="Gmail SMTP credentials not configured in Settings.")

            cursor.execute("SELECT * FROM settings WHERE id = 1;")
            settings = dict(cursor.fetchone())
            pdf_buf = invoice_service.generate_invoice_pdf_buffer(sale, settings)

            background_tasks.add_task(
                notification_service.dispatch_invoice_email_task,
                s["gmail_sender"],
                s["gmail_app_password"],
                email,
                sale["invoice_number"],
                pdf_buf.getvalue(),
                invoice_id
            )
            return {"status": "SENT", "channel": "EMAIL", "recipient": email}

        raise HTTPException(status_code=400, detail="Invalid channel. Choose 'WHATSAPP' or 'EMAIL'.")
    finally:
        conn.close()


@app.post("/api/invoices/{invoice_id}/send-email")
def send_custom_invoice_email(invoice_id: int, req: EmailRequest):
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sales WHERE id = ?;", (invoice_id,))
        sale = cursor.fetchone()
        if not sale:
            raise HTTPException(status_code=404, detail="Invoice not found.")

        cursor.execute("SELECT * FROM settings WHERE id = 1;")
        settings = cursor.fetchone()
        sender = settings["gmail_sender"] if settings else ""
        app_pw = settings["gmail_app_password"] if settings else ""

        if not sender or not app_pw:
            return {
                "sent": False,
                "mode": "web_compose",
                "message": "Gmail credentials not configured in settings."
            }

        # Direct synchronous dispatch for immediate feedback
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["Subject"] = req.subject or f"Receipt for Invoice {sale['invoice_number']} - SOL Soul of Lifestyle"
        msg["From"] = f"SOL Soul of Lifestyle <{sender}>"
        msg["To"] = req.recipient_email
        html_content = req.body_html or f"<p>Thank you for shopping at SOL Soul of Lifestyle.<br>Invoice: {sale['invoice_number']}<br>Grand Total: ₹{sale['grand_total']:.2f}</p>"
        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(sender, app_pw)
            server.sendmail(sender, req.recipient_email, msg.as_string())

        return {"sent": True, "recipient": req.recipient_email}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")
    finally:
        conn.close()


# ----------------- Sold Products & Analytics API -----------------

@app.get("/api/sales/sold-products")
def get_sold_products():
    conn = get_db()
    try:
        return reporting_service.get_sold_products_breakdown(conn)
    finally:
        conn.close()


@app.get("/api/analytics/dashboard")
def get_analytics_dashboard():
    conn = get_db()
    try:
        return reporting_service.get_analytics_dashboard(conn)
    finally:
        conn.close()


# ----------------- Data Export, Backup & CSV Import -----------------

@app.get("/api/export/csv/{entity}")
def export_csv(entity: str):
    conn = get_db()
    try:
        cursor = conn.cursor()
        output = io.StringIO()
        writer = csv.writer(output)

        if entity == "invoices" or entity == "sales":
            writer.writerow(["Invoice #", "Date", "Customer Name", "Customer Phone", "Items Summary", "Subtotal", "Discount", "Tax", "Grand Total", "Payment Method", "Status", "Notes"])
            cursor.execute("SELECT * FROM sales ORDER BY id DESC;")
            sales = cursor.fetchall()
            for s in sales:
                cursor.execute("SELECT product_name, size, color, quantity, unit_price, line_total FROM sale_items WHERE sale_id = ?;", (s["id"],))
                items = cursor.fetchall()
                items_str = " | ".join([f"{it['product_name']} ({it['size']}/{it['color']}) x{it['quantity']} = {it['line_total']}" for it in items])
                writer.writerow([
                    s["invoice_number"], s["created_at"], s["customer_name"], s["customer_phone"],
                    items_str, s["subtotal"], s["discount_amount"], s["tax_amount"], s["grand_total"],
                    s["payment_method"], s["sale_status"], s["notes"]
                ])
            filename = f"SOL_Sales_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        elif entity == "products":
            writer.writerow(["Product Name", "SKU", "Barcode", "Category", "Size", "Color", "Brand", "Cost Price", "Selling Price", "Stock Quantity", "Low Stock Limit"])
            cursor.execute("""
            SELECT p.name, pv.sku, pv.barcode, p.category, pv.size, pv.color, p.brand, pv.cost_price, pv.selling_price, COALESCE(inv.stock_quantity, 0), COALESCE(inv.low_stock_threshold, 5)
            FROM product_variants pv
            JOIN products p ON pv.product_id = p.id
            LEFT JOIN inventory inv ON inv.variant_id = pv.id
            ORDER BY p.name ASC, pv.size ASC;
            """)
            for p in cursor.fetchall():
                writer.writerow(list(p))
            filename = f"SOL_Inventory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        elif entity == "customers":
            writer.writerow(["Customer Name", "Phone", "Email", "City", "Loyalty Tier", "Total Spent", "Total Orders", "Loyalty Points", "Last Visit", "Notes"])
            customers = customers_service.list_customers(conn)
            for c in customers:
                writer.writerow([
                    c["name"], c["phone"], c["email"], c["city"], c["tier"],
                    c["total_spent"], c["total_orders"], c["loyalty_points"], c["last_visit"], c["notes"]
                ])
            filename = f"SOL_Customers_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        else:
            raise HTTPException(status_code=400, detail="Invalid entity for CSV export. Options: sales, products, customers")

        output.seek(0)
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    finally:
        conn.close()


@app.post("/api/import/csv/products")
async def import_products_csv(request: Request):
    """
    Transactional, audited merchandise import via CSV (Section 21).
    Validates all rows, creates parent products, variants, inventory, and opening stock ledger records.
    """
    contents = await request.body()
    try:
        decoded = contents.decode("utf-8-sig")
    except Exception:
        decoded = contents.decode("latin-1")

    reader = csv.DictReader(io.StringIO(decoded))
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        imported_count = 0
        updated_count = 0

        with conn:
            cursor = conn.cursor()
            for row in reader:
                row_lower = {str(k).strip().lower(): str(v).strip() for k, v in row.items() if k}
                name = row_lower.get("product name") or row_lower.get("name") or row_lower.get("title")
                sku = row_lower.get("sku") or row_lower.get("code")

                if not name or not sku:
                    continue

                category = row_lower.get("category") or "General"
                size = row_lower.get("size") or "Free Size"
                color = row_lower.get("color") or "Standard"
                brand = row_lower.get("brand") or "SOL"
                barcode = row_lower.get("barcode") or sku

                try:
                    cost_price = max(0.0, float(row_lower.get("cost price", 0) or row_lower.get("cost", 0) or 0))
                except ValueError:
                    cost_price = 0.0

                try:
                    selling_price = max(0.0, float(row_lower.get("selling price", 0) or row_lower.get("price", 0) or row_lower.get("mrp", 0) or 0))
                except ValueError:
                    selling_price = 0.0

                try:
                    stock = max(0, int(row_lower.get("stock quantity", 0) or row_lower.get("stock", 0) or row_lower.get("qty", 0) or 0))
                except ValueError:
                    stock = 0

                try:
                    low_thresh = max(0, int(row_lower.get("low stock limit", 5) or 5))
                except ValueError:
                    low_thresh = 5

                # Check if variant already exists
                cursor.execute("SELECT id, product_id FROM product_variants WHERE sku = ?;", (sku,))
                v_existing = cursor.fetchone()

                if v_existing:
                    v_id = v_existing["id"]
                    p_id = v_existing["product_id"]
                    cursor.execute("""
                    UPDATE product_variants 
                    SET barcode = ?, size = ?, color = ?, cost_price = ?, selling_price = ?, updated_at = ?
                    WHERE id = ?;
                    """, (barcode, size, color, cost_price, selling_price, now, v_id))

                    cursor.execute("UPDATE products SET name = ?, category = ?, brand = ?, updated_at = ? WHERE id = ?;", (name, category, brand, now, p_id))

                    # Update stock via stock adjustment if changed
                    cursor.execute("SELECT stock_quantity FROM inventory WHERE variant_id = ?;", (v_id,))
                    cur_inv = cursor.fetchone()
                    if cur_inv and cur_inv["stock_quantity"] != stock:
                        delta = stock - cur_inv["stock_quantity"]
                        inventory_service.adjust_stock(conn, v_id, delta, "CSV Import Sync", "CSV sync adjustment", user_id=1)

                    updated_count += 1
                else:
                    # Create product using products_service to ensure all ledger entries are created
                    products_service.create_product(conn, ProductCreate(
                        sku=sku,
                        barcode=barcode,
                        name=name,
                        category=category,
                        size=size,
                        color=color,
                        brand=brand,
                        cost_price=cost_price,
                        selling_price=selling_price,
                        stock_quantity=stock,
                        low_stock_threshold=low_thresh
                    ), user_id=1)
                    imported_count += 1

        return {"success": True, "created": imported_count, "updated": updated_count}
    finally:
        conn.close()


@app.get("/api/backup/download")
def download_database_backup():
    """Flushes SQLite WAL logs and streams the complete .db file for offline backup."""
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=404, detail="Database file not found.")

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA wal_checkpoint(FULL);")
        conn.close()
    except Exception as e:
        print("WAL checkpoint notice:", e)

    filename = f"SOL_Database_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    return FileResponse(
        path=DB_PATH,
        filename=filename,
        media_type="application/x-sqlite3",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ----------------- Store Settings API -----------------

@app.get("/api/settings")
def get_settings():
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM settings WHERE id = 1;")
        row = cursor.fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


@app.put("/api/settings")
def update_settings(s: SettingsUpdate):
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        with conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE settings SET 
                store_name = ?, tagline = ?, phone = ?, email = ?, address = ?, 
                gstin = ?, currency_symbol = ?, default_tax_rate = ?, upi_id = ?, 
                return_policy = ?, google_sheets_webhook_url = ?, gmail_sender = ?, 
                gmail_app_password = ?, updated_at = ?
            WHERE id = 1;
            """, (
                s.store_name, s.tagline or "", s.phone or "", s.email or "", s.address or "",
                s.gstin or "", s.currency_symbol, s.default_tax_rate, s.upi_id or "",
                s.return_policy or "", s.google_sheets_webhook_url or "", s.gmail_sender or "",
                s.gmail_app_password or "", now
            ))
            cursor.execute("SELECT * FROM settings WHERE id = 1;")
            return dict(cursor.fetchone())
    finally:
        conn.close()


# ----------------- Audit Logs API -----------------

@app.get("/api/audit/logs")
def get_audit_logs(limit: int = 50, offset: int = 0):
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ? OFFSET ?;", (limit, offset))
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


# ----------------- Serve Frontend Static Assets -----------------

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
@app.get("/pos")
@app.get("/billing")
@app.get("/app")
def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(
            index_file,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return {"message": "SOL POS & CRM Backend API is active."}


@app.get("/.well-known/assetlinks.json")
def serve_assetlinks():
    assetlinks_path = os.path.join(STATIC_DIR, "assetlinks.json")
    if os.path.exists(assetlinks_path):
        return FileResponse(assetlinks_path, media_type="application/json")
    return [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": "com.sol.lifestyle.pos",
                "sha256_cert_fingerprints": []
            }
        }
    ]
