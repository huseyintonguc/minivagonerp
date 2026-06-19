import uvicorn
import multiprocessing
import main  # PyInstaller'in projemizi tanıması için eklendi

if __name__ == "__main__":
    multiprocessing.freeze_support()
    print("Siparis Yonetim Sistemi Baslatiliyor...")
    print("Sisteme girmek icin tarayicinizdan su adresi acin: http://127.0.0.1:8000")
    print("Uygulamayi kapatmak icin bu pencereyi (konsolu) kapatabilirsiniz.")
    
    # "main:app" stringi yerine doğrudan main.app nesnesini çağırıyoruz
    uvicorn.run(main.app, host="127.0.0.1", port=8000, reload=False)