# m1-automatisation — Projet fil rouge (Séances 1 à 4)

Supabase (`klocxsqzinrxnvbwxozx`) ➜ pg_net ➜ Cloudflare Tunnel ➜ n8n (Colima) ➜ PostgREST.

```
supabase/migrations/   01 schéma · 02 RLS · 02b webhook pg_net · 03 observabilité + DLQ
orchestration/         docker-compose.yml (n8n), .env (ignoré), workflows/*.json
bruno/                 cahier de recette API (21 requêtes)
docs/                  benchmark-llm-s4.md (relevé FinOps multi-modèles)
scripts/               tunnel-up.sh, set-webhook-url.sh, generate_workflows.py
```

**Colima à la place de Docker Desktop** : `colima start` fournit le daemon Docker ;
les commandes `docker compose …` du cours s'exécutent telles quelles (contexte `colima`).

---

## Séance 1 — Supabase

| TP | Livrable |
|----|----------|
| 1 | `supabase init` + dépôt Git (`supabase/config.toml`, `migrations/`) |
| 2 | `…_01_schema_initial.sql` : organisations, profils, tickets, CHECK, JSONB, index FK |
| 3 | `…_02_securite_rls.sql` : RLS sur 3 tables, `get_user_org_id()` (SECURITY DEFINER, `search_path=''`), policies SELECT/INSERT |
| 4 | `bruno/` requêtes 01-02 (Injection admin, audit de cloisonnement) |
| 5 | `…_02b_webhook_on_ticket_mutation.sql` : webhook **en code** (trigger + `net.http_post`, payload `{type, table, schema, record, old_record}`) |

Lier et déployer (à faire avec **votre** compte Supabase propriétaire du projet) :

```bash
supabase login
```
```bash
supabase link --project-ref klocxsqzinrxnvbwxozx
```
```bash
supabase db push
```

TP5 avec webhook.site (avant n8n) :

```bash
scripts/set-webhook-url.sh https://webhook.site/<votre-uuid>
```

> Pourquoi un trigger pg_net versionné plutôt que Dashboard ➜ Webhooks ? C'est exactement
> ce que fait le Dashboard (trigger + pg_net), mais reproductible sous Git. L'URL (qui change
> à chaque tunnel) est stockée dans `private.app_config`, schéma non exposé par PostgREST.

