"""Köprünün güvenlik kapıları (ders 4.2): imzasız istek ve yanlış anahtar reddedilmeli.

    uv run python test_guvenlik.py [http://127.0.0.1:8080]
"""
import asyncio, base64, hashlib, hmac, os, sys

import httpx
import websockets
from dotenv import load_dotenv

load_dotenv()
TABAN = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
HOST = "ornek.test"
FORM = {"CallSid": "CAtest", "From": "+900000000000", "To": "+10000000000"}
gecen = kalan = 0


def adim(ad, kosul):
    global gecen, kalan
    print(("GEÇTİ  " if kosul else "KALDI  ") + ad)
    gecen, kalan = gecen + bool(kosul), kalan + (not kosul)


def imza(token, url, form):
    veri = url + "".join(k + form[k] for k in sorted(form))
    return base64.b64encode(hmac.new(token.encode(), veri.encode(), hashlib.sha1).digest()).decode()


dogru = imza(os.environ["TWILIO_AUTH_TOKEN"], f"https://{HOST}/gelen-arama", FORM)
r = httpx.post(f"{TABAN}/gelen-arama", data=FORM, headers={"Host": HOST})
adim(f"imzasız istek reddedildi ({r.status_code})", r.status_code == 403)
r = httpx.post(f"{TABAN}/gelen-arama", data=FORM, headers={"Host": HOST, "X-Twilio-Signature": imza("yanlis", f"https://{HOST}/gelen-arama", FORM)})
adim(f"yanlış anahtarla imza reddedildi ({r.status_code})", r.status_code == 403)
r = httpx.post(f"{TABAN}/gelen-arama", data=FORM, headers={"Host": HOST, "X-Twilio-Signature": dogru})
adim(f"doğru imza TwiML aldı ({r.status_code})", r.status_code == 200 and "<Stream" in r.text)
adim("TwiML'deki ses adresi anahtarlı", f"/medya/{os.environ['SESLI_ANAHTAR']}" in r.text)


async def ws_dene(yol):
    try:
        async with websockets.connect(TABAN.replace("http", "ws") + yol) as ws:
            await asyncio.wait_for(ws.recv(), 3)
            return "açık"
    except websockets.exceptions.InvalidStatus as ex:
        return f"reddedildi {ex.response.status_code}"
    except websockets.exceptions.ConnectionClosed as ex:
        return f"kapatıldı {ex.rcvd.code if ex.rcvd else ''}"
    except asyncio.TimeoutError:
        return "açık"

sonuc = asyncio.run(ws_dene("/medya/yanlis-anahtar"))
adim(f"yanlış anahtarla ses akışı açılmadı ({sonuc})", sonuc != "açık")
sonuc = asyncio.run(ws_dene("/medya"))
adim(f"anahtarsız ses akışı açılmadı ({sonuc})", sonuc != "açık")
print(f"────────────\n{gecen} GEÇTİ · {kalan} KALDI")
sys.exit(1 if kalan else 0)
