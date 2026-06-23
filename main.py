from fastapi import FastAPI, Request, HTTPException, Depends, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import os
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import asyncio
from contextlib import asynccontextmanager

from database import get_db, DBProduct, DBOrder, MarketplaceSettings
from marketplace_api import get_client
from scheduler import auto_sync_orders_task

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Uygulama başlarken arkaplan görevini başlat
    task = asyncio.create_task(auto_sync_orders_task())
    yield
    # Kapanırken iptal et
    task.cancel()

app = FastAPI(title="Sipariş ve Fatura Yönetim Sistemi", lifespan=lifespan)

templates = Jinja2Templates(directory="templates")
# Statik dosyaların (resimlerin) okunabilmesi için gerekli satır
app.mount("/static", StaticFiles(directory="static"), name="static")

# Mock Veri Modelleri
class Product(BaseModel):
    id: str
    name: str
    price: float
    quantity: int
    barcode: str

class Order(BaseModel):
    order_id: str
    customer_name: str
    customer_address: str
    customer_phone: str
    platform: str # Trendyol, Hepsiburada, Kendi Sitemiz vb.
    order_date: str
    status: str
    total_amount: float
    products: List[Product]

# Örnek (Mock) Sipariş Veritabanı
mock_orders = [
    Order(
        order_id="TR-987654321",
        customer_name="Ahmet Yılmaz",
        customer_address="Atatürk Mah. Cumhuriyet Cad. No:1 D:5 Ataşehir/İstanbul",
        customer_phone="0555 123 45 67",
        platform="Trendyol",
        order_date="2023-10-25 14:30",
        status="Hazırlanıyor",
        total_amount=549.90,
        products=[
            Product(id="P1", name="Erkek Mavi Gömlek L Beden", price=299.90, quantity=1, barcode="8691234567890"),
            Product(id="P2", name="Siyah Deri Kemer", price=250.00, quantity=1, barcode="8690987654321")
        ]
    ),
    Order(
        order_id="HB-112233445",
        customer_name="Ayşe Kaya",
        customer_address="Gültepe Mah. Lale Sok. No:12 Kağıthane/İstanbul",
        customer_phone="0532 987 65 43",
        platform="Hepsiburada",
        order_date="2023-10-26 09:15",
        status="Yeni Sipariş",
        total_amount=1299.00,
        products=[
            Product(id="P3", name="Kablosuz Kulaklık Siyah", price=1299.00, quantity=1, barcode="8695555555555")
        ]
    )
]

@app.get("/", response_class=HTMLResponse)
def index_page(
    request: Request, 
    error_msg: Optional[str] = None, 
    start_date: Optional[str] = None, 
    end_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Sipariş listeleme (Dashboard) arayüzünü döndürür"""
    query = db.query(DBOrder)
    
    # EĞER EKLENECEK KISIM BURASI: Filtreleme hiç girilmemişse (default durum), son 3 günü göster
    if start_date is None and end_date is None:
        default_start_dt = datetime.now() - timedelta(days=3)
        start_date = default_start_dt.strftime("%Y-%m-%d")
    
    if start_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(DBOrder.created_at >= start_dt)
        except ValueError:
            pass
            
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            # Günün sonuna kadar dahil etmek için
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
            query = query.filter(DBOrder.created_at <= end_dt)
        except ValueError:
            pass
            
    orders = query.order_by(DBOrder.created_at.desc()).all()
    return templates.TemplateResponse(request=request, name="index.html", context={
        "orders": orders, 
        "error_msg": error_msg,
        "start_date": start_date,
        "end_date": end_date
    })

@app.post("/api/sync_orders")
def sync_orders(platform_name: str = Form(...), db: Session = Depends(get_db)):
    """Pazaryerinden API ile siparişleri çeker ve yerel DB'ye yazar."""
    settings = db.query(MarketplaceSettings).filter(MarketplaceSettings.platform_name == platform_name).first()
    
    if settings:
        client = get_client(supplier_id=settings.supplier_id, api_key=settings.api_key, api_secret=settings.api_secret, platform=platform_name)
    else:
        client = get_client(platform=platform_name)

    response = client.fetch_all_orders()
    
    if "error" in response:
        error_msg = response["error"]
        return RedirectResponse(url=f"/?error_msg={error_msg}", status_code=303)

    import json
    
    orders_data = response.get("content", [])
    
    if orders_data:
        for item in orders_data:
            existing_order = db.query(DBOrder).filter(DBOrder.platform_order_id == item.get("orderNumber")).first()
            
            # Kargo numarası
            cargo_num = item.get("cargoTrackingNumber", "")
            if not cargo_num and item.get("cargoTrackingLink"):
                cargo_num = item.get("cargoTrackingLink").split("=")[-1]
                
            # Ürün kalemlerini JSON olarak kaydet
            lines = item.get("lines", [])
            items_json_str = json.dumps(lines)

            if existing_order:
                existing_order.status = item.get("status", "Bilinmiyor")
                existing_order.cargo_tracking_number = cargo_num
                existing_order.items_json = items_json_str
            else:
                new_order = DBOrder(
                    platform_order_id=item.get("orderNumber"),
                    platform=platform_name,
                    customer_name=item.get("shipmentAddress", {}).get("fullName", "Bilinmiyor"),
                    customer_phone=item.get("shipmentAddress", {}).get("phone", ""),
                    customer_address=item.get("shipmentAddress", {}).get("fullAddress", ""),
                    total_amount=item.get("grossAmount", 0.0),
                    status=item.get("status", "Yeni"),
                    cargo_tracking_number=cargo_num,
                    items_json=items_json_str
                )
                db.add(new_order)
        db.commit()
        
    return RedirectResponse(url="/", status_code=303)

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, success_msg: Optional[str] = None, db: Session = Depends(get_db)):
    """Ayarlar arayüzünü döndürür."""
    settings = db.query(MarketplaceSettings).all()
    return templates.TemplateResponse(request=request, name="settings.html", context={"settings": settings, "success_msg": success_msg})

