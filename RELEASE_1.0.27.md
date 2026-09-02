# CUP System v1.0.27 — Chat history controls + LLM clarity

## Cronologia conversazioni
- Admin: **Cancella chat** elimina la sessione selezionata, messaggi e allegati.
- Admin: **Svuota cronologia demo** elimina tutte le sessioni conversazionali dopo doppia conferma.
- Prenotazioni, pazienti e dati CUP non vengono cancellati.
- Gli allegati presenti sul volume chat vengono rimossi insieme alla sessione.
- Il chatbot pubblico recupera automaticamente da una sessione eliminata: al successivo caricamento riceve 404, rimuove l'ID locale e crea una nuova sessione.

## LLM
Il chatbot supporta un provider OpenAI-compatible tramite `LLM_ENABLED`, `LLM_BASE_URL`, `LLM_API_KEY` e `LLM_MODEL`. Nella configurazione di default `LLM_ENABLED=false`: senza configurazione esplicita il chatbot usa il flusso CUP deterministico. Quando il provider e' abilitato, le domande libere passano all'LLM, mentre prenotazione e operazioni strutturate restano governate dal backend CUP.
