"""
Database connection and schema setup for Clothing POS & CRM.
Uses SQLite with WAL mode for fast, concurrent, and reliable local operations.
"""
import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clothing_pos.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # 1. Products Table (Inventory with Clothing Attributes)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT UNIQUE NOT NULL,
        barcode TEXT UNIQUE,
        name TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'General',
        size TEXT NOT NULL DEFAULT 'Free Size',
        color TEXT NOT NULL DEFAULT 'Standard',
        brand TEXT DEFAULT 'In-House',
        cost_price REAL NOT NULL DEFAULT 0.0,
        selling_price REAL NOT NULL DEFAULT 0.0,
        stock_quantity INTEGER NOT NULL DEFAULT 0,
        low_stock_threshold INTEGER DEFAULT 5,
        image_url TEXT DEFAULT '',
        qr_data TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # 2. Customers Table (CRM)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT UNIQUE NOT NULL,
        email TEXT DEFAULT '',
        city TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        loyalty_points INTEGER DEFAULT 0,
        tier TEXT DEFAULT 'Bronze',
        total_spent REAL DEFAULT 0.0,
        total_orders INTEGER DEFAULT 0,
        last_visit TEXT,
        created_at TEXT NOT NULL
    );
    """)

    # 3. Invoices Table (Billing)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_number TEXT UNIQUE NOT NULL,
        customer_id INTEGER,
        customer_name TEXT DEFAULT 'Walk-in Customer',
        customer_phone TEXT DEFAULT '',
        subtotal REAL NOT NULL DEFAULT 0.0,
        discount_type TEXT DEFAULT 'fixed',
        discount_val REAL DEFAULT 0.0,
        discount_amount REAL DEFAULT 0.0,
        tax_rate REAL DEFAULT 0.0,
        tax_amount REAL DEFAULT 0.0,
        grand_total REAL NOT NULL DEFAULT 0.0,
        payment_method TEXT DEFAULT 'Cash',
        payment_status TEXT DEFAULT 'Paid',
        cash_tendered REAL DEFAULT 0.0,
        change_returned REAL DEFAULT 0.0,
        notes TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL
    );
    """)

    # 4. Invoice Items Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS invoice_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER NOT NULL,
        product_id INTEGER,
        sku TEXT,
        product_name TEXT NOT NULL,
        size TEXT DEFAULT '',
        color TEXT DEFAULT '',
        unit_price REAL NOT NULL,
        quantity INTEGER NOT NULL,
        discount_amount REAL DEFAULT 0.0,
        line_total REAL NOT NULL,
        cost_price REAL DEFAULT 0.0,
        FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
    );
    """)

    # 5. Stock Logs (Audit trail for inventory movements)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stock_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        change_type TEXT NOT NULL, -- 'sale', 'restock', 'adjustment', 'return'
        quantity_change INTEGER NOT NULL,
        new_quantity INTEGER NOT NULL,
        reference_id TEXT,
        note TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
    );
    """)

    # 6. Store Settings Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        store_name TEXT NOT NULL DEFAULT 'Vogue & Stitch Clothing Co.',
        tagline TEXT DEFAULT 'Premium Apparel & Fast Fashion',
        phone TEXT DEFAULT '+91 98765 43210',
        email TEXT DEFAULT 'contact@voguestitch.com',
        address TEXT DEFAULT 'Shop 14, High Street Fashion Hub, MG Road',
        gstin TEXT DEFAULT '29AAAAA1234A1Z1',
        currency_symbol TEXT DEFAULT '₹',
        default_tax_rate REAL DEFAULT 5.0,
        upi_id TEXT DEFAULT 'sol@upi',
        return_policy TEXT DEFAULT 'Items can be exchanged within 7 days with original tags and bill. No cash refunds.',
        google_sheets_webhook_url TEXT DEFAULT '',
        gmail_sender TEXT DEFAULT '',
        gmail_app_password TEXT DEFAULT '',
        updated_at TEXT NOT NULL
    );
    """)

    # 7. Product Variants Table (Normalized Fashion Variant Units)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS product_variants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        sku TEXT UNIQUE NOT NULL,
        barcode TEXT UNIQUE,
        size TEXT NOT NULL DEFAULT 'Free Size',
        color TEXT NOT NULL DEFAULT 'Standard',
        cost_price REAL NOT NULL DEFAULT 0.0,
        selling_price REAL NOT NULL DEFAULT 0.0,
        gst_rate REAL NOT NULL DEFAULT 5.0,
        image_url TEXT DEFAULT '',
        qr_data TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
    );
    """)

    # 8. Inventory Table (Variant-Level Stock Record)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        variant_id INTEGER UNIQUE NOT NULL,
        stock_quantity INTEGER NOT NULL DEFAULT 0,
        low_stock_threshold INTEGER DEFAULT 5,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (variant_id) REFERENCES product_variants(id) ON DELETE CASCADE
    );
    """)

    # 9. Inventory Transactions (Auditable Stock Movement Ledger)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventory_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL, -- 'SALE', 'RESTOCK', 'ADJUSTMENT', 'RETURN'
        variant_id INTEGER NOT NULL,
        quantity_change INTEGER NOT NULL,
        stock_before INTEGER NOT NULL,
        stock_after INTEGER NOT NULL,
        sale_id INTEGER,
        user_id INTEGER DEFAULT 1,
        note TEXT,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (variant_id) REFERENCES product_variants(id) ON DELETE CASCADE,
        FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE SET NULL
    );
    """)

    # 10. Sales Table (Normalized Checkout & Billing)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_number TEXT UNIQUE NOT NULL,
        customer_id INTEGER,
        customer_name TEXT DEFAULT 'Walk-in Customer',
        customer_phone TEXT DEFAULT '',
        customer_email TEXT DEFAULT '',
        subtotal REAL NOT NULL DEFAULT 0.0,
        discount_type TEXT DEFAULT 'fixed',
        discount_val REAL DEFAULT 0.0,
        discount_amount REAL DEFAULT 0.0,
        tax_rate REAL DEFAULT 0.0,
        tax_amount REAL DEFAULT 0.0,
        grand_total REAL NOT NULL DEFAULT 0.0,
        payment_method TEXT DEFAULT 'Cash',
        payment_status TEXT DEFAULT 'Paid',
        cash_tendered REAL DEFAULT 0.0,
        change_returned REAL DEFAULT 0.0,
        notes TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL
    );
    """)

    # 11. Sale Items Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sale_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER NOT NULL,
        product_id INTEGER,
        variant_id INTEGER,
        sku TEXT,
        product_name TEXT NOT NULL,
        size TEXT DEFAULT '',
        color TEXT DEFAULT '',
        unit_price REAL NOT NULL,
        quantity INTEGER NOT NULL,
        discount_amount REAL DEFAULT 0.0,
        line_total REAL NOT NULL,
        cost_price REAL DEFAULT 0.0,
        FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE CASCADE,
        FOREIGN KEY (variant_id) REFERENCES product_variants(id) ON DELETE SET NULL
    );
    """)

    # 12. Payments Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER NOT NULL,
        payment_method TEXT NOT NULL,
        amount REAL NOT NULL,
        status TEXT DEFAULT 'Completed',
        transaction_ref TEXT DEFAULT '',
        cash_tendered REAL DEFAULT 0.0,
        change_returned REAL DEFAULT 0.0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE CASCADE
    );
    """)

    # 13. Invoice Delivery Logs Table (WhatsApp & Email Logs)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS invoice_delivery_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER NOT NULL,
        channel TEXT NOT NULL, -- 'WHATSAPP', 'EMAIL'
        recipient TEXT NOT NULL,
        status TEXT NOT NULL, -- 'SENT', 'FAILED'
        error_message TEXT DEFAULT '',
        sent_at TEXT NOT NULL,
        FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE CASCADE
    );
    """)

    # 14. Users Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT DEFAULT 'cashier',
        created_at TEXT NOT NULL
    );
    """)

    conn.commit()
    seed_initial_data(conn)
    conn.close()

def seed_initial_data(conn):
    cursor = conn.cursor()
    
    # Check if settings exist
    cursor.execute("SELECT COUNT(*) FROM settings WHERE id = 1;")
    if cursor.fetchone()[0] == 0:
        now = datetime.now().isoformat()
        cursor.execute("""
        INSERT INTO settings (id, store_name, tagline, phone, email, address, gstin, currency_symbol, default_tax_rate, upi_id, return_policy, updated_at)
        VALUES (1, 'Vogue & Stitch Apparel', 'Style Redefined • Premium Quality', '+91 98765 43210', 'sales@voguestitch.com', 'Shop #12, Fashion Promenade, Commercial Street', '29AAAAA1234A1Z1', '₹', 5.0, 'voguestore@okaxis', 'Exchange within 7 days with invoice & tag intact.', ?)
        """, (now,))

    # Check if products exist
    cursor.execute("SELECT COUNT(*) FROM products;")
    if cursor.fetchone()[0] == 0:
        now = datetime.now().isoformat()
        sample_products = [
            # SKU, Barcode, Name, Category, Size, Color, Brand, Cost, Selling, Stock, LowStock
            ('SHIRT-OXF-WHT-M', '8901234001', 'Classic Oxford Cotton Shirt', 'Shirts', 'M', 'Pure White', 'Vogue Men', 650.0, 1499.0, 18, 5),
            ('SHIRT-OXF-BLU-L', '8901234002', 'Classic Oxford Cotton Shirt', 'Shirts', 'L', 'Sky Blue', 'Vogue Men', 650.0, 1499.0, 14, 5),
            ('SHIRT-LIN-SGE-L', '8901234003', 'Casual Pure Linen Shirt', 'Shirts', 'L', 'Sage Green', 'Vogue Men', 900.0, 1999.0, 9, 4),
            ('DENIM-SLM-IND-32', '8901234004', 'Slim Fit Stretch Denim Jeans', 'Denim & Jeans', '32', 'Indigo Blue', 'Stitch Denim', 850.0, 2199.0, 15, 4),
            ('DENIM-SLM-BLK-34', '8901234005', 'Slim Fit Stretch Denim Jeans', 'Denim & Jeans', '34', 'Jet Black', 'Stitch Denim', 850.0, 2199.0, 8, 4),
            ('TEE-OVR-CRB-XL', '8901234006', 'Heavyweight Oversized Graphic Tee', 'T-Shirts', 'XL', 'Carbon Black', 'StreetPulse', 380.0, 899.0, 25, 6),
            ('TEE-OVR-BEI-L', '8901234007', 'Heavyweight Oversized Minimal Tee', 'T-Shirts', 'L', 'Oatmeal Beige', 'StreetPulse', 380.0, 899.0, 20, 6),
            ('KURTA-CHIK-PCH-M', '8901234008', 'Chikankari Handcrafted Kurta', 'Ethnic Wear', 'M', 'Peach Bloom', 'Aura Heritage', 1100.0, 2699.0, 6, 3),
            ('KURTA-CHIK-NVY-XL', '8901234009', 'Chikankari Handcrafted Kurta', 'Ethnic Wear', 'XL', 'Royal Navy', 'Aura Heritage', 1100.0, 2699.0, 4, 3),
            ('DRESS-FLR-RED-S', '8901234010', 'Floral Midi Summer Dress', 'Dresses', 'S', 'Crimson Floral', 'Bella Vibe', 750.0, 1799.0, 11, 4),
            ('JKT-BMB-OLV-L', '8901234011', 'Quilted Bomber Flight Jacket', 'Jackets', 'L', 'Olive Drab', 'OuterEdge', 1600.0, 3499.0, 5, 2),
            ('POLO-CLS-NVY-M', '8901234012', 'Pique Cotton Classic Polo', 'T-Shirts', 'M', 'Navy Blue', 'Vogue Men', 480.0, 1199.0, 16, 5),
            ('TRSR-CHNO-KHK-32', '8901234013', 'Straight Fit Stretch Chinos', 'Trousers', '32', 'Khaki Sand', 'Vogue Men', 700.0, 1699.0, 12, 4),
            ('SAREE-SLK-MAR-FS', '8901234014', 'Banarasi Art Silk Saree', 'Ethnic Wear', 'Free Size', 'Maroon & Gold', 'Aura Heritage', 1800.0, 3999.0, 7, 3),
            ('HOODIE-FLC-GRY-L', '8901234015', 'Fleece Lined Relaxed Hoodie', 'Jackets', 'L', 'Heather Grey', 'StreetPulse', 720.0, 1699.0, 3, 5), # Low stock item
            ('CAP-STR-BLK-FS', '8901234016', 'Embroidered Baseball Cap', 'Accessories', 'Free Size', 'Black', 'StreetPulse', 180.0, 499.0, 22, 5)
        ]
        
        for p in sample_products:
            qr_payload = p[0] # SKU is QR payload
            cursor.execute("""
            INSERT INTO products (sku, barcode, name, category, size, color, brand, cost_price, selling_price, stock_quantity, low_stock_threshold, qr_data, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], p[8], p[9], p[10], qr_payload, now, now))
            
            # Insert initial stock log
            prod_id = cursor.lastrowid
            cursor.execute("""
            INSERT INTO stock_logs (product_id, change_type, quantity_change, new_quantity, reference_id, note, created_at)
            VALUES (?, 'restock', ?, ?, 'INITIAL_SEED', 'Initial inventory setup', ?)
            """, (prod_id, p[9], p[9], now))

    # Check if customers exist
    cursor.execute("SELECT COUNT(*) FROM customers;")
    if cursor.fetchone()[0] == 0:
        now = datetime.now().isoformat()
        sample_customers = [
            ('Aarav Sharma', '+91 98201 11223', 'aarav.sharma@example.com', 'Mumbai', 'Prefers slim shirts, size L, frequent weekend shopper', 350, 'Gold', 18450.0, 6, now, now),
            ('Priya Patel', '+91 97123 44556', 'priya.patel@example.com', 'Ahmedabad', 'Loves ethnic wear & sarees, festive buyer', 520, 'Platinum', 32900.0, 8, now, now),
            ('Rohan Verma', '+91 98450 77889', 'rohan.v@example.com', 'Bangalore', 'Likes oversized streetwear, sizes XL', 120, 'Silver', 6450.0, 3, now, now),
            ('Sneha Kulkarni', '+91 99223 88112', 'sneha.k@example.com', 'Pune', 'Prefers midi dresses & pastels, size S', 85, 'Bronze', 3598.0, 2, now, now),
            ('Vikramaditya Roy', '+91 98310 99001', 'vikram.roy@example.com', 'Kolkata', 'Purchases formal shirts and jackets, high ticket', 410, 'Gold', 22400.0, 4, now, now)
        ]
        for c in sample_customers:
            cursor.execute("""
            INSERT INTO customers (name, phone, email, city, notes, loyalty_points, tier, total_spent, total_orders, last_visit, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, c)

    # Check if sample invoices exist to populate best-sellers immediately
    cursor.execute("SELECT COUNT(*) FROM invoices;")
    if cursor.fetchone()[0] == 0:
        now = datetime.now().isoformat()
        
        # Get customer IDs
        cursor.execute("SELECT id, name, phone FROM customers LIMIT 3;")
        cust_list = cursor.fetchall()

        # Get product IDs
        cursor.execute("SELECT id, sku, name, size, color, selling_price, cost_price FROM products;")
        prod_map = {row['sku']: dict(row) for row in cursor.fetchall()}

        sample_bills = [
            {
                'inv_num': 'INV-2026-0001',
                'cust': cust_list[0] if len(cust_list) > 0 else None,
                'items': [
                    ('SHIRT-OXF-WHT-M', 2, 1499.0),
                    ('DENIM-SLM-IND-32', 1, 2199.0)
                ],
                'discount': 200.0,
                'method': 'UPI'
            },
            {
                'inv_num': 'INV-2026-0002',
                'cust': cust_list[1] if len(cust_list) > 1 else None,
                'items': [
                    ('KURTA-CHIK-PCH-M', 1, 2699.0),
                    ('SAREE-SLK-MAR-FS', 1, 3999.0)
                ],
                'discount': 500.0,
                'method': 'Card'
            },
            {
                'inv_num': 'INV-2026-0003',
                'cust': cust_list[2] if len(cust_list) > 2 else None,
                'items': [
                    ('TEE-OVR-CRB-XL', 2, 899.0),
                    ('CAP-STR-BLK-FS', 1, 499.0)
                ],
                'discount': 100.0,
                'method': 'Cash'
            },
            {
                'inv_num': 'INV-2026-0004',
                'cust': cust_list[0] if len(cust_list) > 0 else None,
                'items': [
                    ('JKT-BMB-OLV-L', 1, 3499.0),
                    ('POLO-CLS-NVY-M', 1, 1199.0)
                ],
                'discount': 300.0,
                'method': 'UPI'
            }
        ]

        for sb in sample_bills:
            cust = sb['cust']
            c_id = cust['id'] if cust else None
            c_name = cust['name'] if cust else 'Walk-in Customer'
            c_phone = cust['phone'] if cust else ''

            subtotal = sum(item[1] * item[2] for item in sb['items'])
            disc = sb['discount']
            tax = round((subtotal - disc) * 0.05, 2)
            grand = round(subtotal - disc + tax, 2)

            cursor.execute("""
            INSERT INTO invoices (invoice_number, customer_id, customer_name, customer_phone, subtotal, discount_type, discount_val, discount_amount, tax_rate, tax_amount, grand_total, payment_method, payment_status, notes, created_at)
            VALUES (?, ?, ?, ?, ?, 'fixed', ?, ?, 5.0, ?, ?, ?, 'Paid', 'Regular Sale', ?)
            """, (sb['inv_num'], c_id, c_name, c_phone, subtotal, disc, disc, tax, grand, sb['method'], now))
            inv_id = cursor.lastrowid

            for sku, qty, price in sb['items']:
                p = prod_map.get(sku)
                if p:
                    line_tot = qty * price
                    cursor.execute("""
                    INSERT INTO invoice_items (invoice_id, product_id, sku, product_name, size, color, unit_price, quantity, discount_amount, line_total, cost_price)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?, ?)
                    """, (inv_id, p['id'], sku, p['name'], p['size'], p['color'], price, qty, line_tot, p['cost_price']))

    # 4. Populate product_variants and inventory from products (Variant-level fashion inventory)
    cursor.execute("SELECT COUNT(*) FROM product_variants;")
    if cursor.fetchone()[0] == 0:
        now = datetime.now().isoformat()
        cursor.execute("SELECT * FROM products;")
        all_prods = cursor.fetchall()
        for pr in all_prods:
            cursor.execute("""
            INSERT INTO product_variants (
                product_id, sku, barcode, size, color, cost_price, selling_price, gst_rate, image_url, qr_data, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 5.0, ?, ?, ?, ?)
            """, (
                pr['id'], pr['sku'], pr['barcode'], pr['size'], pr['color'],
                pr['cost_price'], pr['selling_price'], pr['image_url'] or '',
                pr['qr_data'] or pr['sku'], pr['created_at'], pr['updated_at']
            ))
            variant_id = cursor.lastrowid
            
            cursor.execute("""
            INSERT INTO inventory (variant_id, stock_quantity, low_stock_threshold, updated_at)
            VALUES (?, ?, ?, ?)
            """, (variant_id, pr['stock_quantity'], pr['low_stock_threshold'], now))
            
            cursor.execute("""
            INSERT INTO inventory_transactions (
                type, variant_id, quantity_change, stock_before, stock_after, user_id, note, timestamp
            )
            VALUES ('RESTOCK', ?, ?, 0, ?, 1, 'Initial Variant Stock Ingest', ?)
            """, (variant_id, pr['stock_quantity'], pr['stock_quantity'], now))

    # 5. Seed default user if none
    cursor.execute("SELECT COUNT(*) FROM users;")
    if cursor.fetchone()[0] == 0:
        now = datetime.now().isoformat()
        cursor.execute("""
        INSERT INTO users (id, username, full_name, role, created_at)
        VALUES (1, 'cashier_sol', 'SOL Store Cashier', 'cashier', ?)
        """, (now,))

    # 6. Mirror existing invoices into sales and payments if empty
    cursor.execute("SELECT COUNT(*) FROM sales;")
    if cursor.fetchone()[0] == 0:
        cursor.execute("SELECT * FROM invoices;")
        invs = cursor.fetchall()
        for inv in invs:
            cursor.execute("""
            INSERT INTO sales (
                invoice_number, customer_id, customer_name, customer_phone, customer_email,
                subtotal, discount_type, discount_val, discount_amount, tax_rate, tax_amount,
                grand_total, payment_method, payment_status, notes, created_at
            )
            VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                inv['invoice_number'], inv['customer_id'], inv['customer_name'], inv['customer_phone'],
                inv['subtotal'], inv['discount_type'], inv['discount_val'], inv['discount_amount'],
                inv['tax_rate'], inv['tax_amount'], inv['grand_total'], inv['payment_method'],
                inv['payment_status'], inv['notes'], inv['created_at']
            ))
            s_id = cursor.lastrowid
            
            cursor.execute("""
            INSERT INTO payments (sale_id, payment_method, amount, status, cash_tendered, change_returned, created_at)
            VALUES (?, ?, ?, 'Completed', ?, ?, ?)
            """, (s_id, inv['payment_method'], inv['grand_total'], inv['cash_tendered'], inv['change_returned'], inv['created_at']))
            
            cursor.execute("SELECT * FROM invoice_items WHERE invoice_id = ?", (inv['id'],))
            for itm in cursor.fetchall():
                # find variant_id
                cursor.execute("SELECT id FROM product_variants WHERE sku = ?", (itm['sku'],))
                var_row = cursor.fetchone()
                v_id = var_row['id'] if var_row else None
                
                cursor.execute("""
                INSERT INTO sale_items (
                    sale_id, product_id, variant_id, sku, product_name, size, color,
                    unit_price, quantity, discount_amount, line_total, cost_price
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    s_id, itm['product_id'], v_id, itm['sku'], itm['product_name'],
                    itm['size'], itm['color'], itm['unit_price'], itm['quantity'],
                    itm['discount_amount'], itm['line_total'], itm['cost_price']
                ))

    conn.commit()
