"""Sesli agent telefon köprüsü (ders 3.2): Twilio Media Streams ↔ Gemini Live.

    uv run uvicorn kopru:app --port 8080

Twilio numarasının "A call comes in" adresi → https://SUNUCU/gelen-arama
  1. /gelen-arama : TwiML döner, Twilio aramanın sesini wss://SUNUCU/medya'ya akıtır
  2. /medya       : Twilio sesi (8 kHz μ-law) → 16 kHz PCM → Gemini
                    Gemini sesi (24 kHz PCM) → 8 kHz μ-law → Twilio
Arayan araya girerse (interrupted) Twilio'ya "clear" gönderilir, agent susar.

Güvenlik (ders 4.2): /gelen-arama yalnız Twilio imzası (X-Twilio-Signature) doğruysa cevap verir;
ses akışı /medya/<SESLI_ANAHTAR> — anahtarı bilmeyen modele bağlanamaz (dakika başı ücret).
.env: GOOGLE_API_KEY, SESLI_ANAHTAR, TWILIO_AUTH_TOKEN (örnek: ortam/.env.ornek)
"""
import asyncio, base64, hashlib, hmac, json, os, time

import numpy as np
from fastapi import FastAPI, Request, Response, WebSocket
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

MODEL = os.environ.get("SESLI_MODEL", "gemini-3.8-live")
ANAHTAR = os.environ["SESLI_ANAHTAR"]
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")

TALIMAT = """Sen Diş Kliniği Gülüş'ün telefon asistanısın.
Türkçe konuş. Kısa konuş: en çok iki cümle.
Sayıları ve saatleri kelimeyle söyle.
Emin değilsen tahmin etme, sor.
Tıbbi tavsiye verme; gerekirse insana aktar.
Görüşme başlayınca kendini tanıt: "Diş Kliniği Gülüş, size nasıl yardımcı olabilirim?\""""

ARACLAR = [types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="bos_saat_bul", description="Verilen gün için boş randevu saatlerini döndürür.",
        parameters={"type": "object", "properties": {"gun": {"type": "string", "description": "YYYY-AA-GG ya da gün adı"}},
                    "required": ["gun"]}),
    types.FunctionDeclaration(
        name="randevu_al", description="Arayan bir saati onaylayınca randevuyu kaydeder. Ad soyadı arayandan öğrenmeden çağırma.",
        parameters={"type": "object", "properties": {"gun": {"type": "string"}, "saat": {"type": "string", "description": "SS:DD"},
                                                     "ad_soyad": {"type": "string"}}, "required": ["gun", "saat", "ad_soyad"]}),
    types.FunctionDeclaration(
        name="insana_aktar", description="Arayanı klinikteki bir çalışana aktarır (tıbbi soru, şikâyet, emin olunmayan durum).",
        parameters={"type": "object", "properties": {"neden": {"type": "string"}}, "required": ["neden"]}),
])]


def bos_saat_bul(gun):   # ders için sahte takvim
    return {"gun": gun, "bos_saatler": ["10:30", "14:00", "16:30"]}


def randevu_al(gun, saat, ad_soyad):
    return {"durum": "kaydedildi", "gun": gun, "saat": saat, "ad_soyad": ad_soyad}


def insana_aktar(neden):
    return {"durum": "aktarılıyor", "neden": neden}


ISLEVLER = {"bos_saat_bul": bos_saat_bul, "randevu_al": randevu_al, "insana_aktar": insana_aktar}

# ---------- ses dönüşümü: μ-law 8 kHz ↔ PCM16 ----------
def ulaw_coz(b: bytes) -> np.ndarray:
    u = ~np.frombuffer(b, np.uint8)
    isaret, us, mant = u & 0x80, (u >> 4) & 7, u & 0x0F
    x = (((mant.astype(np.int32) << 3) + 0x84) << us) - 0x84
    return np.where(isaret, -x, x).astype(np.int16)


def ulaw_kodla(x: np.ndarray) -> bytes:
    x = x.astype(np.int32)
    isaret = np.where(x < 0, 0x80, 0)
    x = np.minimum(np.abs(x), 32635) + 0x84
    us = np.floor(np.log2(x)).astype(np.int32) - 7
    mant = (x >> (us + 3)) & 0x0F
    return (~(isaret | (us << 4) | mant) & 0xFF).astype(np.uint8).tobytes()


def yeniden_ornekle(x: np.ndarray, kaynak: int, hedef: int) -> np.ndarray:
    n = int(len(x) * hedef / kaynak)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.int16) if len(x) else x


app = FastAPI()


