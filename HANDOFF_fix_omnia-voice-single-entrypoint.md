# Handoff — fix/omnia-voice-single-entrypoint (Fase 4)

## Branch / Commit
`fix/omnia-voice-single-entrypoint`, commit `31c5d89`
(base: `feat/omnia-console-chat-actions` → `eb07fd3`)

## Obiettivo
Un solo percorso "Omnia Voice", come indicato dalla roadmap originale
(il commento `OMNIA_VOICE_MENU_UNIFIED_V1` nel codice segnalava un
tentativo di unificazione mai completato).

## Analisi (prima di scegliere la soluzione)
Non era solo ridondanza estetica. C'erano due punti di ingresso identici:
1. **Tab sidebar** (`#calls-nav-item`) — incorpora `voice-conversations.html`
   in iframe, con un proprio pulsante "Apri in nuova scheda". Nascosto
   automaticamente se l'operatore non ha `can_phone` (`app.js:306`).
2. **Link in topbar** — stessa destinazione, ma **senza alcun filtro**:
   sempre visibile, indipendentemente da `can_phone`.

Verificato anche lato backend: `GET /api/voice-v2/conversations` richiede
solo `require_role("operator","admin")`, non `can_phone` — quindi non era
un problema di sicurezza, ma un'incoerenza di UX tra due punti di ingresso
identici con comportamento diverso.

Ti ho proposto due opzioni (allineare il filtro sul link in topbar, oppure
rimuoverlo del tutto) e hai scelto la rimozione, dato che il tab sidebar
copre già interamente il caso d'uso.

## File modificato
`frontend/index.html` — 13 righe (10 inserite, incluso un commento
esplicativo lasciato nel markup; 3 rimosse, il link e le sue righe).

## Test eseguiti (end-to-end reali)
PostgreSQL locale, backend FastAPI reale, due operatori di test creati
appositamente (uno con `can_phone=True`, uno con `can_phone=False`),
Chromium reale via Playwright:

1. **Operatore CON can_phone**: link duplicato assente in topbar ✓; link
   Omnia Console (Slice 1, Fase 3) non toccato, ancora presente ✓; voce
   Omnia Voice visibile in sidebar ✓; zero errori JS ✓
2. **Operatore SENZA can_phone**: link duplicato assente in topbar ✓; link
   Omnia Console ancora presente ✓; voce Omnia Voice **nascosta** in
   sidebar (comportamento preesistente, confermato invariato) ✓; zero
   errori JS ✓
3. `node --check` su tutti i 7 blocchi `<script>` di `index.html` → OK
4. `git diff --check` → OK

Utenti di test rimossi al termine.

## Rischi
Nessuno individuato: il tab sidebar già offriva tutto ciò che offriva il
link rimosso (embed + apertura in nuova scheda), quindi non c'è perdita
di funzionalità per nessun profilo operatore.

## Rollback
`git revert 31c5d89`.

## Stato roadmap
Con questa modifica si chiude la Fase 4. Riepilogo di tutto il lavoro
svolto finora sulla roadmap OMNIA:
- Fase 1 — Consolidamento Patient Context: fatto
- Fase 2 — Documentazione retroattiva 1.1.0/1.1.1: fatto
- Fase 3 — Console come shell primaria:
  - Slice 1 (URL diretto): fatto
  - Slice 2a/2b/2c (deep-link, storico, azioni chat): fatto
- Fase 4 — Unificazione punto di ingresso Omnia Voice: fatto
- Fase 5 — Dismissione "Conversazioni" legacy: non iniziata, resta
  condizionata al completamento della matrice di parità P0 (Sezione 12
  del report di validazione) — WhatsApp/Telegram/Web Chat nella stessa
  UI, note interne, riconciliazione paziente, trasferimento, owner.
