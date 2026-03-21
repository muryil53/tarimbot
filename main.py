import os
import json
import base64
import httpx
from flask import Flask, request, jsonify
import anthropic

app = Flask(__name__)

# ── AYARLAR ──────────────────────────────────────────
WHATSAPP_TOKEN   = os.environ.get("WHATSAPP_TOKEN")
ANTHROPIC_KEY    = os.environ.get("ANTHROPIC_KEY")
PHONE_NUMBER_ID  = "977054132153285"
VERIFY_TOKEN     = "tarimbot2024"

anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

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

# ── WHATSAPP MESAJ GÖNDER ────────────────────────────
def mesaj_gonder(telefon, metin):
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    veri = {
        "messaging_product": "whatsapp",
        "to": telefon,
        "type": "text",
        "text": {"body": metin}
    }
    httpx.post(url, headers=headers, json=veri)

# ── WHATSAPP GÖRSEL İNDİR ────────────────────────────
def gorsel_indir(media_id):
    url = f"https://graph.facebook.com/v18.0/{media_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    r = httpx.get(url, headers=headers)
    media_url = r.json().get("url")
    r2 = httpx.get(media_url, headers=headers)
    return base64.b64encode(r2.content).decode("utf-8")

# ── CLAUDE'A SOR ─────────────────────────────────────
def claude_sor(metin=None, gorsel_b64=None, mime="image/jpeg"):
    mesajlar = []

    if gorsel_b64:
        icerik = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime,
                    "data": gorsel_b64
                }
            }
        ]
        if metin:
            icerik.append({"type": "text", "text": metin})
        else:
            icerik.append({"type": "text", "text": "Bu görseli analiz et ve tarımsal öneri ver."})
        mesajlar.append({"role": "user", "content": icerik})
    else:
        mesajlar.append({"role": "user", "content": metin})

    yanit = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=SISTEM,
        messages=mesajlar
    )
    return yanit.content[0].text

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
    try:
        entry    = veri["entry"][0]
        degisim  = entry["changes"][0]["value"]
        mesajlar = degisim.get("messages", [])

        for mesaj in mesajlar:
            telefon = mesaj["from"]
            tur     = mesaj["type"]

            if tur == "text":
                soru   = mesaj["text"]["body"]
                yanit  = claude_sor(metin=soru)
                mesaj_gonder(telefon, yanit)

            elif tur in ["image", "document"]:
                media_id  = mesaj[tur]["id"]
                mime_type = mesaj[tur].get("mime_type", "image/jpeg")
                caption   = mesaj[tur].get("caption", "")
                gorsel    = gorsel_indir(media_id)
                yanit     = claude_sor(metin=caption or None, gorsel_b64=gorsel, mime=mime_type)
                mesaj_gonder(telefon, yanit)

    except Exception as e:
        print(f"Hata: {e}")

    return jsonify({"status": "ok"}), 200

# ── ÇALIŞTIR ─────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
