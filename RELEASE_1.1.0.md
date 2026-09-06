# CUP System / Omnia v1.1.0 — Nota di rilascio retroattiva

> **Nota metodologica**: questa nota è stata ricostruita a posteriori (Fase 2 della
> roadmap OMNIA, `OMNIA_PROJECT_VALIDATION_REPORT.md`) leggendo il codice reale,
> non da un changelog originale — non esisteva alcuna nota tra `RELEASE_1.0.30.md`
> e la versione applicativa dichiarata `1.1.1`. Il confine esatto tra "cosa è
> arrivato in 1.1.0" e "cosa è arrivato in 1.1.1" **non è determinabile con
> certezza dallo snapshot** (nessuna cronologia Git inclusa): quanto segue è la
> miglior ricostruzione possibile in base a marcatori di versione trovati nel
> codice stesso (banner V1-V16, commenti `_V1`/`_V11` nei blocchi backend).
> Dove il confine è incerto è segnalato esplicitamente.

## Architettura — nuovo layer "Omnia Console"

Introdotto `frontend/omnia-console.html`, incorporato come iframe dentro la shell
operatore esistente (`index.html`/`app.js`) tramite un pannello dedicato
(`omnia-console-workspace-v4`). Non sostituisce la shell: si apre sopra di essa
durante un'interazione telefonica.

Il file marca la propria evoluzione interna con banner in console, dal più
vecchio al più recente reperibile nello snapshot:

- **V4** — Phone Controls
- **V6** — Active Session
- **V7** — Live Call UX
- **V8** — Authoritative Phone
- **V10** — Timeline Context
- **V11** — Patient Context (introduce `GET /api/omnichannel/patients/{id}/operator-context`)

(V5 e V9 non hanno un banner proprio nello snapshot: **NOT VERIFIABLE FROM SNAPSHOT**
se siano stati rimossi in refactor successivi o se semplicemente non loggavano.)

## Nuove aree amministrative

Introdotte pagine e API dedicate per la gestione anagrafica clinica, separate
dalla shell operatore principale:

- `admin-catalog.html` + `/api/admin/catalog/*` — CRUD medici e tipologie di
  visita (ORM).
- `admin-settings.html` + `/api/admin/settings/*` — CRUD medici e tipologie di
  visita (SQL diretto). **Attenzione**: gestisce le stesse tabelle
  (`doctors`, `visit_types`) di `admin-catalog.html` con logica indipendente —
  non è stato possibile determinare dallo snapshot se una delle due pagine sia
  quella dismessa a favore dell'altra o se entrambe siano correnti. Segnalato
  come voce di debito tecnico nel report di validazione (Sezione 14).
- `admin-agenda-visits.html` + `/api/admin/agenda-visits` — matrice di
  abbinamento agende ↔ tipologie di visita.

## Riconciliazione paziente per canale voce

- `GET/POST /api/patient-identity/resolve` — risoluzione paziente per
  telefono/nome/codice fiscale, con normalizzazione numero e codice fiscale.
  Usato dal flusso "ricerca paziente" della vista telefonica in `app.js`
  (`[OMNIA PHONE] ricerca paziente`).
- `patient_relationship_routes.py` — gestione contatti/delegati del paziente
  (`GET/POST/PATCH /api/patients/{id}/relationships`).

## Note

Nessuna modifica di schema DB documentata separatamente da questa nota: le
colonne necessarie a queste funzionalità risultano già coperte dal blocco
`ALTER TABLE IF NOT EXISTS` presente in `main.py` fin da versioni precedenti,
oppure da tabelle create via `Base.metadata.create_all` per i nuovi modelli.
