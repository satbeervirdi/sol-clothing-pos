"""
Notification & External Sync Service for SOL POS & CRM.
Handles WhatsApp deep-linking, Gmail SMTP background dispatch,
and Google Sheets webhook synchronization.
"""
import json
import smtplib
import urllib.parse
import urllib.request
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from typing import Dict, Any

from database import get_db


def build_whatsapp_link(phone: str, customer_name: str, invoice_number: str, grand_total: float, store_name: str = "SOL • Soul of Lifestyle") -> str:
    """Generates sanitized direct WhatsApp messaging deep link for receipt sharing."""
    clean_digits = "".join(filter(str.isdigit, phone))
    msg = (
        f"Hi {customer_name},\n\n"
        f"Thank you for shopping with {store_name}.\n\n"
        f"Invoice: {invoice_number}\n"
        f"Amount: ₹{grand_total:.2f}\n\n"
        f"Your digital tax invoice is generated."
    )
    return f"https://api.whatsapp.com/send?phone={clean_digits}&text={urllib.parse.quote(msg)}"


def dispatch_invoice_email_task(sender: str, password: str, recipient: str, inv_number: str, pdf_bytes: bytes, sale_id: int):
    """Background task to dispatch PDF invoice via Gmail SMTP."""
    conn = get_db()
    try:
        msg = MIMEMultipart()
        msg['From'] = f"SOL • Soul of Lifestyle <{sender}>"
        msg['To'] = recipient
        msg['Subject'] = f"Your SOL Invoice — {inv_number}"

        body = (
            f"Hello,\n\n"
            f"Thank you for shopping with SOL — Soul of Lifestyle.\n"
            f"Please find your tax invoice {inv_number} attached as a PDF.\n\n"
            f"Warm regards,\nSOL Retail Team"
        )
        msg.attach(MIMEText(body, 'plain'))

        pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
        pdf_part.add_header('Content-Disposition', 'attachment', filename=f"{inv_number}.pdf")
        msg.attach(pdf_part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(sender, password)
            server.send_message(msg)

        conn.execute("UPDATE invoice_delivery_logs SET status = 'SENT' WHERE sale_id = ? AND channel = 'EMAIL';", (sale_id,))
        conn.commit()
    except Exception as e:
        conn.execute("UPDATE invoice_delivery_logs SET status = 'FAILED', error_message = ? WHERE sale_id = ? AND channel = 'EMAIL';", (str(e), sale_id))
        conn.commit()
    finally:
        conn.close()


def sync_invoice_to_google_sheets(invoice_data: Dict[str, Any], webhook_url: str):
    """
    Sends outbound transaction summary to Google Sheets webhook (Section 21: Database -> Sheets).
    """
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
        print("[Google Sheets Sync Notice]:", e)
