"""
Pytest configuration and fixtures for SOL POS & CRM test suite.
"""
import os
import tempfile
import pytest
from starlette.testclient import TestClient
from database import init_db, get_db
from main import app


@pytest.fixture(scope="function")
def test_db():
    """
    Creates an isolated temporary SQLite database, runs migrations and baseline seeds,
    sets SOL_DB_PATH, and tears it down after test completion.
    """
    fd, path = tempfile.mkstemp(suffix=".db", prefix="sol_test_")
    os.close(fd)
    
    # Set environment variable so all service calls and route handlers target this test database
    old_env = os.environ.get("SOL_DB_PATH")
    os.environ["SOL_DB_PATH"] = path

    # Initialize schema & baseline data
    init_db(path)

    yield path

    # Cleanup
    if old_env is not None:
        os.environ["SOL_DB_PATH"] = old_env
    else:
        os.environ.pop("SOL_DB_PATH", None)

    for ext in ["", "-wal", "-shm"]:
        p = path + ext
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


@pytest.fixture(scope="function")
def db_conn(test_db):
    """
    Provides a direct SQLite connection to the test database.
    """
    conn = get_db(test_db)
    yield conn
    conn.close()


@pytest.fixture(scope="function")
def client(test_db):
    """
    FastAPI TestClient with SOL_DB_PATH pointed at the isolated test database.
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="function")
def sample_customer(db_conn):
    """
    Creates a baseline customer in the test database.
    """
    from services.customers_service import create_customer
    from models import CustomerCreate
    cust_in = CustomerCreate(
        name="Arjun Sharma",
        phone="9876543210",
        email="arjun.sharma@example.com",
        city="Mumbai",
        tier="Regular",
        notes="Loyal customer"
    )
    return create_customer(db_conn, cust_in)


@pytest.fixture(scope="function")
def sample_product_with_variants(db_conn):
    """
    Creates a product with 2 variants and initialized inventory stock.
    Variant 1: Size M, Stock 10, Price 1500
    Variant 2: Size L, Stock 5, Price 1600
    """
    from services.products_service import create_product, create_variant
    from services.inventory_service import stock_in
    from models import ProductCreate, VariantCreate, StockInRequest

    prod_in = ProductCreate(
        name="SOL Heavyweight Oversized Tee",
        sku="SOL-TEE-OVS-M",
        barcode="8901234567891",
        category="T-Shirts",
        brand="SOL",
        size="M",
        color="Onyx Black",
        selling_price=1500.0,
        cost_price=600.0,
        low_stock_threshold=3
    )
    v1_item = create_product(db_conn, prod_in)
    product_id = v1_item["product_id"]
    v1_id = v1_item["variant_id"]

    v2_item = create_variant(db_conn, VariantCreate(
        product_id=product_id,
        sku="SOL-TEE-OVS-L",
        barcode="8901234567892",
        size="L",
        color="Onyx Black",
        selling_price=1600.0,
        cost_price=650.0,
        initial_stock=0,
        low_stock_threshold=2
    ))
    v2_id = v2_item["variant_id"]

    # Stock-in Variant 1: 10 units
    stock_in(
        conn=db_conn,
        variant_id=v1_id,
        quantity=10,
        unit_cost=600.0,
        reason="Initial stock reception"
    )

    # Stock-in Variant 2: 5 units
    stock_in(
        conn=db_conn,
        variant_id=v2_id,
        quantity=5,
        unit_cost=650.0,
        reason="Initial stock reception"
    )

    return {
        "product_id": product_id,
        "variant_1": {"id": v1_id, "sku": "SOL-TEE-OVS-M", "stock": 10, "price": 1500.0},
        "variant_2": {"id": v2_id, "sku": "SOL-TEE-OVS-L", "stock": 5, "price": 1600.0}
    }