def twilio_imzasi_dogru(url: str, form: dict, imza: str) -> bool:
    """Twilio: HMAC-SHA1(auth token, URL + sıralı form alanları), base64"""
    veri = url + "".join(k + form[k] for k in sorted(form))
    beklenen = base64.b64encode(hmac.new(TWILIO_TOKEN.encode(), veri.encode(), hashlib.sha1).digest()).decode()
    return bool(TWILIO_TOKEN) and hmac.compare_digest(beklenen, imza)


@app.post("/gelen-arama")
async def gelen_arama(istek: Request):
    host = istek.headers.get("x-forwarded-host") or istek.headers["host"]
    form = {k: str(v) for k, v in (await istek.form()).items()}
    if not twilio_imzasi_dogru(f"https://{host}/gelen-arama", form, istek.headers.get("x-twilio-signature", "")):
        return Response("imza geçersiz", status_code=403)
    xml = f'<Response><Connect><Stream url="wss://{host}/medya/{ANAHTAR}"/></Connect></Response>'
    return Response(xml, media_type="text/xml")


@app.websocket("/medya/{anahtar}")
async def medya(twilio: WebSocket, anahtar: str):
    if not hmac.compare_digest(anahtar, ANAHTAR):
        await twilio.close(code=1008)
        return
    await twilio.accept()
    ayar = types.LiveConnectConfig(
        response_modalities=["AUDIO"], system_instruction=TALIMAT, tools=ARACLAR,
        speech_config=types.SpeechConfig(language_code="tr-TR"),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig())
    durum = {"sid": None, "son_ses": None}
    dokum = {"arayan": "", "agent": ""}
    async with genai.Client().aio.live.connect(model=MODEL, config=ayar) as ai:

        async def twilio_to_ai():
            async for metin in twilio.iter_text():
                m = json.loads(metin)
                if m["event"] == "start":
                    durum["sid"] = m["start"]["streamSid"]
                    print(f"[arama] başladı {durum['sid']}", flush=True)
                    await ai.send_realtime_input(text="(Arama bağlandı. Karşılama cümlesini söyle.)")
                elif m["event"] == "media":
                    pcm = yeniden_ornekle(ulaw_coz(base64.b64decode(m["media"]["payload"])), 8000, 16000)
                    await ai.send_realtime_input(audio=types.Blob(data=pcm.tobytes(), mime_type="audio/pcm;rate=16000"))
                    durum["son_ses"] = time.time()
                elif m["event"] == "stop":
                    print("[arama] bitti", flush=True)
                    return

        async def ai_to_twilio():
            while True:
                async for m in ai.receive():
                    if m.tool_call:
                        yanit = []
                        for f in m.tool_call.function_calls:
                            print(f"[araç] {f.name}({dict(f.args)})", flush=True)
                            islev = ISLEVLER.get(f.name)
                            try:   # modelin uydurduğu araç ya da eksik argüman aramayı düşürmesin
                                sonuc = islev(**f.args) if islev else {"hata": f"{f.name} diye bir araç yok"}
                            except TypeError as ex:
                                sonuc = {"hata": str(ex)}
                            yanit.append(types.FunctionResponse(id=f.id, name=f.name, response=sonuc))
                        await ai.send_tool_response(function_responses=yanit)
                    sc = m.server_content
                    if not sc:
                        continue
                    if sc.interrupted:   # arayan araya girdi: Twilio'daki sırayı boşalt
                        await twilio.send_json({"event": "clear", "streamSid": durum["sid"]})
                    if sc.input_transcription and sc.input_transcription.text:
                        dokum["arayan"] += sc.input_transcription.text
                    if sc.output_transcription and sc.output_transcription.text:
                        if dokum["arayan"]:
                            print(f"[arayan] {dokum['arayan'].strip()}", flush=True)
                            dokum["arayan"] = ""
                        dokum["agent"] += sc.output_transcription.text
                    if sc.turn_complete and dokum["agent"]:
                        print(f"[agent] {dokum['agent'].strip()}", flush=True)
                        dokum["agent"] = ""
                    if sc.model_turn:
                        for p in sc.model_turn.parts:
                            if p.inline_data and p.inline_data.data and durum["sid"]:
                                pcm = yeniden_ornekle(np.frombuffer(p.inline_data.data, np.int16), 24000, 8000)
                                await twilio.send_json({"event": "media", "streamSid": durum["sid"],
                                                        "media": {"payload": base64.b64encode(ulaw_kodla(pcm)).decode()}})

        gorevler = [asyncio.create_task(twilio_to_ai()), asyncio.create_task(ai_to_twilio())]
        await asyncio.wait(gorevler, return_when=asyncio.FIRST_COMPLETED)
        for g in gorevler:
            g.cancel()
