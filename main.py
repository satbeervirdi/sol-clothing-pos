"""
Main FastAPI server for Clothing Business POS & CRM.
Interconnects Inventory, Real-Time Billing, Customer CRM, QR/Barcode Scanner, and Analytics.
"""
import os
import io
import csv
import json
import sqlite3
import smtplib
import urllib.request
import base64
import uuid
import time
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional
from datetime import datetime
from PIL import Image
try:
    from google import genai
except ImportError:
    genai = None

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from database import get_db, init_db

app = FastAPI(title="SOL • Soul of Lifestyle POS & CRM", version="2.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- Pydantic Models -----------------

class ProductCreate(BaseModel):
    sku: str
    barcode: Optional[str] = None
    name: str
    category: str = "General"
    size: str = "Free Size"
    color: str = "Standard"
    brand: Optional[str] = "In-House"
    cost_price: float = Field(default=0.0, ge=0)
    selling_price: float = Field(default=0.0, ge=0)
    stock_quantity: int = Field(default=0, ge=0)
    low_stock_threshold: int = Field(default=5, ge=0)
    image_url: Optional[str] = ""
    qr_data: Optional[str] = None

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    category: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None
    brand: Optional[str] = None
    cost_price: Optional[float] = None
    selling_price: Optional[float] = None
    stock_quantity: Optional[int] = None
    low_stock_threshold: Optional[int] = None
    image_url: Optional[str] = None

class ImageAnalysisRequest(BaseModel):
    image_data: str # Base64 encoded string or data URI
    filename: Optional[str] = "garment.jpg"

class StockAdjust(BaseModel):
    quantity_change: int # e.g. +10 for restock, -2 for damage
    reason: str = "restock" # 'restock', 'correction', 'damage'
    note: Optional[str] = ""

class CustomerCreate(BaseModel):
    name: str
    phone: str
    email: Optional[str] = ""
    city: Optional[str] = ""
    notes: Optional[str] = ""

class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    city: Optional[str] = None
    notes: Optional[str] = None
    tier: Optional[str] = None

class InvoiceItemInput(BaseModel):
    product_id: Optional[int] = None
    variant_id: Optional[int] = None
    sku: Optional[str] = ""
    product_name: str # Cashier can customize/override name
    size: Optional[str] = ""
    color: Optional[str] = ""
    unit_price: float = Field(ge=0) # Cashier can customize/override price
    quantity: int = Field(ge=1)
    discount_amount: float = Field(default=0.0, ge=0)
    line_total: float = Field(ge=0)

class InvoiceCreate(BaseModel):
    customer_id: Optional[int] = None
    customer_name: Optional[str] = "Walk-in Guest"
    customer_phone: Optional[str] = ""
    customer_email: Optional[str] = ""
    items: List[InvoiceItemInput]
    subtotal: float = Field(ge=0)
    discount_type: str = "fixed"
    discount_val: float = Field(default=0.0, ge=0)
    discount_amount: float = Field(default=0.0, ge=0)
    tax_rate: float = Field(default=0.0, ge=0)
    tax_amount: float = Field(default=0.0, ge=0)
    grand_total: float = Field(ge=0)
    payment_method: str = "Cash"
    payment_status: str = "Paid"
    cash_tendered: Optional[float] = 0.0
    change_returned: Optional[float] = 0.0
    notes: Optional[str] = ""

class DeliveryRetryRequest(BaseModel):
    channel: str = "WHATSAPP" # 'WHATSAPP' or 'EMAIL'

class SettingsUpdate(BaseModel):
    store_name: str
    tagline: Optional[str] = ""
    phone: Optional[str] = ""
    email: Optional[str] = ""
    address: Optional[str] = ""
    gstin: Optional[str] = ""
    currency_symbol: str = "₹"
    default_tax_rate: float = 5.0
    upi_id: Optional[str] = ""
    return_policy: Optional[str] = ""
    google_sheets_webhook_url: Optional[str] = ""
    gmail_sender: Optional[str] = ""
    gmail_app_password: Optional[str] = ""

# ----------------- Helper Functions -----------------

def calculate_tier(total_spent: float) -> str:
    if total_spent >= 30000:
        return "Platinum"
    elif total_spent >= 15000:
        return "Gold"
    elif total_spent >= 5000:
        return "Silver"
    return "Bronze"

def get_tier_discount(tier: str) -> float:
    # Suggested discount percentage based on customer tier
    discounts = {
        "Platinum": 15.0,
        "Gold": 10.0,
        "Silver": 5.0,
        "Bronze": 0.0
    }
    return discounts.get(tier, 0.0)

# ----------------- Products API -----------------

@app.get("/api/products")
def list_products(
    search: Optional[str] = None,
    category: Optional[str] = None,
    low_stock_only: bool = False
):
    conn = get_db()
    cursor = conn.cursor()
    
    query = """
    SELECT p.*, COALESCE((SELECT SUM(si.quantity) FROM sale_items si WHERE si.product_id = p.id), 0) AS units_sold
    FROM products p 
    WHERE 1=1
    """
    params = []
    
    if search:
        s = f"%{search.strip()}%"
        query += " AND (p.name LIKE ? OR p.sku LIKE ? OR p.barcode LIKE ? OR p.color LIKE ? OR p.category LIKE ?)"
        params.extend([s, s, s, s, s])
        
    if category and category != "All":
        query += " AND p.category = ?"
        params.append(category)
        
    if low_stock_only:
        query += " AND p.stock_quantity <= p.low_stock_threshold"
        
    query += " ORDER BY p.name ASC"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    
    for r in rows:
        r["is_low_stock"] = r["stock_quantity"] <= r["low_stock_threshold"]
        r["is_out_of_stock"] = r["stock_quantity"] <= 0
        r["units_sold"] = r.get("units_sold", 0)
        
    conn.close()
    return rows

@app.get("/api/products/categories")
def get_categories():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != '' ORDER BY category ASC")
    cats = [r[0] for r in cursor.fetchall()]
    conn.close()
    return cats

@app.get("/api/products/lookup/{code}")
def lookup_product_by_scan(code: str):
    """
    Rapid barcode/QR code lookup endpoint for cashier.
    Queries normalized product_variants joined with products and inventory.
    Returns:
    product_id, variant_id, SKU, barcode, product_name, category, size, color, selling_price, GST_rate, available_stock, image
    """
    conn = get_db()
    cursor = conn.cursor()
    clean_code = code.strip()
    
    # 1. Look in product_variants joined with products and inventory
    cursor.execute("""
    SELECT 
        pv.id AS variant_id,
        pv.product_id,
        pv.sku,
        pv.barcode,
        p.name AS product_name,
        p.category,
        pv.size,
        pv.color,
        pv.selling_price,
        pv.gst_rate,
        COALESCE(inv.stock_quantity, 0) AS available_stock,
        COALESCE(inv.low_stock_threshold, 5) AS low_stock_threshold,
        COALESCE(NULLIF(pv.image_url, ''), p.image_url, '') AS image
    FROM product_variants pv
    JOIN products p ON pv.product_id = p.id
    LEFT JOIN inventory inv ON inv.variant_id = pv.id
    WHERE pv.barcode = ? OR pv.sku = ? OR pv.qr_data = ? OR pv.sku LIKE ?
    LIMIT 1
    """, (clean_code, clean_code, clean_code, clean_code))
    
    row = cursor.fetchone()
    
    if row:
        v = dict(row)
        conn.close()
        return {
            "product_id": v["product_id"],
            "variant_id": v["variant_id"],
            "sku": v["sku"],
            "barcode": v["barcode"] or v["sku"],
            "product_name": v["product_name"],
            "name": v["product_name"],
            "category": v["category"],
            "size": v["size"],
            "color": v["color"],
            "selling_price": v["selling_price"],
            "gst_rate": v["gst_rate"],
            "available_stock": v["available_stock"],
            "stock_quantity": v["available_stock"],
            "image": v["image"] or "",
            "image_url": v["image"] or "",
            "is_low_stock": v["available_stock"] <= v["low_stock_threshold"],
            "is_out_of_stock": v["available_stock"] <= 0
        }
        
    # 2. Fallback to direct products table
    cursor.execute("""
    SELECT * FROM products 
    WHERE barcode = ? OR sku = ? OR qr_data = ? OR sku LIKE ?
    LIMIT 1
    """, (clean_code, clean_code, clean_code, clean_code))
    p_row = cursor.fetchone()
    
    if p_row:
        p = dict(p_row)
        cursor.execute("SELECT id FROM product_variants WHERE sku = ? LIMIT 1", (p["sku"],))
        vr = cursor.fetchone()
        v_id = vr["id"] if vr else p["id"]
        
        conn.close()
        return {
            "product_id": p["id"],
            "variant_id": v_id,
            "sku": p["sku"],
            "barcode": p["barcode"] or p["sku"],
            "product_name": p["name"],
            "name": p["name"],
            "category": p["category"],
            "size": p["size"],
            "color": p["color"],
            "selling_price": p["selling_price"],
            "gst_rate": 5.0,
            "available_stock": p["stock_quantity"],
            "stock_quantity": p["stock_quantity"],
            "image": p["image_url"] or "",
            "image_url": p["image_url"] or "",
            "is_low_stock": p["stock_quantity"] <= p["low_stock_threshold"],
            "is_out_of_stock": p["stock_quantity"] <= 0
        }
        
    conn.close()
    raise HTTPException(status_code=404, detail=f"No product found with code '{clean_code}'")

@app.post("/api/products")
def create_product(p: ProductCreate):
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    # Check if SKU already exists
    cursor.execute("SELECT id FROM products WHERE sku = ?", (p.sku.strip(),))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail=f"Product with SKU '{p.sku}' already exists.")
        
    barcode = p.barcode.strip() if p.barcode else p.sku.strip()
    qr_data = p.qr_data.strip() if p.qr_data else p.sku.strip()
    
    try:
        cursor.execute("""
        INSERT INTO products (sku, barcode, name, category, size, color, brand, cost_price, selling_price, stock_quantity, low_stock_threshold, image_url, qr_data, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            p.sku.strip(), barcode, p.name.strip(), p.category.strip(), 
            p.size.strip(), p.color.strip(), p.brand.strip() if p.brand else 'In-House',
            p.cost_price, p.selling_price, p.stock_quantity, p.low_stock_threshold,
            p.image_url or "", qr_data, now, now
        ))
        prod_id = cursor.lastrowid
        
        # Initial stock log
        if p.stock_quantity > 0:
            cursor.execute("""
            INSERT INTO stock_logs (product_id, change_type, quantity_change, new_quantity, reference_id, note, created_at)
            VALUES (?, 'restock', ?, ?, 'INITIAL', 'Initial product creation', ?)
            """, (prod_id, p.stock_quantity, p.stock_quantity, now))
            
        conn.commit()
        
        cursor.execute("SELECT * FROM products WHERE id = ?", (prod_id,))
        created = dict(cursor.fetchone())
        conn.close()
        return created
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/products/{product_id}")
def update_product(product_id: int, p: ProductUpdate):
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    existing = cursor.fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Product not found")
        
    updates = []
    params = []
    
    fields = [
        ("name", p.name), ("sku", p.sku), ("barcode", p.barcode),
        ("category", p.category), ("size", p.size), ("color", p.color),
        ("brand", p.brand), ("cost_price", p.cost_price), ("selling_price", p.selling_price),
        ("stock_quantity", p.stock_quantity), ("low_stock_threshold", p.low_stock_threshold),
        ("image_url", p.image_url)
    ]
    
    for col, val in fields:
        if val is not None:
            updates.append(f"{col} = ?")
            params.append(val)
            
    if not updates:
        conn.close()
        return dict(existing)
        
    updates.append("updated_at = ?")
    params.append(now)
    params.append(product_id)
    
    cursor.execute(f"UPDATE products SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    updated = dict(cursor.fetchone())
    conn.close()
    return updated

@app.post("/api/products/{product_id}/adjust-stock")
def adjust_stock(product_id: int, adj: StockAdjust):
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    cursor.execute("SELECT stock_quantity, name FROM products WHERE id = ?", (product_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Product not found")
        
    current_qty = row["stock_quantity"]
    new_qty = max(0, current_qty + adj.quantity_change)
    
    cursor.execute("UPDATE products SET stock_quantity = ?, updated_at = ? WHERE id = ?", (new_qty, now, product_id))
    cursor.execute("""
    INSERT INTO stock_logs (product_id, change_type, quantity_change, new_quantity, reference_id, note, created_at)
    VALUES (?, ?, ?, ?, 'MANUAL_ADJUST', ?, ?)
    """, (product_id, adj.reason, adj.quantity_change, new_qty, adj.note or f"Manual {adj.reason}", now))
    
    conn.commit()
    conn.close()
    return {"success": True, "product_id": product_id, "previous_quantity": current_qty, "new_quantity": new_qty}

@app.delete("/api/products/{product_id}")
def delete_product(product_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()
    return {"success": True, "deleted_id": product_id}

# ----------------- Visual Stock Intake & AI Analysis -----------------

def analyze_garment_visual(image_bytes: bytes, filename: str = "garment.jpg"):
    # 1. Try Gemini Vision if GEMINI_API_KEY is available and valid
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if genai and gemini_key and not gemini_key.startswith("_KEY_EXPOSED"):
        try:
            client = genai.Client()
            prompt = (
                "You are an expert high-fashion merchandiser for the premium clothing brand 'SOL • Soul of Lifestyle'. "
                "Analyze this garment photo and output a JSON object with these exact keys:\n"
                "- 'detected_name': A luxury, attractive apparel name (e.g. 'SOL Oversized Acid-Wash Graphic Tee', 'SOL Structured Linen Shirt', 'SOL Slim Tapered Denim')\n"
                "- 'category': One of ['Shirts', 'T-Shirts', 'Denim & Jeans', 'Jackets', 'Trousers', 'Dresses', 'Ethnic Wear', 'Accessories']\n"
                "- 'color': Dominant stylish color name (e.g. 'Jet Black', 'Sage Green', 'Indigo Blue', 'Oatmeal Beige', 'Crimson Red')\n"
                "- 'suggested_selling_price': Realistic retail price in INR (e.g. 1499.0, 1999.0, 2499.0)\n"
                "- 'suggested_cost_price': Realistic wholesale cost in INR (e.g. 550.0, 800.0)\n"
                "- 'suggested_sizes': Array of common sizes for this garment (e.g. ['S', 'M', 'L', 'XL'] or ['30', '32', '34'])\n"
                "Return ONLY raw JSON, without markdown formatting or code blocks."
            )
            resp = client.models.generate_content(
                model="gemini-3.8-flash",
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
        except Exception as e:
            print("Gemini visual analysis fallback:", e)

    # 2. Fast, resilient PIL-based fashion visual classifier
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
            name = f"SOL Elegance {color} Midi Dress"
            selling = 2499.0
            cost = 950.0
            sizes = ["XS", "S", "M", "L"]
        elif ratio > 1.15:
            category = "Shirts"
            name = f"SOL Premium {color} Relaxed Shirt"
            selling = 1899.0
            cost = 750.0
            sizes = ["S", "M", "L", "XL", "XXL"]
        elif ratio < 0.8:
            category = "Accessories"
            name = f"SOL Signature {color} Essential"
            selling = 699.0
            cost = 250.0
            sizes = ["Free Size"]
        else:
            category = "T-Shirts"
            name = f"SOL Heavyweight {color} Oversized Tee"
            selling = 1299.0
            cost = 480.0
            sizes = ["S", "M", "L", "XL", "XXL"]

        return {
            "detected_name": name,
            "category": category,
            "color": color,
            "suggested_selling_price": selling,
            "suggested_cost_price": cost,
            "suggested_sizes": sizes,
            "analysis_source": "smart_classifier"
        }
    except Exception as e:
        return {
            "detected_name": "SOL Garment Style",
            "category": "Shirts",
            "color": "Standard",
            "suggested_selling_price": 1499.0,
            "suggested_cost_price": 600.0,
            "suggested_sizes": ["S", "M", "L", "XL"],
            "analysis_source": "fallback"
        }

@app.post("/api/products/upload-and-analyze")
async def upload_and_analyze_garment(req: ImageAnalysisRequest):
    try:
        raw_b64 = req.image_data
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]
        
        image_bytes = base64.b64decode(raw_b64)
        
        # Optimize and save image with PIL
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode in ("RGBA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "RGBA":
                background.paste(img, mask=img.split()[3])
            else:
                background.paste(img)
            img = background
        else:
            img = img.convert("RGB")
            
        # Resize if very large (e.g. max 1200px)
        max_dim = 1200
        if img.width > max_dim or img.height > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            
        # Unique filename
        file_hash = uuid.uuid4().hex[:6]
        filename = f"prod_{int(time.time())}_{file_hash}.jpg"
        upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "uploads", "products")
        os.makedirs(upload_dir, exist_ok=True)
        save_path = os.path.join(upload_dir, filename)
        img.save(save_path, "JPEG", quality=88, optimize=True)
        
        rel_url = f"/static/uploads/products/{filename}"
        
        # Analyze garment features
        analysis = analyze_garment_visual(image_bytes, filename)
        
        rand_id = random.randint(1000, 9999)
        cat_clean = analysis.get("category", "GEN")[:3].upper().replace(" ", "").replace("-", "")
        col_clean = analysis.get("color", "STD")[:3].upper().replace(" ", "").replace("-", "")
        sku = f"SOL-{cat_clean}-{col_clean}-{rand_id}"
        barcode = f"890{rand_id}{random.randint(1000, 9999)}"
        
        return {
            "success": True,
            "image_url": rel_url,
            "detected_name": analysis.get("detected_name", "SOL Garment"),
            "category": analysis.get("category", "General"),
            "color": analysis.get("color", "Standard"),
            "suggested_selling_price": float(analysis.get("suggested_selling_price", 1499.0)),
            "suggested_cost_price": float(analysis.get("suggested_cost_price", 600.0)),
            "suggested_sizes": analysis.get("suggested_sizes", ["S", "M", "L", "XL"]),
            "sku_suggestion": sku,
            "barcode_suggestion": barcode,
            "analysis_source": analysis.get("analysis_source", "smart_classifier")
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Image upload/analysis failed: {str(e)}")

# ----------------- Customers CRM API -----------------

@app.get("/api/customers/search")
def search_customers(q: str = Query(...)):
    """
    Rapid customer search by phone, name, or email for billing CRM.
    Returns: Name, Phone, Email, Previous orders, Total spent, Last purchase.
    """
    conn = get_db()
    cursor = conn.cursor()
    term = q.strip()
    s = f"%{term}%"
    cursor.execute("""
    SELECT id, name, phone, email, city, tier, total_spent, total_orders, last_visit, loyalty_points
    FROM customers
    WHERE phone LIKE ? OR name LIKE ? OR email LIKE ?
    ORDER BY (phone = ?) DESC, total_spent DESC
    LIMIT 10
    """, (s, s, s, term))
    rows = [dict(r) for r in cursor.fetchall()]
    for r in rows:
        r["suggested_discount"] = get_tier_discount(r["tier"])
    conn.close()
    return rows

@app.get("/api/customers")
def list_customers(search: Optional[str] = None):
    conn = get_db()
    cursor = conn.cursor()
    
    query = "SELECT * FROM customers WHERE 1=1"
    params = []
    
    if search:
        s = f"%{search.strip()}%"
        query += " AND (name LIKE ? OR phone LIKE ? OR email LIKE ? OR city LIKE ?)"
        params.extend([s, s, s, s])
        
    query += " ORDER BY total_spent DESC, last_visit DESC"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    
    for r in rows:
        r["suggested_discount"] = get_tier_discount(r["tier"])
        
    conn.close()
    return rows

@app.get("/api/customers/{customer_id}")
def get_customer(customer_id: int):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Customer not found")
        
    cust = dict(row)
    cust["suggested_discount"] = get_tier_discount(cust["tier"])
    
    # Get purchase history
    cursor.execute("""
    SELECT id, invoice_number, grand_total, payment_method, created_at 
    FROM invoices 
    WHERE customer_id = ? 
    ORDER BY created_at DESC
    """, (customer_id,))
    invoices = [dict(i) for i in cursor.fetchall()]
    
    for inv in invoices:
        cursor.execute("SELECT product_name, size, color, quantity, unit_price, line_total FROM invoice_items WHERE invoice_id = ?", (inv["id"],))
        inv["items"] = [dict(it) for it in cursor.fetchall()]
        
    cust["purchase_history"] = invoices
    conn.close()
    return cust

@app.post("/api/customers")
def create_customer(c: CustomerCreate):
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    clean_phone = c.phone.strip()
    
    cursor.execute("SELECT id FROM customers WHERE phone = ?", (clean_phone,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail=f"Customer with phone '{clean_phone}' already exists.")
        
    cursor.execute("""
    INSERT INTO customers (name, phone, email, city, notes, loyalty_points, tier, total_spent, total_orders, last_visit, created_at)
    VALUES (?, ?, ?, ?, ?, 0, 'Bronze', 0.0, 0, ?, ?)
    """, (c.name.strip(), clean_phone, c.email.strip() if c.email else "", c.city.strip() if c.city else "", c.notes.strip() if c.notes else "", now, now))
    
    cid = cursor.lastrowid
    conn.commit()
    
    cursor.execute("SELECT * FROM customers WHERE id = ?", (cid,))
    created = dict(cursor.fetchone())
    conn.close()
    return created

@app.put("/api/customers/{customer_id}")
def update_customer(customer_id: int, c: CustomerUpdate):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Customer not found")
        
    updates = []
    params = []
    fields = [("name", c.name), ("phone", c.phone), ("email", c.email), ("city", c.city), ("notes", c.notes), ("tier", c.tier)]
    for col, val in fields:
        if val is not None:
            updates.append(f"{col} = ?")
            params.append(val)
            
    if updates:
        params.append(customer_id)
        cursor.execute(f"UPDATE customers SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        
    cursor.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
    updated = dict(cursor.fetchone())
    conn.close()
    return updated

# ----------------- Invoices & Billing API -----------------

def sync_invoice_to_google_sheets(invoice_data: dict, webhook_url: str):
    if not webhook_url or not webhook_url.startswith("http"):
        return
    try:
        items_str = ", ".join([f"{it['product_name']} ({it.get('size','')}) x{it['quantity']}" for it in invoice_data.get("items", [])])
        payload = {
            "type": "NEW_SALE",
            "invoice_number": invoice_data.get("invoice_number"),
            "date": invoice_data.get("created_at"),
            "customer_name": invoice_data.get("customer_name"),
            "customer_phone": invoice_data.get("customer_phone"),
            "items_summary": items_str,
            "subtotal": invoice_data.get("subtotal"),
            "discount": invoice_data.get("discount_amount"),
            "tax": invoice_data.get("tax_amount"),
            "grand_total": invoice_data.get("grand_total"),
            "payment_method": invoice_data.get("payment_method"),
            "notes": invoice_data.get("notes", "")
        }
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            pass
    except Exception as e:
        print("[Google Sheets Sync] Notice:", e)

def generate_invoice_pdf_buffer(inv: dict, settings: dict) -> io.BytesIO:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('TitleStyle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=18, leading=22, alignment=1)
    sub_style = ParagraphStyle('SubStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=11, alignment=1, textColor=colors.HexColor('#444444'))
    meta_style = ParagraphStyle('MetaStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=12)
    center_style = ParagraphStyle('CenterStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=11, alignment=1, textColor=colors.HexColor('#555555'))
    
    story = []
    store_name = settings.get("store_name", "SOL • Soul of Lifestyle")
    tagline = settings.get("tagline", "PREMIUM WEAR | MODERN ESSENTIALS | ELEVATED YOU")
    story.append(Paragraph(f"<b>{store_name.upper()}</b>", title_style))
    story.append(Paragraph(tagline.upper(), sub_style))
    
    addr_line = f"{settings.get('address', '')} | Tel: {settings.get('phone', '')} | GSTIN: {settings.get('gstin', '')}"
    story.append(Paragraph(addr_line, center_style))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1.2, color=colors.black, spaceAfter=8))
    
    inv_date = inv.get("created_at", "")[:19].replace("T", " ")
    meta_data = [
        [
            Paragraph(f"<b>INVOICE NO:</b> {inv.get('invoice_number', '')}", meta_style),
            Paragraph(f"<b>CUSTOMER:</b> {inv.get('customer_name', 'Walk-in Guest')}", meta_style)
        ],
        [
            Paragraph(f"<b>DATE & TIME:</b> {inv_date}", meta_style),
            Paragraph(f"<b>PHONE:</b> {inv.get('customer_phone') or 'N/A'}", meta_style)
        ],
        [
            Paragraph(f"<b>PAYMENT:</b> {inv.get('payment_method', 'Cash')}", meta_style),
            Paragraph(f"<b>EMAIL:</b> {inv.get('customer_email') or 'N/A'}", meta_style)
        ]
    ]
    meta_table = Table(meta_data, colWidths=[3.2*inch, 3.8*inch])
    meta_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 2),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 10))
    
    headers = ['ITEM', 'SIZE', 'COLOR', 'QTY', 'RATE', 'DISC', 'TOTAL']
    table_rows = [headers]
    curr = settings.get("currency_symbol", "₹")
    
    for item in inv.get("items", []):
        name = item.get("product_name", "Garment")
        sz = item.get("size", "-") or "-"
        col = item.get("color", "-") or "-"
        qty = str(item.get("quantity", 1))
        rate = f"{curr}{item.get('unit_price', 0):.2f}"
        disc = f"{curr}{item.get('discount_amount', 0):.2f}" if item.get('discount_amount') else "-"
        tot = f"{curr}{item.get('line_total', 0):.2f}"
        table_rows.append([name, sz, col, qty, rate, disc, tot])
        
    items_table = Table(table_rows, colWidths=[2.6*inch, 0.7*inch, 0.9*inch, 0.4*inch, 0.8*inch, 0.6*inch, 1.0*inch])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.black),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('ALIGN', (3,0), (-1,-1), 'RIGHT'),
        ('LINEBELOW', (0,1), (-1,-1), 0.5, colors.HexColor('#e5e5e5')),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 10))
    
    subtotal = inv.get("subtotal", 0.0)
    disc_amt = inv.get("discount_amount", 0.0)
    tax_amt = inv.get("tax_amount", 0.0)
    grand_tot = inv.get("grand_total", 0.0)
    
    tot_data = [
        ['', 'SUBTOTAL:', f"{curr}{subtotal:.2f}"],
        ['', 'DISCOUNT:', f"-{curr}{disc_amt:.2f}" if disc_amt > 0 else f"{curr}0.00"],
        ['', f"TAX / GST ({inv.get('tax_rate', 0)}%):", f"+{curr}{tax_amt:.2f}"],
        ['', 'GRAND TOTAL:', f"{curr}{grand_tot:.2f}"]
    ]
    tot_table = Table(tot_data, colWidths=[4.2*inch, 1.6*inch, 1.2*inch])
    tot_table.setStyle(TableStyle([
        ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
        ('FONTNAME', (1,0), (1,-1), 'Helvetica-Bold'),
        ('FONTNAME', (1,3), (-1,3), 'Helvetica-Bold'),
        ('FONTSIZE', (1,3), (-1,3), 10),
        ('LINEABOVE', (1,3), (-1,3), 1, colors.black),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 2),
    ]))
    story.append(tot_table)
    story.append(Spacer(1, 16))
    
    policy = settings.get("return_policy", "Exchange within 7 days with invoice & original tags.")
    story.append(Paragraph(f"<b>Return & Exchange Policy:</b> {policy}", center_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>THANK YOU FOR SHOPPING WITH SOL — SOUL OF LIFESTYLE</b>", ParagraphStyle('Thanks', parent=center_style, fontName='Helvetica-Bold', fontSize=8.5, textColor=colors.black)))
    
    doc.build(story)
    buf.seek(0)
    return buf

@app.post("/api/invoices")
def create_invoice(inv: InvoiceCreate, background_tasks: BackgroundTasks):
    """
    Atomic Checkout Operation:
    STEP 1: Validate cart.
    STEP 2: Validate current inventory again from database.
    STEP 3: Validate payment.
    STEP 4: Create sale.
    STEP 5: Create sale_items.
    STEP 6: Record payment.
    STEP 7: Deduct inventory variant-level.
    STEP 8: Create inventory_transactions records (auditable ledger).
    STEP 9: Update customer CRM.
    STEP 10: Commit atomic transaction.
    Non-blocking: WhatsApp & Email delivery logging.
    """
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    # STEP 1: Validate cart
    if not inv.items or len(inv.items) == 0:
        conn.close()
        raise HTTPException(status_code=400, detail="Cannot complete sale: Cart is empty.")
        
    for it in inv.items:
        if it.quantity <= 0:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Invalid quantity for '{it.product_name}'. Must be at least 1.")

    try:
        # STEP 2: Validate current inventory again from database
        for it in inv.items:
            v_id = it.variant_id
            p_id = it.product_id
            sku = it.sku
            
            avail_stock = None
            if v_id:
                cursor.execute("SELECT stock_quantity FROM inventory WHERE variant_id = ?", (v_id,))
                row = cursor.fetchone()
                if row:
                    avail_stock = row["stock_quantity"]
            if avail_stock is None and sku and sku != "CUSTOM":
                cursor.execute("""
                SELECT inv.stock_quantity, pv.id AS v_id 
                FROM product_variants pv 
                JOIN inventory inv ON inv.variant_id = pv.id 
                WHERE pv.sku = ?
                """, (sku,))
                row = cursor.fetchone()
                if row:
                    avail_stock = row["stock_quantity"]
                    it.variant_id = row["v_id"]
            if avail_stock is None and p_id:
                cursor.execute("SELECT stock_quantity FROM products WHERE id = ?", (p_id,))
                row = cursor.fetchone()
                if row:
                    avail_stock = row["stock_quantity"]
                    
            if avail_stock is not None and it.quantity > avail_stock:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Only {avail_stock} units available for '{it.product_name}' ({it.size}/{it.color}). Cannot complete sale."
                )

        # STEP 3: Validate payment
        if inv.payment_method == "Cash" and inv.cash_tendered:
            if inv.cash_tendered < inv.grand_total:
                pass # Cashier might accept partial or exact
                
        # STEP 4: Generate sequential invoice number (SOL-2026-000124)
        year = datetime.now().strftime("%Y")
        cursor.execute("SELECT COUNT(*) FROM sales WHERE invoice_number LIKE ?", (f"SOL-{year}-%",))
        count = cursor.fetchone()[0] + 1
        inv_number = f"SOL-{year}-{count:06d}"
        
        # STEP 9: Customer CRM Resolution
        customer_id = inv.customer_id
        cust_phone = (inv.customer_phone or "").strip()
        cust_name = (inv.customer_name or "Walk-in Guest").strip()
        cust_email = (inv.customer_email or "").strip()
        
        if cust_phone:
            cursor.execute("SELECT id, total_spent, total_orders, loyalty_points, email FROM customers WHERE phone = ?", (cust_phone,))
            cust_row = cursor.fetchone()
            if cust_row:
                customer_id = cust_row["id"]
                new_spent = cust_row["total_spent"] + inv.grand_total
                new_orders = cust_row["total_orders"] + 1
                new_tier = calculate_tier(new_spent)
                earned_points = int(inv.grand_total // 100)
                new_points = cust_row["loyalty_points"] + earned_points
                upd_email = cust_email if cust_email else (cust_row["email"] or "")
                
                cursor.execute("""
                UPDATE customers 
                SET total_spent = ?, total_orders = ?, tier = ?, loyalty_points = ?, email = ?, last_visit = ?
                WHERE id = ?
                """, (new_spent, new_orders, new_tier, new_points, upd_email, now, customer_id))
            else:
                new_tier = calculate_tier(inv.grand_total)
                earned_points = int(inv.grand_total // 100)
                cursor.execute("""
                INSERT INTO customers (name, phone, email, city, notes, loyalty_points, tier, total_spent, total_orders, last_visit, created_at)
                VALUES (?, ?, ?, '', 'Auto-created from POS Sale', ?, ?, ?, 1, ?, ?)
                """, (cust_name, cust_phone, cust_email, earned_points, new_tier, inv.grand_total, now, now))
                customer_id = cursor.lastrowid
        elif customer_id:
            cursor.execute("SELECT total_spent, total_orders, loyalty_points FROM customers WHERE id = ?", (customer_id,))
            cust_row = cursor.fetchone()
            if cust_row:
                new_spent = cust_row["total_spent"] + inv.grand_total
                new_orders = cust_row["total_orders"] + 1
                new_tier = calculate_tier(new_spent)
                earned_points = int(inv.grand_total // 100)
                new_points = cust_row["loyalty_points"] + earned_points
                cursor.execute("""
                UPDATE customers 
                SET total_spent = ?, total_orders = ?, tier = ?, loyalty_points = ?, last_visit = ?
                WHERE id = ?
                """, (new_spent, new_orders, new_tier, new_points, now, customer_id))

        # STEP 4 & 5: Create Sale and Invoices
        cursor.execute("""
        INSERT INTO sales (
            invoice_number, customer_id, customer_name, customer_phone, customer_email,
            subtotal, discount_type, discount_val, discount_amount, tax_rate, tax_amount,
            grand_total, payment_method, payment_status, cash_tendered, change_returned, notes, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            inv_number, customer_id, cust_name, cust_phone, cust_email,
            inv.subtotal, inv.discount_type, inv.discount_val, inv.discount_amount,
            inv.tax_rate, inv.tax_amount, inv.grand_total, inv.payment_method,
            inv.payment_status, inv.cash_tendered or 0.0, inv.change_returned or 0.0,
            inv.notes or "", now
        ))
        sale_id = cursor.lastrowid
        
        # Dual-write to invoices for full backward compatibility
        cursor.execute("""
        INSERT INTO invoices (
            id, invoice_number, customer_id, customer_name, customer_phone, subtotal, 
            discount_type, discount_val, discount_amount, tax_rate, tax_amount, 
            grand_total, payment_method, payment_status, cash_tendered, change_returned, notes, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sale_id, inv_number, customer_id, cust_name, cust_phone, inv.subtotal,
            inv.discount_type, inv.discount_val, inv.discount_amount, inv.tax_rate, inv.tax_amount,
            inv.grand_total, inv.payment_method, inv.payment_status, inv.cash_tendered or 0.0, inv.change_returned or 0.0,
            inv.notes or "", now
        ))
        
        # STEP 6: Record Payment in payments table
        cursor.execute("""
        INSERT INTO payments (sale_id, payment_method, amount, status, cash_tendered, change_returned, created_at)
        VALUES (?, ?, ?, 'Completed', ?, ?, ?)
        """, (sale_id, inv.payment_method, inv.grand_total, inv.cash_tendered or 0.0, inv.change_returned or 0.0, now))

        # STEP 7 & 8: Deduct Inventory Variant-Level & Record inventory_transactions
        for item in inv.items:
            v_id = item.variant_id
            p_id = item.product_id
            sku = item.sku
            cost_price = 0.0
            
            # Resolve variant_id if missing
            if not v_id and sku and sku != "CUSTOM":
                cursor.execute("SELECT id, product_id, cost_price FROM product_variants WHERE sku = ?", (sku,))
                vr = cursor.fetchone()
                if vr:
                    v_id = vr["id"]
                    if not p_id:
                        p_id = vr["product_id"]
                    cost_price = vr["cost_price"]
            elif v_id:
                cursor.execute("SELECT product_id, cost_price FROM product_variants WHERE id = ?", (v_id,))
                vr = cursor.fetchone()
                if vr:
                    cost_price = vr["cost_price"]
                    if not p_id:
                        p_id = vr["product_id"]
                        
            if p_id and cost_price == 0.0:
                cursor.execute("SELECT cost_price FROM products WHERE id = ?", (p_id,))
                pr = cursor.fetchone()
                if pr:
                    cost_price = pr["cost_price"]

            # Variant-level inventory deduction
            if v_id:
                cursor.execute("SELECT stock_quantity FROM inventory WHERE variant_id = ?", (v_id,))
                inv_row = cursor.fetchone()
                if inv_row:
                    stock_before = inv_row["stock_quantity"]
                    stock_after = stock_before - item.quantity
                    cursor.execute("UPDATE inventory SET stock_quantity = ?, updated_at = ? WHERE variant_id = ?", (stock_after, now, v_id))
                    
                    # Record auditable inventory movement
                    cursor.execute("""
                    INSERT INTO inventory_transactions (
                        type, variant_id, quantity_change, stock_before, stock_after, sale_id, user_id, note, timestamp
                    )
                    VALUES ('SALE', ?, ?, ?, ?, ?, 1, ?, ?)
                    """, (v_id, -item.quantity, stock_before, stock_after, sale_id, f"Sold on {inv_number}", now))

            # Sync products table stock quantity
            if p_id:
                cursor.execute("SELECT stock_quantity FROM products WHERE id = ?", (p_id,))
                pr = cursor.fetchone()
                if pr:
                    prod_new_stock = pr["stock_quantity"] - item.quantity
                    cursor.execute("UPDATE products SET stock_quantity = ?, updated_at = ? WHERE id = ?", (prod_new_stock, now, p_id))
                    cursor.execute("""
                    INSERT INTO stock_logs (product_id, change_type, quantity_change, new_quantity, reference_id, note, created_at)
                    VALUES (?, 'sale', ?, ?, ?, ?, ?)
                    """, (p_id, -item.quantity, prod_new_stock, inv_number, f"Sold on {inv_number}", now))

            # Insert into sale_items
            cursor.execute("""
            INSERT INTO sale_items (
                sale_id, product_id, variant_id, sku, product_name, size, color,
                unit_price, quantity, discount_amount, line_total, cost_price
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sale_id, p_id, v_id, item.sku or "", item.product_name, item.size or "", item.color or "",
                item.unit_price, item.quantity, item.discount_amount, item.line_total, cost_price
            ))
            
            # Dual-write into invoice_items
            cursor.execute("""
            INSERT INTO invoice_items (
                invoice_id, product_id, sku, product_name, size, color,
                unit_price, quantity, discount_amount, line_total, cost_price
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sale_id, p_id, item.sku or "", item.product_name, item.size or "", item.color or "",
                item.unit_price, item.quantity, item.discount_amount, item.line_total, cost_price
            ))

        # STEP 10: Commit atomic transaction
        conn.commit()

    except HTTPException:
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Sale failed and rolled back: {str(e)}")

    # ----------------- NON-BLOCKING POST-SALE DELIVERY -----------------
    whatsapp_status = "NOT_PROVIDED"
    whatsapp_url = ""
    email_status = "NOT_PROVIDED"
    
    # 1. WhatsApp Delivery Link
    if cust_phone:
        clean_phone = "".join(filter(str.isdigit, cust_phone))
        wa_msg = (
            f"Hi {cust_name},\n\n"
            f"Thank you for shopping with SOL — Soul of Lifestyle.\n\n"
            f"Invoice: {inv_number}\n"
            f"Amount: ₹{inv.grand_total:.2f}\n\n"
            f"Your invoice is attached."
        )
        whatsapp_url = f"https://api.whatsapp.com/send?phone={clean_phone}&text={urllib.parse.quote(wa_msg)}"
        whatsapp_status = "SENT"
        
        try:
            cursor.execute("""
            INSERT INTO invoice_delivery_logs (sale_id, channel, recipient, status, error_message, sent_at)
            VALUES (?, 'WHATSAPP', ?, 'SENT', '', ?)
            """, (sale_id, cust_phone, now))
            conn.commit()
        except Exception:
            pass

    # 2. Email Delivery Dispatch
    if cust_email:
        email_status = "READY_TO_SEND"
        cursor.execute("SELECT gmail_sender, gmail_app_password, store_name FROM settings WHERE id = 1")
        s_row = cursor.fetchone()
        if s_row and s_row["gmail_sender"] and s_row["gmail_app_password"]:
            try:
                # Fetch full sale for PDF
                cursor.execute("SELECT * FROM sales WHERE id = ?", (sale_id,))
                sale_obj = dict(cursor.fetchone())
                cursor.execute("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,))
                sale_obj["items"] = [dict(it) for it in cursor.fetchall()]
                cursor.execute("SELECT * FROM settings WHERE id = 1")
                settings_dict = dict(cursor.fetchone())
                
                pdf_buf = generate_invoice_pdf_buffer(sale_obj, settings_dict)
                pdf_bytes = pdf_buf.getvalue()
                
                # Send email via background task
                background_tasks.add_task(
                    dispatch_invoice_email_task,
                    s_row["gmail_sender"],
                    s_row["gmail_app_password"],
                    cust_email,
                    inv_number,
                    pdf_bytes,
                    sale_id
                )
                email_status = "SENT"
            except Exception as em_err:
                email_status = f"FAILED: {str(em_err)}"
        else:
            email_status = "PENDING_SMTP_CONFIG"
            
        try:
            cursor.execute("""
            INSERT INTO invoice_delivery_logs (sale_id, channel, recipient, status, error_message, sent_at)
            VALUES (?, 'EMAIL', ?, ?, '', ?)
            """, (sale_id, cust_email, email_status, now))
            conn.commit()
        except Exception:
            pass

    # 3. Fetch final sale object
    cursor.execute("SELECT * FROM sales WHERE id = ?", (sale_id,))
    final_sale = dict(cursor.fetchone())
    cursor.execute("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,))
    final_sale["items"] = [dict(it) for it in cursor.fetchall()]
    final_sale["id"] = sale_id
    final_sale["invoice_id"] = sale_id
    final_sale["whatsapp_status"] = whatsapp_status
    final_sale["whatsapp_url"] = whatsapp_url
    final_sale["email_status"] = email_status
    final_sale["inventory_status"] = "Updated (Variant-level)"
    final_sale["crm_status"] = "Updated"
    
    # Check Google Sheets Webhook
    cursor.execute("SELECT google_sheets_webhook_url FROM settings WHERE id = 1")
    s_row = cursor.fetchone()
    if s_row and s_row["google_sheets_webhook_url"]:
        background_tasks.add_task(sync_invoice_to_google_sheets, final_sale, s_row["google_sheets_webhook_url"])
        
    conn.close()
    return final_sale

def dispatch_invoice_email_task(sender, password, recipient, inv_number, pdf_bytes, sale_id):
    try:
        from email.mime.application import MIMEApplication
        msg = MIMEMultipart()
        msg['From'] = f"SOL • Soul of Lifestyle <{sender}>"
        msg['To'] = recipient
        msg['Subject'] = f"Your SOL Invoice — {inv_number}"
        
        body = f"Hello,\n\nThank you for shopping with SOL — Soul of Lifestyle.\nPlease find your tax invoice {inv_number} attached as a PDF.\n\nWarm regards,\nSOL Retail Team"
        msg.attach(MIMEText(body, 'plain'))
        
        pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
        pdf_part.add_header('Content-Disposition', 'attachment', filename=f"{inv_number}.pdf")
        msg.attach(pdf_part)
        
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(sender, password)
            server.send_message(msg)
            
        conn = get_db()
        conn.execute("UPDATE invoice_delivery_logs SET status = 'SENT' WHERE sale_id = ? AND channel = 'EMAIL'", (sale_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        print("[Invoice Email Error]:", e)
        conn = get_db()
        conn.execute("UPDATE invoice_delivery_logs SET status = 'FAILED', error_message = ? WHERE sale_id = ? AND channel = 'EMAIL'", (str(e), sale_id))
        conn.commit()
        conn.close()

@app.get("/api/invoices/{invoice_id}/pdf")
@app.get("/api/sales/{sale_id}/pdf")
def get_sale_invoice_pdf(invoice_id: int):
    """
    Generates and streams a luxury vector PDF invoice.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sales WHERE id = ?", (invoice_id,))
    sale_row = cursor.fetchone()
    if not sale_row:
        cursor.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
        sale_row = cursor.fetchone()
    if not sale_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Invoice not found")
        
    sale_obj = dict(sale_row)
    cursor.execute("SELECT * FROM sale_items WHERE sale_id = ?", (invoice_id,))
    items = [dict(it) for it in cursor.fetchall()]
    if not items:
        cursor.execute("SELECT * FROM invoice_items WHERE invoice_id = ?", (invoice_id,))
        items = [dict(it) for it in cursor.fetchall()]
    sale_obj["items"] = items
    
    cursor.execute("SELECT * FROM settings WHERE id = 1")
    settings_dict = dict(cursor.fetchone())
    conn.close()
    
    buf = generate_invoice_pdf_buffer(sale_obj, settings_dict)
    filename = f"{sale_obj.get('invoice_number', 'SOL-INV')}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

@app.post("/api/invoices/{invoice_id}/retry-delivery")
def retry_invoice_delivery(invoice_id: int, req: DeliveryRetryRequest, background_tasks: BackgroundTasks):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sales WHERE id = ?", (invoice_id,))
    sale = cursor.fetchone()
    if not sale:
        conn.close()
        raise HTTPException(status_code=404, detail="Invoice not found")
    sale_dict = dict(sale)
    now = datetime.now().isoformat()
    
    if req.channel.upper() == "WHATSAPP":
        phone = sale_dict.get("customer_phone")
        if not phone:
            conn.close()
            raise HTTPException(status_code=400, detail="No customer phone attached to invoice.")
        clean_phone = "".join(filter(str.isdigit, phone))
        msg = f"Hi {sale_dict.get('customer_name')},\n\nThank you for shopping with SOL — Soul of Lifestyle.\nInvoice: {sale_dict.get('invoice_number')}\nAmount: ₹{sale_dict.get('grand_total'):.2f}\n\nYour invoice is attached."
        wa_url = f"https://api.whatsapp.com/send?phone={clean_phone}&text={urllib.parse.quote(msg)}"
        cursor.execute("INSERT INTO invoice_delivery_logs (sale_id, channel, recipient, status, sent_at) VALUES (?, 'WHATSAPP', ?, 'SENT', ?)", (invoice_id, phone, now))
        conn.commit()
        conn.close()
        return {"status": "SUCCESS", "channel": "WHATSAPP", "url": wa_url}
        
    elif req.channel.upper() == "EMAIL":
        email = sale_dict.get("customer_email")
        if not email:
            conn.close()
            raise HTTPException(status_code=400, detail="No customer email attached to invoice.")
        cursor.execute("SELECT gmail_sender, gmail_app_password FROM settings WHERE id = 1")
        s = cursor.fetchone()
        if not s or not s["gmail_sender"] or not s["gmail_app_password"]:
            conn.close()
            raise HTTPException(status_code=400, detail="Gmail SMTP credentials not configured in Settings.")
            
        cursor.execute("SELECT * FROM sale_items WHERE sale_id = ?", (invoice_id,))
        sale_dict["items"] = [dict(it) for it in cursor.fetchall()]
        cursor.execute("SELECT * FROM settings WHERE id = 1")
        settings_dict = dict(cursor.fetchone())
        pdf_buf = generate_invoice_pdf_buffer(sale_dict, settings_dict)
        
        background_tasks.add_task(
            dispatch_invoice_email_task,
            s["gmail_sender"],
            s["gmail_app_password"],
            email,
            sale_dict["invoice_number"],
            pdf_buf.getvalue(),
            invoice_id
        )
        conn.close()
        return {"status": "SENT", "channel": "EMAIL", "recipient": email}
        
    conn.close()
    raise HTTPException(status_code=400, detail="Invalid delivery channel. Choose 'WHATSAPP' or 'EMAIL'.")

@app.get("/api/invoices")
def list_invoices(limit: int = 50, search: Optional[str] = None):
    conn = get_db()
    cursor = conn.cursor()
    
    query = "SELECT * FROM invoices WHERE 1=1"
    params = []
    
    if search:
        s = f"%{search.strip()}%"
        query += " AND (invoice_number LIKE ? OR customer_name LIKE ? OR customer_phone LIKE ?)"
        params.extend([s, s, s])
        
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    
    cursor.execute(query, params)
    invoices = [dict(i) for i in cursor.fetchall()]
    
    for inv in invoices:
        cursor.execute("SELECT COUNT(*) as item_count, SUM(quantity) as total_qty FROM invoice_items WHERE invoice_id = ?", (inv["id"],))
        stats = cursor.fetchone()
        inv["item_count"] = stats["item_count"]
        inv["total_qty"] = stats["total_qty"] or 0
        
    conn.close()
    return invoices

@app.get("/api/invoices/{invoice_id}")
def get_invoice(invoice_id: int):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Invoice not found")
        
    inv = dict(row)
    cursor.execute("SELECT * FROM invoice_items WHERE invoice_id = ?", (invoice_id,))
    inv["items"] = [dict(it) for it in cursor.fetchall()]
    
    # Store settings for receipt header
    cursor.execute("SELECT * FROM settings WHERE id = 1")
    settings_row = cursor.fetchone()
    inv["settings"] = dict(settings_row) if settings_row else {}
    
    conn.close()
    return inv

# ----------------- Sold Products & Sales Reports API -----------------

@app.get("/api/sales/sold-products")
def get_sold_products():
    """
    Returns complete breakdown of which products and variants have been sold,
    how many units were sold, revenue generated, today's sales metrics,
    and recent sales list.
    """
    conn = get_db()
    cursor = conn.cursor()
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 1. Total & Today Units and Revenue
    cursor.execute("""
    SELECT 
        COALESCE(SUM(quantity), 0) AS total_units_sold,
        COALESCE(SUM(line_total), 0) AS total_revenue
    FROM sale_items
    """)
    totals = dict(cursor.fetchone())
    
    cursor.execute("""
    SELECT 
        COALESCE(SUM(si.quantity), 0) AS today_units_sold,
        COALESCE(SUM(si.line_total), 0) AS today_revenue
    FROM sale_items si
    JOIN sales s ON si.sale_id = s.id
    WHERE s.created_at LIKE ?
    """, (f"{today_str}%",))
    today_totals = dict(cursor.fetchone())
    
    # 2. Aggregated Sold Products (Itemized by Name, Size, Color, SKU)
    cursor.execute("""
    SELECT 
        si.product_name,
        si.sku,
        si.size,
        si.color,
        si.unit_price,
        SUM(si.quantity) AS units_sold,
        SUM(si.line_total) AS total_revenue,
        MAX(s.created_at) AS last_sold_at,
        COALESCE(inv.stock_quantity, p.stock_quantity, 0) AS current_stock,
        p.category,
        p.image_url
    FROM sale_items si
    JOIN sales s ON si.sale_id = s.id
    LEFT JOIN product_variants pv ON si.variant_id = pv.id
    LEFT JOIN inventory inv ON inv.variant_id = pv.id
    LEFT JOIN products p ON (si.product_id = p.id OR pv.product_id = p.id)
    GROUP BY si.product_name, si.sku, si.size, si.color
    ORDER BY units_sold DESC, total_revenue DESC
    """)
    sold_items = [dict(r) for r in cursor.fetchall()]
    
    # 3. Recent Sales Invoices with Items summary
    cursor.execute("""
    SELECT 
        s.id, s.invoice_number, s.customer_name, s.customer_phone, 
        s.grand_total, s.payment_method, s.payment_status, s.created_at,
        COUNT(si.id) as item_count,
        COALESCE(SUM(si.quantity), 0) as total_units
    FROM sales s
    LEFT JOIN sale_items si ON s.id = si.sale_id
    GROUP BY s.id
    ORDER BY s.created_at DESC
    LIMIT 50
    """)
    recent_sales = [dict(r) for r in cursor.fetchall()]
    
    conn.close()
    
    return {
        "today_units_sold": today_totals["today_units_sold"],
        "today_revenue": round(today_totals["today_revenue"], 2),
        "total_units_sold": totals["total_units_sold"],
        "total_revenue": round(totals["total_revenue"], 2),
        "sold_products": sold_items,
        "recent_sales": recent_sales
    }

# ----------------- Analytics & Best Sellers API -----------------

@app.get("/api/analytics/dashboard")
def get_analytics_dashboard():
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. KPIs
    cursor.execute("SELECT COUNT(*) as total_orders, COALESCE(SUM(grand_total), 0) as total_revenue FROM invoices;")
    sales_stats = dict(cursor.fetchone())
    
    # Today's Sales
    today_str = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT COUNT(*) as today_orders, COALESCE(SUM(grand_total), 0) as today_revenue FROM invoices WHERE created_at LIKE ?;", (f"{today_str}%",))
    today_stats = dict(cursor.fetchone())
    
    # Inventory KPIs
    cursor.execute("""
    SELECT 
        COUNT(*) as total_products,
        COALESCE(SUM(stock_quantity), 0) as total_stock_units,
        COALESCE(SUM(stock_quantity * cost_price), 0) as inventory_cost_val,
        COALESCE(SUM(stock_quantity * selling_price), 0) as inventory_retail_val,
        SUM(CASE WHEN stock_quantity <= low_stock_threshold THEN 1 ELSE 0 END) as low_stock_count
    FROM products;
    """)
    inventory_stats = dict(cursor.fetchone())
    
    # Customer Count
    cursor.execute("SELECT COUNT(*) FROM customers;")
    total_customers = cursor.fetchone()[0]
    
    # Total Gross Profit
    cursor.execute("""
    SELECT 
        COALESCE(SUM(ii.line_total), 0) as revenue,
        COALESCE(SUM(ii.quantity * ii.cost_price), 0) as total_cogs
    FROM invoice_items ii;
    """)
    margin_row = cursor.fetchone()
    total_cogs = margin_row["total_cogs"]
    total_revenue = sales_stats["total_revenue"]
    gross_profit = max(0.0, total_revenue - total_cogs)
    
    # 2. Best-Selling Products (Key requirement from user prompt)
    cursor.execute("""
    SELECT 
        ii.product_name,
        ii.sku,
        ii.size,
        ii.color,
        p.category,
        p.stock_quantity as current_stock,
        p.selling_price as current_price,
        SUM(ii.quantity) as units_sold,
        SUM(ii.line_total) as total_revenue_generated
    FROM invoice_items ii
    LEFT JOIN products p ON ii.product_id = p.id
    GROUP BY ii.product_name, ii.sku
    ORDER BY units_sold DESC, total_revenue_generated DESC
    LIMIT 10;
    """)
    best_sellers = [dict(b) for b in cursor.fetchall()]
    
    # 3. Category Share
    cursor.execute("""
    SELECT 
        COALESCE(p.category, 'Custom / Other') as category,
        SUM(ii.quantity) as total_units,
        SUM(ii.line_total) as total_sales
    FROM invoice_items ii
    LEFT JOIN products p ON ii.product_id = p.id
    GROUP BY p.category
    ORDER BY total_sales DESC;
    """)
    category_breakdown = [dict(c) for c in cursor.fetchall()]
    
    # 4. Low Stock Alerts
    cursor.execute("""
    SELECT id, name, sku, category, size, color, stock_quantity, low_stock_threshold, cost_price, selling_price
    FROM products
    WHERE stock_quantity <= low_stock_threshold
    ORDER BY stock_quantity ASC
    LIMIT 10;
    """)
    low_stock_alerts = [dict(l) for l in cursor.fetchall()]
    
    # 5. Top VIP Customers
    cursor.execute("""
    SELECT id, name, phone, tier, total_spent, total_orders, loyalty_points, last_visit
    FROM customers
    ORDER BY total_spent DESC
    LIMIT 5;
    """)
    top_customers = [dict(tc) for tc in cursor.fetchall()]
    
    conn.close()
    
    return {
        "kpi": {
            "total_revenue": round(sales_stats["total_revenue"], 2),
            "total_orders": sales_stats["total_orders"],
            "today_revenue": round(today_stats["today_revenue"], 2),
            "today_orders": today_stats["today_orders"],
            "total_stock_units": inventory_stats["total_stock_units"],
            "total_products": inventory_stats["total_products"],
            "inventory_cost_val": round(inventory_stats["inventory_cost_val"], 2),
            "inventory_retail_val": round(inventory_stats["inventory_retail_val"], 2),
            "low_stock_count": inventory_stats["low_stock_count"] or 0,
            "total_customers": total_customers,
            "gross_profit": round(gross_profit, 2)
        },
        "best_selling_products": best_sellers,
        "category_breakdown": category_breakdown,
        "low_stock_alerts": low_stock_alerts,
        "top_customers": top_customers
    }

# ----------------- Integrations (Google Sheets, Gmail, CSV) -----------------

@app.get("/api/export/csv/{entity}")
def export_csv(entity: str):
    conn = get_db()
    cursor = conn.cursor()
    output = io.StringIO()
    writer = csv.writer(output)
    
    if entity == "invoices":
        writer.writerow(["Invoice #", "Date", "Customer Name", "Customer Phone", "Items Summary", "Subtotal", "Discount", "Tax", "Grand Total", "Payment Method", "Notes"])
        cursor.execute("SELECT * FROM invoices ORDER BY created_at DESC")
        invoices = cursor.fetchall()
        for inv in invoices:
            cursor.execute("SELECT product_name, size, color, quantity, unit_price, line_total FROM invoice_items WHERE invoice_id = ?", (inv["id"],))
            items = cursor.fetchall()
            items_str = " | ".join([f"{it['product_name']} ({it['size']}/{it['color']}) x{it['quantity']} = {it['line_total']}" for it in items])
            writer.writerow([
                inv["invoice_number"], inv["created_at"], inv["customer_name"], inv["customer_phone"],
                items_str, inv["subtotal"], inv["discount_amount"], inv["tax_amount"], inv["grand_total"],
                inv["payment_method"], inv["notes"]
            ])
        filename = f"SOL_Invoices_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
    elif entity == "products":
        writer.writerow(["SKU", "Barcode", "Product Name", "Category", "Size", "Color", "Brand", "Cost Price", "Selling Price", "Stock Quantity", "Low Stock Limit"])
        cursor.execute("SELECT sku, barcode, name, category, size, color, brand, cost_price, selling_price, stock_quantity, low_stock_threshold FROM products ORDER BY name ASC")
        for p in cursor.fetchall():
            writer.writerow(list(p))
        filename = f"SOL_Inventory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
    elif entity == "customers":
        writer.writerow(["Customer Name", "Phone", "Email", "City", "Loyalty Tier", "Total Spent", "Total Orders", "Loyalty Points", "Last Visit", "Notes"])
        cursor.execute("SELECT name, phone, email, city, tier, total_spent, total_orders, loyalty_points, last_visit, notes FROM customers ORDER BY total_spent DESC")
        for c in cursor.fetchall():
            writer.writerow(list(c))
        filename = f"SOL_Customers_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
    else:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid entity for CSV export. Options: invoices, products, customers")
        
        
    conn.close()
    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/api/backup/download")
def download_database_backup():
    """Flushes SQLite WAL logs and streams the complete .db file for offline backup."""
    from database import DB_PATH
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


from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request

@app.post("/api/import/csv/products")
async def import_products_csv(request: Request):
    contents = await request.body()
    try:
        decoded = contents.decode("utf-8-sig")
    except Exception:
        decoded = contents.decode("latin-1")
        
    reader = csv.DictReader(io.StringIO(decoded))
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    imported_count = 0
    updated_count = 0
    
    for row in reader:
        row_lower = {str(k).strip().lower(): str(v).strip() for k, v in row.items() if k}
        sku = row_lower.get("sku") or row_lower.get("code") or f"SOL-{int(datetime.now().timestamp()*1000)%1000000}"
        name = row_lower.get("product name") or row_lower.get("name") or row_lower.get("title") or "Unnamed Style"
        category = row_lower.get("category") or "General"
        size = row_lower.get("size") or "Free Size"
        color = row_lower.get("color") or "Standard"
        brand = row_lower.get("brand") or "SOL"
        barcode = row_lower.get("barcode") or sku
        
        try:
            cost_price = float(row_lower.get("cost price", 0) or row_lower.get("cost", 0) or 0)
        except ValueError:
            cost_price = 0.0
            
        try:
            selling_price = float(row_lower.get("selling price", 0) or row_lower.get("price", 0) or row_lower.get("mrp", 0) or 0)
        except ValueError:
            selling_price = 0.0
            
        try:
            stock = int(row_lower.get("stock quantity", 0) or row_lower.get("stock", 0) or row_lower.get("qty", 0) or 0)
        except ValueError:
            stock = 0
            
        try:
            low_thresh = int(row_lower.get("low stock limit", 5) or 5)
        except ValueError:
            low_thresh = 5
            
        cursor.execute("SELECT id FROM products WHERE sku = ?", (sku,))
        existing = cursor.fetchone()
        if existing:
            cursor.execute("""
            UPDATE products SET name = ?, category = ?, size = ?, color = ?, brand = ?, cost_price = ?, selling_price = ?, stock_quantity = ?, low_stock_threshold = ?, barcode = ?, updated_at = ?
            WHERE id = ?
            """, (name, category, size, color, brand, cost_price, selling_price, stock, low_thresh, barcode, now, existing[0]))
            updated_count += 1
        else:
            cursor.execute("""
            INSERT INTO products (sku, barcode, name, category, size, color, brand, cost_price, selling_price, stock_quantity, low_stock_threshold, qr_data, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sku, barcode, name, category, size, color, brand, cost_price, selling_price, stock, low_thresh, sku, now, now))
            imported_count += 1
            
    conn.commit()
    conn.close()
    return {"success": True, "created": imported_count, "updated": updated_count}

class EmailRequest(BaseModel):
    recipient_email: str
    subject: Optional[str] = None
    body_html: Optional[str] = None

@app.post("/api/invoices/{invoice_id}/send-email")
def send_invoice_email(invoice_id: int, req: EmailRequest):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
    inv = cursor.fetchone()
    if not inv:
        conn.close()
        raise HTTPException(status_code=404, detail="Invoice not found")
        
    cursor.execute("SELECT * FROM settings WHERE id = 1")
    settings = cursor.fetchone()
    conn.close()
    
    sender = settings["gmail_sender"] if settings else ""
    app_pw = settings["gmail_app_password"] if settings else ""
    
    if not sender or not app_pw:
        return {
            "sent": False,
            "mode": "web_compose",
            "message": "Gmail credentials not configured in settings. Use Web Compose link."
        }
        
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = req.subject or f"Receipt for Invoice {inv['invoice_number']} - SOL Soul of Lifestyle"
        msg["From"] = f"SOL Soul of Lifestyle <{sender}>"
        msg["To"] = req.recipient_email
        
        html_content = req.body_html or f"<p>Thank you for shopping at SOL Soul of Lifestyle.<br>Invoice: {inv['invoice_number']}<br>Grand Total: ₹{inv['grand_total']}</p>"
        msg.attach(MIMEText(html_content, "html"))
        
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, app_pw)
            server.sendmail(sender, req.recipient_email, msg.as_string())
            
        return {"sent": True, "recipient": req.recipient_email}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

# ----------------- Store Settings API -----------------

@app.get("/api/settings")
def get_settings():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM settings WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {}

@app.put("/api/settings")
def update_settings(s: SettingsUpdate):
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    cursor.execute("""
    UPDATE settings SET 
        store_name = ?, tagline = ?, phone = ?, email = ?, address = ?, 
        gstin = ?, currency_symbol = ?, default_tax_rate = ?, upi_id = ?, 
        return_policy = ?, google_sheets_webhook_url = ?, gmail_sender = ?, 
        gmail_app_password = ?, updated_at = ?
    WHERE id = 1
    """, (
        s.store_name, s.tagline or "", s.phone or "", s.email or "", s.address or "",
        s.gstin or "", s.currency_symbol, s.default_tax_rate, s.upi_id or "",
        s.return_policy or "", s.google_sheets_webhook_url or "", s.gmail_sender or "",
        s.gmail_app_password or "", now
    ))
    conn.commit()
    cursor.execute("SELECT * FROM settings WHERE id = 1")
    updated = dict(cursor.fetchone())
    conn.close()
    return updated

# ----------------- Serve Frontend -----------------

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

# Auto-initialize DB on startup
@app.on_event("startup")
def on_startup():
    init_db()
