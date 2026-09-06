# CUP System / Omnia v1.1.2 — Nota di rilascio

A differenza di `RELEASE_1.1.0.md` e `RELEASE_1.1.1.md` (retroattive,
ricostruite a posteriori per documentare lavoro passato non documentato),
questa nota descrive lavoro fatto e testato contestualmente al rilascio
stesso, con analisi preventiva e verifica end-to-end per ogni singola voce.

Riferimento completo: `OMNIA_PROJECT_VALIDATION_REPORT.md` (analisi
iniziale) e `REVISIONE_COMPLESSIVA.md` (dettaglio di ogni commit, test
eseguiti, rischi, limiti dichiarati).

## Consolidamento Patient Context

Unificati i due endpoint indipendenti che leggevano dati sovrapponibili
del paziente con query e forme di risposta divergenti:
`GET /api/patients/{id}/overview` (ORM) e
`GET /api/omnichannel/patients/{id}/operator-context` (SQL grezzo).
Ora entrambi delegano a `app/services/patient_context_service.py`.
Contratto di risposta di entrambi gli endpoint verificato invariato
(confronto byte-per-byte vecchio/nuovo su dati di test).

Corretto contestualmente un bug latente: i blocchi `except` di
`operator-context` chiamavano `logger.exception()` senza che `logger`
fosse mai importato nel file (`NameError` in caso di errore di query
reale, mai attivato finora). Rimossa anche una doppia fetch di rete
(`app.js`, `load360()`/`OmniaPatient360Load` invocata due volte per
ogni apertura scheda paziente, per un wrapper ridondante).

## Omnia Console

- Raggiungibile ora da URL diretto (`/omnia-console.html`), non solo
  come iframe incorporato nella shell legacy. In accesso standalone,
  senza il bridge verso il client SIP (che resta unico, in `app.js`,
  per design — nessuna seconda registrazione SIP), un banner spiega
  chiaramente il degrado dei soli controlli telefono.
- "Apri conversazione" ora porta davvero alla conversazione selezionata
  (deep-link `?open_session=<id>`), non più a una dashboard generica.
- Storico completo dei messaggi mostrato correttamente nel pannello
  conversazione (corretto un bug per cui la funzione, già presente,
  non riconosceva la forma della risposta dell'endpoint messaggi e
  restituiva sempre lista vuota).
- L'operatore può ora prendere in carico, rispondere e chiudere una
  conversazione chat interamente da Omnia Console, senza tornare alla
  shell legacy — riusando esclusivamente endpoint già esistenti.
  Verificato che questo funziona già, senza ulteriore lavoro, anche per
  conversazioni WhatsApp e Telegram (routing per canale già gestito
  server-side), non solo Web Chat.
- Aggiunta distinzione visiva del canale (badge WhatsApp/Telegram/Web
  Chat) nell'inbox, dato già disponibile lato backend ma non mostrato.

## Omnia Voice

Rimosso un punto di ingresso duplicato in topbar verso
`/voice-conversations.html`: era incoerente con la voce equivalente in
sidebar, che rispetta il permesso `can_phone` dell'operatore mentre il
link in topbar non lo faceva. Resta un solo punto di ingresso (sidebar,
con incorporazione + apertura in nuova scheda), che copre lo stesso caso
d'uso senza l'incoerenza.

## Non incluso in questo rilascio

La vista legacy "Conversazioni" non è stata rimossa. Restano privi di
un endpoint backend dedicato — verificato esplicitamente prima di
escluderli da questo rilascio — note interne su una conversazione,
riconciliazione manuale paziente↔conversazione, e trasferimento
conversazione ad altro operatore. Introdurli richiede nuovo lavoro di
backend (per le note, verosimilmente anche di schema), fuori scope per
questo rilascio.

## Compatibilità

Nessuna modifica di schema database. Nessun nuovo endpoint backend.
Nessuna nuova variabile d'ambiente. Tutte le modifiche sono
retrocompatibili con i client/consumatori esistenti dei due endpoint
Patient Context consolidati.
