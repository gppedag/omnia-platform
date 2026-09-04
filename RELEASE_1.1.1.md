# CUP System / Omnia v1.1.1 — Nota di rilascio retroattiva

> Vedi premessa metodologica in `RELEASE_1.1.0.md`: nota ricostruita a
> posteriori (Fase 2 roadmap OMNIA) leggendo il codice reale, confine con
> 1.1.0 non determinabile con certezza assoluta dallo snapshot.

## Omnia Voice — vista dedicata

- Nuova pagina standalone `frontend/voice-conversations.html`, raggiungibile
  sia da link diretto in navigazione sia come tab interno alla shell
  operatore (`data-tab="voice-conversations"`).
- Nuovo router backend `voice_upgrade_routes.py` (`/api/voice-v2`):
  `POST /event` (registra un turno di conversazione vocale e lo analizza),
  `GET /conversations` (lista conversazioni voce, consumata da
  `voice-conversations.html`).

**Nota di correzione rispetto a una prima ricostruzione**: `/api/voice-v2`
**non** è un motore NLU indipendente da quello esistente. La funzione
`deterministic_analysis()` chiama `voice_nlu_service.analyze()` (lo stesso
servizio già usato da `/api/voice/analyze`, introdotto in precedenza — v.
`RELEASE_1.0.29.md`) e ne usa il risultato come base, sovrapponendo poi
un set di pattern regex proprie (rilevamento richiesta operatore, intento di
prenotazione/spostamento/annullamento, sentiment positivo/negativo) come
override quando il testo contiene un match esplicito. L'output è
esplicitamente marcato nel codice con `"decision_source": "deterministic+hybrid"`.
In pratica: `/api/voice-v2/event` **estende** `voice_nlu_service`, non lo
duplica — ma la relazione tra i due non era documentata da nessuna parte
prima di questa nota, ed è comunque un secondo punto in cui la logica di
rilevamento intento può cambiare comportamento.

## Omnia Console — consolidamento finale (V13–V16)

Ultime iterazioni rilevabili nei banner di log di `omnia-console.html`:

- **V13** — UI Consolidation
- **V15** — Interaction Workspace (introduce lo scambio documenti in tempo
  reale durante la chiamata, `OMNIA_EXCHANGE_TIMER`)
- **V16** — Interaction Completion

(V12 e V14 non hanno banner propri nello snapshot: **NOT VERIFIABLE FROM
SNAPSHOT** il motivo.)

## Riallocazione appuntamenti

Nuovo sottosistema `reallocation_routes.py` + `reallocation_service.py` per
la gestione di interruzioni di servizio (es. assenza medico) e la
riallocazione automatica/assistita degli appuntamenti impattati:
creazione "incidente" su un'agenda, generazione casi di riallocazione,
proposta automatica di primo slot compatibile, notifica al paziente
(anche self-service via link pubblico `/api/reallocation/public/{token}`),
conferma/annullamento da parte dell'operatore.

Non risulta consumato né da Omnia Console né da Omnia Voice: è un
sottosistema amministrativo/operativo a sé, non ancora referenziato dalla
matrice di parità Legacy↔Console (v. Sezione 12 del report di validazione).

## Eligibilità agenda/tipologia visita

Nuovo endpoint `GET /api/calendar-eligibility` — dato un medico o una
tipologia di visita, restituisce le combinazioni compatibili e le agende
attive corrispondenti. Non risultano frontend consumer nello snapshot:
**NOT VERIFIABLE FROM SNAPSHOT** se sia già in uso da un client non incluso
o se sia stato predisposto per uno sviluppo non ancora agganciato in UI.
