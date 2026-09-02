# CUP System v1.0.12

## Dashboard Journey
- Nuovo riquadro **Journey attivi** nella Dashboard operatore.
- Visualizzazione immediata del percorso multicanale: Telefono, SMS, Web, WhatsApp, Telegram, handoff, operatore, documenti, Chatwoot.
- Azione **Apri Journey** per entrare direttamente nella conversazione.
- Azione **Chatwoot** quando esiste un binding della conversazione.
- Menu `Chatbot` rinominato `Conversazioni`.

## Impostazioni centralizzate
Nuovo tab amministrativo **Impostazioni** con persistenza su PostgreSQL (`system_settings`).
Le impostazioni salvate sovrascrivono a runtime i valori `.env` e vengono ricaricate a ogni avvio.

Sezioni:
- Generale: URL pubblico, catalogo prestazioni, upload, TTL link SMS.
- Asterisk/AMI: host, porta, utente, password, handoff, interno operatore, context e originate channel.
- Telegram: bot token e webhook secret.
- WhatsApp: token Cloud API, verify token, Phone Number ID, App Secret e Graph version.
- Chatwoot: URL, account, token, inbox, team, webhook e autosync.
- SMS: gateway, token, sender e timeout.
- LLM: endpoint OpenAI-compatible, API key, modello, temperature e timeout.
- LiveKit: URL, API key e secret.

Le credenziali sensibili non vengono restituite in chiaro dalla API delle impostazioni. Un campo segreto vuoto mantiene il valore già configurato.

## Test integrazioni
Ogni sezione dispone di un pulsante Test per validare la connettività/configurazione di Asterisk, Telegram, WhatsApp, Chatwoot, LLM, LiveKit e SMS.

## Asterisk dinamico
Il listener AMI ora ritenta automaticamente la connessione e rilegge la configurazione corrente a ogni tentativo.
