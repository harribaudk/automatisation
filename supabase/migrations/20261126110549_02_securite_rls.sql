-- =====================================================================
-- TP 3 (Séance 1) — Cloisonnement Multi-Tenant par Row Level Security
-- =====================================================================

-- 1. Verrouillage obligatoire (deny-all par défaut)
ALTER TABLE public.organisations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profils       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tickets       ENABLE ROW LEVEL SECURITY;

-- 2. Fonction utilitaire : organisation de l'utilisateur courant
--    SECURITY DEFINER : lit profils sans repasser par sa propre RLS
--    (évite la récursion infinie si une policy de profils l'appelle).
--    search_path figé = protection contre le détournement de schéma.
CREATE OR REPLACE FUNCTION public.get_user_org_id()
RETURNS UUID
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT organisation_id
    FROM public.profils
    WHERE id = (SELECT auth.uid())
$$;

REVOKE ALL ON FUNCTION public.get_user_org_id() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.get_user_org_id() TO authenticated;

-- 3. Règles d'étanchéité (rôle authenticated)

-- tickets : lecture limitée à l'organisation courante
--   (SELECT ...) => sous-requête scalaire évaluée une seule fois (initPlan)
CREATE POLICY "tickets_select_meme_organisation" ON public.tickets
    FOR SELECT TO authenticated
    USING (organisation_id = (SELECT public.get_user_org_id()));

-- tickets : création uniquement en son nom ET dans son organisation
CREATE POLICY "tickets_insert_auteur_et_organisation" ON public.tickets
    FOR INSERT TO authenticated
    WITH CHECK (
        cree_par = (SELECT auth.uid())
        AND organisation_id = (SELECT public.get_user_org_id())
    );

-- Bonus cohérence : chacun voit son organisation et les membres de celle-ci
CREATE POLICY "organisations_select_la_sienne" ON public.organisations
    FOR SELECT TO authenticated
    USING (id = (SELECT public.get_user_org_id()));

CREATE POLICY "profils_select_meme_organisation" ON public.profils
    FOR SELECT TO authenticated
    USING (organisation_id = (SELECT public.get_user_org_id()));
