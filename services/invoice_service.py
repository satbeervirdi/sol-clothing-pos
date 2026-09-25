"""
Invoice PDF & Print Receipt Service for SOL POS & CRM.
Generates luxury thermal receipts and vector tax invoices.
"""
import io
from typing import Dict, Any

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
except ImportError:
    pass


def generate_invoice_pdf_buffer(inv: Dict[str, Any], settings: Dict[str, Any]) -> io.BytesIO:
    """
    Renders an official vector PDF invoice into a memory buffer.
    """
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
            Paragraph(f"<b>PAYMENT:</b> {inv.get('payment_method', 'Cash')} ({inv.get('payment_status', 'Paid')})", meta_style),
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
