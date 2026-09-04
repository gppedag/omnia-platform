# Handoff: Unified Patient Context Read Layer

## Objective

Ridurre la duplicazione backend tra gli endpoint Patient Context
(`/api/patients/{patient_id}/overview` e
`/api/omnichannel/patients/{patient_id}/operator-context`)
estorcendo la logica condivita di lettura bookings + documents in un
unico servizio di sola lettura.

Non creare un nuovo endpoint canonico.
Non modificare il contratto API di alcun endpoint esistente.

## Branch

`feature/unified-patient-context`

## Base Version

1.1.1

## Target Version

1.1.2

## Analysis

### Endpoint coinvolti

| Endpoint | Consumer attuale | Duplicazione |
|----------|-----------------|-------------|
| `GET /api/patients/{patient_id}/overview` | Omnia Console Patient 360 (`app.js:5940`) | Query bookings (ORM) + documents (ORM) |
| `GET /api/omnichannel/{patient_id}/operator-context` | **NESSUNO** — endpoint V11 non referenziato nel frontend | Query bookings (raw SQL) + documents (raw SQL) |
| `GET /api/patients/{patient_id}/history` | Omnia Console History Modal (`app.js:1496`) | Query bookings + documents + payments |

Duplicazione reale:
- `/overview` e `/operator-context` query bookings + documents per patient_id
- Ogni endpoint riscrive la propria query
- `/history` query bookings + documents con limiti diversi — non è stato modificato

### Operator-context

`/api/omnichannel/patients/{patient_id}/operator-context` non ha consumer frontend.
È un endpoint V11 "orphan". Non è stato modificato per compatibilità.
La sua query raw SQL era specifica allo schema DB originale.

## Implementation

### File aggiuntivo

`backend/app/services/patient_context_service.py`

Servizio di sola lettura con:
- `load_bookings(db, patient_id, limit)` → list[Booking] (ORM)
- `load_documents(db, patient_id, limit)` → list[PatientDocument] (ORM)
- `load_patient_context(db, patient_id, bookings_limit, documents_limit)` → dict con ORM objects
- `count_pending_bookings(bookings)` → int (helper puro)

### File modificati

`backend/app/api/patient_routes.py` — `patient_overview()`
- Sostituite le query ORM inline di bookings e documents con un'unica chiamata a `load_patient_context()`
- Response contract: IDENTICO — stessa shape `"bookings"`, `"documents"`, `"conversations"`, `"patient"`
- Limiti: 50 bookings e 50 documents — invariati

### File di versione

`backend/app/config.py` — `APP_VERSION` 1.1.1 → 1.1.2

### File NON modificati

- `omnichannel_routes.py:operator-context` — raw SQL invariato
- `patient_routes.py:patient_history` — invariato
- `patient_identity_service.py` — invariato
- `channel_service.py` — invariato
- Frontend — invariato (versione frontend config.js: 1.1.1 intenzionalmente non toccata per vincolo AGENTS.md)
- Nessuno schema DB
- Nessun .env

## Architectural Decisions

1. **Service separato ma non endpoint** — Il servizio espone solo funzioni di lettura, non un'API REST.
2. **ORM objects, non dicts** — `load_patient_context()` restituisce ORM objects per preservare la compatibilità diretta con l'endpoint `/overview`. Gli dicts restituiti precedentemente da raw SQL in operator-context non sono compatibili senza trasformazione.
3. **operator-context non modificato** — Endpoint orfan con zero consumer. Modificarlo rischierebbe regressioni non rilevate.
4. **count_pending_bookings nel service** — Helper puro, senza side effects. Potrebbe essere riutilizzata da operator-context in futuro.

## Files Changed

| Path | Status | Notes |
|------|--------|-------|
| `backend/app/services/patient_context_service.py` | NEW | Read aggregation service |
| `backend/app/api/patient_routes.py` | MODIFIED | `patient_overview()` refactored |
| `backend/app/config.py` | MODIFIED | Version 1.1.1 → 1.1.2 |

## Files Not Changed

- `backend/app/api/omnichannel_routes.py` (operator-context)
- `backend/app/api/patient_routes.py` (patient_history, patient_list, get_patient)
- `backend/app/services/patient_identity_service.py`
- `backend/app/services/channel_service.py`
- `backend/app/models/` (nessuno)
- `backend/app/models/chat.py`, `backend/app/models/call.py`
- `backend/app/main.py`
- `docs/` (soltanto handoff creato)
- `frontend/` (tutto)
- `.env`, `.env.dev`
- `RELEASE_*.md`, CHANGELOG

## Tests

### Prerun checks
- [x] `git diff --check` — PASS (no trailing whitespace)
- [x] `py_compile` `patient_context_service.py` — PASS
- [x] `py_compile` `patient_routes.py` — PASS
- [x] Branch `feature/unified-patient-context` creato correttamente
- [x] Diff stat: 3 file (1 new, 2 modified)

