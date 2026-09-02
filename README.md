# CUP System v1.0.24.2

In questa fase di sviluppo la console operatore non richiede email/password: la schermata di ingresso propone una droplist **Admin / Operatore**. Il backend emette comunque un JWT associato a un vero utente demo, perciò RBAC e abilitazioni chat/telefono continuano a essere verificati lato API. Disabilitare `DEV_ROLE_LOGIN_ENABLED` in produzione.

# CUP System v1.0.21

## Novita v1.0.23

- credenziali demo admin/operatore automatiche;
- chatbot con proposta di 2-3 slot realmente liberi, senza data/ora libera inserita dal paziente;
- ricontrollo disponibilita al momento della conferma;
- apprendimento AI supervisionato dalle chat degli operatori;
- pipeline voce LiveKit/Asterisk basata su trascrizione, consenso, anonimizzazione e approvazione admin;
- esempi approvati usati dinamicamente dal modello LLM e disponibili al voice agent LiveKit.

Vedi `RELEASE_1.0.23.md`.

## v1.0.21 - Analytics semplici per ruolo

La piattaforma separa gli analytics in due livelli: quattro indicatori operativi nella dashboard degli operatori e una sezione amministrativa completa accessibile solo agli admin. Sono inclusi no-show, saturazione agende, promemoria, pre-visita, handoff, lista d'attesa, recall, canali, conversione chatbot-prenotazione e carico operatori. Il dataset demo aggiunge uno storico sintetico per rendere subito leggibili i KPI.


## Novità v1.0.18 - Promemoria appuntamenti

- scheduler persistente per promemoria automatici delle prenotazioni CUP interne;
- offset configurabili, ad esempio 48h, 24h e 2h prima dell'appuntamento;
- invio immediato della conferma alla creazione della prenotazione;
- canali supportati: SMS, WhatsApp Business, email SMTP e Telegram (con chat ID paziente);
- link firmato per confermare o annullare l'appuntamento senza login;
- annullamento dei reminder futuri quando la prenotazione viene cancellata;
- ripianificazione automatica quando data/ora cambiano;
- retry automatico con numero massimo tentativi configurabile;
- nuova pagina operatore **Promemoria** con coda, storico, stato provider e retry manuale;
- pannello promemoria nel dettaglio prenotazione con invio manuale immediato;
- configurazione completa da Impostazioni > Promemoria appuntamenti.

Per il gestionale esterno il motore reminder CUP resta opzionale: viene usato solo per appuntamenti importati/sincronizzati nel database CUP; in modalità `chatbot_only` non vengono creati reminder di prenotazione.


PoC full-stack per gestione CUP con dashboard operatore, prenotazioni/pazienti,
integrazione telefonica Asterisk/AMI, LiveKit opzionale e chatbot web per end user.

## Novità v1.0.15

- modulo Agende/Prenotazioni opzionale per esercizio;
- modalità `internal`, `external` o `chatbot_only`;
- embedding del gestionale prenotazioni esterno nel frame operatore, con apertura in nuova scheda come fallback;
- chatbot consapevole della modalità: non crea prenotazioni CUP quando il gestionale è esterno;
- configurazione centralizzata da Impostazioni > Prenotazioni esercizio.

## Novità precedenti

- chatbot pubblico end-user avviabile direttamente da `chatbot.html`;
- upload documenti durante la conversazione;
- formati ammessi: PDF, PNG/JPG, DOC/DOCX e TXT;
- limite predefinito 10 MB per file e 10 allegati per sessione;
- persistenza degli allegati su volume Docker `cup_uploads`;
- metadati allegati salvati in PostgreSQL (`chat_attachments`);
- download allegati dalla conversazione utente;
- visualizzazione e download degli allegati nella inbox operatore autenticata;
- controlli su estensione, MIME type, dimensione, sessione e nome file;
- `deploy.conf` incluso per il deployer generico con test frontend/API/chatbot;
- versioning coerente `1.0.12`.

## Funzioni già presenti

- backend FastAPI + JWT;
- PostgreSQL + ORM;
- dashboard operatore;
- CRUD prenotazioni;
- elenco pazienti e chiamate;
- chatbot web deterministico per prenotazioni;
- handoff a operatore e inbox conversazioni;
- Asterisk/AMI opzionale;
- LiveKit opzionale;
- webhook Telegram/WhatsApp/Facebook predisposti.

## Avvio rapido