@app.post("/api/save_settings")
def save_settings(
    platform_name: str = Form(...),
    supplier_id: str = Form(...),
    api_key: str = Form(...),
    api_secret: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Pazaryeri API ayarlarını veritabanına kaydeder."""
    existing = db.query(MarketplaceSettings).filter(MarketplaceSettings.platform_name == platform_name).first()
    
    if existing:
        existing.supplier_id = supplier_id
        existing.api_key = api_key
        existing.api_secret = api_secret
    else:
        new_setting = MarketplaceSettings(
            platform_name=platform_name,
            supplier_id=supplier_id,
            api_key=api_key,
            api_secret=api_secret
        )
        db.add(new_setting)
        
    db.commit()
    return RedirectResponse(url="/settings?success_msg=Ayarlar başarıyla kaydedildi.", status_code=303)

@app.get("/products", response_class=HTMLResponse)
def products_page(request: Request, error_msg: Optional[str] = None, db: Session = Depends(get_db)):
    """Veritabanındaki ürünleri listeler"""
    products = db.query(DBProduct).all()
    return templates.TemplateResponse(request=request, name="products.html", context={"products": products, "error_msg": error_msg})

@app.post("/api/sync_products")
def sync_products(platform_name: str = Form(...), db: Session = Depends(get_db)):
    """Pazaryerinden API ile ürünleri çeker ve yerel DB'ye yazar."""
    # 1. DB'den ayarları oku
    settings = db.query(MarketplaceSettings).filter(MarketplaceSettings.platform_name == platform_name).first()
    
    # 2. Client'ı ayarlar ile oluştur
    if settings:
        client = get_client(supplier_id=settings.supplier_id, api_key=settings.api_key, api_secret=settings.api_secret, platform=platform_name)
    else:
        # Ayar yoksa mock client oluştur
        client = get_client(platform=platform_name)

    # 3. Ürünleri Çek
    response = client.fetch_all_products()
    
    if "error" in response:
        # Eğer API'den hata döndüyse, bu hatayı ekranda göstermek üzere yönlendir
        error_msg = response["error"]
        return RedirectResponse(url=f"/products?error_msg={error_msg}", status_code=303)

    products_data = response.get("content", [])
    
    if products_data:
        for item in products_data:
            img_url = ""
            if "images" in item and len(item["images"]) > 0:
                img_url = item["images"][0].get("url", "")
                
            # Ürün veritabanında var mı kontrol et
            existing_product = db.query(DBProduct).filter(DBProduct.platform_product_id == item["id"]).first()
            if existing_product:
                existing_product.price = item["price"]
                existing_product.stock = item["stock"]
                existing_product.name = item["title"]
                if img_url:
                    existing_product.image_url = img_url
            else:
                new_product = DBProduct(
                    platform_product_id=item["id"],
                    barcode=item["barcode"],
                    name=item["title"],
                    stock=item["stock"],
                    price=item["price"],
                    platform=platform_name,
                    image_url=img_url
                )
                db.add(new_product)
                
        db.commit()
        
    # İşlem bitince ürünler sayfasına geri dön
    return RedirectResponse(url="/products", status_code=303)

@app.post("/api/upload_image")
async def upload_product_image(barcode: str = Form(...), file: UploadFile = File(...)):
    """Kullanıcının yüklediği görseli barkod adıyla kaydeder."""
    try:
        # Sadece jpg, jpeg, png kabul edelim
        extension = file.filename.split(".")[-1].lower()
        if extension not in ["jpg", "jpeg", "png", "webp"]:
            return RedirectResponse(url="/products?error_msg=Geçersiz dosya formatı. Sadece JPG ve PNG yükleyebilirsiniz.", status_code=303)
            
        # Eğer klasör yoksa oluştur
        os.makedirs("static/images", exist_ok=True)    
        
        file_location = f"static/images/{barcode}.jpg"
        
        with open(file_location, "wb+") as file_object:
            file_object.write(file.file.read())
            
        return RedirectResponse(url="/products", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/products?error_msg=Resim yüklenirken hata oluştu: {str(e)}", status_code=303)

@app.post("/api/add_product")
def add_product_manual(
    barcode: str = Form(...),
    name: str = Form(...),
    price: float = Form(...),
    stock: int = Form(...),
    platform: str = Form(...),
    db: Session = Depends(get_db)
):
    """Sisteme manuel ürün ekler."""
    existing_product = db.query(DBProduct).filter(DBProduct.barcode == barcode).first()
    if existing_product:
        return RedirectResponse(url="/products?error_msg=Bu barkoda sahip ürün zaten mevcut.", status_code=303)
        
    # Manuel ürünlerde platform_product_id olarak "MANUAL-{barkod}" kullanıyoruz
    new_product = DBProduct(
        platform_product_id=f"MANUAL-{barcode}",
        barcode=barcode,
        name=name,
        stock=stock,
        price=price,
        platform=platform
    )
    db.add(new_product)
    db.commit()
    return RedirectResponse(url="/products", status_code=303)

@app.post("/api/update_price")
def update_product_price(db_id: int = Form(...), new_price: float = Form(...), db: Session = Depends(get_db)):
    """Arayüzden gelen fiyat güncellemesini alır, pazaryerine iletir ve DB'yi günceller."""
    product = db.query(DBProduct).filter(DBProduct.id == db_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Veritabanında ürün bulunamadı.")
        
    # İlgili platformun ayarlarını bul
    settings = db.query(MarketplaceSettings).filter(MarketplaceSettings.platform_name == product.platform).first()
    if settings:
        client = get_client(supplier_id=settings.supplier_id, api_key=settings.api_key, api_secret=settings.api_secret, platform=product.platform)
    else:
        client = get_client(platform=product.platform)
        
    # Pazaryerindeki API'ye fiyat güncelleme isteği atıyoruz
    api_response = client.update_price(product.barcode, new_price)
    
    if api_response.get("success"):
        # API onayladıysa veritabanını da güncelliyoruz
        product.price = new_price
        db.commit()
    
    return RedirectResponse(url="/products", status_code=303)

@app.get("/api/orders", response_model=List[Order])
def get_orders():
    """Tüm siparişleri JSON olarak döndürür (Pazaryerinden çekiyormuşuz gibi)"""
    return mock_orders

@app.get("/api/orders/{order_id}", response_model=Order)
def get_order(order_id: str):
    """Belirli bir siparişin detaylarını döndürür"""
    for order in mock_orders:
        if order.order_id == order_id:
            return order
    raise HTTPException(status_code=404, detail="Sipariş bulunamadı.")

@app.get("/invoice/{order_id}", response_class=HTMLResponse)
def invoice_page(request: Request, order_id: str, db: Session = Depends(get_db)):
    """Seçilen siparişin fatura/çıktı şablonunu döndürür"""
    order = db.query(DBOrder).filter(DBOrder.platform_order_id == order_id).first()
            
    if not order:
        return HTMLResponse(content="Sipariş bulunamadı.", status_code=404)
        
    return templates.TemplateResponse(request=request, name="invoice.html", context={"order": order})

@app.post("/api/mark_printed/{order_id}")
def mark_printed(order_id: str, db: Session = Depends(get_db)):
    """Arayüzden (JS fetch) gelen istekle siparişi yazdırıldı olarak işaretler."""
    order = db.query(DBOrder).filter(DBOrder.platform_order_id == order_id).first()
    if order:
        order.is_printed = True
        db.commit()
        return {"success": True}
    raise HTTPException(status_code=404, detail="Sipariş bulunamadı.")

@app.get("/bulk_invoice", response_class=HTMLResponse)
def bulk_invoice_page(request: Request, order_ids: str, db: Session = Depends(get_db)):
    """Seçilen siparişlerin toplu fatura/çıktı şablonunu döndürür"""
    ids_list = order_ids.split(",")
    orders = db.query(DBOrder).filter(DBOrder.platform_order_id.in_(ids_list)).all()
            
    if not orders:
        return HTMLResponse(content="Seçili sipariş bulunamadı.", status_code=404)
        
    return templates.TemplateResponse(request=request, name="bulk_invoice.html", context={"orders": orders})

@app.post("/api/mark_printed_bulk")
def mark_printed_bulk(order_ids: List[str] = Form(...), db: Session = Depends(get_db)):
    """Arayüzden gelen liste ile siparişleri toplu yazdırıldı olarak işaretler."""
    # Javascript listesini yakalamak için düz string gelme ihtimaline karşı
    if len(order_ids) == 1 and "," in order_ids[0]:
        order_ids = order_ids[0].split(",")
        
    orders = db.query(DBOrder).filter(DBOrder.platform_order_id.in_(order_ids)).all()
    for order in orders:
        order.is_printed = True
    db.commit()
    return {"success": True}

@app.post("/api/delete_order/{order_id}")
def delete_order(order_id: str, db: Session = Depends(get_db)):
    """Belirtilen siparişi veritabanından siler."""
    order = db.query(DBOrder).filter(DBOrder.platform_order_id == order_id).first()
    if order:
        db.delete(order)
        db.commit()
    return RedirectResponse(url="/", status_code=303)