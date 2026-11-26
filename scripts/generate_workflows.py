#!/usr/bin/env python3
"""Génère les 3 workflows n8n (exports JSON versionnables) du projet fil rouge.
Aucun secret ici : les clés vivent dans les Credentials n8n (référencées par ID)."""
import json, uuid, pathlib

PROJECT_URL = "https://klocxsqzinrxnvbwxozx.supabase.co"
REST = f"{PROJECT_URL}/rest/v1"
OUT = pathlib.Path(__file__).resolve().parent.parent / "orchestration" / "workflows"

CORE_ID, SUB_ID, OPS_ID = "CoreTicketsIngst", "SubAuditNotifica", "OpsGlobalErrorHd"
SUPA_CRED = {"supabaseApi": {"id": "SupaServiceRole1", "name": "Supabase service_role"}}
DISCORD_CRED = {"discordWebhookApi": {"id": "DiscordAstreinte", "name": "Discord astreinte"}}

def nid(name):  # IDs stables entre deux générations => diffs Git propres
    return str(uuid.uuid5(uuid.NAMESPACE_URL, name))

def node(name, type_, version, pos, params, **extra):
    n = {"id": nid(name), "name": name, "type": type_, "typeVersion": version,
         "position": pos, "parameters": params}
    n.update(extra)
    return n

def supa_http(name, pos, method, url, body=None, headers=None, **extra):
    p = {"method": method, "url": url,
         "authentication": "predefinedCredentialType", "nodeCredentialType": "supabaseApi",
         "options": {}}
    if headers:
        p["sendHeaders"] = True
        p["headerParameters"] = {"parameters": [{"name": k, "value": v} for k, v in headers.items()]}
    if body:
        p["sendBody"] = True
        p["specifyBody"] = "json"
        p["jsonBody"] = body
    return node(name, "n8n-nodes-base.httpRequest", 4.2, pos, p, credentials=SUPA_CRED, **extra)

def if_node(name, pos, left, operator, right=""):
    return node(name, "n8n-nodes-base.if", 2.2, pos, {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [{"id": nid(name + "cond"), "leftValue": left, "rightValue": right, "operator": operator}],
            "combinator": "and"},
        "looseTypeValidation": True, "options": {}})

def code(name, pos, js):
    return node(name, "n8n-nodes-base.code", 2, pos, {"jsCode": js})

def discord(name, pos, content, **extra):
    return node(name, "n8n-nodes-base.discord", 2, pos,
                {"authentication": "webhook", "operation": "sendLegacy", "content": content, "options": {}},
                credentials=DISCORD_CRED, **extra)

def noop(name, pos):
    return node(name, "n8n-nodes-base.noOp", 1, pos, {})

def link(conns, src, dst, out=0):
    c = conns.setdefault(src, {"main": []})["main"]
    while len(c) <= out:
        c.append([])
    c[out].append({"node": dst, "type": "main", "index": 0})

def workflow(id_, name, nodes, conns, settings=None):
    return {"id": id_, "name": name, "active": False, "nodes": nodes, "connections": conns,
            "settings": {"executionOrder": "v1", **(settings or {})}, "pinData": {}, "tags": []}

# ---------------------------------------------------------------------------
# [SUB] Audit & Notification
# ---------------------------------------------------------------------------
SUB_INPUTS = [("idempotency_key", "string"), ("workflow_name", "string"), ("ticket_id", "string"),
              ("statut", "string"), ("details", "object"), ("alert_message", "string")]

sub_nodes = [
    node("When Executed by Another Workflow", "n8n-nodes-base.executeWorkflowTrigger", 1.1, [0, 0],
         {"inputSource": "workflowInputs",
          "workflowInputs": {"values": [{"name": n, "type": t} for n, t in SUB_INPUTS]}}),
    supa_http("Upsert workflow_logs", [240, 0], "POST",
              f"{REST}/workflow_logs?on_conflict=idempotency_key",
              body="={{ JSON.stringify({\n"
                   "  idempotency_key: $json.idempotency_key,\n"
                   "  workflow_name: $json.workflow_name,\n"
                   "  ticket_id: $json.ticket_id ? $json.ticket_id : null,\n"
                   "  statut: $json.statut,\n"
                   "  details: $json.details || {}\n"
                   "}) }}",
              headers={"Prefer": "resolution=merge-duplicates,return=representation"},
              retryOnFail=True, maxTries=3, waitBetweenTries=2000),
    if_node("Alerte à émettre ?", [480, 0],
            "={{ $('When Executed by Another Workflow').first().json.alert_message }}",
            {"type": "string", "operation": "notEmpty", "singleValue": True}),
    discord("Discord astreinte", [720, -100],
            "={{ $('When Executed by Another Workflow').first().json.alert_message }}",
            onError="continueErrorOutput"),
    code("Bilan : notifié", [960, -200], "return [{ json: { audit_saved: true, notification_sent: true } }];"),
    code("Bilan : notification KO", [960, 0],
         "return [{ json: { audit_saved: true, notification_sent: false,\n"
         "  notification_error: $input.first().json.error?.message ?? 'unknown' } }];"),
    code("Bilan : sans notification", [720, 150], "return [{ json: { audit_saved: true, notification_sent: false } }];"),
]
sub_c = {}
link(sub_c, "When Executed by Another Workflow", "Upsert workflow_logs")
link(sub_c, "Upsert workflow_logs", "Alerte à émettre ?")
link(sub_c, "Alerte à émettre ?", "Discord astreinte", 0)
link(sub_c, "Alerte à émettre ?", "Bilan : sans notification", 1)
link(sub_c, "Discord astreinte", "Bilan : notifié", 0)
link(sub_c, "Discord astreinte", "Bilan : notification KO", 1)
SUB = workflow(SUB_ID, "[SUB] Audit & Notification", sub_nodes, sub_c)

