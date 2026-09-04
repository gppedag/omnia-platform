# OMNIA PROJECT VALIDATION REPORT

Analisi statica dello snapshot `omnia-cloud-review-20260904-000106.zip`.
Nessuna modifica è stata effettuata al codice. Nessuna funzionalità è stata implementata.
Dove il codice non permette una conclusione certa è indicato **NOT VERIFIABLE FROM SNAPSHOT**.

---

## 1. Executive Summary

OMNIA (alias "CUP System") è una piattaforma FastAPI + PostgreSQL + frontend statico che gestisce prenotazioni sanitarie multicanale (Web, WhatsApp, Telegram, SMS, Voice/telefonia) con handoff AI→operatore, Patient 360, pre-visita/check-in, promemoria, lista d'attesa, pagamenti e firma documentale.

Il repository è a un punto di transizione reale, non solo dichiarato: sotto la superficie del vecchio impianto "Conversazioni omnicanale" (tab dentro `index.html`, guidata da `app.js`, 19.906 righe) sta crescendo un secondo layer, **Omnia Console** (`omnia-console.html`, 8.399 righe), che nel codice stesso si autodefinisce attraverso 16 iterazioni progressive (V1→V16, log `[OMNIA CONSOLE] ... attiva`) culminate letteralmente in una release chiamata **"Interaction Workspace V15"** e **"Interaction Completion V16"**. Questo coincide, quasi testualmente, con l'architettura target proposta nella Fase 6 della richiesta: il codice sta già convergendo lì da solo, ma **non come sostituzione della shell legacy**, bensì come **iframe incorporato dentro `index.html`** (`/omnia-console.html?embedded=1&native=1`).

Punti chiave:

- **Versionamento incoerente**: l'app dichiara `APP_VERSION=1.1.1` (config, docker-compose, titolo di `index.html`), ma l'ultima nota di rilascio scritta è `RELEASE_1.0.30.md`. Non esiste alcuna documentazione per tutto ciò che sta tra 1.0.30 e 1.1.1 — che include Omnia Console, Omnia Voice standalone, patient relationships, admin catalog, admin agenda/visits, admin settings, reallocation, booking eligibility, patient identity e `/api/voice-v2`. È una violazione diretta della disciplina di handoff richiesta da `AGENTS.md`.
- **Duplicazione confermata, non presunta**, in almeno tre punti concreti: (a) due implementazioni NLU/voce indipendenti (`voice_nlu_service.py` vs regex proprie in `voice_upgrade_routes.py`); (b) due endpoint "patient 360 per operatore" paralleli (`/api/patients/{id}/overview` ORM-based usato da `app.js`, e `/api/omnichannel/patients/{id}/operator-context` raw-SQL usato da `omnia-console.html`); (c) due punti di ingresso per "Omnia Voice" (tab embedded in `index.html` + pagina standalone `voice-conversations.html`, con la classica indicazione già vista nel codice: `<!-- OMNIA_VOICE_MENU_UNIFIED_V1 -->`, segno di un tentativo pregresso di unificazione mai completato).
- Le integrazioni esterne (Asterisk/MikoPBX, LiveKit, Chatwoot, WhatsApp, Telegram, LLM) sono **quasi tutte disattivate di default e gated da flag/env**, coerentemente con la direzione multi-cliente dichiarata in `AGENTS.md`; ma questo rende impossibile, dallo snapshot, dire quali siano davvero "VERIFIED" in produzione (vedi Sezione 8).
- Non esiste Alembic: lo schema evolve tramite `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` eseguiti a ogni avvio in `main.py`. Funziona, ma è un debito tecnico esplicito e senza rollback strutturato.

---

## 2. Repository State

| Elemento | Valore | Fonte |
|---|---|---|
| Repo dichiarato | `gppedag/omnia-platform` | `PROJECT_SNAPSHOT.md` |
| Branch | `develop` | `PROJECT_SNAPSHOT.md` |
| HEAD dichiarato | `2bbe88a95ad175eb18f4427a3dfc7d887cd3f580` | `PROJECT_SNAPSHOT.md` |
| Ultimo commit dichiarato | "Merge Omnia version 1.1.1" | `PROJECT_SNAPSHOT.md` |
| Metadati Git reali | assenti (`.git/` escluso di proposito) | snapshot sanitizzato |
| File totali | 173 | conteggio diretto |
| Dimensione backend / frontend | ~920 KB / ~4.4 MB | conteggio diretto |

Non è possibile verificare indipendentemente commit, autore o storia: **NOT VERIFIABLE FROM SNAPSHOT**. Tutto ciò che segue è dedotto dal contenuto dei file, non dalla cronologia Git.

---

## 3. Current Version

Tre fonti di versione, non allineate tra loro:

1. `backend/app/config.py`: `APP_VERSION: str = "1.1.1"`
2. `docker-compose.yml`: `APP_VERSION: ${APP_VERSION:-1.1.1}`, ma i `labels: cup.release: "1.0.27"` su `backend` e `frontend` sono rimasti fermi a 1.0.27
3. `frontend/index.html`: `<title>Omnia Flow v1.1.1 - Operatore</title>`, script caricato come `js/app.js?v=20260902-rel11`
4. `README.md`: titolo generale `CUP System v1.0.24.2`, ma include changelog fino a `RELEASE_1.0.30.md`

Nessun file `RELEASE_1.1.0.md` o `RELEASE_1.1.1.md` esiste. La versione applicativa corrente più credibile è **1.1.1**, ma **il salto da 1.0.30 a 1.1.1 non ha nota di rilascio**: è una discrepanza diretta tra documentazione e codice, da segnalare esplicitamente come richiesto.

---

## 4. Architecture Map