```bash
cp .env.example .env
# Modificare almeno password DB, JWT_SECRET_KEY e ADMIN_BOOTSTRAP_TOKEN.
docker compose up -d --build
```

- Dashboard operatore: `http://localhost:8080/`
- Chat end-user: `http://localhost:8080/chatbot.html`
- API health: `http://localhost:8080/api/health`

## Chat end-user e documenti

La pagina `chatbot.html` apre/ripristina automaticamente una sessione casuale UUID.
L'utente può inviare messaggi e usare il pulsante graffetta per allegare uno o più
file. Gli allegati vengono salvati in `/data/uploads/chat/<session_id>/` nel backend,
ma il percorso è persistente grazie al volume Docker `cup_uploads`.

Endpoint principali:

- `POST /api/chatbot/web/start`
- `POST /api/chatbot/web`
- `GET /api/chatbot/web/{session_id}/messages`
- `POST /api/chatbot/web/{session_id}/attachments`
- `GET /api/chatbot/web/{session_id}/attachments/{attachment_id}`

Gli operatori autenticati vedono gli allegati nella stessa inbox e possono scaricarli
tramite endpoint protetto JWT.

### Configurazione upload

```env
CHAT_UPLOAD_DIR=/data/uploads/chat
CHAT_MAX_UPLOAD_BYTES=10485760
CHAT_MAX_ATTACHMENTS=10
```

## Primo amministratore

Imposta `ADMIN_BOOTSTRAP_TOKEN` in `.env`, quindi usa l'endpoint di registrazione
con header `X-Admin-Bootstrap-Token` per creare il primo account admin/operator.

## Deploy generico

Il pacchetto include `deploy.conf`:

```ini
FRONTEND_URL=http://frontend/
HEALTH_URL=http://frontend/api/health
CHATBOT_URL=http://frontend/chatbot.html
```

Questi check possono essere usati da `deploy-zip-generic.sh` per dichiarare
`DEPLOY_STATUS=SUCCESS` solo dopo verifiche applicative reali.

## Persistenza

I dati PostgreSQL usano `pg_data`; i documenti caricati dal chatbot usano
`cup_uploads`. Un aggiornamento del codice tramite Compose non deve eliminare questi
volumi.

## Sicurezza / produzione

Questa resta una PoC. Prima di usare documenti reali sanitari in produzione sono
necessari almeno: autenticazione/identificazione del paziente, consenso privacy,
retention e cancellazione documenti, cifratura at-rest, antivirus/malware scanning,
rate limiting, CAPTCHA/anti-abuso, audit trail, storage object dedicato, backup e
policy GDPR. Il semplice UUID di sessione non deve essere considerato un meccanismo
di autenticazione sufficiente per documenti sanitari reali.

## v1.0.12 Omnichannel

Version 1.0.12 adds a unified conversation layer for Web, WhatsApp Business and Telegram, optional OpenAI-compatible LLM orchestration, persistent cross-channel documents, operator ownership/handoff events and optional Asterisk AMI phone escalation. See `INTEGRATIONS_1.0.12.md`.

## Novita v1.0.12 - Chatwoot operator queue

La v1.0.12 introduce l'integrazione Chatwoot come console operatori e gestore code. CUP resta il Conversation Core e source of truth; Chatwoot riceve le conversazioni in handoff, assegna team/agenti e rimanda le risposte degli operatori al canale originale. Sono inclusi mapping persistente `chatwoot_bindings`, webhook bidirezionale, sincronizzazione storico, note documentali, team assignment e integrazione con il flusso Asterisk esistente.

Vedi `CHATWOOT_1.0.12.md` per configurazione e webhook.

## v1.0.18 - Demo e UX
La v1.0.18 introduce un cockpit operativo ridisegnato e un dataset dimostrativo sintetico. Il seeder non elimina ne modifica dati reali; usa anagrafiche con prefisso email `demo.cup+`. In un ambiente non demo impostare `DEMO_DATA_ENABLED=false` e `DEMO_AUTO_SEED=false`.

## v1.0.18 - Lista d'attesa automatica
Chatwoot è ora integrato nel tab Impostazioni. La sezione Pazienti è stata resa compatibile con dati legacy e il seed demo può riparare automaticamente un dataset parziale. La lista d'attesa permette di associare paziente, visita, agenda/medico, intervallo temporale, fascia oraria e priorità. Alla cancellazione di un appuntamento il sistema contatta automaticamente i candidati compatibili e assegna lo slot in modo atomico al primo che accetta.


