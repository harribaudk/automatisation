-- Nettoyage : fonction trigger héritée d'une ancienne tentative (exposée en RPC
-- dans le schéma public, signalée par `supabase db advisors`). Le webhook actif
-- utilise private.notify_ticket_mutation(), non exposée par PostgREST.
DROP FUNCTION IF EXISTS public.notify_ticket_mutation();