```
Nginx (static) ── frontend/ (HTML statico, nessun bundler/build step)
   │
   ├─ index.html  ──────────► "Omnia Flow" — SHELL OPERATORE PRINCIPALE (SPA a tab, no router reale: hash-based #tab)
   │     guidata da js/app.js (19.906 righe, monolite unico)
   │     tab "Conversazioni"        → legacy omnichannel inbox (chat/handoff)
   │     tab "Omnia Voice"          → embed di voice-conversations.html via tab
   │     launcher "omnia-console-*" → IFRAME verso omnia-console.html?embedded=1
   │
   ├─ omnia-console.html ────► "OMNIA CONSOLE" — non raggiungibile da URL diretto nella nav;
   │     8.399 righe, JS inline, versionato internamente V1→V16 nei log console
   │     (Active Session, Live Call UX, Authoritative Phone, Timeline Context,
   │      Patient Context, UI Consolidation, Interaction Workspace, Interaction Completion)
   │
   ├─ voice-conversations.html ► "OMNIA VOICE" — pagina standalone (4.696 righe),
   │     raggiungibile sia come link top-nav sia come tab dentro index.html
   │
   ├─ pagine pubbliche paziente (self-contained, un solo file ciascuna):
   │     chatbot.html, patient-portal.html, checkin.html, previsit.html,
   │     reminder.html, waitlist.html, payment.html, signature.html,
   │     followup.html, recall.html, canali-digitali.html
   │
   └─ pagine admin dedicate: admin-settings.html, admin-catalog.html, admin-agenda-visits.html
   │
FastAPI (backend/app/main.py)
   │  30 router inclusi in app.include_router(...), CORS aperto a "*"
   │  Nessun prefisso di versionamento API globale (prefissi locali per router: /api/xxx)
   │
PostgreSQL 14 (schema gestito senza Alembic: create_all + ALTER TABLE IF NOT EXISTS a ogni boot)
   │
Servizi esterni opzionali (docker-compose profiles, tutti disattivabili):
   - asterisk (profilo "telephony", immagine andrius/asterisk — surrogato di sviluppo)
   - livekit  (profilo "realtime", immagine livekit/livekit-server)
   - omnia-stt (servizio sempre attivo, worker Python, legge registrazioni da
     /var/spool/mikopbx/... — prova diretta che in produzione il PBX reale è MikoPBX,
     non il container "asterisk" di sviluppo)
   - Chatwoot: NON containerizzato, è un servizio esterno raggiunto via webhook/API
     (CHATWOOT_BASE_URL, CHATWOOT_ENABLED=false di default)
```

---

## 5. Frontend Architecture

| File | Righe | Ruolo reale (verificato) |
|---|---:|---|
| `frontend/js/app.js` | 19.906 | Monolite JS della shell operatore legacy: routing a tab via hash, chiamate fetch dirette, gestione stato globale in variabili top-level. Contiene 8 `setInterval` e 36 `setTimeout` di cui diversi persistenti per il refresh (chat, coda handoff, "call island"). |
| `frontend/omnia-console.html` | 8.399 | Pagina self-contained (script inline) incorporata via `<iframe>` dentro `index.html`. Contiene 9 `setInterval`/15 `setTimeout` propri, indipendenti da quelli di `app.js` — quando è aperta, i due insiemi di polling girano in parallelo. |
| `frontend/voice-conversations.html` | 4.696 | Pagina self-contained per la vista chiamate Voice; anch'essa con polling proprio (5 `setInterval`). |
| `frontend/index.html` | 5.082 | Markup/nav della shell + 7 blocchi `<script>` inline di bootstrap, il grosso della logica è delegato a `app.js`. |
| `frontend/js/api.js` | 426 | Unico livello di astrazione HTTP centralizzato individuato — ma **non è usato in modo esclusivo**: `app.js`, `omnia-console.html` e `voice-conversations.html` contengono anche chiamate `fetch()` dirette proprie, non tutte passano da `api.js`. |
| `frontend/js/chatbot.js`, `patient-portal.js` | 298 / 337 | Isolati, per le pagine pubbliche paziente — corretta separazione di responsabilità. |
| pagine pubbliche mono-file (`checkin.html`, `payment.html`, `previsit.html`, `waitlist.html`, `signature.html`, `followup.html`, `recall.html`, `canali-digitali.html`) | 1–8 (minificate) | Non sono stub incompleti: sono pagine complete, autonome, con `fetch()` inline verso endpoint pubblici token-based (`/api/previsit/checkin/public`, `/api/payments/public/{token}`, `/api/signatures/public/{token}`, ecc.). Pattern coerente e ripetuto correttamente su tutte. |

Non esiste build step (webpack/vite/bundler): il frontend è servito staticamente da Nginx (`docker-compose.yml`, servizio `frontend: image: nginx:alpine`), coerente con `nginx.conf`/`nginx.dev.conf` presenti.

---

## 6. Backend Architecture

FastAPI, 33 router totali (`backend/app/api/*.py`), montati tutti in `app/main.py` senza versionamento globale del path. Struttura a 3 livelli: `api/` (route + validazione Pydantic) → `services/` (business logic) → `models/` (SQLAlchemy ORM).

I file più grandi per riga di codice sono un buon proxy del carico di responsabilità:

| File | Righe | Contenuto verificato |
|---|---:|---|
| `api/chatbot_routes.py` | 1.863 | Chatbot web deterministico + upload allegati + gestione sessione |
| `api/omnichannel_routes.py` | 1.594 | Webhook WhatsApp/Telegram, journey, sessioni, owner/handoff, **endpoint `operator-context`** (vedi Sez. 14) |
| `api/patient_routes.py` | 1.341 | CRUD paziente + blocco `OMNIA_PATIENT_360_V1` (endpoint `/overview`) |
| `services/reminder_service.py` | 1.077 | Motore promemoria multi-canale con retry/scheduling |
| `api/reallocation_routes.py` | 1.044 | Gestione interruzioni di servizio/riallocazione appuntamenti su larga scala |
| `api/call_routes.py` | 978 | CRUD chiamate telefoniche, integrazione con AMI |
| `api/voice_upgrade_routes.py` | 739 | Secondo stack Voice (`/api/voice-v2`), non documentato in nessun `RELEASE_*.md` |
| `services/ami_listener.py` | 718 | Listener asincrono eventi Asterisk AMI |

`app/main.py` (209 righe) è il composition root: registra i router, esegue le migrazioni "manuali" ad `ALTER TABLE`, avvia 4 worker in background (`start_ami_listener`, `handoff_routes.timeout_worker`, `reminder_worker`, `waitlist_worker`, `care_worker`) come `asyncio.create_task` allo startup — nessun supervisore/retry esplicito se uno di questi task muore silenziosamente (**rischio operativo**, vedi Sez. 15).

Import difensivo per LiveKit:
```python
try:
    from app.api import livekit_routes
except ImportError as exc:
    livekit_routes = None
```
Il `Dockerfile` del backend installa **solo** `requirements.txt`, non `requirements-livekit.txt` (dipendenza `livekit-api` separata, commentata come opzionale). Quindi **nella build Docker standard, `/api/livekit/token` non è mai attivo**: va installato manualmente il pacchetto extra. Questo è verificabile col codice, non è un'ipotesi.

---

## 7. Data Model

Nessun file di migrazioni Alembic trovato nel repository (`find . -iname "*alembic*"` → nessun risultato). Lo schema è definito interamente dai modelli SQLAlchemy in `backend/app/models/*.py` (19 file: booking, calendar, call, care, chat, chatwoot, commerce, handoff, notification, omnichannel, patient, patient_relationship, portal, previsit, reallocation, reminder, system_setting, training, user, waitlist) e mantenuto in sincronia a runtime da:

