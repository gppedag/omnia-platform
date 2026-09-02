# CUP System v1.0.28 - Voice NLU, sentiment e conversational guardrails

## Obiettivo
La voce usa l'LLM come strato di comprensione, non come motore transazionale. Disponibilita, prezzi, slot, prenotazioni, cancellazioni e modifiche continuano a essere eseguiti dai servizi CUP deterministici.

## Nuovo endpoint voice AI
`POST /api/voice/analyze` protetto da `X-Voice-AI-Token`.

Input principale: testo STT, `call_id`, `session_id`, numero chiamante e conteggio dei fallimenti di comprensione.

Output strutturato:
- intent CUP ammesso;
- entita rilevate;
- sentiment operativo;
- confidence 0..1;
- `next_action` deterministico;
- eventuale risposta di chiarimento/redirect;
- richiesta handoff quando necessaria.

## Guardrail di dominio
Intent ammessi: prenotazione, conferma, modifica/disdetta, disponibilita/prezzo, informazioni struttura, documenti, verifica appuntamento, operatore, check-in/sala, pagamenti/documenti. Le richieste fuori dominio vengono riportate al CUP senza conversazione libera.

## Confidence e handoff
- soglia predefinita 0.62;
- sotto soglia: domanda di chiarimento;
- dopo 2 fallimenti: handoff;
- richiesta esplicita operatore: handoff;
- sentiment `critical`: handoff automatico se abilitato.

## Sentiment
Categorie: positive, neutral, confused, frustrated, critical. E' un indicatore di customer care e instradamento, non una valutazione clinica, psicologica o diagnostica.

## Storico chiamate
Le chiamate possono memorizzare `ai_intent`, `ai_sentiment`, `ai_confidence` e un breve riepilogo. La console mostra intent, sentiment e confidence.

## Configurazione
La funzionalita voice NLU e' abilitata di default. Per usare realmente un LLM occorre configurare `LLM_BASE_URL` e `LLM_MODEL`; in assenza di provider il servizio usa un fallback ristretto a regole, senza bloccare la telefonia.

`VOICE_AI_SERVICE_TOKEN` puo essere dedicato; se vuoto, l'endpoint accetta il `HANDOFF_SERVICE_TOKEN` gia configurato.
