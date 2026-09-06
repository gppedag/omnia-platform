# Omnia Development Rules

## Repository and Branching
- GitHub gppedag/omnia-platform è source of truth
- main = produzione/stabile
- develop = integrazione
- feature/* = evolutive
- fix/* = bugfix
- mai sviluppare direttamente su main
- nuovi branch normalmente da develop

## Environments
- DEV: /srv/apps/omnia-dev
- PROD: /srv/apps/demo-cup
- NON modificare PROD durante sviluppo
- DEV e PROD devono mantenere database, runtime data e configurazioni distinti
- non riusare volumi PostgreSQL o upload PROD nel DEV
- non assumere che tutti i container appartengano allo stesso docker-compose

## Read Before Write
Prima di ogni modifica:
1. ispeziona implementazione esistente
2. cerca funzioni/componenti duplicati
3. cerca timer/setInterval/setTimeout correlati
4. verifica API/backend/database coinvolti
5. verifica eventuali versioni V1/V2/V3...
6. verifica git status e branch
7. se la specifica non corrisponde al codice reale, fermati e segnala la discrepanza

## Workflow
1. analisi
2. branch da develop
3. implementazione
4. test
5. diff review
6. commit
7. push
8. test DEV
9. controlled release
10. deploy PROD solo se esplicitamente richiesto
- Production deployment is allowed only when explicitly requested by the user

## Safety
- NEVER docker compose down -v
- NEVER delete Docker volumes
- NEVER modify production .env
- NEVER commit secrets/password/token/private keys/runtime data
- evitare restart globali
- ricreare solo i container necessari
- nessun deploy automatico PROD
- nessuna modifica DB PROD durante sviluppo
- nessuna operazione distruttiva senza richiesta esplicita

## Architecture
L'architettura corrente comprende:
- FastAPI backend
- PostgreSQL
- frontend static HTML/JS su Nginx
- Omnia Console
- Omnia Voice
- Asterisk/MikoPBX
- LiveKit
- Chatwoot
- omnichannel: SMS/WhatsApp/Telegram/Web
- document exchange
- STT/TTS/LLM dove presenti

## Code Quality
- evitare patch stratificate quando è possibile consolidare
- attenzione a override/decorator multipli
- evitare polling duplicati
- evitare repaint DOM periodici inutili
- non introdurre grandi refactor durante fix urgenti
- preservare comportamento non collegato alla modifica
- preferire configurazione/feature flags a fork cliente-specifici

## Database
- verificare il meccanismo schema esistente prima di ogni modifica
- non assumere migrations/Alembic se non presenti
- non modificare schema PROD durante sviluppo
- qualsiasi modifica schema deve avere una strategia di upgrade e rollback

## Integrations
Prima di modificare integrazioni:
- verificare endpoint/config reali
- distinguere DEV da PROD
- non riutilizzare credenziali/recipient/account PROD senza richiesta
- testare Asterisk/MikoPBX, LiveKit, Chatwoot, WhatsApp in DEV quando possibile

## Mandatory Checks
Prima di commit, quando applicabili:
- git diff --check
- syntax checks
- test esistenti
- git diff --stat
- secret scan ragionevole
- verifica working tree
- Frontend JavaScript:
  node --check frontend/js/app.js
- Backend Python:
  eseguire compile/syntax check sui file Python modificati
- Docker:
  validare la configurazione Compose prima di avviare o ricreare servizi

## Handoff Document

Per ogni feature/fix significativa:
- creare docs/handoffs/<branch-name>.md (sostituire "/" con "-")
- includere:
  Objective
  Branch
  Base Version
  Target Version
  Analysis
  Implementation
  Files Changed
  Architectural Decisions
  Tests
  DEV Test Procedure
  Risks
  Open Issues
  Release / Deploy
  Rollback
  Production Alignment
- il file deve descrivere solo ciò che è realmente stato implementato
- niente secret/runtime data
- aggiornarlo prima del commit finale

### Handoff Metadata
AGENTS VERSION
- Base Version
- Target Version
- Version references updated
- Old version references intentionally retained

HANDOFF DOCUMENT
- path
- status

PRODUCTION ALIGNMENT
- Required YES/NO
- Current PROD version/commit if known
- Candidate version/commit
- ask user whether to proceed

## Production Release Authorization

PROD rimane read-only per default.
OpenCode può modificare PROD SOLO su richiesta esplicita dell'utente.

Prima di ogni deploy PROD:
- eseguire git fetch origin
- verificare il branch corrente
- verificare working tree pulito
- verificare origin/main
- creare un tag o punto di rollback prima della release
- mostrare la release da applicare
- preferire fast-forward da origin/main
- evitare cherry-pick ad hoc salvo richiesta motivata
- mai force push su main
- mai rebase su main durante release
- mai docker compose down -v
- mai cancellare volumi
- mai modificare .env PROD salvo richiesta esplicita specifica
- mai modificare DB PROD automaticamente
- ricreare/restartare solo i servizi necessari
- verificare health/log dopo deploy
- se qualcosa non è coerente, fermarsi prima di modificare PROD

Documentare sempre:
- commit/release
- tag/rollback point
- servizi toccati
- test eseguiti
- procedure di rollback

## Task Handoff Document

Per ogni feature/fix significativa:
- creare docs/handoffs/<branch-name>.md (sostituire "/" con "-")
- includere:
  Objective
  Branch
  Base Version
  Target Version
  Analysis
  Implementation
  Files Changed
  Architectural Decisions
  Tests
  DEV Test Procedure
  Risks
  Open Issues
  Release / Deploy
  Rollback
  Production Alignment
- il file deve descrivere solo ciò che è realmente stato implementato
- niente secret/runtime data
- aggiornarlo prima del commit finale

## Application Versioning
Formato MAJOR.MINOR.PATCH.

Per ogni feature/fix o modifica funzionale significativa:
- incrementare automaticamente PATCH di 1
- esempio 1.1.1 -> 1.1.2
- un solo bump per feature/branch, non per commit
- non fare ulteriori bump per correzioni nello stesso branch
- una nuova attività deve leggere la versione corrente da develop

NON incrementare automaticamente la versione per:
- AGENTS.md
- sola documentazione
- commenti
- attività read-only
- modifiche esclusivamente infrastrutturali DEV
salvo richiesta esplicita.

## Version Source of Truth
Prima del bump cercare e mantenere coerenti, quando applicabili:
- backend/app/config.py
- frontend/config.js
- docker-compose.yml
- frontend/index.html
- frontend/chatbot.html
- .env.example
- altri riferimenti runtime/current trovati

Non modificare:
- .env runtime
- .env.dev solo per il bump
- RELEASE_*.md storici
- changelog storici

Distinguere:
application version
environment label

## Version Workflow
Per ogni nuova feature/fix:
- verificare develop aggiornato
- leggere Base Version
- calcolare Target Version = PATCH + 1
- indicarle nel piano e nel handoff
- creare branch
- implementare
- aggiornare riferimenti versione
- aggiornare docs/handoffs/<branch>.md
- cercare vecchie versioni residue
- classificare residui come:
  runtime/current
  presentation/current
  historical/documentation
- test DEV
- merge develop
- chiedere se allineare PROD

## OpenCode / ChatGPT Collaboration
- GitHub è source of truth
- OpenCode è agente operativo sul repository
- ChatGPT viene usato per design, analisi e review
- specifiche ChatGPT vanno verificate contro il codice reale
- se esiste una discrepanza, fermarsi e segnalarla
- prima di passare lavoro ad altro agente: commit + push
- prima di riprendere lavoro: fetch/pull

## Multi-Customer Direction
- codebase unica
- differenze cliente-specifiche via:
  - configuration
  - branding
  - environment
  - feature flags
  - integration configuration
- evitare fork separati per cliente