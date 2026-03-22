# tarimbot v2.0
import os
import base64
import httpx
from datetime import datetime, timezone
from flask import Flask, request, jsonify
import anthropic
from supabase import create_client

app = Flask(__name__)

# ── AYARLAR ──────────────────────────────────────────
WHATSAPP_TOKEN  = os.environ.get("WHATSAPP_TOKEN")
ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_KEY")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "977054132153285")
VERIFY_TOKEN    = "tarimbot2024"
SUPABASE_URL    = os.environ.get("SUPABASE_URL", "https://onqhsmlwwogcdtminwhm.supabase.co")
SUPABASE_KEY    = os.environ.get("SUPABASE_KEY")

anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── KATEGORİ PROMPTLARI ──────────────────────────────
KATEGORI_PROMPTLARI = {
    "toprak": "Kullanıcı TOPRAK ISLAHE hakkında soru soruyor. Toprak pH, tuzluluk, organik madde, drenaj konularına odaklan.",
    "besleme": "Kullanıcı BİTKİ BESLEME hakkında soru soruyor. NPK değerleri, gübre önerileri, besin eksiklikleri konularına odaklan.",
    "hastalik": "Kullanıcı HASTALIK & ZARARLI hakkında soru soruyor. Hastalık teşhisi, ilaç önerileri, önleyici tedbirler konularına odaklan.",
}

# ── SİSTEM PROMPTU ───────────────────────────────────
SISTEM = """Sen Türkiye'nin en deneyimli örtüaltı tarım danışmanısın.
Özellikle Antalya/Kumluca bölgesinde pembe domates, biber, salatalık ve 
diğer örtüaltı ürünleri konusunda uzmanlaşmışsın.

Görevin:
- Kullanıcının gönderdiği NPK ölçüm cihazı ekran görüntüsünü oku ve değerleri çıkar
- Bitki görseli geldiyse hastalık/zararlı teşhisi yap
- Gübre, ilaç ve bakım önerileri ver
- Soru gelirse net ve pratik cevap ver

Önemli kurallar:
- Her zaman Türkçe cevap ver
- Kısa ve anlaşılır ol, çiftçi dostu dil kullan
- Emin olmadığın şeyi söyleme, "uzman görüşü al" de
- Yanlış gübre/ilaç önerisi ciddi zarar verir, dikkatli ol
- Amonyum sülfat gibi yanlış kullanımları mutlaka uyar

Cevap formatı:
🔍 Teşhis: (ne gördün)
⚠️ Sorun: (varsa)
✅ Öneri: (ne yapılmalı)
💊 Ürün: (varsa spesifik öneri)
"""

# ── KAYIT DURUMU (geçici bellek) ─────────────────────
kayit_adimi = {}
kayit_verisi = {}
kullanici_kategorisi = {}

# ── SUPABASE FONKSİYONLARI ───────────────────────────

def kullanici_getir(telefon):
    try:
        r = supabase.table("users").select("*").eq("telefon", telefon).execute()
        return r.data[0] if r.data else None
    except:
        return None

def kullanici_kaydet(telefon, ad, sirket, rol="ciftci"):
    try:
        supabase.table("users").insert({
            "telefon": telefon,
            "ad_soyad": ad,
            "sirket": sirket,
            "rol": rol,
            "kredi": 20,
            "durum": "aktif"
        }).execute()
        return True
    except:
        return False

def kredi_durum(telefon):
    try:
        r = supabase.table("users").select("kredi").eq("telefon", telefon).execute()
        return r.data[0]["kredi"] if r.data else 0
    except:
        return 0

def kredi_dus(telefon, miktar=1, aciklama="Soru"):
    try:
        kullanici = kullanici_getir(telefon)
        yeni_kredi = max(0, kullanici["kredi"] - miktar)
        supabase.table("users").update({"kredi": yeni_kredi}).eq("telefon", telefon).execute()
        supabase.table("kredi_hareketleri").insert({
            "telefon": telefon,
            "miktar": -miktar,
            "islem_tipi": "harcama",
            "aciklama": aciklama
        }).execute()
        return yeni_kredi
    except:
        return 0

def mesaj_logla(telefon, tip, soru, cevap, kategori=None, kredi=1):
    try:
        supabase.table("mesajlar").insert({
            "telefon": telefon,
            "mesaj_tipi": tip,
            "kategori": kategori,
            "soru": soru[:500] if soru else None,
            "cevap": cevap[:1000] if cevap else None,
            "kullanilan_kredi": kredi
        }).execute()
    except Exception as e:
        print(f"Log hatası: {e}")

