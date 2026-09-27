#!/usr/bin/env bash
# Sesli Agent 101 lab — her parçayı dener, GEÇTİ / KALDI yazar (ders 4.1).
#   bash kontrol.sh            # tam: model oturumu + telefonsuz arama (~1 dk, .env'de GOOGLE_API_KEY gerekir)
#   bash kontrol.sh --hizli    # modelsiz: ortam + ses dönüşümü + güvenlik
cd "$(dirname "$0")"
[ -f .env ] || { cp ortam/.env.ornek .env; echo "not: ortam/.env.ornek → .env kopyalandı, anahtarları doldurun"; }
doldur() {   # boş ya da hiç olmayan ayarı yerinde doldurur (aynı ad iki satırda kalmasın)
  if grep -q "^$1=.\+" .env; then return; fi
  if grep -q "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else echo "$1=$2" >> .env; fi
}
doldur SESLI_ANAHTAR "$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')"
doldur TWILIO_AUTH_TOKEN "yerel-deneme-$(python3 -c 'import secrets;print(secrets.token_hex(8))')"
PORT=8765
gecen=0; kalan=0
adim() { if eval "$2" >/dev/null 2>&1; then echo "GEÇTİ  $1"; gecen=$((gecen+1)); else echo "KALDI  $1"; kalan=$((kalan+1)); fi; }

adim "ortam kilitli (uv sync --frozen)"            "uv sync --frozen --quiet"
adim "μ-law ↔ PCM dönüşümü (çözme birebir, SNR > 35 dB)" "uv run --quiet python -c \"
import numpy as np, kopru as k
x=(np.sin(np.linspace(0,200*np.pi,8000))*12000).astype(np.int16); y=k.ulaw_coz(k.ulaw_kodla(x))
assert k.ulaw_kodla(np.array([0]))==b'\xff' and 10*np.log10((x.astype(float)**2).sum()/((x-y.astype(float))**2).sum())>35\""
uv run --quiet uvicorn kopru:app --host 127.0.0.1 --port $PORT > /tmp/kopru-kontrol.log 2>&1 &
SUNUCU=$!
trap 'kill $SUNUCU 2>/dev/null' EXIT
for i in $(seq 30); do curl -s -o /dev/null 127.0.0.1:$PORT/ && break; sleep 1; done
adim "köprü sunucusu açıldı"                        "curl -s -o /dev/null 127.0.0.1:$PORT/"
adim "güvenlik: imza + anahtar kapıları 6/6"         "uv run --quiet python test_guvenlik.py http://127.0.0.1:$PORT"
if [ "$1" != "--hizli" ]; then
  adim "model: Türkçe cevap + araç çağrısı"          "uv run --quiet python deneme_oturum.py | grep -q 'ARAÇ ÇAĞRISI bos_saat_bul'"
  A=$(grep '^SESLI_ANAHTAR=' .env | tail -1 | cut -d= -f2)
  adim "telefonsuz arama: agent konuştu"             "uv run --quiet python twilio_taklit.py ws://127.0.0.1:$PORT/medya/$A | grep -Eq 'agent sesi [1-9][0-9]*\.'"
  adim "telefonsuz arama: randevu aracı çağrıldı"     "grep -q '\[araç\] bos_saat_bul' /tmp/kopru-kontrol.log"
fi
echo "────────────"
echo "$gecen GEÇTİ · $kalan KALDI"
[ "$kalan" -eq 0 ]