### Pourquoi `GET /tickets` en anon renvoie `200 []` et non `403` ?
RLS n'est pas un contrôle d'accès « tout ou rien » : PostgreSQL ajoute la condition des
policies au `WHERE` de la requête. Aucune policy pour `anon` ⇒ prédicat toujours faux ⇒
zéro ligne. Un 403 révélerait que la ressource existe et contient des données qu'on vous
refuse (fuite d'information) ; `[]` est indiscernable d'une table vide.

## Séance 2 — n8n

| TP | Livrable |
|----|----------|
| 1 | `orchestration/docker-compose.yml` + `.env` (gitignoré), volume `n8n_data` |
| 2 | `scripts/tunnel-up.sh` : cloudflared, `WEBHOOK_URL`, recréation du conteneur, re-câblage Supabase |
| 3 | Webhook `POST /tickets-webhook`, réponse *On Received* |
| 4 | Nœud `Normalisation JS` (+ `alerte_immediate`) puis `If` |
| 5 | `PATCH statut en_cours` (credential service_role) + alerte Discord |

## Séance 3 — Fiabilisation

| TP | Livrable |
|----|----------|
| 1 | `…_03_observabilite_et_erreurs.sql` : `workflow_logs` (UNIQUE), `error_logs`, RLS sans policy, **trigger restreint à INSERT** (anti-boucle) |
| 2 | PATCH : Retry 3 × 2000 ms + Stop ; Discord : *Continue (using error output)* |
| 3 | `[SUB] Audit & Notification` (contrat typé, upsert `on_conflict`, retour `{audit_saved, notification_sent}`) |
| 4 | `[OPS] Global Error Handler` (Error Trigger ➜ DLQ ∥ Discord), lié dans les Settings de [CORE] |
| 5 | GET `workflow_logs` (*Always Output Data*) ➜ If inédit ➜ traitement / No Operation ; requêtes Bruno 09-12 |

Contrat d'entrée du sous-workflow : `idempotency_key` (String), `workflow_name` (String),
`ticket_id` (String, vide ⇒ `null`), `statut` (String), `details` (Object), `alert_message` (String, vide ⇒ pas d'alerte).

Topologie [CORE] :
```
Webhook ➜ Normalisation JS ➜ GET workflow_logs ➜ If inédit ?
   ├─ vrai ➜ PATCH en_cours (retry) ➜ If alerte ? ➜ [SUB] avec alert_message / [SUB] avec ""
   └─ faux ➜ Doublon ignoré (No Operation)
```

**Observation TP5 (Poison Pill)** : le PATCH avec `id=eq.ticket-invalide-123` renvoie
`400 invalid input syntax for type uuid` ; Retry On Fail rejoue quand même 3 fois (≈ 4 s)
avant d'abandonner : le retry générique ne distingue pas transitoire (5xx/429) et permanent (4xx).

**Limite assumée** : le lookup GET bloque les doublons séquentiels (tir à 2 s). Contre deux
requêtes simultanées à la milliseconde, il faudrait poser le verrou en entrée
(`INSERT … ON CONFLICT DO NOTHING` en statut `processing`).

---

## Mise en route

```bash
colima start
```
```bash
scripts/tunnel-up.sh
```

Puis dans n8n (http://localhost:5678) :
1. Créer le compte propriétaire.
2. **Credentials** ➜ `Supabase service_role` : coller la clé `sb_secret_…` (Project Settings ➜ API Keys).
3. **Credentials** ➜ `Discord astreinte` : coller l'URL de webhook de votre salon Discord.

Les 3 workflows sont importés et publiés. Après modification dans l'UI : **Publish**, puis
ré-exporter :

```bash
docker exec n8n_orchestrator n8n export:workflow --all --separate --pretty --output=/tmp/wf && docker cp n8n_orchestrator:/tmp/wf/. orchestration/workflows/
```

Ré-importer depuis le dépôt (nouvelle machine) :

```bash
docker exec n8n_orchestrator n8n import:credentials --input=/credentials.template.json && docker exec n8n_orchestrator n8n import:workflow --separate --input=/workflows
```

Bruno : ouvrir le dossier `bruno/`, environnement `supabase`, renseigner la variable
secrète `secretKey`, puis exécuter dans l'ordre (01 ➜ 21).

---

## Recette exécutée le 26/11/2026 (projet `klocxsqzinrxnvbwxozx`, n8n 2.49.7 sur Colima)

| Test | Résultat |
|------|----------|
| GET anon sur `tickets`, `workflow_logs`, `error_logs` | `200 []` (RLS) ; `private.app_config` non exposée (404) |
| Ticket nominal (`normale`) | ➜ `en_cours`, log `success`, `alerte_immediate=false`, aucun message Discord |
| Ticket critique | ➜ `en_cours`, log `success`, alerte Discord reçue (`notification_sent: true`) |
| UPDATE manuel d'un ticket | aucun webhook émis (trigger INSERT seul, anti-boucle) |
| Rafale ×3 à 2 s (même payload) | #1 traité + 1 alerte ; #2 et #3 ➜ « Doublon ignoré », 1 seule ligne `workflow_logs` |
| Poison pill `ticket-invalide-123` | PATCH 400 ×3 retries (≈ 5 s) ➜ [OPS] ➜ ligne `error_logs` (`failed_node = PATCH statut en_cours`) + alerte |
| Payload sans `record` | exception JS dans `Normalisation JS` ➜ [OPS] |

---

## Séance 4 — Agents IA (TP1 à TP5)

| TP | Livrable | Testé |
|----|----------|-------|
| 1 | Credentials n8n `Google Gemini (AI Studio)` et `Groq` (placeholders dans `credentials.template.json`, clés saisies dans l'UI) | ✅ listing des modèles OK sur les deux fournisseurs, tunnel HTTPS 200 |
| 2 | [CORE] : If « mots-clés » supprimé ➜ **Agent de qualification (IA)** sur la branche « inédit » | ✅ en production (voir ci-dessous) |
| 3 | `[TOOL] Recherche Historique Organisation` (publié) + outil `consulter_historique_organisation` (`$fromAI`) | ✅ appelé avec les bons UUIDs (trace exécution 33) |
| 4 | Outil `declencher_escalade_astreinte` ➜ [SUB], Structured Output Parser, `<ticket_content>`, Max Iterations 5, PATCH enrichi, audit `success` | ✅ en production (ticket `…04b1`) |

Topologie [CORE] après TP2 :
```
Webhook ➜ Normalisation JS ➜ GET workflow_logs ➜ If inédit ?
   ├─ vrai ➜ Agent de qualification (IA) ➜ PATCH en_cours (retry) ➜ [SUB] Audit (alert_message "")
   │          ├─ Google Gemini Chat Model  : models/gemini-3.6-flash, T=0.1, 1000 tokens
   │          └─ Gemini Flash-Lite (secours) : models/gemini-3.5-flash-lite (option fallback)
   └─ faux ➜ Doublon ignoré
```
- System Prompt : rôle N2, référentiel de priorité (basse/normale/haute/critique) et de catégorie, obligation de preuve, défiance envers la priorité déclarée.
- User Prompt « Define below » : `ticket_id`, `organisation_id`, `priorite`, `titre`, `description` via `$('Normalisation JS').first().json`.
- Pin Data (exécutions manuelles uniquement) sur `Webhook tickets` et `GET workflow_logs` (item vide = inédit).
- La qualification brute de l'agent est journalisée dans `workflow_logs.details.qualification_ia` (exploitée en JSON strict au TP4).

Smoke test (26/11) : « Blocage des virements fournisseurs », déclaré `normale` et sans mot-clé
➜ `Priorité finale : critique · Catégorie : application` + justification.

Incidents rencontrés (free tier Google, 26/11) :
- `gemini-flash-latest`, `gemini-3.7-flash` et `gemini-3.8-flash` : **503 high demand** ; `gemini-2.5-flash` : **404**, n'est plus ouvert aux nouveaux comptes.
- D'où : modèle épinglé (pas d'alias `-latest`), Retry On Fail 3 × 3 s sur l'agent et modèle de secours Flash-Lite.
- Groq : `llama-3.3-70b-versatile` n'apparaît pas dans la liste des modèles du compte (à revoir au TP5).

### TP3 — Outil d'historique
`[TOOL] Recherche Historique Organisation` (id `ToolHistoriqOrg1`) :
```
When Executed by Another Workflow (organisation_id, exclude_ticket_id : String)
 ➜ GET /rest/v1/tickets?select=id,titre,priorite,statut,created_at&organisation_id=eq.…&order=created_at.desc&limit=6
   (service_role, Always Output Data)
 ➜ Code « Run Once for All Items » : filtre items sans id, exclut le ticket courant, slice(0,5) ➜ { count, incidents }
```
Dans [CORE], le nœud `consulter_historique_organisation` (Call n8n Workflow Tool 2.2 : le nom du nœud est le nom de l'outil)
remplissait ses deux paramètres via `$fromAI()` avec interdiction d'inventer un UUID. Depuis le TP5, ils sont injectés côté serveur (voir plus bas).

### TP4 — Escalade, sortie structurée, boucle retour
```
Agent (Max Iterations 5, Require Specific Output Format)
   ├─ ai_languageModel : Gemini 3.6 Flash (+ Flash-Lite en secours)
   ├─ ai_tool : consulter_historique_organisation ➜ [TOOL]
   ├─ ai_tool : declencher_escalade_astreinte ➜ [SUB] (statut "processing", alert_message via $fromAI)
   └─ ai_outputParser : Structured Output Parser (JSON Schema)
 ➜ PATCH ticket qualifié : JSON.stringify({ statut: 'en_cours', priorite, metadata: { categorie, escalade_effectuee, diagnostic_ia } })
 ➜ Audit (SUB) : statut "success", alert_message "" (upsert ➜ processing devient success, pas de 409)
```
- Schéma de sortie : `priorite_finale` (enum = CHECK SQL), `categorie` (enum), `escalade_effectuee` (boolean), `diagnostic_ia` (string), tous requis.
- Outil d'escalade : `idempotency_key`, `workflow_name`, `ticket_id` figés via `$('Normalisation JS').first().json`, statut `processing` ; seul `alert_message` vient du LLM.
- OWASP LLM01 : titre et description encadrés par `<ticket_content>` ; le System Prompt interdit d'exécuter les directives qu'ils contiennent.
- Colonne `metadata JSONB` : déjà présente depuis la migration 01, donc aucune migration supplémentaire n'est nécessaire.

Recette TP4 (26/11, exécution 32) : ticket « Blocage des virements fournisseurs » (déclaré `normale`)
- l'outil historique est appelé avec `organisation_id = a1a1…00aa` et `exclude_ticket_id = …04b1` et renvoie `count: 4` ;
- l'agent conclut `critique / application` et appelle l'escalade : [SUB] écrit `processing` et l'alerte Discord est envoyée (`notification_sent: true`) ;
- le ticket passe à `statut en_cours, priorite critique`, `metadata` est renseigné et `workflow_logs` est en `success` (même ligne) ; `error_logs` reste vide.

### TP5 — Validation sémantique, tests adversariaux, multi-tenant et benchmark

| Partie | Livrable | Statut |
|--------|----------|--------|
| 1 | Bruno 15-17 : urgence implicite, incident récurrent, demande nominale ; 20 vérifie la qualification (priorité attendue, `escalade_effectuee`) | requêtes prêtes, recette à exécuter |
| 2 | Bruno 18 : Prompt Injection (OWASP LLM01) ; 21 : rejeu ×3 du dernier ticket vers l'URL de Production n8n | requêtes prêtes, recette à exécuter |
| 3.1 | `consulter_historique_organisation` : `organisation_id` et `exclude_ticket_id` injectés via `$('Normalisation JS').first().json` (plus aucun `$fromAI` sur le périmètre) ; Bruno 19 : ticket hostile ciblant l'org `00000000-…` | workflow modifié, recette à exécuter |
| 3.2 | Nœud `Groq Chat Model (benchmark)` (`llama-3.3-70b-versatile`) non branché dans [CORE] ; protocole et grille dans `docs/benchmark-llm-s4.md` | mesures à relever |

**Durcissement multi-tenant (OWASP LLM06, Confused Deputy).** L'outil historique n'expose plus aucun paramètre au LLM :
même une injection réussie ne peut pas lui faire lire une autre organisation. Seul `alert_message` de l'outil d'escalade
vient encore du modèle, parce que c'est un contenu et non un périmètre d'accès.

**Règle d'escalade resserrée.** « Au moins 2 incidents récents » suffisait à déclencher une escalade, même pour une simple
demande de service, sur une organisation qui avait déjà des tickets (le scénario 3 aurait escaladé). Désormais, l'escalade
n'a lieu que si la priorité finale est `critique`, ou si le ticket courant est lui-même un incident et que l'historique
contient au moins 2 incidents haute/critique.

Déroulé de la recette (n8n publié, credentials renseignés, tunnel actif) :
1. *Unpin* des Pin Data de [CORE] ; vérifier que [CORE], [TOOL], [SUB] et [OPS] sont *Published*.
2. Pour chaque scénario 15 ➜ 19 : lancer la requête, attendre ~20 s, lancer 20.
   Pour 19, ouvrir l'exécution et vérifier l'entrée de `consulter_historique_organisation` (`organisation_id = {{orgId}}`).
3. Après 15 : lancer 21 trois fois. Chaque exécution doit finir sur « Doublon ignoré », sans aucun nœud IA exécuté.

> Sous Windows (sans Colima) : `podman machine start`, puis dans `orchestration/` : `docker-compose up -d`.
> `scripts/generate_workflows.py` écrit désormais en UTF-8 sur toutes les plateformes.