## v1.0.20 - Pre-visita digitale, consensi e check-in
- Template di pre-visita associabili alla tipologia di visita.
- Questionario pubblico con link JWT e consenso tracciato.
- Stato pre-visita pending/completed visibile agli operatori.
- Check-in paziente da link sicuro e workflow accoglienza: non arrivato, arrivato, in attesa, in visita, completato, no-show.
- Link pre-visita e check-in integrati nei promemoria.
- Dataset demo aggiornabile senza duplicare pazienti/prenotazioni.
- Nuova sezione operatore Pre-visita & Check-in e parametri centralizzati in Impostazioni.

## v1.0.20 - Ruoli, Follow-up e Recall

La UI distingue tre spazi concettuali:
- **Operatore**: lavoro quotidiano, comunicazioni e percorso paziente.
- **Admin**: setup tecnico e organizzativo, visibile e modificabile solo agli amministratori.
- **Paziente**: pagine pubbliche semplici per azioni contestuali.

Il modulo continuità di cura genera follow-up post-visita e recall periodici automatici, configurabili globalmente e per tipologia di visita.


## v1.0.22 - Operatori, pagamenti e firma documentale

La console operatore puo' essere limitata per canale (`chat`, `telefono` o entrambi) da **Setup piattaforma > Operatori & canali**. Le limitazioni sono applicate sia nella navigazione sia nelle API. La barra NethVoice e' stata rimossa dal frontend; telefonia e handoff restano gestiti dalla coda CUP/Asterisk.

L'area **Pagamenti & documenti** consente di inviare richieste di pagamento e PDF da firmare al paziente. Per i pagamenti il CUP non acquisisce dati carta: con Stripe usa Checkout ospitato; in alternativa supporta modalita manuale o URL di provider esterno. La firma interna registra documento originale e audit trail crittografico, ma non va considerata firma qualificata quando la normativa richiede un prestatore qualificato.

## Account demo di accesso (v1.0.23.1)
Con `DEMO_LOGIN_USERS_ENABLED=true` il backend garantisce ad ogni avvio questi account, indipendentemente da `DEMO_DATA_ENABLED` e `DEMO_AUTO_SEED`:
- Admin: `admin@demo.cup` / `AdminDemo123!`
- Operatore chat+telefono: `operatore@demo.cup` / `OperatorDemo123!`
Disabilitare il flag in produzione.

## v1.0.23.5 - Login sviluppo corretto
Corretto il blocco JavaScript che impediva la registrazione del submit del login a causa di modali Bootstrap mancanti. Ripristinati i modali operativi e aggiunto controllo versione UI/API. Durante lo sviluppo usare `DEV_ROLE_LOGIN_ENABLED=true`.

## v1.0.25
La pagina pubblica `/chatbot.html` e ora il sito demo Clinica San Michele con chatbot flottante e sala d attesa virtuale.


## v1.0.26 — Prestazioni deduplicate e disponibilità estese
- Catalogo prestazioni consolidato: i duplicati per nome vengono unificati automaticamente preservando configurazioni, prezzi e relazioni.
- Nuove prestazioni duplicate bloccate anche da API Admin.
- Portale paziente: ricerca Privato fino a 8 settimane e SSN fino a 8 mesi (endpoint fino a 365 giorni).
- Ogni proposta di appuntamento mostra esplicitamente prezzo privato o ticket SSN.


## v1.0.27 — gestione cronologia chat
Nel pannello Conversazioni l'Admin puo' eliminare una singola chat o svuotare tutta la cronologia demo. Le azioni non eliminano pazienti o prenotazioni. Il motore LLM e' opzionale e disabilitato per default (`LLM_ENABLED=false`).

## v1.0.29 - Voice AI guidata
Il voice agent usa un NLU vincolato agli intenti CUP. L'LLM, quando configurato, comprende intento, entita e sentiment; non decide disponibilita, prezzi o prenotazioni. L'endpoint server-to-server e' `POST /api/voice/analyze` con header `X-Voice-AI-Token`. Le richieste fuori dominio vengono ricondotte alle funzioni CUP; bassa confidence, richieste esplicite e sentiment critico possono causare handoff automatico.


## v1.0.30
Chatwoot conversation hub: journey_id/patient_id condivisi, routing sul canale corrente, Web/Telegram/WhatsApp/Voice convergenti e CUP source-of-truth dei workflow.
