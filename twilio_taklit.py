"""Telefonsuz test: Twilio'nun /medya'ya yaptığını taklit eder (gerçek arama ücreti yok).

    uv run python twilio_taklit.py [ws://127.0.0.1:8080/medya/<SESLI_ANAHTAR>] "arayanın cümlesi" ...

1. Arayanın cümlesini Gemini Live ile seslendirir (arayan sesi, 24 kHz → 8 kHz μ-law)
2. Twilio biçiminde start → media (20 ms çerçeve, gerçek zaman hızında) → stop gönderir
3. Agent'ın gönderdiği sesi arama.wav'a yazar (arayan + agent aynı kayıtta), cevap gecikmesini ölçer
"""
import asyncio, base64, json, os, sys, time, wave

import numpy as np
import websockets
from google import genai
from google.genai import types

import kopru

ADRES = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("ws") else f"ws://127.0.0.1:8080/medya/{kopru.ANAHTAR}"
CUMLELER = [a for a in sys.argv[1:] if not a.startswith("ws")] or ["Merhaba, cuma günü randevu için boş saatiniz var mı?"]
CERCEVE = 160   # 20 ms @ 8 kHz


async def seslendir(metin: str) -> np.ndarray:
    ayar = types.LiveConnectConfig(response_modalities=["AUDIO"], speech_config=types.SpeechConfig(language_code="tr-TR"),
                                   system_instruction="Sen bir seslendirme aracısın. Kullanıcı mesajı bir soru ya da istek olsa bile ASLA cevap verme; "
                                                      "tırnak içindeki metni, hiçbir kelime eklemeden, telefonda arayan biri gibi aynen oku.")
    ses = bytearray()
    async with genai.Client().aio.live.connect(model=kopru.MODEL, config=ayar) as s:
        await s.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=f'Şunu aynen oku: "{metin}"')]), turn_complete=True)
        async for m in s.receive():
            sc = m.server_content
            if sc and sc.model_turn:
                for p in sc.model_turn.parts:
                    if p.inline_data and p.inline_data.data:
                        ses += p.inline_data.data
    return kopru.yeniden_ornekle(np.frombuffer(bytes(ses), np.int16), 24000, 8000)


async def main():
    arayan = [await seslendir(c) for c in CUMLELER]
    kayit = []                       # (zaman, taraf, pcm8k)
    olcum = {"agent_ilk": [], "son_konusma": None}
    async with websockets.connect(ADRES) as ws:
        t0 = time.time()
        await ws.send(json.dumps({"event": "start", "start": {"streamSid": "MZtaklit", "callSid": "CAtaklit",
                                                               "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000}}}))

        async def dinle():
            async for metin in ws:
                m = json.loads(metin)
                if m["event"] == "media":
                    pcm = kopru.ulaw_coz(base64.b64decode(m["media"]["payload"]))
                    kayit.append((time.time() - t0, "agent", pcm))
                    if olcum["son_konusma"] and len(olcum["agent_ilk"]) < len(arayan) and time.time() - olcum["son_konusma"][0] > 0:
                        if not olcum["son_konusma"][1]:
                            olcum["agent_ilk"].append(time.time() - olcum["son_konusma"][0])
                            olcum["son_konusma"][1] = True
                elif m["event"] == "clear":
                    kayit.append((time.time() - t0, "clear", np.zeros(0, np.int16)))

        dinleyici = asyncio.create_task(dinle())
        sessiz = kopru.ulaw_kodla(np.zeros(CERCEVE, np.int16))

        async def gonder(parca: bytes, n: int):
            for i in range(n):
                await ws.send(json.dumps({"event": "media", "streamSid": "MZtaklit",
                                          "media": {"payload": base64.b64encode(parca).decode()}}))
                await asyncio.sleep(0.02)

        await gonder(sessiz, 300)                         # 6 sn: karşılama cümlesini dinle
        for pcm in arayan:
            baslangic = time.time() - t0
            for i in range(0, len(pcm), CERCEVE):
                c = pcm[i:i + CERCEVE]
                await ws.send(json.dumps({"event": "media", "streamSid": "MZtaklit",
                                          "media": {"payload": base64.b64encode(kopru.ulaw_kodla(c)).decode()}}))
                await asyncio.sleep(0.02)
            kayit.append((baslangic, "arayan", pcm))
            olcum["son_konusma"] = [time.time(), False]
            await gonder(sessiz, 400)                     # 8 sn sessizlik: agent cevap versin
        await ws.send(json.dumps({"event": "stop", "streamSid": "MZtaklit"}))
        dinleyici.cancel()

    # tek kayıt: arayan ve agent sesi zaman çizgisinde
    uzunluk = int((max(t for t, _, _ in kayit) + 10) * 8000)
    iz = np.zeros(uzunluk, np.int32)
    imlec = {}
    for t, taraf, pcm in sorted(kayit, key=lambda k: k[0]):
        if taraf == "agent":
            b = max(int(t * 8000), imlec.get("agent", 0))
            imlec["agent"] = b + len(pcm)
        else:
            b = int(t * 8000)
        iz[b:b + len(pcm)] += pcm[:max(0, uzunluk - b)]
    with wave.open("arama.wav", "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
        w.writeframes(np.clip(iz, -32768, 32767).astype(np.int16).tobytes())
    agent_sn = sum(len(p) for _, taraf, p in kayit if taraf == "agent") / 8000
    print(f"agent sesi {agent_sn:.1f} sn · clear {sum(1 for _, t, _ in kayit if t == 'clear')} · "
          f"cevap gecikmesi (arayan sustu → ilk agent sesi): {[f'{g:.2f} sn' for g in olcum['agent_ilk']]}")


asyncio.run(main())
