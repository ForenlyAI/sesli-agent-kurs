"""Gemini Live ilk deneme (ders 2.2 ve 2.4): talimat + araç + Türkçe soru → sesli cevap.

    uv run python deneme_oturum.py [model] "soru"
Çıktı: cevap.wav (24 kHz), ilk sesin gelme süresi, araç çağrısı, cevabın yazıya dökümü.
"""
import asyncio, os, sys, time, wave

from google import genai
from google.genai import types

from dotenv import load_dotenv

load_dotenv()   # .env: GOOGLE_API_KEY (ya da Vertex AI ayarları — ortam/.env.ornek)

MODEL = sys.argv[1] if len(sys.argv) > 1 else "gemini-3.8-live"
SORU = sys.argv[2] if len(sys.argv) > 2 else "Merhaba, cuma günü randevu için boş saatiniz var mı?"

TALIMAT = """Sen Diş Kliniği Gülüş'ün telefon asistanısın.
Türkçe konuş. Kısa konuş: en çok iki cümle.
Sayıları ve saatleri kelimeyle söyle.
Emin değilsen tahmin etme, sor.
Tıbbi tavsiye verme; gerekirse insana aktar."""

ARACLAR = [types.Tool(function_declarations=[types.FunctionDeclaration(
    name="bos_saat_bul",
    description="Verilen gün için boş randevu saatlerini döndürür.",
    parameters={"type": "object", "properties": {"gun": {"type": "string", "description": "YYYY-AA-GG ya da gün adı"}},
                "required": ["gun"]})])]


def bos_saat_bul(gun):
    return {"gun": gun, "bos_saatler": ["10:30", "14:00", "16:30"]}


async def main():
    c = genai.Client()
    ayar = types.LiveConnectConfig(
        response_modalities=["AUDIO"], system_instruction=TALIMAT, tools=ARACLAR,
        output_audio_transcription=types.AudioTranscriptionConfig(),
        speech_config=types.SpeechConfig(language_code="tr-TR"))
    ses, dokum, ilk = bytearray(), [], None
    async with c.aio.live.connect(model=MODEL, config=ayar) as s:
        t0 = time.time()
        await s.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=SORU)]), turn_complete=True)
        bitti = False
        while not bitti:
          async for m in s.receive():
              if m.tool_call:
                  for f in m.tool_call.function_calls:
                      print(f"ARAÇ ÇAĞRISI {f.name}({dict(f.args)}) @ {time.time() - t0:.2f} sn")
                      await s.send_tool_response(function_responses=[types.FunctionResponse(
                          id=f.id, name=f.name, response=bos_saat_bul(**f.args))])
              sc = m.server_content
              if sc:
                  if sc.model_turn:
                      for p in sc.model_turn.parts:
                          if p.inline_data and p.inline_data.data:
                              if ilk is None:
                                  ilk = time.time() - t0
                              ses += p.inline_data.data
                  if sc.output_transcription and sc.output_transcription.text:
                      dokum.append(sc.output_transcription.text)
                  if sc.turn_complete and ses:
                      bitti = True
    with wave.open("cevap.wav", "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(bytes(ses))
    print(f"model {MODEL} · ilk ses {ilk:.2f} sn · ses {len(ses) / 48000:.1f} sn")
    print("DÖKÜM:", "".join(dokum))


asyncio.run(main())
