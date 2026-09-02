# Chatwoot integration - CUP System v1.0.8

La v1.0.8 usa Chatwoot come console/code operatori mantenendo CUP System come source of truth per conversazioni, documenti, prenotazioni, LLM e telefonia.

## Architettura

Web / WhatsApp / Telegram -> CUP Conversation Core -> LLM
                                      |
                                      +-> handoff -> Chatwoot queue/team -> operatore
                                                           |
                                                           +-> risposta -> CUP -> canale originale
                                                           +-> Asterisk per escalation telefonica

Ogni conversazione CUP mantiene il proprio `session_id`. La tabella `chatwoot_bindings` associa il `session_id` al `conversation_id` Chatwoot. Lo storico CUP e i documenti non vengono trasferiti come storage primario: Chatwoot riceve messaggi sincronizzati e note private con i link ai documenti CUP.

## Requisiti Chatwoot

1. Installazione Chatwoot separata, per esempio `https://chatwoot.ai.example.it`.
2. Account Chatwoot e API Inbox.
3. API access token di un amministratore/agente con permessi sull'account.
4. Team opzionale per auto-assignment.
5. Webhook Chatwoot verso CUP.

Chatwoot non viene incluso nel `docker-compose.yml` CUP: rimane un servizio indipendente e aggiornabile separatamente.

## Variabili `.env`

```env
CHATWOOT_ENABLED=true
CHATWOOT_BASE_URL=https://chatwoot.ai.example.it
CHATWOOT_ACCOUNT_ID=1
CHATWOOT_API_TOKEN=replace_me
CHATWOOT_INBOX_IDENTIFIER=replace_me
CHATWOOT_TEAM_ID=1
CHATWOOT_WEBHOOK_TOKEN=replace_with_random_secret
CHATWOOT_TIMEOUT_SECONDS=20
CHATWOOT_AUTO_SYNC_HANDOFF=true
CUP_PUBLIC_BASE_URL=https://demo-cup.ai.example.it
```

`CHATWOOT_INBOX_IDENTIFIER` e' l'identifier dell'API Inbox, non l'ID numerico dell'inbox.

## Flusso LLM -> operatore

Quando CUP mette una sessione in `handoff`:

1. crea, se necessario, il contatto Chatwoot;
2. crea la conversazione nell'API Inbox;
3. assegna la conversazione al team configurato in `CHATWOOT_TEAM_ID`;
4. sincronizza storico messaggi e metadati documentali;
5. mantiene `session_id` CUP come identificatore di correlazione;
6. opzionalmente avvia l'escalation Asterisk.

La risposta dell'agente Chatwoot viene ricevuta da `/api/chatwoot/webhook`, registrata come `role=operator` nel database CUP e inoltrata al canale originario tramite gli adapter CUP (WhatsApp, Telegram o Web).

## Webhook

Endpoint CUP:

```text
POST /api/chatwoot/webhook
```

Header richiesto quando `CHATWOOT_WEBHOOK_TOKEN` e' configurato:

```text
X-CUP-Chatwoot-Token: <secret>
```

Eventi da sottoscrivere:

- `message_created`
- `conversation_status_changed`
- `conversation_updated`

Un amministratore CUP puo' richiedere la creazione del webhook tramite:

```text
POST /api/chatwoot/setup-webhook
```

Il callback viene costruito da `CUP_PUBLIC_BASE_URL`.

## API CUP Chatwoot

```text
GET  /api/chatwoot/status
POST /api/chatwoot/sessions/{session_id}/sync
POST /api/chatwoot/setup-webhook
POST /api/chatwoot/webhook
```

I primi tre endpoint richiedono autenticazione CUP; `setup-webhook` richiede ruolo admin.

## Documenti

Il repository documentale rimane CUP. Quando un documento viene caricato via Web, WhatsApp o Telegram, Chatwoot riceve una nota privata contenente nome, MIME type, dimensione e URL CUP. Questo evita di duplicare lo storage documentale e mantiene la relazione con il `session_id` originale.

Per produzione sanitaria l'endpoint documentale deve essere protetto con autenticazione/autorizzazione o URL firmati; la configurazione PoC non sostituisce i requisiti privacy e sicurezza.

## Handoff telefonico

Chatwoot gestisce coda, agenti e assegnazione. Asterisk resta gestito dal CUP. Il flusso consigliato e':

```text
handoff CUP -> Chatwoot team -> agente prende in carico
                           -> opzionale originate Asterisk -> operatore/telefono
```

Eventi telefonici e messaggi restano correlati alla stessa conversazione CUP.
