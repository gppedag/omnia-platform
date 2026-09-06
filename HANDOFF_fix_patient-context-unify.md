# Handoff — fix/patient-context-unify (Fase 1 roadmap OMNIA)

## Branch
`fix/patient-context-unify` (da `develop`)

## Commit
`f273adb` — *fix(patient-context): unifica overview/operator-context, rimuove doppia fetch load360*
(baseline snapshot: `efa02cf`)

## File modificati
- `backend/app/services/patient_context_service.py` — **nuovo file**. Contiene l'unica logica di lettura condivisa (`get_operator_full_overview`, `get_operator_light_context`) usata da entrambi gli endpoint.
- `backend/app/api/patient_routes.py` — `patient_overview()` ridotto a thin wrapper del servizio. Contratto di risposta HTTP **invariato**.
- `backend/app/api/omnichannel_routes.py` — `omnia_operator_patient_context()` ridotto a thin wrapper del servizio. Contratto di risposta HTTP **invariato**. Rimosso anche l'uso di `logger` (mai importato in questo file — bug latente pre-esistente, ora corretto spostando il logging nel nuovo servizio con logger correttamente importato).
- `frontend/js/app.js` — rimosso un wrapper ridondante attorno a `window.openPatientDetail` che causava una doppia fetch di `/api/patients/{id}/overview` ad ogni apertura della scheda paziente. Nessun markup toccato.

## Test eseguiti (realmente, non solo dichiarati)
1. `python3 -m py_compile` su tutti e 3 i file Python modificati/nuovi → OK
2. `python3 ast.parse(...)` su tutti e 3 i file Python → OK
3. Import diretto dei moduli (`patient_context_service`, `patient_routes`, `omnichannel_routes`) senza errori
4. Import completo dell'app FastAPI (`from app.main import app`) → 219 route caricate correttamente, entrambe le route target presenti (`/api/patients/{patient_id}/overview`, `/api/omnichannel/patients/{patient_id}/operator-context`)
5. **Test funzionale di equivalenza su PostgreSQL 16 locale**: schema creato via `Base.metadata.create_all` + le stesse `ALTER TABLE IF NOT EXISTS` di `main.py`; seed di un paziente con 2 prenotazioni (una `pending`), una sessione chat con 2 messaggi, un documento. Confronto JSON (dump ordinato, valori normalizzati) tra l'implementazione originale (ricostruita identica dal codice pre-refactor) e la nuova via servizio: **risultato identico byte-per-byte per entrambi gli endpoint**.
6. Test del guard difensivo: tabella `patient_documents` droppata a runtime → nessun crash, `documents: []`, `pending_count` calcolato correttamente sulle bookings rimaste.
7. Test del fix del bug `logger`: forzato un errore reale di query (tabella inesistente) → il nuovo servizio logga l'eccezione e ritorna `[]` senza sollevare `NameError` (comportamento che si sarebbe verificato con il codice originale se quel path di errore fosse mai stato esercitato in produzione).
8. `git diff --check` → nessun problema di whitespace
9. `node --check frontend/js/app.js` → OK

Non eseguito (fuori scope Fase 1, richiede ambiente reale): test end-to-end nel browser delle 3 UI consumer (le due modali paziente in `app.js` + il pannello in `omnia-console.html`); verifica di rete in DevTools che dopo il fix resti una sola chiamata a `/overview` per apertura scheda.

## Come testare in DEV
1. Applicare la patch allegata (`0001-fix-patient-context-unify.patch`) su un checkout pulito di `develop` in `/srv/apps/omnia-dev`, oppure sostituire i 4 file con le versioni allegate.
2. Rebuild del container backend (`docker compose build backend && docker compose up -d backend`) — nessuna migrazione DB necessaria.
3. Aprire la scheda paziente da entrambe le modali in `index.html`/`app.js` e verificare che i dati (prenotazioni, conversazioni, documenti) siano identici a prima.
4. Aprire Omnia Console durante una chiamata attiva e verificare che il pannello "Contesto paziente" (prossima prenotazione, documenti recenti, badge pending) funzioni come prima.
5. In DevTools → Network, verificare che l'apertura della scheda paziente generi **una sola** richiesta a `/api/patients/{id}/overview` (prima erano due).

## Rischi
- Il guard difensivo su tabelle mancanti è stato preservato e testato, ma solo in un ambiente di test pulito; non replica ogni possibile stato di schema parzialmente migrato in DEV/PROD reale.
- La rimozione del wrapper in `app.js` è stata validata staticamente (script non deferred/async → nessun problema di ordine di esecuzione) ma non ancora in un browser reale.

## Release / deploy
- Nessuna modifica di schema DB, nessuna variabile d'ambiente nuova.
- Versione proposta: `1.1.2` (patch, da confermare — non applicata automaticamente a `config.py`/`docker-compose.yml` in questo commit, in attesa di approvazione esplicita come da `CLOUD_AGENT_INSTRUCTIONS.md`).
- Deploy PROD: **non eseguito e non richiesto** in questa fase, come da regola "deploy PROD solo se esplicitamente richiesto".

## Rollback
`git revert f273adb` sul branch, oppure ripristino diretto dei 4 file dalle rispettive versioni in `efa02cf` (baseline).
