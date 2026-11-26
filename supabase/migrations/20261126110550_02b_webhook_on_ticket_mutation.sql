-- =====================================================================
-- TP 5 (Séance 1) — Database Webhook "on_ticket_mutation" (Code-First)
-- ---------------------------------------------------------------------
-- Équivalent versionné de Dashboard ➜ Database ➜ Webhooks : un trigger
-- AFTER INSERT/UPDATE qui pousse le payload standard Supabase
--   { type, table, schema, record, old_record }
-- dans la file asynchrone de pg_net (net.http_request_queue).
-- La transaction métier n'attend JAMAIS la réponse HTTP.
--
-- L'URL cible n'est pas codée en dur (elle change à chaque tunnel
-- Cloudflare) : elle est lue dans private.app_config.
--   UPDATE private.app_config SET value = 'https://...'
--   WHERE key = 'tickets_webhook_url';
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pg_net WITH SCHEMA extensions;

-- Schéma privé : non exposé par PostgREST
CREATE SCHEMA IF NOT EXISTS private;
REVOKE ALL ON SCHEMA private FROM PUBLIC, anon, authenticated;

CREATE TABLE IF NOT EXISTS private.app_config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW())
);

-- Valeur initiale : URL webhook.site (TP5 S1) puis n8n (S2/S3)
INSERT INTO private.app_config (key, value)
VALUES ('tickets_webhook_url', '')
ON CONFLICT (key) DO NOTHING;

CREATE OR REPLACE FUNCTION private.notify_ticket_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_url TEXT;
BEGIN
    SELECT value INTO v_url
    FROM private.app_config
    WHERE key = 'tickets_webhook_url';

    -- Pas d'URL configurée : on ne bloque surtout pas l'écriture métier
    IF v_url IS NULL OR v_url = '' THEN
        RETURN NULL;
    END IF;

    PERFORM net.http_post(
        url     := v_url,
        body    := jsonb_build_object(
                       'type',       TG_OP,
                       'table',      TG_TABLE_NAME,
                       'schema',     TG_TABLE_SCHEMA,
                       'record',     CASE WHEN TG_OP = 'DELETE' THEN NULL ELSE to_jsonb(NEW) END,
                       'old_record', CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE to_jsonb(OLD) END
                   ),
        headers := jsonb_build_object('Content-Type', 'application/json'),
        timeout_milliseconds := 5000
    );

    RETURN NULL; -- trigger AFTER : valeur de retour ignorée
END;
$$;

DROP TRIGGER IF EXISTS on_ticket_mutation ON public.tickets;
CREATE TRIGGER on_ticket_mutation
    AFTER INSERT OR UPDATE ON public.tickets
    FOR EACH ROW
    EXECUTE FUNCTION private.notify_ticket_mutation();