def ban_kontrol(telefon):
    try:
        kullanici = kullanici_getir(telefon)
        if not kullanici:
            return False
        if kullanici["durum"] == "banli":
            ban_bitis = kullanici.get("ban_bitis")
            if ban_bitis:
                bitis = datetime.fromisoformat(ban_bitis.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) < bitis:
                    return True
                else:
                    supabase.table("users").update({"durum": "aktif"}).eq("telefon", telefon).execute()
        return False
    except:
        return False

# ── WHATSAPP FONKSİYONLARI ───────────────────────────

def menu_gonder(telefon):
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    veri = {
        "messaging_product": "whatsapp",
        "to": telefon,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "🌱 TarimBot\n\nNe hakkında yardım istiyorsunuz?"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "toprak", "title": "🌱 Toprak Islahı"}},
                    {"type": "reply", "reply": {"id": "besleme", "title": "💊 Bitki Besleme"}},
                    {"type": "reply", "reply": {"id": "hastalik", "title": "🦠 Hastalık & Zararlı"}}
                ]
            }
        }
    }
    r = httpx.post(url, headers=headers, json=veri)
    print(f"Menü: {r.status_code}")

def mesaj_gonder(telefon, metin):
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    veri = {
        "messaging_product": "whatsapp",
        "to": telefon,
        "type": "text",
        "text": {"body": metin}
    }
    r = httpx.post(url, headers=headers, json=veri)
    print(f"WA: {r.status_code} {r.text}")

def gorsel_indir(media_id):
    url = f"https://graph.facebook.com/v18.0/{media_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    r = httpx.get(url, headers=headers)
    media_url = r.json().get("url")
    r2 = httpx.get(media_url, headers=headers)
    return base64.b64encode(r2.content).decode("utf-8")

# ── CLAUDE ───────────────────────────────────────────

def claude_sor(metin=None, gorsel_b64=None, mime="image/jpeg", kategori=None):
    sistem = SISTEM
    if kategori and kategori in KATEGORI_PROMPTLARI:
        sistem += f"\n\nÖNEMLİ: {KATEGORI_PROMPTLARI[kategori]}"

    mesajlar = []
    if gorsel_b64:
        icerik = [{"type": "image", "source": {"type": "base64", "media_type": mime, "data": gorsel_b64}}]
        icerik.append({"type": "text", "text": metin if metin else "Bu görseli analiz et ve tarımsal öneri ver."})
        mesajlar.append({"role": "user", "content": icerik})
    else:
        mesajlar.append({"role": "user", "content": metin})

    yanit = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=sistem,
        messages=mesajlar
    )
    return yanit.content[0].text

# ── KAYIT AKIŞI ──────────────────────────────────────

def kayit_akisi(telefon, mesaj):
    adim = kayit_adimi.get(telefon, 0)

    if adim == 0:
        kayit_adimi[telefon] = 1
        kayit_verisi[telefon] = {}
        mesaj_gonder(telefon, "👋 Merhaba! TarimBot'a hoşgeldiniz!\n\n📝 Kayıt olmak için birkaç bilgiye ihtiyacımız var.\n\nAdınız Soyadınız?")

    elif adim == 1:
        kayit_verisi[telefon]["ad"] = mesaj
        kayit_adimi[telefon] = 2
        mesaj_gonder(telefon, "🏡 Çiftlik veya şirket adınız?")

    elif adim == 2:
        kayit_verisi[telefon]["sirket"] = mesaj
        kayit_adimi[telefon] = 3
        mesaj_gonder(telefon, "👤 Rolünüz nedir?\n\n1 - Çiftçi\n2 - Ziraat Mühendisi")

    elif adim == 3:
        rol = "muhendis" if "2" in mesaj or "mühendis" in mesaj.lower() else "ciftci"
        kayit_verisi[telefon]["rol"] = rol
        veri = kayit_verisi[telefon]
        basari = kullanici_kaydet(telefon, veri["ad"], veri["sirket"], rol)

        if basari:
            kayit_adimi.pop(telefon, None)
            kayit_verisi.pop(telefon, None)
            mesaj_gonder(telefon, f"✅ Kaydınız tamamlandı {veri['ad']}!\n\n🎁 Başlangıç hediyesi: 20 kredi yüklendi!\n\n1 metin sorusu = 1 kredi\n1 görsel analiz = 3 kredi")
            menu_gonder(telefon)
        else:
            mesaj_gonder(telefon, "❌ Kayıt sırasında hata oluştu. Lütfen tekrar deneyin.")
            kayit_adimi.pop(telefon, None)

