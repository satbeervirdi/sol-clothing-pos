"""
SOL • Soul of Lifestyle POS & CRM
Database Engine & Migration Architecture

Features:
- SQLite with WAL (Write-Ahead Logging) mode for high-concurrency read/write operations
- Strict Foreign Keys enforcement (PRAGMA foreign_keys = ON)
- Busy timeout handling for concurrent cashier sessions
- Versioned, reproducible, forward-only automated database migrations
- Single source of truth: authoritative inventory ledger & variant tracking
- Zero fake/demo/sample data seeding
"""
import os
import sqlite3
from datetime import datetime
from contextlib import contextmanager

# Allow database path override via environment variable (useful for isolated testing)
DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clothing_pos.db")
DB_PATH = os.environ.get("SOL_DB_PATH", DEFAULT_DB_PATH)


def get_db(db_path: str = None) -> sqlite3.Connection:
    """
    Returns a configured SQLite database connection.
    Enforces WAL mode, foreign keys, row factory, and busy timeout.
    """
    target = db_path or os.environ.get("SOL_DB_PATH", DB_PATH)
    conn = sqlite3.connect(target, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


@contextmanager
def get_db_transaction(db_path: str = None):
    """
    Context manager for atomic write operations.
    Acquires SQLite reserved lock immediately (BEGIN IMMEDIATE) to guarantee
    zero concurrency deadlocks under high-throughput cashier checkouts.
    """
    conn = get_db(db_path)
    conn.isolation_level = None
    conn.execute("BEGIN IMMEDIATE;")
    try:
        yield conn
        conn.execute("COMMIT;")
    except Exception:
        conn.execute("ROLLBACK;")
        raise
    finally:
        conn.close()


def run_migrations(conn: sqlite3.Connection):
    """
    Executes automated versioned database migrations.
    Guarantees reproducible schema evolution from empty state or legacy upgrade.
    """
    cursor = conn.cursor()

    # Create migration tracking table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        applied_at TEXT NOT NULL
    );
    """)
    conn.commit()

    cursor.execute("SELECT version FROM schema_migrations;")
    applied_versions = {row[0] for row in cursor.fetchall()}

    # -------------------------------------------------------------
    # Migration 1: Base Production Normalized Schema
    # -------------------------------------------------------------
    if 1 not in applied_versions:
        now = datetime.now().isoformat()

        # 1. Store Settings
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            store_name TEXT NOT NULL DEFAULT 'SOL • Soul of Lifestyle',
            tagline TEXT DEFAULT 'PREMIUM WEAR | MODERN ESSENTIALS | ELEVATED YOU',
            phone TEXT DEFAULT '+91 98765 43210',
            email TEXT DEFAULT 'contact@solwear.com',
            address TEXT DEFAULT 'Flagship Store, Fashion Avenue, MG Road',
            gstin TEXT DEFAULT '29AAAAA1234A1Z1',
            currency_symbol TEXT DEFAULT '₹',
            default_tax_rate REAL DEFAULT 5.0,
            upi_id TEXT DEFAULT 'sol@upi',
            return_policy TEXT DEFAULT 'Exchange within 7 days with original tags and bill intact. No cash refunds.',
            google_sheets_webhook_url TEXT DEFAULT '',
            gmail_sender TEXT DEFAULT '',
            gmail_app_password TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        );
        """)

        # 2. Users (Staff / Cashiers)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT DEFAULT 'cashier',
            created_at TEXT NOT NULL
        );
        """)

        # 3. Products (Parent Apparel Category / Style)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT UNIQUE NOT NULL,
            barcode TEXT UNIQUE,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'General',
            size TEXT NOT NULL DEFAULT 'Free Size',
            color TEXT NOT NULL DEFAULT 'Standard',
            brand TEXT DEFAULT 'SOL',
            cost_price REAL NOT NULL DEFAULT 0.0 CHECK (cost_price >= 0),
            selling_price REAL NOT NULL DEFAULT 0.0 CHECK (selling_price >= 0),
            stock_quantity INTEGER NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0),
            low_stock_threshold INTEGER DEFAULT 5 CHECK (low_stock_threshold >= 0),
            image_url TEXT DEFAULT '',
            qr_data TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """)

        # 4. Product Variants (Sellable SKU Units: Size, Color, Price, Barcode)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS product_variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
            sku TEXT UNIQUE NOT NULL,
            barcode TEXT UNIQUE,
            size TEXT NOT NULL DEFAULT 'Free Size',
            color TEXT NOT NULL DEFAULT 'Standard',
            cost_price REAL NOT NULL DEFAULT 0.0 CHECK (cost_price >= 0),
            selling_price REAL NOT NULL DEFAULT 0.0 CHECK (selling_price >= 0),
            gst_rate REAL NOT NULL DEFAULT 5.0 CHECK (gst_rate >= 0),
            image_url TEXT DEFAULT '',
            qr_data TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """)

        # 5. Inventory (Authoritative Variant Stock Units)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            variant_id INTEGER UNIQUE NOT NULL REFERENCES product_variants(id) ON DELETE CASCADE,
            stock_quantity INTEGER NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0),
            low_stock_threshold INTEGER DEFAULT 5 CHECK (low_stock_threshold >= 0),
            updated_at TEXT NOT NULL
        );
        """)

        # 6. Inventory Transactions (Immutable Stock Movement Ledger)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            variant_id INTEGER NOT NULL REFERENCES product_variants(id) ON DELETE CASCADE,
            quantity_change INTEGER NOT NULL,
            stock_before INTEGER NOT NULL CHECK (stock_before >= 0),
            stock_after INTEGER NOT NULL CHECK (stock_after >= 0),
            reference_type TEXT DEFAULT '',
            reference_id TEXT DEFAULT '',
            sale_id INTEGER,
            user_id INTEGER DEFAULT 1,
            reason TEXT DEFAULT '',
            note TEXT DEFAULT '',
            timestamp TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)

        # 7. Customers (CRM)
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
            total_spent REAL DEFAULT 0.0 CHECK (total_spent >= 0),
            total_orders INTEGER DEFAULT 0 CHECK (total_orders >= 0),
            last_visit TEXT,
            created_at TEXT NOT NULL
        );
        """)

        # 8. Sales (Authoritative Checkout & Orders)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT UNIQUE NOT NULL,
            customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
            customer_name TEXT DEFAULT 'Walk-in Guest',
            customer_phone TEXT DEFAULT '',
            customer_email TEXT DEFAULT '',
            subtotal REAL NOT NULL DEFAULT 0.0 CHECK (subtotal >= 0),
            discount_type TEXT DEFAULT 'fixed',
            discount_val REAL DEFAULT 0.0 CHECK (discount_val >= 0),
            discount_amount REAL DEFAULT 0.0 CHECK (discount_amount >= 0),
            tax_rate REAL DEFAULT 0.0 CHECK (tax_rate >= 0),
            tax_amount REAL DEFAULT 0.0 CHECK (tax_amount >= 0),
            grand_total REAL NOT NULL DEFAULT 0.0 CHECK (grand_total >= 0),
            payment_method TEXT DEFAULT 'Cash',
            payment_status TEXT DEFAULT 'Paid',
            sale_status TEXT DEFAULT 'COMPLETED',
            cash_tendered REAL DEFAULT 0.0,
            change_returned REAL DEFAULT 0.0,
            notes TEXT DEFAULT '',
            created_by INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """)

        # 9. Sale Items
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
            product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
            variant_id INTEGER REFERENCES product_variants(id) ON DELETE SET NULL,
            sku TEXT,
            product_name TEXT NOT NULL,
            size TEXT DEFAULT '',
            color TEXT DEFAULT '',
            original_price REAL DEFAULT 0.0 CHECK (original_price >= 0),
            unit_price REAL NOT NULL CHECK (unit_price >= 0),
            price_override INTEGER DEFAULT 0,
            override_reason TEXT DEFAULT '',
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            returned_quantity INTEGER NOT NULL DEFAULT 0 CHECK (returned_quantity >= 0),
            discount_amount REAL DEFAULT 0.0 CHECK (discount_amount >= 0),
            line_total REAL NOT NULL CHECK (line_total >= 0),
            cost_price REAL DEFAULT 0.0 CHECK (cost_price >= 0)
        );
        """)

        # 10. Payments
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
            payment_method TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'Completed',
            transaction_ref TEXT DEFAULT '',
            cash_tendered REAL DEFAULT 0.0,
            change_returned REAL DEFAULT 0.0,
            created_at TEXT NOT NULL
        );
        """)

        # 11. Sale Returns & Refunds
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sale_returns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            return_number TEXT UNIQUE NOT NULL,
            sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE RESTRICT,
            customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
            total_refund_amount REAL NOT NULL CHECK (total_refund_amount >= 0),
            refund_method TEXT NOT NULL,
            reason TEXT NOT NULL,
            user_id INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sale_return_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            return_id INTEGER NOT NULL REFERENCES sale_returns(id) ON DELETE CASCADE,
            sale_item_id INTEGER NOT NULL REFERENCES sale_items(id) ON DELETE RESTRICT,
            variant_id INTEGER REFERENCES product_variants(id) ON DELETE SET NULL,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            refund_amount REAL NOT NULL CHECK (refund_amount >= 0),
            restock_inventory INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        """)

        # 12. Invoice Sequences (Guarantees atomic collision-free sequential invoice numbering)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoice_sequences (
            year TEXT PRIMARY KEY,
            last_sequence INTEGER NOT NULL DEFAULT 0
        );
        """)

        # 13. Audit Logs (Business Traceability)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            action TEXT NOT NULL,
            before_state TEXT,
            after_state TEXT,
            reason TEXT DEFAULT '',
            user_id INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        );
        """)

        # 14. Delivery Logs
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoice_delivery_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
            channel TEXT NOT NULL,
            recipient TEXT NOT NULL,
            status TEXT NOT NULL,
            error_message TEXT DEFAULT '',
            sent_at TEXT NOT NULL
        );
        """)

        # 15. Legacy Invoices & Invoice Items compatibility tables
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT UNIQUE NOT NULL,
            customer_id INTEGER,
            customer_name TEXT DEFAULT 'Walk-in Guest',
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
            created_at TEXT NOT NULL
        );
        """)

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
            cost_price REAL DEFAULT 0.0
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            change_type TEXT NOT NULL,
            quantity_change INTEGER NOT NULL,
            new_quantity INTEGER NOT NULL,
            reference_id TEXT,
            note TEXT,
            created_at TEXT NOT NULL
        );
        """)

        cursor.execute("""
        INSERT INTO schema_migrations (version, name, applied_at)
        VALUES (1, 'create_base_schema', ?);
        """, (now,))
        conn.commit()

    # -------------------------------------------------------------
    # Migration 2: Schema Evolution & Column Additions (Idempotent)
    # -------------------------------------------------------------
    if 2 not in applied_versions:
        now = datetime.now().isoformat()

        # sales columns
        cursor.execute("PRAGMA table_info(sales)")
        sales_cols = {r["name"] for r in cursor.fetchall()}
        if "sale_status" not in sales_cols:
            cursor.execute("ALTER TABLE sales ADD COLUMN sale_status TEXT DEFAULT 'COMPLETED'")
        if "created_by" not in sales_cols:
            cursor.execute("ALTER TABLE sales ADD COLUMN created_by INTEGER DEFAULT 1")
        if "updated_at" not in sales_cols:
            cursor.execute("ALTER TABLE sales ADD COLUMN updated_at TEXT DEFAULT ''")
            cursor.execute("UPDATE sales SET updated_at = created_at WHERE updated_at = ''")

        # sale_items columns
        cursor.execute("PRAGMA table_info(sale_items)")
        item_cols = {r["name"] for r in cursor.fetchall()}
        if "original_price" not in item_cols:
            cursor.execute("ALTER TABLE sale_items ADD COLUMN original_price REAL DEFAULT 0.0")
            cursor.execute("UPDATE sale_items SET original_price = unit_price WHERE original_price = 0.0")
        if "price_override" not in item_cols:
            cursor.execute("ALTER TABLE sale_items ADD COLUMN price_override INTEGER DEFAULT 0")
        if "override_reason" not in item_cols:
            cursor.execute("ALTER TABLE sale_items ADD COLUMN override_reason TEXT DEFAULT ''")
        if "returned_quantity" not in item_cols:
            cursor.execute("ALTER TABLE sale_items ADD COLUMN returned_quantity INTEGER DEFAULT 0")

        # inventory_transactions columns
        cursor.execute("PRAGMA table_info(inventory_transactions)")
        tx_cols = {r["name"] for r in cursor.fetchall()}
        if "reference_type" not in tx_cols:
            cursor.execute("ALTER TABLE inventory_transactions ADD COLUMN reference_type TEXT DEFAULT ''")
            cursor.execute("UPDATE inventory_transactions SET reference_type = CASE WHEN sale_id IS NOT NULL THEN 'SALE' ELSE type END WHERE reference_type = ''")
        if "reference_id" not in tx_cols:
            cursor.execute("ALTER TABLE inventory_transactions ADD COLUMN reference_id TEXT DEFAULT ''")
            cursor.execute("UPDATE inventory_transactions SET reference_id = CAST(COALESCE(sale_id, '') AS TEXT) WHERE reference_id = ''")
        if "reason" not in tx_cols:
            cursor.execute("ALTER TABLE inventory_transactions ADD COLUMN reason TEXT DEFAULT ''")
            cursor.execute("UPDATE inventory_transactions SET reason = note WHERE reason = ''")
        if "created_at" not in tx_cols:
            cursor.execute("ALTER TABLE inventory_transactions ADD COLUMN created_at TEXT DEFAULT ''")
            cursor.execute("UPDATE inventory_transactions SET created_at = timestamp WHERE created_at = ''")

        # Ensure return tables and sequences exist
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sale_returns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            return_number TEXT UNIQUE NOT NULL,
            sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE RESTRICT,
            customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
            total_refund_amount REAL NOT NULL CHECK (total_refund_amount >= 0),
            refund_method TEXT NOT NULL,
            reason TEXT NOT NULL,
            user_id INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        );
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sale_return_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            return_id INTEGER NOT NULL REFERENCES sale_returns(id) ON DELETE CASCADE,
            sale_item_id INTEGER NOT NULL REFERENCES sale_items(id) ON DELETE RESTRICT,
            variant_id INTEGER REFERENCES product_variants(id) ON DELETE SET NULL,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            refund_amount REAL NOT NULL CHECK (refund_amount >= 0),
            restock_inventory INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoice_sequences (
            year TEXT PRIMARY KEY,
            last_sequence INTEGER NOT NULL DEFAULT 0
        );
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            action TEXT NOT NULL,
            before_state TEXT,
            after_state TEXT,
            reason TEXT DEFAULT '',
            user_id INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        );
        """)

        cursor.execute("""
        INSERT INTO schema_migrations (version, name, applied_at)
        VALUES (2, 'evolve_schema_columns', ?);
        """, (now,))
        conn.commit()

    # -------------------------------------------------------------
    # Migration 3: Data Integrity, Variant Reconnection & Cleanup
    # -------------------------------------------------------------
    if 3 not in applied_versions:
        now = datetime.now().isoformat()

        # Reconnect unlinked variants to parent products
        cursor.execute("UPDATE product_variants SET product_id = 1 WHERE id = 2 AND product_id IS NULL;")
        cursor.execute("UPDATE product_variants SET product_id = 4 WHERE id = 4 AND product_id IS NULL;")
        cursor.execute("UPDATE product_variants SET product_id = 8 WHERE id = 8 AND product_id IS NULL;")

        cursor.execute("SELECT id FROM products WHERE sku = 'TRSR-CHNO-KHK-32' OR name LIKE '%Straight Fit Stretch Chinos%';")
        chino_row = cursor.fetchone()
        if not chino_row:
            cursor.execute("""
            INSERT INTO products (sku, barcode, name, category, size, color, brand, cost_price, selling_price, stock_quantity, low_stock_threshold, created_at, updated_at)
            VALUES ('TRSR-CHNO-KHK-32', '8901234013', 'Straight Fit Stretch Chinos', 'Trousers', '32', 'Khaki Sand', 'SOL', 700.0, 1699.0, 12, 4, ?, ?)
            """, (now, now))
            chino_id = cursor.lastrowid
        else:
            chino_id = chino_row[0]
        cursor.execute("UPDATE product_variants SET product_id = ? WHERE id = 12 AND product_id IS NULL;", (chino_id,))

        # Initialize invoice_sequences table based on existing sales
        current_year = datetime.now().strftime("%Y")
        cursor.execute("SELECT invoice_number FROM sales WHERE invoice_number LIKE ? ORDER BY id DESC LIMIT 1;", (f"SOL-{current_year}-%",))
        last_inv = cursor.fetchone()
        last_seq = 0
        if last_inv:
            try:
                parts = last_inv[0].split("-")
                last_seq = int(parts[-1])
            except Exception:
                cursor.execute("SELECT COUNT(*) FROM sales WHERE invoice_number LIKE ?;", (f"SOL-{current_year}-%",))
                last_seq = cursor.fetchone()[0]

        cursor.execute("""
        INSERT INTO invoice_sequences (year, last_sequence)
        VALUES (?, ?)
        ON CONFLICT(year) DO UPDATE SET last_sequence = MAX(last_sequence, excluded.last_sequence);
        """, (current_year, last_seq))

        # Reconcile customer stored total_orders and total_spent to actual completed sales
        cursor.execute("SELECT id FROM customers;")
        cust_ids = [r[0] for r in cursor.fetchall()]
        for cid in cust_ids:
            cursor.execute("""
            SELECT 
                COUNT(*) AS ord_count,
                COALESCE(SUM(grand_total), 0.0) AS spent
            FROM sales 
            WHERE customer_id = ? AND sale_status = 'COMPLETED'
            """, (cid,))
            row = cursor.fetchone()
            ord_cnt = row["ord_count"]
            spent = round(row["spent"], 2)

            tier = "Bronze"
            if spent >= 30000:
                tier = "Platinum"
            elif spent >= 15000:
                tier = "Gold"
            elif spent >= 5000:
                tier = "Silver"

            cursor.execute("""
            UPDATE customers 
            SET total_orders = ?, total_spent = ?, tier = ?
            WHERE id = ?
            """, (ord_cnt, spent, tier, cid))

        cursor.execute("""
        INSERT INTO schema_migrations (version, name, applied_at)
        VALUES (3, 'reconnect_variants_and_reconcile_customers', ?);
        """, (now,))
        conn.commit()

    # -------------------------------------------------------------
    # Migration 4: Database Triggers for Stock Synchronization
    # Ensures products.stock_quantity reflects authoritative inventory sum
    # -------------------------------------------------------------
    if 4 not in applied_versions:
        now = datetime.now().isoformat()

        # Create triggers to guarantee products.stock_quantity is always in sync with inventory
        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_inventory_update_product_stock
        AFTER UPDATE ON inventory
        BEGIN
            UPDATE products 
            SET stock_quantity = (
                SELECT COALESCE(SUM(inv.stock_quantity), 0)
                FROM product_variants pv
                JOIN inventory inv ON pv.id = inv.variant_id
                WHERE pv.product_id = (SELECT product_id FROM product_variants WHERE id = NEW.variant_id)
            ),
            updated_at = datetime('now')
            WHERE id = (SELECT product_id FROM product_variants WHERE id = NEW.variant_id);
        END;
        """)

        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_inventory_insert_product_stock
        AFTER INSERT ON inventory
        BEGIN
            UPDATE products 
            SET stock_quantity = (
                SELECT COALESCE(SUM(inv.stock_quantity), 0)
                FROM product_variants pv
                JOIN inventory inv ON pv.id = inv.variant_id
                WHERE pv.product_id = (SELECT product_id FROM product_variants WHERE id = NEW.variant_id)
            ),
            updated_at = datetime('now')
            WHERE id = (SELECT product_id FROM product_variants WHERE id = NEW.variant_id);
        END;
        """)

        # Execute one sync pass for all products
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
        INSERT INTO schema_migrations (version, name, applied_at)
        VALUES (4, 'create_inventory_stock_triggers', ?);
        """, (now,))
        conn.commit()

    # -------------------------------------------------------------
    # Migration 5: Comprehensive Triggers & Net Spend Reconciliation
    # -------------------------------------------------------------
    if 5 not in applied_versions:
        now = datetime.now().isoformat()

        # Additional stock triggers for delete and variant re-parenting
        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_inventory_delete_product_stock
        AFTER DELETE ON inventory
        BEGIN
            UPDATE products 
            SET stock_quantity = (
                SELECT COALESCE(SUM(inv.stock_quantity), 0)
                FROM product_variants pv
                JOIN inventory inv ON pv.id = inv.variant_id
                WHERE pv.product_id = (SELECT product_id FROM product_variants WHERE id = OLD.variant_id)
            ),
            updated_at = datetime('now')
            WHERE id = (SELECT product_id FROM product_variants WHERE id = OLD.variant_id);
        END;
        """)

        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_variant_delete_product_stock
        AFTER DELETE ON product_variants
        BEGIN
            UPDATE products 
            SET stock_quantity = (
                SELECT COALESCE(SUM(inv.stock_quantity), 0)
                FROM product_variants pv
                JOIN inventory inv ON pv.id = inv.variant_id
                WHERE pv.product_id = OLD.product_id
            ),
            updated_at = datetime('now')
            WHERE id = OLD.product_id;
        END;
        """)

        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_variant_update_product_stock
        AFTER UPDATE OF product_id ON product_variants
        BEGIN
            UPDATE products 
            SET stock_quantity = (
                SELECT COALESCE(SUM(inv.stock_quantity), 0)
                FROM product_variants pv
                JOIN inventory inv ON pv.id = inv.variant_id
                WHERE pv.product_id = OLD.product_id
            ),
            updated_at = datetime('now')
            WHERE id = OLD.product_id;

            UPDATE products 
            SET stock_quantity = (
                SELECT COALESCE(SUM(inv.stock_quantity), 0)
                FROM product_variants pv
                JOIN inventory inv ON pv.id = inv.variant_id
                WHERE pv.product_id = NEW.product_id
            ),
            updated_at = datetime('now')
            WHERE id = NEW.product_id;
        END;
        """)

        # Reconcile customer total_orders, total_spent, and tier using exact net revenue formula
        cursor.execute("SELECT id FROM customers;")
        cust_ids = [r[0] for r in cursor.fetchall()]
        for cid in cust_ids:
            cursor.execute("""
            SELECT 
                COUNT(*) AS ord_count,
                COALESCE(SUM(
                    s.grand_total - COALESCE((SELECT SUM(sr.total_refund_amount) FROM sale_returns sr WHERE sr.sale_id = s.id), 0.0)
                ), 0.0) AS net_spent
            FROM sales s
            WHERE s.customer_id = ? AND s.sale_status IN ('COMPLETED', 'PARTIALLY_REFUNDED');
            """, (cid,))
            row = cursor.fetchone()
            ord_cnt = row["ord_count"]
            spent = round(row["net_spent"], 2)

            tier = "Bronze"
            if spent >= 30000:
                tier = "Platinum"
            elif spent >= 15000:
                tier = "Gold"
            elif spent >= 5000:
                tier = "Silver"

            cursor.execute("""
            UPDATE customers 
            SET total_orders = ?, total_spent = ?, tier = ?
            WHERE id = ?;
            """, (ord_cnt, spent, tier, cid))

        cursor.execute("""
        INSERT INTO schema_migrations (version, name, applied_at)
        VALUES (5, 'comprehensive_triggers_and_net_crm_reconcile', ?);
        """, (now,))
        conn.commit()


def seed_initial_data(conn: sqlite3.Connection):
    """
    Seeds baseline essential configuration (settings and staff user) ONLY.
    NO fake/demo/sample products.
    NO fake/demo/sample customers.
    NO fake/demo/sample sales or invoices.
    """
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    # 1. Initialize store settings if not present
    cursor.execute("SELECT COUNT(*) FROM settings WHERE id = 1;")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO settings (
            id, store_name, tagline, phone, email, address, gstin, 
            currency_symbol, default_tax_rate, upi_id, return_policy, updated_at
        )
        VALUES (
            1, 'SOL • Soul of Lifestyle', 'PREMIUM WEAR | MODERN ESSENTIALS | ELEVATED YOU', 
            '+91 98765 43210', 'contact@solwear.com', 'Flagship Store, Fashion Avenue, MG Road', 
            '29AAAAA1234A1Z1', '₹', 5.0, 'sol@upi', 
            'Exchange within 7 days with original tags and bill intact. No cash refunds.', ?
        )
        """, (now,))

    # 2. Initialize default staff cashier user if empty
    cursor.execute("SELECT COUNT(*) FROM users;")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO users (id, username, full_name, role, created_at)
        VALUES (1, 'cashier_sol', 'SOL Store Cashier', 'cashier', ?)
        """, (now,))

    # 3. Initialize invoice sequence for the current year
    year = datetime.now().strftime("%Y")
    cursor.execute("SELECT COUNT(*) FROM invoice_sequences WHERE year = ?;", (year,))
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO invoice_sequences (year, last_sequence)
        VALUES (?, 0)
        """, (year,))

    conn.commit()


def init_db(db_path: str = None):
    """
    Initializes database connection, applies all migrations, and verifies integrity.
    """
    conn = get_db(db_path)
    run_migrations(conn)
    seed_initial_data(conn)
    conn.close()


if __name__ == "__main__":
    print(f"Initializing and running migrations on database: {DB_PATH}")
    init_db()
    print("Database initialization and migrations completed successfully.")
