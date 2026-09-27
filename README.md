# Sesli Agent 101 · Lab — Telefonla konuşan randevu asistanı

Bir diş kliniğinin telefon asistanı: arayanı Türkçe karşılar, boş saatleri takvimden bulur, randevuyu kaydeder,
tıbbi soruda insana aktarır. Model **Gemini Live** (sesi dinler, sesle cevap verir); telefon tarafı **Twilio Media Streams**.

> **ÖRNEK VERİ:** Klinik, takvim ve kişiler uydurmadır. Randevu araçları sahte bir takvime bakar.

## En kolay yol: GitHub Codespaces

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/ForenlyAI/sesli-agent-kurs?quickstart=1)

1. [Google AI Studio](https://aistudio.google.com)'dan bir API anahtarı alın (ücretsiz kota).
2. Codespace açılırken `GOOGLE_API_KEY` sorulur; anahtarı oraya yapıştırın. Anahtar depoya girmez.
3. Kurulum kendiliğinden yapılır (~1 dk). Sonra:

```bash
bash kontrol.sh            # 7 adım · GEÇTİ / KALDI (~1 dk)
```

Gerçek telefon gerekmez: `twilio_taklit.py` Twilio'nun köprüye gönderdiği mesajları birebir taklit eder.

## Kendi bilgisayarınızda

```bash
uv sync                          # Python 3.12+ ve uv (docs.astral.sh/uv)
cp ortam/.env.ornek .env         # GOOGLE_API_KEY'i doldurun · .env'i paylaşmayın
bash kontrol.sh
```

## Dersler ve dosyalar

| Ders | Dosya | Komut |
|---|---|---|
| 2.1 · kurulum ve anahtar | `ortam/.env.ornek`, `pyproject.toml` | `uv sync` |
| 2.2 · ilk konuşma · 2.4 · araç çağırma | `deneme_oturum.py` | `uv run python deneme_oturum.py` → `cevap.wav` |
| 3.2 · Twilio köprüsü | `kopru.py` | `uv run uvicorn kopru:app --port 8080` |
| 3.2 · telefonsuz arama | `twilio_taklit.py` | `uv run python twilio_taklit.py ws://127.0.0.1:8080/medya/<SESLI_ANAHTAR> "Cuma boş saat var mı?"` → `arama.wav` |
| 4.1 · test · 4.2 · güvenlik | `kontrol.sh`, `test_guvenlik.py` | `bash kontrol.sh` |

## Gerçek telefonla denemek (ders 3.1–3.2, isteğe bağlı)

Twilio hesabı ve numarası gerekir; arama dakikası ücretlidir.

1. Köprüyü internetten erişilebilir yapın. Codespaces'te 8080 portunu **Public** yapın ya da bir tünel kullanın.
2. `.env`'e Twilio hesabınızın `TWILIO_AUTH_TOKEN` değerini yazın. Köprü imzasız istekleri reddeder.
3. Twilio'da numaranın **A call comes in** adresini `https://ADRESINIZ/gelen-arama` (HTTP POST) yapın ve numarayı arayın.

## Model

`gemini-3.8-live` hem Google AI Studio anahtarıyla hem Vertex AI'da aynı adla çalışır. Vertex için `ortam/.env.ornek` içindeki Yol B.
Sürümler ve ölçümler: `ortam/SURUM.yml`.