# ---------------------------------------------------------------------------
# [CORE] Ingestion & Routage Tickets
# ---------------------------------------------------------------------------
NORMALISATION_JS = r"""// TP4 S2 + TP3 S3 — Normalisation défensive du payload CDC Supabase
const body = $input.first().json.body ?? {};
const { type, table, record } = body;

// Poison pill de contrat : on lève une exception => [OPS] Global Error Handler
if (!record || typeof record !== 'object' || !record.id) {
  throw new Error('Payload CDC invalide : objet "record" (avec id) absent');
}

// throw new Error("Crash de test DLQ"); // <- TP4 S3 : décommenter, Publish, tester, recommenter

const titre = String(record.titre ?? '');
const priorite = String(record.priorite ?? 'normale');
const MOTS_CLES = ['panne', 'bloquant', 'urgent'];
const titreMin = titre.toLowerCase();

const alerte_immediate =
  priorite === 'critique' || MOTS_CLES.some((m) => titreMin.includes(m));

// Clé d'idempotence déterministe : table + UUID + opération + statut initial
const idempotency_key = `${table ?? 'tickets'}_${record.id}_${type ?? 'INSERT'}_${record.statut ?? 'nouveau'}`;

return [{
  json: {
    idempotency_key,
    type: type ?? null,
    ticket_id: record.id,
    titre,
    description: record.description ?? '',
    priorite,
    statut_initial: record.statut ?? null,
    organisation_id: record.organisation_id ?? null,
    alerte_immediate,
  },
}];
"""

N = "$('Normalisation JS').first().json"
sub_inputs_schema = [{"id": n, "displayName": n, "required": False, "defaultMatch": False, "display": True,
                      "canBeUsedToMatch": True, "type": t, "removed": False} for n, t in SUB_INPUTS]

def exec_sub(name, pos, alert_expr):
    values = {
        "idempotency_key": f"={{{{ {N}.idempotency_key }}}}",
        "workflow_name": "={{ $workflow.name }}",
        "ticket_id": f"={{{{ {N}.ticket_id }}}}",
        "statut": "success",
        "details": f"={{{{ {{ priorite: {N}.priorite, alerte_immediate: {N}.alerte_immediate, "
                   f"statut_final: $('PATCH statut en_cours').first().json.statut, execution_id: $execution.id }} }}}}",
        "alert_message": alert_expr,
    }
    return node(name, "n8n-nodes-base.executeWorkflow", 1.2, pos, {
        "workflowId": {"__rl": True, "value": SUB_ID, "mode": "list",
                       "cachedResultName": "[SUB] Audit & Notification"},
        "workflowInputs": {"mappingMode": "defineBelow", "value": values, "matchingColumns": [],
                           "schema": sub_inputs_schema, "attemptToConvertTypes": False,
                           "convertFieldsToString": True},
        "options": {"waitForSubWorkflow": True}})

ALERT = ("={{ `🚨 **Ticket critique**\\n"
         "• Titre : ${" + N + ".titre}\\n"
         "• UUID : ${" + N + ".ticket_id}\\n"
         "• Priorité : ${" + N + ".priorite}\\n"
         "• Statut : en_cours (pris en charge automatiquement)` }}")