1. `Base.metadata.create_all(bind=engine)` — crea tabelle mancanti, **non altera quelle esistenti**;
2. un blocco di ~25 istruzioni `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` scritte a mano in `main.py`, con commento esplicito: *"Migrazione retrocompatibile per prenotazioni create dalle release <=1.0.12"*;
3. `UPDATE` una-tantum per popolare colonne nuove su righe esistenti (es. prezzi privati/ticket SSN per codici visita specifici, hardcoded: `CARD`, `DERM`, `ECO`, `CTRL`, `URG`).

Questo approccio **funziona per aggiungere colonne**, ma non gestisce rinomini, cambi di tipo, o rimozioni — e non ha un meccanismo di rollback dichiarato, in diretto contrasto con la regola di `AGENTS.md`: *"qualsiasi modifica schema deve avere una strategia di upgrade e rollback"*. È debito tecnico riconosciuto implicitamente dagli stessi commenti nel codice, non un'invenzione di questa analisi.

Tabelle/entità chiave dedotte dai modelli e dalle query: `patients`, `bookings`, `visit_types`, `agendas`, `calls`, `chat_sessions`, `chat_attachments`, `chatwoot_bindings`, `users`, `handoffs`, `reallocation_case`/`service_interruption`, `waitlist_entry`, `reminder`, `previsit_template`, `patient_document`. Schema esatto colonna-per-colonna: **NOT VERIFIABLE FROM SNAPSHOT** senza eseguire il codice contro un DB reale.

---

## 8. External Integrations

| Integrazione | Stato | Evidenza |
|---|---|---|
| **Asterisk/AMI** | CONFIGURATION-DEPENDENT | `services/ami_listener.py` (718 righe) + `services/asterisk_gateway.py` implementano il protocollo AMI reale (libreria `panoramisk` in `requirements.txt`). Attivo solo se `ASTERISK_HANDOFF_ENABLED=true` e host raggiungibile; il container `asterisk` in `docker-compose.yml` è dietro `profiles: ["telephony"]` e usa l'immagine generica `andrius/asterisk`, **non MikoPBX**. |
| **MikoPBX (produzione)** | CONFIGURATION-DEPENDENT / non containerizzato in questo repo | Prova indiretta ma concreta: il servizio `omnia-stt` monta in sola lettura `/var/spool/mikopbx/storage/usbdisk1/mikopbx/astspool/monitor:/recordings:ro` — un path reale di MikoPBX, presente **fuori** dal docker-compose (host esterno). Conferma che in PROD il PBX reale non è il container Asterisk generico del compose. |
| **LiveKit (token video-chat browser)** | INCOMPLETE nella build standard | Route `/api/livekit/token` esiste (`livekit_routes.py`, 19 righe) ma richiede il pacchetto `livekit-api`, installato solo via `requirements-livekit.txt`, **non incluso nel Dockerfile**. Import protetto da `try/except`: se il pacchetto manca, il router semplicemente non si carica (log di warning), l'app continua a funzionare. |
| **LiveKit (pipeline voce esterna, agente telefonico)** | CONFIGURATION-DEPENDENT / parzialmente esterna | L'agente vocale stesso (che parlerebbe con il chiamante via Asterisk+LiveKit) **non è nel repository** — solo client di esempio (`examples/livekit_training_client.py`, `voice_nlu_client.py`, `livekit_handoff_client.py`) che mostrano il contratto verso CUP (`POST /api/voice/analyze`, `POST /api/handoffs/request`). L'implementazione reale dell'agente: **NOT VERIFIABLE FROM SNAPSHOT**. |
| **Chatwoot** | CONFIGURATION-DEPENDENT, disattivo di default | `CHATWOOT_ENABLED=false` in `.env.example`. Servizio esterno via HTTP (`services/chatwoot_service.py`, 281 righe, client verso REST API Chatwoot). `RELEASE_1.0.30.md` documenta un "Conversation Hub Mode" (`CHATWOOT_HUB_MODE=true`) con `journey_id`/`patient_id` condivisi — coerente col codice (`chat_sessions.journey_id` in `models/chat.py`). |
| **WhatsApp Business Cloud API** | CONFIGURATION-DEPENDENT | Webhook `GET/POST /api/omnichannel/whatsapp/webhook` implementati; richiedono `WHATSAPP_API_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, verifica firma `WHATSAPP_APP_SECRET`. Vuoti di default. |
| **Telegram** | CONFIGURATION-DEPENDENT | `POST /api/omnichannel/telegram/webhook`; richiede `TELEGRAM_BOT_TOKEN`. |
| **SMS** | CONFIGURATION-DEPENDENT | `services/sms_service.py` + `SMS_GATEWAY_URL`/`SMS_GATEWAY_TOKEN`, vuoti di default; usato da reminder/followup/recall/payment/signature (tutti configurabili per canale via `*_CHANNELS` in env). |
| **LLM (orchestrazione risposte/NLU)** | Disattivato di default, opzionale | `LLM_ENABLED=false`; quando attivo punta a un endpoint OpenAI-compatibile locale (`LLM_BASE_URL=http://host.docker.internal:4000/v1`). Usato sia da `chatbot_routes` sia da `voice_nlu_service._llm_analyze`, con fallback deterministico a regole se assente/disabilitato (`_fallback_analyze`). |
| **Voice AI / NLU** | **VERIFIED come composizione a due layer, non duplicazione totale (corretto in Fase 2)** | Vedi Sezione 14 punto 1: `voice-v2` usa `voice_nlu_service.analyze()` come base e sovrappone regex proprie come override deterministico ad alta confidenza. |

Nessuna di queste integrazioni può essere dichiarata "funzionante in produzione" dal solo snapshot: tutte richiedono credenziali/servizi esterni non presenti nell'archivio sanitizzato, per esplicita dichiarazione in `PROJECT_SNAPSHOT.md`.

---

## 9. Legacy "Conversazioni omnicanale"

Non è un file separato: è il **tab "Conversazioni"** dentro `index.html` (`data-tab="chatbot"`), gestito interamente da `app.js`. Non ha un URL proprio, non è raggiungibile fuori dalla SPA legacy.