# ── WEBHOOK ──────────────────────────────────────────

@app.route("/webhook", methods=["GET"])
def webhook_dogrula():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Hata", 403

@app.route("/webhook", methods=["POST"])
def webhook_al():
    veri = request.get_json()
    telefon = None
    try:
        entry    = veri["entry"][0]
        degisim  = entry["changes"][0]["value"]
        mesajlar = degisim.get("messages", [])

        for mesaj in mesajlar:
            telefon = mesaj["from"]
            tur     = mesaj["type"]

            # ── BAN KONTROLÜ ──
            if ban_kontrol(telefon):
                mesaj_gonder(telefon, "🚫 Hesabınız geçici olarak askıya alınmıştır.\n\nBilgi: 0850 840 3853")
                continue

            kullanici = kullanici_getir(telefon)

            # ── KAYITSIZ KULLANICI ──
            if not kullanici:
                if telefon in kayit_adimi:
                    metin = mesaj.get("text", {}).get("body", "") if tur == "text" else ""
                    kayit_akisi(telefon, metin)
                else:
                    kayit_akisi(telefon, "")
                continue

            # ── KREDİ KONTROLÜ ──
            kredi = kredi_durum(telefon)
            if kredi <= 0:
                mesaj_gonder(telefon, "💳 Krediniz tükendi!\n\nKredi yüklemek için:\n📞 0850 840 3853")
                continue

            # ── BUTON CEVABI ──
            if tur == "interactive":
                buton_id     = mesaj["interactive"]["button_reply"]["id"]
                buton_baslik = mesaj["interactive"]["button_reply"]["title"]
                kullanici_kategorisi[telefon] = buton_id
                mesaj_gonder(telefon, f"{buton_baslik} seçtiniz.\n\nSorunuzu yazın veya görsel gönderin 👇")

            # ── METİN MESAJI ──
            elif tur == "text":
                soru = mesaj["text"]["body"].strip()

                if soru.lower() in ["merhaba", "menü", "menu", "başla", "hi", "selam", "."]:
                    ad = kullanici.get("ad_soyad", "").split()[0]
                    mesaj_gonder(telefon, f"👋 Merhaba {ad}!\n💳 Krediniz: {kredi}")
                    menu_gonder(telefon)
                else:
                    kategori = kullanici_kategorisi.get(telefon)
                    yanit    = claude_sor(metin=soru, kategori=kategori)
                    kalan    = kredi_dus(telefon, 1, "Metin sorusu")
                    mesaj_logla(telefon, "text", soru, yanit, kategori, 1)
                    mesaj_gonder(telefon, yanit)
                    mesaj_gonder(telefon, f"💳 Kalan kredi: {kalan}")
                    menu_gonder(telefon)

            # ── GÖRSEL ──
            elif tur in ["image", "document"]:
                if kredi < 3:
                    mesaj_gonder(telefon, f"💳 Görsel analiz için 3 kredi gerekli.\nMevcut krediniz: {kredi}\n\n📞 0850 840 3853")
                    continue
                media_id  = mesaj[tur]["id"]
                mime_type = mesaj[tur].get("mime_type", "image/jpeg")
                caption   = mesaj[tur].get("caption", "")
                kategori  = kullanici_kategorisi.get(telefon)
                gorsel    = gorsel_indir(media_id)
                yanit     = claude_sor(metin=caption or None, gorsel_b64=gorsel, mime=mime_type, kategori=kategori)
                kalan     = kredi_dus(telefon, 3, "Görsel analiz")
                mesaj_logla(telefon, "gorsel", caption, yanit, kategori, 3)
                mesaj_gonder(telefon, yanit)
                mesaj_gonder(telefon, f"💳 Kalan kredi: {kalan}")
                menu_gonder(telefon)

    except Exception as e:
        print(f"HATA: {e}")
        import traceback
        traceback.print_exc()
        if telefon:
            try:
                mesaj_gonder(telefon, f"Sistem hatası: {str(e)}")
            except:
                pass

    return jsonify({"status": "ok"}), 200

@app.route("/", methods=["GET"])
def health():
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
