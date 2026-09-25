# 🛍️ THREADFLOW • Smart Clothing POS, CRM & Inventory System

An innovative, unified operating system designed specifically for clothing retail businesses, boutiques, and apparel brands. All components are **deeply interconnected**: scanning a garment deducts stock in real-time, links sales to the customer's CRM profile, recalculates best-selling apparel rankings, and instantly generates printable thermal bills, dynamic UPI payment QR codes, and one-click WhatsApp e-receipts.

---

## ⚡ Quick Start (Ready to Use Right Now!)

The system is already running on your machine:
- **Local POS Terminal:** [http://localhost:8000](http://localhost:8000)
- **Local Network (Mobile/Tablet/Cashier iPad):** `http://<your-mac-ip>:8000`
- **Interactive API Documentation:** [http://localhost:8000/docs](http://localhost:8000/docs)

To run or restart the server in the future:
```bash
cd /Users/macbookair/second-brain/clothing-pos-crm
python3 run.py
```

---

## 🌟 Key Features & Deeply Interconnected Workflows

### 1. 📷 Live QR / Barcode Scanning
- **Built-in Camera Scanner:** Click **"Scan QR"** to activate your webcam, laptop camera, or mobile camera with an interactive targeting box and zero-latency audio scan beep.
- **Physical USB/Bluetooth Barcode Gun Listener:** Plug in any standard handheld laser scanner. The system catches scans globally and adds items to the cart in milliseconds.
- **Instant Garment Lookup:** Matches SKU codes (e.g. `SHIRT-OXF-WHT-M`) or standard 1D barcodes (`8901234001`).

### 2. ✏️ On-The-Fly Custom Name & Price ("According to Yourself")
- **Inline Editing in Cart:** Cashiers can click directly on the item name or unit price in the bill table to change it on the fly (e.g. negotiated price, clearance offer, festive discount).
- **"➕ Custom Item" Button:** Add unlisted apparel, alteration/tailoring charges (e.g., *"Jeans Hemming"*, *"Bespoke Stitched Suit"*), gift boxes, or custom accessory combos with custom name, price, quantity, size, and color without pre-registering an SKU.

### 3. 📦 Real-Time Inventory & Stock Auto-Sync
- **Automatic Stock Deduction:** When an invoice is finalized, quantities in the SQLite database decrease automatically within an atomic transaction.
- **Stock Audit Logs:** Tracks every movement (sale, restock, manual adjustment) with invoice references.
- **Low-Stock Alerts:** Visual amber/red warning badges when items fall to or below threshold.
- **Quick Restock Modal:** 1-click restock button with audit reason notes.

### 4. 👥 Customer CRM with VIP Loyalty Tiers
- **Quick Phone Search & Auto-Suggest:** Start typing a customer's phone number or name to pull up their profile.
- **Auto-Registration:** If a new customer's phone number is entered during checkout, the system automatically registers them in the CRM!
- **VIP Loyalty Tiers:**
  - 🥉 **Bronze** (New / Regular)
  - 🥈 **Silver** (₹5,000+ spent) → 5% suggested discount
  - 🥇 **Gold** (₹15,000+ spent) → 10% suggested discount
  - 💎 **Platinum VIP** (₹30,000+ spent) → 15% suggested discount
- **Purchase History Timeline:** Click on any customer to inspect every invoice they ever received, garments bought, preferred sizes, and total lifetime spend.

### 5. 🏆 Best-Selling Products Leaderboard & Analytics
- **Live Leaderboard:** Real-time ranking of top garments by units sold, total revenue generated, and remaining stock.
- **Category Share Breakdown:** Visual progress bars displaying revenue distribution across Shirts, Denim, Ethnic Wear, T-Shirts, Dresses, Jackets, etc.
- **Profit Margin Tracking:** Real-time Gross Profit calculation (Sales minus Cost of Goods Sold).
- **Low-Stock Urgency Radar:** Items at risk of stocking out with 1-click restock actions.

### 6. 🧾 Multi-Format Billing, Printing & WhatsApp Sharing
- **Thermal POS Receipt Format (80mm / 58mm):** Authentic receipt layout with store header, itemized details, discounts, taxes, return policy, and verification QR code.
- **Standard A4 Tax Invoice:** Professional printable letterhead invoice.
- **📲 One-Click WhatsApp E-Receipt:**
  - Automatically formats an itemized receipt message and opens WhatsApp with one tap:
    ```text
    🛍️ Thank you for shopping at Vogue & Stitch Apparel!
    📄 Invoice: INV-2026-0005
    👤 Customer: Aarav Sharma
    ----------------------------------
    1. Classic Oxford Cotton Shirt (M) x 2 = ₹2,798.00
    2. Express Tailoring & Fitting (Custom) x 1 = ₹450.00
    ----------------------------------
    Subtotal: ₹3,248.00
    Discount: -₹150.00
    GST / Tax (5%): +₹154.90
    GRAND TOTAL PAID: ₹3,252.90 (UPI)
    ----------------------------------
    🏷️ Return / Exchange Policy:
    Exchange within 7 days with invoice & tag intact.
    ```
- **Dynamic UPI Payment QR:** Automatically renders an NPCI-compliant UPI QR code on screen with the exact bill total so customers can scan and pay with Google Pay, PhonePe, or Paytm.
- **Cash Change Calculator:** Quick cash buttons (`+100`, `+500`, `+2000`, `Exact`) and live change returned calculation.

### 7. 🏷️ Garment QR Code Hang Tag Generator
- Print ready-to-cut garment price tags with:
  - Brand & Garment Title
  - Category, Size & Color Badges
  - High-Resolution Scannable QR Code
  - MRP (Inclusive of all taxes)
- Attach to clothing items and scan them at the cashier counter using your webcam or phone camera!

---

## 🗄️ Database Architecture (SQLite with WAL Mode)

Located at `/Users/macbookair/second-brain/clothing-pos-crm/clothing_pos.db`:
- `products`: Apparel details, SKU, barcode, size, color, cost, selling price, stock, threshold, QR data.
- `customers`: Phone (unique), name, email, city, notes, total spent, order count, tier, loyalty points.
- `invoices`: Invoice number, customer link, subtotal, discount, tax, grand total, payment method, cash tendered, change, notes.
- `invoice_items`: Line items with custom overrides, unit price, quantity, snapshots cost price for profit margin.
- `stock_logs`: Complete audit history of inventory changes.
- `settings`: Store name, address, GSTIN, UPI ID, return policy, currency.

---

## 🚀 How to Test the Entire Flow

1. Open **[http://localhost:8000](http://localhost:8000)** in your browser.
2. In the **Billing** tab:
   - Type `98201` in Customer search and select **Aarav Sharma (Gold Tier)**.
   - Click **"Apply 10%"** to apply his VIP discount.
   - Enter `SHIRT-OXF-WHT-M` in the barcode input or click an item from the **Pick Grid**.
   - Notice the item appears in the bill. Click on its price or name to customize it on the fly!
   - Click **"Custom Name & Price"** and add `Tailoring / Alteration` for `₹300`.
   - Select payment mode **UPI** to view the dynamic QR code, or **Cash** to see change calculation.
   - Click **"Complete Sale & Generate Bill"**.
3. View the generated **Thermal Receipt**, test the **"Send on WhatsApp"** button, and see the inventory stock automatically reduce in the **Stock & Inventory** tab!
