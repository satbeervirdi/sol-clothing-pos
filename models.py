"""
Pydantic schemas and request/response models for SOL POS & CRM.
Enforces strict validation, non-negative prices/quantities, and type safety.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    sku: str = Field(..., min_length=1, description="Unique variant SKU")
    barcode: Optional[str] = None
    name: str = Field(..., min_length=1, description="Garment style name")
    category: str = "General"
    size: str = "Free Size"
    color: str = "Standard"
    brand: Optional[str] = "SOL"
    cost_price: float = Field(default=0.0, ge=0.0)
    selling_price: float = Field(default=0.0, ge=0.0)
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
    cost_price: Optional[float] = Field(default=None, ge=0.0)
    selling_price: Optional[float] = Field(default=None, ge=0.0)
    low_stock_threshold: Optional[int] = Field(default=None, ge=0)
    image_url: Optional[str] = None


class VariantCreate(BaseModel):
    product_id: int
    sku: str = Field(..., min_length=1)
    barcode: Optional[str] = None
    size: str = "Free Size"
    color: str = "Standard"
    cost_price: float = Field(default=0.0, ge=0.0)
    selling_price: float = Field(default=0.0, ge=0.0)
    gst_rate: float = Field(default=5.0, ge=0.0)
    initial_stock: int = Field(default=0, ge=0)
    low_stock_threshold: int = Field(default=5, ge=0)
    image_url: Optional[str] = ""
    qr_data: Optional[str] = None


class VariantUpdate(BaseModel):
    sku: Optional[str] = None
    barcode: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None
    cost_price: Optional[float] = Field(default=None, ge=0.0)
    selling_price: Optional[float] = Field(default=None, ge=0.0)
    gst_rate: Optional[float] = Field(default=None, ge=0.0)
    low_stock_threshold: Optional[int] = Field(default=None, ge=0)
    image_url: Optional[str] = None
    name: Optional[str] = None
    category: Optional[str] = None
    brand: Optional[str] = None


class StockInRequest(BaseModel):
    variant_id: int
    quantity: int = Field(..., gt=0, description="Quantity received must be at least 1")
    unit_cost: Optional[float] = Field(default=None, ge=0.0)
    reference: Optional[str] = "PURCHASE"
    reason: Optional[str] = "Stock In / Merchandise Receipt"


class StockAdjustRequest(BaseModel):
    variant_id: Optional[int] = None
    quantity_change: int = Field(..., description="Quantity delta (+ for addition, - for reduction)")
    reason: str = Field(default="CORRECTION", description="Reason: DAMAGED, LOSS, CORRECTION, FOUND, SAMPLE, RETURN")
    note: Optional[str] = ""


class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=5)
    email: Optional[str] = ""
    city: Optional[str] = ""
    notes: Optional[str] = ""


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    city: Optional[str] = None
    notes: Optional[str] = None


class InvoiceItemInput(BaseModel):
    product_id: Optional[int] = None
    variant_id: Optional[int] = None
    sku: Optional[str] = ""
    barcode: Optional[str] = ""
    product_name: str = Field(..., min_length=1)
    size: Optional[str] = ""
    color: Optional[str] = ""
    unit_price: float = Field(..., ge=0.0)
    quantity: int = Field(..., ge=1)
    discount_amount: float = Field(default=0.0, ge=0.0)
    line_total: Optional[float] = Field(default=None, ge=0.0)
    gst_rate: Optional[float] = Field(default=None, ge=0.0)


class BillCalculationRequest(BaseModel):
    items: List[InvoiceItemInput]
    discount_type: str = "fixed" # 'fixed' or 'percent'
    discount_val: float = Field(default=0.0, ge=0.0)
    tax_rate: Optional[float] = Field(default=None, ge=0.0)


class InvoiceCreate(BaseModel):
    customer_id: Optional[int] = None
    customer_name: Optional[str] = "Walk-in Guest"
    customer_phone: Optional[str] = ""
    customer_email: Optional[str] = ""
    items: List[InvoiceItemInput]
    subtotal: Optional[float] = None
    discount_type: str = "fixed"
    discount_val: float = Field(default=0.0, ge=0.0)
    discount_amount: Optional[float] = Field(default=0.0, ge=0.0)
    tax_rate: Optional[float] = Field(default=None, ge=0.0)
    tax_amount: Optional[float] = None
    grand_total: Optional[float] = None
    payment_method: str = "Cash"
    payment_status: Optional[str] = "Paid"
    cash_tendered: Optional[float] = Field(default=0.0, ge=0.0)
    change_returned: Optional[float] = Field(default=0.0, ge=0.0)
    notes: Optional[str] = ""


class SaleReturnItemInput(BaseModel):
    sale_item_id: int
    quantity: int = Field(..., gt=0)
    restock_inventory: bool = True


class SaleReturnRequest(BaseModel):
    items: List[SaleReturnItemInput]
    reason: str = Field(..., min_length=1)
    refund_method: str = "Cash"


class SaleCancelRequest(BaseModel):
    reason: str = Field(..., min_length=1)


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
    default_tax_rate: float = Field(default=5.0, ge=0.0)
    upi_id: Optional[str] = ""
    return_policy: Optional[str] = ""
    google_sheets_webhook_url: Optional[str] = ""
    gmail_sender: Optional[str] = ""
    gmail_app_password: Optional[str] = ""


class EmailRequest(BaseModel):
    recipient_email: str
    subject: Optional[str] = None
    body_html: Optional[str] = None


class ImageAnalysisRequest(BaseModel):
    image_data: str # Base64 encoded string or data URI
    filename: Optional[str] = "garment.jpg"