Capability operative reali verificate in questo tab (via ricerca funzioni/endpoint in `app.js`):
- Inbox conversazioni multicanale (Web/WhatsApp/Telegram), con badge "live" e badge handoff
- Apertura conversazione, risposta operatore, note interne (via `/api/omnichannel/sessions/{id}` e correlati)
- Owner/assegnazione (`POST /sessions/{id}/owner`)
- Handoff (`POST /sessions/{id}/handoff`, più l'intero `handoff_routes.py`: coda, accept/reject, return-ai, callback, presenza operatore)
- Ricerca paziente (`/api/patients/search`), apertura scheda paziente con Patient 360 legacy (`/api/patients/{id}/overview`)
- Storico prenotazioni/relazioni paziente (`/api/patients/{id}/relationships`, `/history`)

Non verificato/non individuato nel tab Conversazioni: sentiment/intent a livello di UI operatore (esiste lato dati per le chiamate — `ai_intent`, `ai_sentiment`, `ai_confidence` in `calls` — ma non ho trovato un rendering equivalente nell'inbox chat), journey/automation come vista dedicata (il concetto `journey_id` esiste nel DB/backend ma non ho trovato una UI legacy che lo esponga esplicitamente all'operatore).

---

## 10. Omnia Console

`frontend/omnia-console.html`, self-contained, **incorporata via iframe** da `app.js` (id `omnia-console-workspace-v4`, sorgente `/omnia-console.html?embedded=1&native=1&v=20260902-noflicker2`) — non è un prodotto separato raggiungibile autonomamente nella navigazione principale, è un pannello che si apre sopra la shell legacy.

Il file stesso documenta la propria evoluzione tramite banner di log identificabili in ordine:

```
Phone Controls V4 → Active Session V6 → Live Call UX V7 → Authoritative Phone V8
→ Timeline Context V10 → Patient Context V11 → UI Consolidation V13
→ Interaction Workspace V15 → Interaction Completion V16
```

(V5, V9, V12, V14 non hanno un banner di log proprio — o sono stati rimossi in refactor successivi, o non loggavano: **NOT VERIFIABLE FROM SNAPSHOT** quale delle due).

Capability verificate: sessione telefonica live con controlli chiamata "autoritativi" (`omniaV8SyncPhone`), timeline/contesto paziente aggregato (chiama `/api/omnichannel/patients/{id}/operator-context`, **non** l'endpoint Patient 360 usato dal resto dell'app — vedi Sez. 14), scambio documenti in tempo reale durante la chiamata (`OMNIA_EXCHANGE_TIMER`, polling ogni pochi secondi). Polling proprio: 9 `setInterval`/15 `setTimeout`, indipendenti da quelli della shell che la ospita.

**Osservazione architetturale centrale**: il nome dell'ultima iterazione strutturale trovata nel codice reale — *"Interaction Workspace"* — coincide quasi letteralmente con il nodo centrale dell'architettura target proposta nella richiesta originale. Questo non è coincidenza casuale: **Omnia Console è già, di fatto, l'abbozzo naturale di quell'Interaction Workspace**, solo che oggi vive come iframe secondario dentro la shell legacy invece che come shell primaria.

---

## 11. Omnia Voice

Doppio punto di accesso verificato, non uno solo:
1. Link top-nav diretto in `index.html`: `<a href="/voice-conversations.html">Omnia Voice</a>` (uscita dalla SPA, pagina intera)
2. Tab interno alla SPA: `data-tab="voice-conversations"` nella sidebar, con badge chiamate live proprio

Il commento `<!-- OMNIA_VOICE_MENU_UNIFIED_V1 -->` trovato immediatamente sopra la voce di menu è la prova che un tentativo di "unificazione" del menu era già stato pianificato/etichettato in passato, ma i due percorsi (link esterno + tab) coesistono ancora oggi nello stesso file.

`voice-conversations.html` chiama **esclusivamente** `/api/voice-v2/conversations` (`voice_upgrade_routes.py`) per la lista chiamate/conversazioni — non tocca affatto `voice_routes.py` (`/api/voice`, lo stack NLU "ufficiale" documentato in `RELEASE_1.0.29.md`). Questo è coerente con quanto emerso in Sezione 14: sono due stack Voice paralleli, e la UI "Omnia Voice" visibile all'operatore dipende dal secondo, meno documentato.

---

## 12. Feature Parity Matrix

Legenda stato: **PRESENT** (reale, usabile da UI) · **PARTIAL** · **MISSING** · **DUPLICATE** (implementato più volte in modo divergente) · **OBSOLETE** · **NEEDS_REDESIGN**.
Priorità: **P0** = necessaria per dismettere Conversazioni · **P1** = importante · **P2** = miglioramento.

| Capability | Legacy (Conversazioni/`app.js`) | Omnia Console | Omnia Voice | Backend | Status | Priority |
|---|---|---|---|---|---|---|
| Inbox conversazioni | PRESENT | PARTIAL (solo in sessione telefonica attiva) | n/a | PRESENT | PARTIAL | P0 |
| Ricerca/filtri | PRESENT (`/patients/search`) | NOT VERIFIABLE FROM SNAPSHOT | PARTIAL (lista chiamate) | PRESENT | PARTIAL | P0 |
| Apertura interazione | PRESENT | PRESENT (sessione voce) | PRESENT | PRESENT | PRESENT | — |
| Risposta operatore | PRESENT | n/a (voce, non testo) | n/a | PRESENT | PRESENT | — |
| Outbound | NOT VERIFIABLE FROM SNAPSHOT | NOT VERIFIABLE FROM SNAPSHOT | NOT VERIFIABLE FROM SNAPSHOT | PARTIAL (`AMI_ORIGINATE_CHANNEL` esiste in config) | NEEDS_REDESIGN | P1 |
| Owner/assegnazione | PRESENT (`/sessions/{id}/owner`) | MISSING | MISSING | PRESENT | PARTIAL | P0 |
| Trasferimento | NOT VERIFIABLE FROM SNAPSHOT (solo per Voice via AMI) | NOT VERIFIABLE FROM SNAPSHOT | NOT VERIFIABLE FROM SNAPSHOT | PARTIAL | NEEDS_REDESIGN | P1 |
| Handoff AI→operatore | PRESENT (`handoff_routes.py` completo: coda, accept/reject, return-ai, callback) | NOT VERIFIABLE FROM SNAPSHOT (embed non sembra esporlo) | n/a | PRESENT | PARTIAL | P0 |
| Chiusura | PRESENT (`set_status`) | NOT VERIFIABLE FROM SNAPSHOT | NOT VERIFIABLE FROM SNAPSHOT | PRESENT | PARTIAL | P0 |
| Riapertura | NOT VERIFIABLE FROM SNAPSHOT | NOT VERIFIABLE FROM SNAPSHOT | NOT VERIFIABLE FROM SNAPSHOT | NOT VERIFIABLE FROM SNAPSHOT | UNKNOWN | P1 |
| Note interne | PRESENT | NOT VERIFIABLE FROM SNAPSHOT | n/a | PRESENT | PARTIAL | P1 |
| Patient 360 | PRESENT (`/patients/{id}/overview`) | PRESENT ma **endpoint diverso** (`/omnichannel/patients/{id}/operator-context`) | MISSING | **DUPLICATE** | **DUPLICATE** | **P0** |
| Riconciliazione paziente | PARTIAL (`patient_identity_routes.py` → `POST /resolve`, un solo endpoint) | NOT VERIFIABLE FROM SNAPSHOT | PARTIAL (risoluzione per numero chiamante, in `voice_nlu`/`omnichannel`) | PRESENT | PARTIAL | P0 |
| Appuntamenti | PRESENT (calendario dedicato) | NOT VERIFIABLE FROM SNAPSHOT | n/a | PRESENT | PRESENT | — |
| Contatti/delegati | PRESENT (`patient_relationship_routes.py`) | MISSING | n/a | PRESENT | PARTIAL | P1 |
| Documenti/allegati | PRESENT (chat) | PRESENT ma **canale separato** (scambio documenti durante chiamata, `OMNIA_EXCHANGE_TIMER`) | n/a | PRESENT (`portal.py`, `PatientDocument`) | DUPLICATE (percorsi UX diversi, stesso concetto) | P1 |
| Document exchange | PRESENT (chatbot allegati) | PRESENT (voce, proprio flusso) | n/a | PRESENT | DUPLICATE | P1 |
| WhatsApp | PRESENT (webhook + inbox) | MISSING | n/a | PRESENT | PARTIAL | P0 |
| SMS | PRESENT (reminder/notifiche, non conversazionale) | n/a | n/a | PRESENT | PRESENT (per lo scopo previsto) | — |
| Telegram | PRESENT | MISSING | n/a | PRESENT | PARTIAL | P0 |
| Web Chat | PRESENT | MISSING | n/a | PRESENT | PARTIAL | P0 |
| Voice | PARTIAL (solo come tab d'ingresso) | PRESENT (il cuore del prodotto) | PRESENT | **DUPLICATE** (due stack NLU) | **DUPLICATE** | **P0** |
| Callback | PRESENT (`handoff_routes.py: /{id}/callback`) | NOT VERIFIABLE FROM SNAPSHOT | NOT VERIFIABLE FROM SNAPSHOT | PRESENT | PARTIAL | P1 |
| Timeline/storico | PARTIAL (`/patients/{id}/history`) | PRESENT ("Timeline Context V10") | PARTIAL | PARTIAL | DUPLICATE | P1 |
| Sentiment | MISSING (in UI) | NOT VERIFIABLE FROM SNAPSHOT | NOT VERIFIABLE FROM SNAPSHOT | PRESENT (colonna `ai_sentiment` su `calls`) | NEEDS_REDESIGN | P2 |
| Intent | MISSING (in UI) | NOT VERIFIABLE FROM SNAPSHOT | NOT VERIFIABLE FROM SNAPSHOT | PRESENT (`ai_intent`, sia da `voice_nlu_service` sia da pattern regex in `voice_upgrade_routes`) | NEEDS_REDESIGN | P2 |
| Journey/automation | MISSING (in UI) | NOT VERIFIABLE FROM SNAPSHOT | NOT VERIFIABLE FROM SNAPSHOT | PRESENT (`journey_id` su `chat_sessions`, usato da Chatwoot hub) | NEEDS_REDESIGN | P1 |

**Nota metodologica importante**: come richiesto, una capability non è stata segnata PRESENT solo perché esiste un endpoint backend — è stata segnata PRESENT solo dove ho trovato una chiamata frontend effettiva a quell'endpoint. Diverse righe sono PARTIAL proprio per questo motivo (backend pronto, frontend non verificato o assente).

---

## 13. Backend Capabilities Not Yet Used by Omnia (Console/Voice)

Endpoint/servizi backend esistenti e non richiamati (per quanto verificabile via `grep`) né da `omnia-console.html` né da `voice-conversations.html`:

- `patient_relationship_routes.py` (contatti/delegati) — usato solo da `app.js` legacy
- `reallocation_routes.py` (1.044 righe, riallocazione appuntamenti su interruzione servizio) — nessun riferimento trovato in Console/Voice
- `admin_catalog_routes.py`, `admin_agenda_visit_routes.py`, `admin_settings_routes.py` — hanno pagine HTML admin dedicate proprie (`admin-*.html`), separate sia da Console sia dalla shell operatore
- `booking_eligibility_routes.py` — non referenziato in Console/Voice
- `training_routes.py` (apprendimento supervisionato AI dagli esempi operatore, v1.0.23) — non referenziato in Console/Voice
- `care_routes.py` (follow-up/recall) — gestito da pagine pubbliche paziente dedicate (`followup.html`, `recall.html`), non dalla console operatore

Questo conferma che **Omnia Console oggi copre solo la fetta "voce in tempo reale + contesto paziente durante la chiamata"** del prodotto, non l'intero perimetro operativo — coerente con l'istruzione di non assumere che Voice debba sostituire Conversazioni.

---

## 14. Technical Debt — Top 10

1. **[CORRETTO in Fase 2 rispetto alla prima stesura]** Due stack Voice/NLU, ma **non indipendenti come inizialmente riportato**: `voice_upgrade_routes.py` (`/api/voice-v2`) importa realmente `voice_nlu_service` e la sua funzione `deterministic_analysis()` usa `voice_nlu_service.analyze()` come base, sovrapponendo poi regex proprie (`HANDOFF_PATTERNS`, `BOOKING_PATTERNS`, `RESCHEDULE_PATTERNS`, `CANCEL_PATTERNS`) come override ad alta confidenza quando trovano un match esplicito — il risultato è esplicitamente etichettato nel codice come `"decision_source": "deterministic+hybrid"`. Non è quindi una duplicazione totale disconnessa, ma un **secondo layer di composizione non documentato** sopra il primo stack. Resta comunque debito tecnico: sono due punti di logica da mantenere in sincronia (se cambia `ALLOWED_INTENTS` in `voice_nlu_service`, va verificato se le regex di `voice_upgrade_routes.py` restano coerenti), e nessuna nota di rilascio lo documenta.
2. **Due endpoint "patient 360 per operatore" indipendenti.** `GET /api/patients/{id}/overview` (ORM, blocco `OMNIA_PATIENT_360_V1`, usato da `app.js`) vs `GET /api/omnichannel/patients/{id}/operator-context` (raw SQL con `sqlalchemy.inspect` difensivo su esistenza tabelle, usato da `omnia-console.html`). Stessa intenzione di prodotto, due query, due contratti di risposta.
3. **`omnia-console.html` stratificato V1→V16** in un singolo file di 8.399 righe, con marcatori di versione lasciati nei log di produzione (`console.info("[OMNIA CONSOLE] ... attiva")`) — esattamente il pattern che `CLOUD_AGENT_INSTRUCTIONS.md` chiede di evitare di ripetere ("non creare automaticamente un'altra patch stile V18/V19/V20").
4. **Polling non coordinato e potenzialmente sovrapposto**: quando Omnia Console è aperta come iframe dentro `index.html`, i timer di `app.js` (8 `setInterval`) e quelli di `omnia-console.html` (9 propri) girano entrambi contemporaneamente nello stesso browser, nessun meccanismo di single-flight o backoff comune individuato.
5. **Doppio punto d'ingresso per Omnia Voice** (tab + link esterno), con un commento (`OMNIA_VOICE_MENU_UNIFIED_V1`) che indica un tentativo di unificazione precedente rimasto incompiuto.
6. **Nessuna nota di rilascio per gran parte della superficie API attuale**: `voice_upgrade_routes.py`, `admin_catalog_routes.py`, `admin_agenda_visit_routes.py`, `admin_settings_routes.py`, `reallocation_routes.py`, `booking_eligibility_routes.py`, `patient_identity_routes.py`, `patient_relationship_routes.py` e l'intero `omnia-console.html` non compaiono in nessun `RELEASE_*.md`. Il changelog documentato si ferma a 1.0.30; l'app dichiara 1.1.1.
7. **Migrazioni schema manuali e non reversibili**: ~25 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` scritte a mano in `main.py`, incluse `UPDATE` con valori hardcoded per codici specifici (`CARD`, `DERM`, `ECO`, `CTRL`, `URG`) — funzionale ma fragile, e in violazione della regola propria di `AGENTS.md` su upgrade/rollback.
8. **4 worker asincroni avviati con `asyncio.create_task` senza supervisione** (`start_ami_listener`, `handoff_routes.timeout_worker`, `reminder_worker`, `waitlist_worker`, `care_worker` — 5 in realtà): se uno di questi solleva un'eccezione non gestita e muore, nulla nel codice sembra riavviarlo o segnalarlo a livello applicativo (verificare i singoli worker per gestione eccezioni interne: **NOT VERIFIABLE FROM SNAPSHOT** in dettaglio senza tracciare ogni funzione).
9. **CORS aperto a `"*"`** con `allow_credentials=True` in `main.py` — combinazione che i browser moderni in realtà bloccano silenziosamente per le richieste con credenziali, e che comunque è una configurazione permissiva da rivedere prima di produzione multi-cliente.
10. **`api.js` non è il solo canale HTTP**: esiste un livello di astrazione (426 righe) ma `app.js`, `omnia-console.html` e `voice-conversations.html` contengono anche `fetch()` dirette proprie — l'astrazione non è applicata in modo uniforme, quindi cambiare base URL, auth header o error handling richiede modifiche in più punti.
11. **[Aggiunto in Fase 2, non presente nell'analisi iniziale]** Duplicazione confermata anche per la gestione di medici/prestazioni: `admin_catalog_routes.py` (`/api/admin/catalog/*`, ORM, consumato da `admin-catalog.html`) e `admin_settings_routes.py` (`/api/admin/settings/*`, SQL grezzo via `text()`, consumato da `admin-settings.html`) implementano entrambi CRUD indipendenti su `doctors` e `visit_types`, con due pagine admin separate che scrivono sulle stesse tabelle senza logica condivisa. Stesso pattern (ORM vs SQL grezzo) già visto per Patient Context — non è un caso isolato, è una tendenza ricorrente nel progetto quando una funzionalità viene "riscritta per una nuova UI" invece di essere centralizzata in un servizio.

---

## 15. Security / Operational Observations

- `DEV_ROLE_LOGIN_ENABLED` e `DEMO_LOGIN_USERS_ENABLED` (con credenziali demo in chiaro nel `README.md`: `admin@demo.cup` / `AdminDemo123!`) sono flag che **devono** essere disattivati in produzione — il progetto stesso lo dichiara esplicitamente più volte nel `README.md`. In `docker-compose.yml` il default per l'ambiente descritto è `DEV_ROLE_LOGIN_ENABLED: "true"` — va verificato che l'overlay/compose di produzione lo sovrascriva (**NOT VERIFIABLE FROM SNAPSHOT**: qui c'è un solo `docker-compose.yml`, presumibilmente quello di sviluppo, dato il commento su `DEV_ROLE_LOGIN_ENABLED`).
- CORS `allow_origins=["*"]` + `allow_credentials=True` (Sez. 14, punto 9).
- Firma documentale interna dichiarata esplicitamente **non qualificata** dal `README.md` stesso ("non va considerata firma qualificata quando la normativa richiede un prestatore qualificato") — coerenza tra codice e documentazione qui corretta, nessuna contraddizione.
- Gestione documenti sanitari: il `README.md` stesso elenca onestamente ciò che manca per un uso reale (cifratura at-rest, antivirus, audit trail, retention/cancellazione, policy GDPR) — di nuovo, trasparenza corretta nella documentazione, non un problema nascosto.
- Nessun secret reale presente nello snapshot (conforme a quanto dichiarato in `PROJECT_SNAPSHOT.md` e `CLOUD_AGENT_INSTRUCTIONS.md`); `.env.example` contiene solo placeholder.

---

## 16. Target Architecture

L'architettura proposta nella richiesta originale:

```
OMNIA CONSOLE → Interaction Workspace → {Voice, Messaging, Channels} → Patient Context → Patient 360
```

**Verifica contro il codice reale**: è sostanzialmente corretta come *destinazione*, e il codice lo conferma da solo — letteralmente, l'ultima iterazione di `omnia-console.html` si autodefinisce "Interaction Workspace" (V15) seguita da "Interaction Completion" (V16). Non è un'architettura da imporre dall'esterno: **è già la direzione in cui il file sta evolvendo**, in modo organico (probabilmente non pianificato a tavolino, dato il naming incrementale V1-V16 senza documentazione).

Correzioni proposte rispetto al diagramma originale, basate su ciò che il codice mostra oggi:

1. **Omnia Console non deve restare un iframe secondario** dentro la shell legacy. Il rapporto di dipendenza va invertito: Omnia Console (rinominata concettualmente "Interaction Workspace") deve diventare la shell primaria, e ciò che oggi è "Conversazioni" (il tab in `app.js`) deve confluire come una delle viste "Messaging" dentro quel workspace, non il contrario.
2. **"Patient Context" e "Patient 360" non sono due livelli distinti nel codice attuale: sono due implementazioni concorrenti dello stesso livello** (Sez. 14, punto 2). Prima di poter disegnare "Patient Context → Patient 360" come una gerarchia pulita, va eliminata la duplicazione: un solo servizio di aggregazione dati paziente, consumato sia dalla vista overview leggera sia dal pannello di contesto durante l'interazione live.
3. **"Voice" nel diagramma target è corretto come canale**, non come prodotto. **[Corretto in Fase 2]**: non è necessario "scegliere quale dei due stack sopravvive", perché non sono indipendenti — `voice-v2` già usa `voice_nlu_service` come base (vedi Sez. 14 punto 1). Il lavoro reale da fare è più semplice di quanto ipotizzato inizialmente: **documentare esplicitamente** il layer di override deterministico come parte integrante del contratto NLU (oggi implicito e non testato in modo esplicito), non eliminare un secondo motore.
4. **"Channels" nel diagramma dovrebbe includere esplicitamente Chatwoot come hub di canale**, non come sistema a parte: `RELEASE_1.0.30.md` descrive già Chatwoot come "conversation hub" con CUP come source-of-truth — è concettualmente già allineato al target, va solo reso coerente lato UI operatore (oggi l'operatore CUP e l'agente Chatwoot sono, di fatto, due superfici diverse).

---

## 17. Migration Roadmap

Cinque fasi, nessun big-bang. Ogni fase è pensata per lasciare il sistema deployabile e rollback-abile al termine.

### Fase 1 — Consolidamento della verità (no feature nuove)
- **OBJECTIVE**: eliminare le duplicazioni note prima di costruire altro sopra.
- **CAPABILITIES**: nessuna nuova capability utente-visibile.
- **ARCHITECTURAL WORK**: unificare `/api/patients/{id}/overview` e `/api/omnichannel/patients/{id}/operator-context` in un solo servizio (`services/patient_context_service.py`), con due presentation adapter se serve backward-compat temporanea. Decidere e documentare quale stack Voice/NLU è quello vivo.
- **FILES/COMPONENTS**: `patient_routes.py`, `omnichannel_routes.py`, `voice_routes.py`, `voice_upgrade_routes.py`, `voice_nlu_service.py`.
- **DEPENDENCIES**: nessuna esterna.
- **RISKS**: rompere `omnia-console.html`, che dipende dalla forma di risposta raw-SQL attuale (difensiva su tabelle mancanti) — va preservata la stessa robustezza nel nuovo servizio unificato.
- **TEST STRATEGY**: test di equivalenza risposta vecchia/nuova su un campione di pazienti reali in DEV prima di rimuovere l'endpoint duplicato.
- **DEFINITION OF DONE**: un solo endpoint patient-context, entrambe le UI lo consumano, `RELEASE_x.md` scritto.

### Fase 2 — Documentare ciò che già esiste
- **OBJECTIVE**: colmare il buco 1.0.30→1.1.1.
- **CAPABILITIES**: nessuna.
- **ARCHITECTURAL WORK**: scrivere `RELEASE_1.1.0.md`/`RELEASE_1.1.1.md` retroattivi per Omnia Console V1-V16, Omnia Voice, admin routes, reallocation, patient identity/relationship — anche solo a consuntivo.
- **FILES/COMPONENTS**: solo documentazione.
- **DEPENDENCIES**: Fase 1 utile ma non bloccante.
- **RISKS**: nessuno tecnico; rischio organizzativo se nessuno ha più il contesto per scrivere retroattivamente cosa fa ogni V.
- **TEST STRATEGY**: n/a.
- **DEFINITION OF DONE**: changelog coerente con `APP_VERSION`.

### Fase 3 — Invertire la gerarchia Shell/Console
- **OBJECTIVE**: rendere Omnia Console (Interaction Workspace) la shell primaria per le interazioni live, mantenendo la shell legacy solo per anagrafica/agende/admin finché non migrate.
- **CAPABILITIES**: nessuna nuova per l'utente finale, ma cambia il punto d'ingresso operatore per chat+voce.
- **ARCHITECTURAL WORK**: estrarre da `omnia-console.html` i pezzi riusabili (JS inline → moduli), farla ospitare il tab "Conversazioni" invece di essere ospitata da `app.js`.
- **FILES/COMPONENTS**: `omnia-console.html`, `app.js`, `index.html`.
- **DEPENDENCIES**: Fase 1 completata (altrimenti si propaga la duplicazione nella nuova shell).
- **RISKS**: alto — è il file JS più grande del progetto (19.906 righe in `app.js`) da toccare; da fare a fette verticali, una funzione/tab alla volta.
- **TEST STRATEGY**: test manuale per tab migrato + smoke test su login/dashboard/agende (le parti non toccate) ad ogni step.
- **DEFINITION OF DONE**: operatore entra da Omnia Console per chat e voce; `app.js` ridotto del corrispondente perimetro.

### Fase 4 — Unificare punti d'ingresso Voice
- **OBJECTIVE**: un solo percorso "Omnia Voice" (rimuovere la doppia via tab+link esterno).
- **CAPABILITIES**: nessuna nuova, riduzione confusione UX.
- **ARCHITECTURAL WORK**: consolidare `voice-conversations.html` come unica destinazione, referenziata sia da link sia da tab con lo stesso stato.
- **FILES/COMPONENTS**: `index.html`, `voice-conversations.html`.
- **DEPENDENCIES**: Fase 1 (stack NLU unico) raccomandata prima.
- **RISKS**: basso.
- **TEST STRATEGY**: verifica che badge "chiamate live" resti sincronizzato in entrambi i contesti di navigazione durante la transizione.
- **DEFINITION OF DONE**: un solo componente Voice, zero duplicazione di polling per la stessa lista chiamate.

### Fase 5 — Dismissione "Conversazioni" legacy
- **OBJECTIVE**: ritirare il tab legacy solo dopo parità P0 raggiunta (Sez. 12).
- **CAPABILITIES**: nessuna nuova; rimozione di codice.
- **ARCHITECTURAL WORK**: portare in Omnia Console tutte le righe P0 della matrice ancora mancanti (inbox completa, ricerca/filtri, owner/assegnazione, handoff, chiusura, riconciliazione paziente, WhatsApp/Telegram/Web Chat all'interno del nuovo workspace).
- **FILES/COMPONENTS**: `app.js` (rimozione progressiva), `omnia-console.html` (estensione).
- **DEPENDENCIES**: Fasi 1-4.
- **RISKS**: alto se fatto prima di aver raggiunto davvero la parità — rischio di perdere funzionalità operative critiche in produzione sanitaria.
- **TEST STRATEGY**: periodo di doppio-binario (entrambe le UI attive) con metriche di utilizzo prima dello spegnimento definitivo.
- **DEFINITION OF DONE**: tab "Conversazioni" rimosso da `index.html`, `RELEASE_x.md` che dichiara la dismissione.

---

## 18. Recommended First Evolution

**OBJECTIVE**: Eliminare la duplicazione del contesto paziente per l'operatore (Sez. 14 punto 2), unificando `/api/patients/{id}/overview` e `/api/omnichannel/patients/{id}/operator-context` in un unico servizio, senza cambiare visibilmente l'esperienza in nessuna delle due UI che lo consumano oggi.

Scelta come prima evolutiva perché: isolata (tocca un solo concetto di dominio), verificabile (le due risposte attuali sono confrontabili campo per campo), reversibile (si può mantenere il vecchio endpoint come alias finché non si è sicuri), e coerente con la Fase 6/Sez. 16 — è esattamente il prerequisito per poter davvero unificare "Patient Context" e "Patient 360" nel target architecture.

- **CURRENT STATE**: due endpoint, due query engine (ORM vs raw SQL con `inspect`), due forme di risposta, consumati rispettivamente da `app.js` e `omnia-console.html`.
- **DESIRED STATE**: un servizio `services/patient_context_service.py` con una funzione (es. `get_operator_context(db, patient_id, depth="light"|"full")`) che entrambi gli endpoint richiamano; le due route restano per compatibilità URL ma delegano alla stessa logica.
- **USER WORKFLOW**: invariato per l'operatore in entrambe le UI — nessuna modifica visibile attesa se l'implementazione preserva i contratti di risposta esistenti.
- **BACKEND CHANGES**: nuovo servizio; `patient_routes.py` e `omnichannel_routes.py` diventano thin wrapper che chiamano il servizio e adattano il formato di output al proprio contratto storico.
- **FRONTEND CHANGES**: nessuna, se i contratti di risposta restano identici bit-per-bit durante la migrazione.
- **DATABASE CHANGES**: nessuna.
- **INTEGRATION CHANGES**: nessuna.
- **FILES LIKELY INVOLVED**: `backend/app/api/patient_routes.py`, `backend/app/api/omnichannel_routes.py`, nuovo `backend/app/services/patient_context_service.py`.
- **ACCEPTANCE CRITERIA**: per un campione di pazienti in DEV, risposta di `/overview` e di `/operator-context` prima e dopo la modifica identica (a parità di dati); nessuna regressione visibile in `app.js` né in `omnia-console.html`.
- **TEST PLAN**: test automatico di confronto risposta pre/post su almeno 10 pazienti con storicità diversa (con e senza prenotazioni, con e senza documenti); test manuale di apertura scheda paziente in entrambe le UI.
- **RISKS**: la versione raw-SQL è difensiva su tabelle mancanti (`sa_inspect`) — se il nuovo servizio unificato non replica questa difensività, `omnia-console.html` potrebbe rompersi in ambienti con schema non completamente aggiornato.
- **ROLLBACK**: mantenere temporaneamente il codice originale di entrambi gli endpoint commentato/tenuto a fianco per un rilascio, oppure feature flag per instradare al vecchio percorso in caso di regressione.

---

## 19. Open Questions

1. `/api/voice-v2` (`voice_upgrade_routes.py`) è realmente in uso da un agente LiveKit esterno in produzione, o è un tentativo di evoluzione mai completato/mai collegato? Non risulta in nessun `RELEASE_*.md` né negli script di esempio in `examples/`.
2. Qual è il piano reale per `docker-compose.yml`: quello incluso sembra un ambiente di sviluppo (`DEV_ROLE_LOGIN_ENABLED: "true"` esplicito, `labels: cup.release: "1.0.27"` disallineato da `APP_VERSION: 1.1.1`) — esiste un compose/override separato per PROD? Non incluso nello snapshot.
3. Il salto di versione 1.0.30 → 1.1.1: è un errore di etichettatura, o rappresenta lavoro reale (Omnia Console V1-V16 + tutte le route admin non documentate) che semplicemente non ha mai ricevuto una nota di rilascio?
4. `omnia-console.html` è pensata per restare per sempre un iframe, o l'assenza di una route/URL diretta è solo un effetto collaterale non intenzionale dello sviluppo incrementale?
5. Chi/cosa consuma oggi `training_routes.py` (apprendimento supervisionato dagli esempi operatore, v1.0.23)? Non risulta referenziato né da Console né da Voice né, a una prima verifica, dalla shell legacy in modo diretto.

---

## 20. Repository Evidence

Riferimenti concreti citati in questo report:

- `main.py`: composition root, 30+ `include_router`, blocco `ALTER TABLE IF NOT EXISTS`, 5 worker `asyncio.create_task`, `CORSMiddleware(allow_origins=["*"], allow_credentials=True)`
- `backend/app/config.py:5` — `APP_VERSION: str = "1.1.1"`
- `backend/app/api/voice_routes.py` — router `/api/voice`, endpoint `/status`, `/transcript`, `/message`, `/analyze`; usa `voice_nlu_service`
- `backend/app/api/voice_upgrade_routes.py` — router `/api/voice-v2`, `HANDOFF_PATTERNS`/`BOOKING_PATTERNS`/`RESCHEDULE_PATTERNS`/`CANCEL_PATTERNS` proprie (righe 36-63), endpoint `/event`, `/conversations`
- `backend/app/services/voice_nlu_service.py` — `ALLOWED_INTENTS`, `_llm_analyze`, `_fallback_analyze`, `analyze`, `apply_policy`
- `backend/app/api/patient_routes.py:1182-1341` — blocco `# OMNIA_PATIENT_360_V1`, endpoint `GET /{patient_id}/overview`
- `backend/app/api/omnichannel_routes.py:1455` — endpoint `GET /patients/{patient_id}/operator-context`, uso di `sqlalchemy.inspect`
- `backend/app/api/livekit_routes.py` — 19 righe, `from livekit import api as livekit_api`, dipendenza in `requirements-livekit.txt` (non in `requirements.txt`, non installata nel `Dockerfile`)
- `docker-compose.yml` — servizi `asterisk` (profilo `telephony`, immagine `andrius/asterisk`), `livekit` (profilo `realtime`), `omnia-stt` (monta `/var/spool/mikopbx/...`), `frontend` (`nginx:alpine`)
- `frontend/index.html` — `<title>Omnia Flow v1.1.1 - Operatore</title>`, tab "Conversazioni" (`data-tab="chatbot"`) e "Omnia Voice" (`data-tab="voice-conversations"`), commento `<!-- OMNIA_VOICE_MENU_UNIFIED_V1 -->`
- `frontend/js/app.js` — righe ~18805-19272, iframe `omnia-console-workspace-v4` verso `/omnia-console.html?embedded=1&native=1`
- `frontend/omnia-console.html` — banner `console.info("[OMNIA CONSOLE] ... attiva")` alle righe 2777 (V4), 3283 (V6), 3800 (V7), 4079 (V8), 4956 (V10), 5525 (V11), 6388 (V13), 7402 (V15 "Interaction Workspace"), 8321 (V16 "Interaction Completion"); riga 5189 chiama `/omnichannel/patients/{id}/operator-context`
- `frontend/voice-conversations.html:984` — unica chiamata trovata: `/api/voice-v2/conversations`
- `README.md` — changelog fino a `RELEASE_1.0.30.md`; credenziali demo esplicite; disclaimer su firma non qualificata e limiti gestione documenti sanitari
- `AGENTS.md`, `CLOUD_AGENT_INSTRUCTIONS.md`, `PROJECT_SNAPSHOT.md` — regole operative e stato dichiarato del repository (letti integralmente prima dell'analisi del codice, come richiesto)

---

*Fine report. In attesa di approvazione prima di qualsiasi ulteriore analisi o implementazione, come richiesto.*
