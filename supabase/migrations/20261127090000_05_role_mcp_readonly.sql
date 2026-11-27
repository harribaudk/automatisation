-- =====================================================================
-- TP 1 (Séance 5) — Rôle PostgreSQL cloisonné pour le serveur MCP (dbhub)
-- Énoncé : « 04_role_mcp_readonly » ; numéroté 05 car 04 est déjà pris
-- (nettoyage de fonction orpheline).
--
-- Moindre privilège : USAGE sur public + SELECT sur des colonnes métier
-- non sensibles de organisations et tickets. Rien d'autre :
--   - pas de profils (données personnelles), ni de tickets.cree_par ;
--   - pas de workflow_logs / error_logs (journaux techniques) ;
--   - pas de auth / private / storage ; aucune écriture.
--
-- AUCUN mot de passe ici. Le rôle est créé NOLOGIN ; à activer HORS Git
-- dans le Supabase SQL Editor :
--   ALTER ROLE mcp_readonly WITH LOGIN PASSWORD '<mot-de-passe-fort>';
-- =====================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mcp_readonly') THEN
        CREATE ROLE mcp_readonly NOLOGIN NOINHERIT;
    END IF;
END
$$;

-- Défense en profondeur : même si un GRANT d'écriture était ajouté par erreur,
-- toute transaction ouverte par ce rôle est en lecture seule et bornée dans le temps.
ALTER ROLE mcp_readonly SET default_transaction_read_only = on;
ALTER ROLE mcp_readonly SET statement_timeout = '10s';
ALTER ROLE mcp_readonly SET idle_in_transaction_session_timeout = '30s';

-- Partir d'une base vide : aucun droit hérité sur les schémas sensibles
REVOKE ALL ON SCHEMA auth, private, storage FROM mcp_readonly;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM mcp_readonly;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM mcp_readonly;

GRANT USAGE ON SCHEMA public TO mcp_readonly;

-- Privilèges par colonne (projection imposée côté base)
GRANT SELECT (id, nom, created_at) ON public.organisations TO mcp_readonly;
GRANT SELECT (id, organisation_id, titre, description, statut, priorite, metadata, created_at)
    ON public.tickets TO mcp_readonly;

-- RLS (Séance 1) : sans policy pour ce rôle, le deny-all renverrait 0 ligne.
-- Lecture transverse assumée : le serveur MCP est un outil d'exploitation interne
-- (supervision N2), pas un accès client ; le cloisonnement par tenant reste porté
-- par les policies « authenticated » existantes.
DROP POLICY IF EXISTS "organisations_select_mcp_readonly" ON public.organisations;
CREATE POLICY "organisations_select_mcp_readonly" ON public.organisations
    FOR SELECT TO mcp_readonly
    USING (true);

DROP POLICY IF EXISTS "tickets_select_mcp_readonly" ON public.tickets;
CREATE POLICY "tickets_select_mcp_readonly" ON public.tickets
    FOR SELECT TO mcp_readonly
    USING (true);
