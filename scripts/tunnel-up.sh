#!/usr/bin/env bash
# Réveil de la stack (TP2 S2 / TP1 S3) en une commande :
#   1. colima + n8n   2. tunnel Cloudflare   3. WEBHOOK_URL dans .env
#   4. recréation du conteneur   5. re-câblage du webhook Supabase (Production URL)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; ORCH="$ROOT/orchestration"; LOG="$ORCH/.cloudflared.log"
colima status >/dev/null 2>&1 || colima start
docker context use colima >/dev/null
(cd "$ORCH" && docker compose up -d)

pkill -f "cloudflared tunnel --url http://localhost:5678" 2>/dev/null || true
nohup cloudflared tunnel --url http://localhost:5678 >"$LOG" 2>&1 &
echo "cloudflared lancé (PID $!), logs : $LOG"
for _ in $(seq 1 30); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)
  [[ -n "$URL" ]] && break; sleep 1
done
[[ -n "${URL:-}" ]] || { echo "URL du tunnel introuvable" >&2; exit 1; }
echo "Tunnel : $URL"

sed -i '' "s|^WEBHOOK_URL=.*|WEBHOOK_URL=$URL/|" "$ORCH/.env"
(cd "$ORCH" && docker compose up -d)
echo -n "Attente de n8n"; until curl -sf http://localhost:5678/healthz >/dev/null; do echo -n .; sleep 2; done; echo " OK"

"$ROOT/scripts/set-webhook-url.sh" "$URL/webhook/tickets-webhook"
echo "Smoke test : curl -I $URL"
