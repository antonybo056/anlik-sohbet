# Anlık Sohbet

İki (veya daha fazla) cihaz arasında gerçek zamanlı sohbet uygulaması. Mesaj, emoji ve fotoğraf gönderebilir, mesajlara tepki verebilir ve yanıt verebilirsin.

Sunucu Python ile çalışır. Cihazlar uygulamayı tarayıcıdan açar, ayrıca bir şey kurmaları gerekmez.

## Kurulum ve çalıştırma

Python 3.9 veya üstü gerekir.

```bash
pip install -r requirements.txt
python server.py
```

Sunucu açılınca ekranda iki adres yazar:

```
Bu bilgisayarda:   http://localhost:8765
Diğer cihazlarda:  http://192.168.1.100:8765
```

1. Bilgisayarda `http://localhost:8765` adresini aç.
2. Telefonda (veya diğer bilgisayarda) **aynı Wi-Fi'a bağlıyken** "Diğer cihazlarda" satırındaki adresi aç. Sohbet ekranındaki QR kodu telefonun kamerasıyla okutmak da olur.
3. İki cihazda da adını yaz, **aynı oda adını** gir ve sohbete katıl.

Farklı bir port için: `python server.py 9000`

### Windows Güvenlik Duvarı

Sunucuyu ilk açtığında Windows "erişime izin ver" diye sorabilir. **Özel ağlar** için izin ver. Aksi halde diğer cihazlar bağlanamaz.

## Özellikler

- Gerçek zamanlı mesajlaşma (WebSocket)
- Emoji paneli (kategoriler ve son kullanılanlar), sadece emojiden oluşan mesajlar büyük görünür
- Fotoğraf gönderme: düğmeyle seç, sürükle-bırak ya da Ctrl+V ile yapıştır
- Mesajlara emoji ile tepki verme ve yanıt verme
- Kendi mesajını silme
- "Yazıyor…" göstergesi, çevrimiçi kişiler listesi, katıldı/ayrıldı bildirimleri
- Odalar: aynı oda adını yazanlar aynı sohbette buluşur
- Mesaj geçmişi `data/` klasöründe saklanır, sunucu yeniden açılınca kaybolmaz
- Bağlantı koparsa otomatik yeniden bağlanma
- Yeni mesajda ses ve sekme başlığında okunmamış sayısı
- Açık ve koyu tema (cihaz ayarını izler), telefon uyumlu

## Farklı ağlardaki cihazlar

Uygulama varsayılan olarak aynı yerel ağda (aynı Wi-Fi) çalışır. Cihazlar farklı ağlardaysa sunucuyu internete açan bir tünel kullanabilirsin, örneğin:

```bash
cloudflared tunnel --url http://localhost:8765
```

Verilen `https://...` adresini iki cihazda da açman yeterli.

## Dosyalar

| Dosya | İçerik |
| --- | --- |
| `server.py` | WebSocket ve web sunucusu |
| `static/index.html` | Tarayıcıda açılan sohbet uygulaması |
| `data/` | Mesaj geçmişi ve gönderilen fotoğraflar (otomatik oluşur) |
