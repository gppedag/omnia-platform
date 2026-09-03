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

## Handoff
A fine attività fornire:
- branch
- commit
- file modificati
- test eseguiti
- come testare in DEV
- rischi
- release/deploy instructions
- rollback

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