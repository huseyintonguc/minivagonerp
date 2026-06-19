import asyncio
from sqlalchemy.orm import Session
from database import SessionLocal, MarketplaceSettings, DBOrder
from marketplace_api import get_client
import datetime

async def auto_sync_orders_task():
    """Her 5 dakikada bir çalışarak tüm platformlardaki yeni siparişleri DB'ye yazar."""
    while True:
        try:
            print(f"[{datetime.datetime.now()}] Otomatik Sipariş Senkronizasyonu Başladı...")
            db: Session = SessionLocal()
            settings_list = db.query(MarketplaceSettings).all()
            
            for settings in settings_list:
                client = get_client(
                    supplier_id=settings.supplier_id, 
                    api_key=settings.api_key, 
                    api_secret=settings.api_secret, 
                    platform=settings.platform_name
                )
                response = client.fetch_all_orders()
                
                import json
                
                if "error" not in response:
                    orders_data = response.get("content", [])
                    for item in orders_data:
                        order_id = item.get("orderNumber")
                        existing_order = db.query(DBOrder).filter(DBOrder.platform_order_id == order_id).first()
                        
                        cargo_num = item.get("cargoTrackingNumber", "")
                        if not cargo_num and item.get("cargoTrackingLink"):
                            cargo_num = item.get("cargoTrackingLink").split("=")[-1]
                            
                        lines = item.get("lines", [])
                        items_json_str = json.dumps(lines)

                        if existing_order:
                            # Varsa sadece status güncelle (Yazdırıldı bilgisini bozma)
                            existing_order.status = item.get("status", existing_order.status)
                            existing_order.cargo_tracking_number = cargo_num
                            existing_order.items_json = items_json_str
                        else:
                            # Yeni siparişse ekle
                            new_order = DBOrder(
                                platform_order_id=order_id,
                                platform=settings.platform_name,
                                customer_name=item.get("shipmentAddress", {}).get("fullName", "Bilinmiyor"),
                                customer_phone=item.get("shipmentAddress", {}).get("phone", ""),
                                customer_address=item.get("shipmentAddress", {}).get("fullAddress", ""),
                                total_amount=item.get("grossAmount", 0.0),
                                status=item.get("status", "Yeni"),
                                is_printed=False,
                                cargo_tracking_number=cargo_num,
                                items_json=items_json_str
                            )
                            db.add(new_order)
                    db.commit()
            db.close()
            print(f"[{datetime.datetime.now()}] Otomatik Sipariş Senkronizasyonu Bitti.")
        except Exception as e:
            print(f"Otomatik senkronizasyon hatası: {e}")
            
        # 5 dakika (300 saniye) bekle
        await asyncio.sleep(300)