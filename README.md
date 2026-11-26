# m1-automatisation — Projet fil rouge (Séances 1 à 3)

Supabase (`klocxsqzinrxnvbwxozx`) ➜ pg_net ➜ Cloudflare Tunnel ➜ n8n (Colima) ➜ PostgREST.

```
supabase/migrations/   01 schéma · 02 RLS · 02b webhook pg_net · 03 observabilité + DLQ
orchestration/         docker-compose.yml (n8n), .env (ignoré), workflows/*.json
bruno/                 cahier de recette API (14 requêtes)
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
secrète `secretKey`, puis exécuter dans l'ordre (01 ➜ 14).

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

## Séance 4 — Agents IA (TP1 et TP2)

| TP | Livrable | Testé |
|----|----------|-------|
| 1 | Credentials n8n `Google Gemini (AI Studio)` et `Groq` (placeholders dans `credentials.template.json`, clés saisies dans l'UI) | ✅ listing des modèles OK sur les deux fournisseurs, tunnel HTTPS 200 |
| 2 | [CORE] : If « mots-clés » supprimé ➜ **Agent de qualification (IA)** sur la branche « inédit » | ✅ en production (voir ci-dessous) |

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
