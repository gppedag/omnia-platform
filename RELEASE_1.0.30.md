# CUP System v1.0.30 - Chatwoot Conversation Hub

## Architettura
- Chatwoot diventa la console/hub operativo per le conversazioni.
- CUP resta source-of-truth per pazienti, prenotazioni, disponibilita, documenti, pagamenti, check-in e workflow.
- Web, Telegram, WhatsApp e voce condividono `journey_id`; `patient_id` viene associato quando l'identita e verificabile.

## Novita
- `chat_sessions.journey_id` e `chat_sessions.patient_id` con migrazione automatica.
- Risoluzione conservativa paziente su telefono/WhatsApp (numero normalizzato) e Telegram (chat id configurato).
- I nuovi canali riconosciuti vengono collegati al journey attivo del paziente.
- Chatwoot riceve `cup_session_id`, `cup_journey_id`, `cup_patient_id`, `cup_channel` come custom attributes.
- Tutti i messaggi Web/Telegram/WhatsApp vengono sincronizzati verso Chatwoot in tempo reale.
- Handoff apre la conversazione Chatwoot senza reinviare tutta la history, evitando duplicati.
- Risposta operatore Chatwoot torna solo sul canale corrente del paziente, non su tutti i canali collegati.
- Le risposte dal pannello CUP vengono riportate come messaggi outgoing Chatwoot, non come note private.
- Voice NLU crea/recupera automaticamente il journey telefonico dal caller number e ne assicura il binding Chatwoot.
- `/api/chatwoot/status` espone `hub_mode` e l'architettura attiva.

## Limiti
- La convergenza cross-channel richiede un'identita verificabile. Un utente web anonimo non viene fuso automaticamente con Telegram/WhatsApp per evitare associazioni errate.
- Per la voce, Chatwoot riceve il journey e gli eventi; audio realtime e media bridge restano responsabilita di Asterisk/LiveKit.
- Chatwoot deve essere realmente configurato (`CHATWOOT_ENABLED`, URL, account, token e inbox identifier).