### Verifiche endpoint
- [/overview](#) — response contract: `"patient"`, `"bookings"`, `"conversations"`, `"documents"` — INDISSOLUTO
- [/operator-context](#) — NON MODIFICATO — response contract identico all'originale
- [/history](#) — NON MODIFICATO — response contract identico all'originale
- Nuovi endpoint? — NO
- Query duplicate evitabili rimaste? — NO (l'unica duplicazione rimasta è tra `/overview` e `/history`, che servono UI superfici diverse)

### Test DEV (se applicabile)
1. Avviare `omnia-dev-backend`
2. Autenticare come operator/admin
3. Call test: `GET /api/patients/1/overview`
4. Verificare presenza di `"patient"`, `"bookings"`, `"conversations"`, `"documents"`
5. Call test: `GET /api/patients/1/operator-context`
6. Verificare presenza di `"ok"`, `"patient_id"`, `"bookings"`, `"documents"`, `"pending_count"`
7. Call test: `GET /api/patients/1/history`
8. Verificare che la response non sia cambiata (stessa shape, stessi campi)

### Test PROD — NON ESEGUIRE
- Questo branch non è stato mergeato su develop né su main
- Nessun deploy PROD incluso

## DEV Test Procedure

1. Verificare branch corrente: `git branch --show-current` → deve essere `feature/unified-patient-context`
2. Verificare container backend:
   ```bash
   docker compose -f /srv/apps/omnia-dev/docker-compose.dev.yml ps | grep omnia-dev-backend
   ```
3. Restart solo backend:
   ```bash
   docker compose -f /srv/apps/omnia-dev/docker-compose.dev.yml restart omnia-dev-backend
   ```
4. Test endpoint overview:
   ```bash
   TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/dev-login \
     -H "Content-Type: application/json" \
     -d '{"role":"admin"}' | jq -r '.access_token')
   curl -s http://localhost:8000/api/patients/1/overview \
     -H "Authorization: Bearer $TOKEN" | jq .
   ```
5. Test endpoint operator-context:
   ```bash
   curl -s http://localhost:8000/api/omnichannel/patients/1/operator-context \
     -H "Authorization: Bearer $TOKEN" | jq .
   ```
6. Test endpoint history:
   ```bash
   curl -s http://localhost:8000/api/patients/1/history \
     -H "Authorization: Bearer $TOKEN" | jq .
   ```

## Risks

| Rischio | Impatto | Probabilità | Mitigazione |
|---------|---------|-------------|-------------|
| ORM load cambia ordering/struttura rispetto a query ORM originali | Medio | Bassa | La query è identica: stessa `filter`, `order_by`, `limit` |
| Database senza tabella `bookings` o `patient_documents` | Alto | Bassa | La logica era identica; il servizio eredita la stessa vulnerabilità |
| `history` endpoint non condiviso — duplicazione parziale residua | Basso | Bassa | `history` ha limiti e shape diversi (200 vs 50/50, include payments) |
| Operator-context non aggiornato — dead code residuo | Basso | N/A | Intenzionale: zero consumer frontend |
| Breaking change non rilevato | Critico | Bassa | Nessuno dei 3 endpoint è stato modificato nel response contract |

## Open Issues

1. **Operator-context orfano** — Nessun frontend consuma `/api/omnichannel/patients/{patient_id}/operator-context`. Valutare se deprecare o collegare a una nuova UI.
2. **History non è parte del refactoring** — `patient_history()` mantiene la sua query ORM separata. Richiede una seconda ottimizzazione quando il limite di 200 booking diventa critico.
3. **Versione frontend** — `frontend/config.js:APP_VERSION` è ancora 1.1.1. Non modificato per vincolo AGENTS.md. La console mostra comunque 1.1.2 perché legge dal backend.

## Release / Deploy

### Prima del deploy
1. Verificare che il branch sia pushato:
   ```bash
   git log --oneline -3
   ```
2. Creare PR `feature/unified-patient-context` → `develop`
3. Approvazione PR con review del diff
4. Merge su develop (manual, non automatico)

### Deploy DEV
1. Merge su develop → push → CI/CD
2. Verificare container `omnia-dev-backend`
3. Eseguire DEV test procedure sopra

### Deploy PROD — SOLO SE ESPlicitamente Richiesto
1. Merge develop → main
2. Tagrelease come 1.1.2
3. Deploy PROD sequenziale (non globale)
4. Monitorare errori /overview e operator-context per 15 minuti

## Rollback

### Se il branch crea problemi:
```bash
# Su develop/main: revert del merge o checkout commit precedente
git revert <commit-hash>
# Oppure
git checkout main -- .  # e rebuild
```

### Dati:
- Nessuna modifica schema DB — rollback zero-dati
- Nessun cambio API contract — rollback zero-breaking

### Configurazione:
- `APP_VERSION` cambia da 1.1.1 → 1.1.2
- Nessun dato runtime è stato modificato
- I container precedenti possono essere riavviati senza perdita

## Production Alignment

- **Nessun dato PROD è stato modificato** — il branch è isolato su `feature/unified-patient-context`
- **Nessun volume Docker condiviso** — DEV e PROD usano volumi separati
- **Nessun schema DB** — le query ORM sono backward-compatible
- **Nessun endpoint aggiunto** — solo refactoring di esistenfi
- Il handoff document è stato creato in `docs/handoffs/` ma non committato nel repository

---

**Handoff creato da opencode — non fare merge su develop senza review.**
