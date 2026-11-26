-- =====================================================================
-- TP 1 (Séance 3) — Observabilité, Idempotence & Dead Letter Queue
-- =====================================================================

-- ---------------------------------------------------------------------
-- Registre d'audit & d'idempotence
-- ---------------------------------------------------------------------
CREATE TABLE public.workflow_logs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key  VARCHAR(255) NOT NULL UNIQUE,
    workflow_name    VARCHAR(120) NOT NULL,
    ticket_id        UUID REFERENCES public.tickets(id) ON DELETE SET NULL,
    statut           TEXT NOT NULL
                     CHECK (statut IN ('processing', 'success', 'ignored')),
    details          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW())
);

CREATE INDEX idx_workflow_logs_ticket_id ON public.workflow_logs(ticket_id);

-- ---------------------------------------------------------------------
-- Dead Letter Queue
-- ---------------------------------------------------------------------
CREATE TABLE public.error_logs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id      TEXT NOT NULL,
    workflow_name     TEXT NOT NULL,
    failed_node       TEXT NOT NULL,
    error_message     TEXT NOT NULL,
    payload_snapshot  JSONB NOT NULL DEFAULT '{}'::jsonb,
    resolved          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW())
);

-- Index partiel : la file de rejeu ne s'intéresse qu'aux erreurs ouvertes
CREATE INDEX idx_error_logs_non_resolues ON public.error_logs(created_at)
    WHERE resolved = FALSE;

-- ---------------------------------------------------------------------
-- Sécurité : RLS activé, AUCUNE policy => accès réservé à service_role
-- (attribut BYPASSRLS). anon / authenticated reçoivent [].
-- ---------------------------------------------------------------------
ALTER TABLE public.workflow_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.error_logs    ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------
-- Anti-boucle : le webhook ne doit plus se déclencher que sur INSERT,
-- sinon le PATCH statut=en_cours émis par n8n relancerait le flux.
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS on_ticket_mutation ON public.tickets;
CREATE TRIGGER on_ticket_mutation
    AFTER INSERT ON public.tickets
    FOR EACH ROW
    EXECUTE FUNCTION private.notify_ticket_mutation();