core_nodes = [
    node("Webhook tickets", "n8n-nodes-base.webhook", 2, [0, 0],
         {"httpMethod": "POST", "path": "tickets-webhook", "responseMode": "onReceived", "options": {}},
         webhookId="4f1c2b7e-0d1a-4c55-9a3e-7b3d2a9f8e10"),
    code("Normalisation JS", [220, 0], NORMALISATION_JS),
    supa_http("GET workflow_logs (idempotence)", [440, 0], "GET",
              f"={REST}/workflow_logs?select=id,statut&idempotency_key=eq.{{{{ encodeURIComponent($json.idempotency_key) }}}}",
              alwaysOutputData=True),
    if_node("Événement inédit ?", [660, 0], "={{ $json.id }}",
            {"type": "string", "operation": "empty", "singleValue": True}),
    noop("Doublon ignoré", [880, 200]),
    supa_http("PATCH statut en_cours", [880, -100], "PATCH",
              f"={REST}/tickets?id=eq.{{{{ {N}.ticket_id }}}}",
              body='{ "statut": "en_cours" }',
              headers={"Prefer": "return=representation"},
              retryOnFail=True, maxTries=3, waitBetweenTries=2000),
    if_node("Alerte immédiate ?", [1100, -100], f"={{{{ {N}.alerte_immediate }}}}",
            {"type": "boolean", "operation": "true", "singleValue": True}),
    exec_sub("Audit + alerte (critique)", [1340, -200], ALERT),
    exec_sub("Audit (nominal)", [1340, 0], ""),
]
core_c = {}
link(core_c, "Webhook tickets", "Normalisation JS")
link(core_c, "Normalisation JS", "GET workflow_logs (idempotence)")
link(core_c, "GET workflow_logs (idempotence)", "Événement inédit ?")
link(core_c, "Événement inédit ?", "PATCH statut en_cours", 0)
link(core_c, "Événement inédit ?", "Doublon ignoré", 1)
link(core_c, "PATCH statut en_cours", "Alerte immédiate ?")
link(core_c, "Alerte immédiate ?", "Audit + alerte (critique)", 0)
link(core_c, "Alerte immédiate ?", "Audit (nominal)", 1)
CORE = workflow(CORE_ID, "[CORE] Ingestion & Routage Tickets", core_nodes, core_c,
                {"errorWorkflow": OPS_ID, "saveManualExecutions": True})

# ---------------------------------------------------------------------------
# [OPS] Global Error Handler
# ---------------------------------------------------------------------------
DIAG_JS = r"""// TP4 S3 — Extraction défensive : ce nœud ne doit JAMAIS planter
const e = $input.first().json ?? {};
const ex = e.execution ?? {};

return [{
  json: {
    execution_id: String(ex.id ?? 'unknown'),
    execution_url: ex.url ?? null,
    workflow_name: e.workflow?.name ?? 'unknown',
    failed_node: ex.lastNodeExecuted ?? ex.error?.node?.name ?? 'unknown',
    error_message: ex.error?.message ?? e.trigger?.error?.message ?? 'unknown',
    payload_snapshot: e, // objet natif, pas de JSON.stringify (pas de double sérialisation)
  },
}];
"""
D = "$('Diagnostic JS').first().json"
ops_nodes = [
    node("Error Trigger", "n8n-nodes-base.errorTrigger", 1, [0, 0], {}),
    code("Diagnostic JS", [220, 0], DIAG_JS),
    supa_http("POST error_logs (DLQ)", [460, -100], "POST", f"{REST}/error_logs",
              body="={{ JSON.stringify({\n"
                   "  execution_id: $json.execution_id,\n"
                   "  workflow_name: $json.workflow_name,\n"
                   "  failed_node: $json.failed_node,\n"
                   "  error_message: $json.error_message,\n"
                   "  payload_snapshot: $json.payload_snapshot\n"
                   "}) }}",
              headers={"Prefer": "return=representation"},
              onError="continueErrorOutput"),
    noop("DLQ indisponible", [700, 0]),
    discord("Alerte astreinte Discord", [460, 120],
            "={{ `🔥 **Crash workflow**\\n"
            "• Workflow : ${" + D + ".workflow_name}\\n"
            "• Exécution : ${" + D + ".execution_id} ${" + D + ".execution_url ?? ''}\\n"
            "• Nœud fautif : ${" + D + ".failed_node}\\n"
            "• Erreur : ${" + D + ".error_message}` }}",
            onError="continueRegularOutput"),
]
ops_c = {}
link(ops_c, "Error Trigger", "Diagnostic JS")
link(ops_c, "Diagnostic JS", "POST error_logs (DLQ)")   # en parallèle :
link(ops_c, "Diagnostic JS", "Alerte astreinte Discord")  # Discord alerté même si Supabase est down
link(ops_c, "POST error_logs (DLQ)", "DLQ indisponible", 1)
OPS = workflow(OPS_ID, "[OPS] Global Error Handler", ops_nodes, ops_c)

OUT.mkdir(parents=True, exist_ok=True)
for wf in (CORE, SUB, OPS):
    (OUT / f"{wf['name']}.json").write_text(json.dumps(wf, ensure_ascii=False, indent=2) + "\n")
    print("écrit :", wf["name"])
