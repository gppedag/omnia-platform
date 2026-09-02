# CUP System 1.0.15 - Handoff Voice AI -> Operatore

## Workflow
- telefonata Asterisk -> LiveKit/LLM resta AI-first;
- LLM o cliente possono creare una richiesta handoff;
- coda operatori con stati waiting_operator/ringing;
- notifica browser + segnale sonoro + badge;
- presenza operatore Disponibile/Occupato/Offline;
- accettazione atomica: il primo operatore acquisisce la richiesta;
- rifiuto individuale senza bloccare il ring group;
- timeout configurabile con callback, ritorno AI, permanenza in coda o voicemail;
- modalità manual, auto_answer e ring_group;
- API service-to-service `/api/handoffs/request` per LiveKit/voice agent;
- originate Asterisk solo dopo accettazione, non al momento della richiesta;
- tutti gli eventi vengono registrati nel Journey.

## Impostazioni
HANDOFF_MODE=ring_group
HANDOFF_TIMEOUT_SECONDS=30
HANDOFF_TIMEOUT_ACTION=callback
HANDOFF_SERVICE_TOKEN=...
HANDOFF_BROWSER_NOTIFICATIONS=true

## Contratto LiveKit / Voice Agent
Quando il cliente o l'LLM chiede un umano, il voice agent chiama:

`POST /api/handoffs/request`

Header opzionale/consigliato: `X-Handoff-Token: <HANDOFF_SERVICE_TOKEN>`.

Payload: `session_id` oppure `call_id` oppure `caller_number`, più `reason`, `source=livekit` e un eventuale `summary`.
Il CUP risponde con lo stato della coda; la telefonata resta in AI/attesa finché un operatore non accetta.
