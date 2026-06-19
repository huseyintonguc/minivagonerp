from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import datetime

SQLALCHEMY_DATABASE_URL = "sqlite:///./entegra.db"
# sqlite için check_same_thread=False
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class DBProduct(Base):
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    platform_product_id = Column(String, unique=True, index=True) # Pazaryerindeki ID'si
    barcode = Column(String, index=True)
    name = Column(String)
    stock = Column(Integer, default=0)
    price = Column(Float, default=0.0)
    platform = Column(String) # Hangi pazaryerinden geldi (Trendyol, Hepsiburada vb.)
    image_url = Column(String, nullable=True) # Pazaryerindeki ürünün görsel URL'i

class DBOrder(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    platform_order_id = Column(String, unique=True, index=True)
    platform = Column(String)
    customer_name = Column(String)
    customer_phone = Column(String)
    customer_address = Column(String)
    total_amount = Column(Float)
    status = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    is_printed = Column(Boolean, default=False)
    cargo_tracking_number = Column(String, nullable=True) # Kargo barkodu
    items_json = Column(String, nullable=True) # JSON formatında ürünler

class MarketplaceSettings(Base):
    __tablename__ = "marketplace_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    platform_name = Column(String, unique=True, index=True) # Trendyol, Hepsiburada vb.
    supplier_id = Column(String, nullable=True) # Satıcı ID (Örn: Trendyol için gerekli)
    api_key = Column(String, nullable=True)
    api_secret = Column(String, nullable=True)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()