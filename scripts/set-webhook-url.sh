#!/usr/bin/env bash
# Met à jour l'URL cible du Database Webhook (trigger pg_net on_ticket_mutation)
# Usage : scripts/set-webhook-url.sh https://xxxx.trycloudflare.com/webhook/tickets-webhook [--local]
set -euo pipefail
URL="${1:?URL manquante}"; TARGET="${2:---linked}"
[[ "$URL" =~ ^https?://[A-Za-z0-9._:/-]+$ ]] || { echo "URL refusée : $URL" >&2; exit 1; }
cd "$(dirname "$0")/.."
supabase db query "$TARGET" "UPDATE private.app_config SET value = '$URL', updated_at = now() WHERE key = 'tickets_webhook_url' RETURNING key, value;"
