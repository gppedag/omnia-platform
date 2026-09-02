# CUP System v1.0.23

## Credenziali demo
Create automaticamente solo quando il dataset demo e abilitato:

- Admin: `admin@demo.cup` / `AdminDemo123!`
- Operatore: `operatore@demo.cup` / `OperatorDemo123!`

L'operatore demo e abilitato sia a chat sia a telefono. In produzione impostare `DEMO_DATA_ENABLED=false` e `DEMO_AUTO_SEED=false`.

## Prenotazione chatbot a slot reali
Il paziente non inserisce piu data e ora liberamente. Dopo la scelta della prestazione il chatbot:

1. individua la tipologia visita associata;
2. seleziona le agende abilitate;
3. legge regole, eccezioni e prenotazioni non cancellate;
4. calcola gli slot liberi;
5. propone fino a 3 alternative;
6. ricontrolla lo slot al momento della conferma per evitare race condition;
7. crea direttamente la prenotazione confermata e genera reminder/pre-visita.

Se lo slot scelto viene occupato nel frattempo, il chatbot ricalcola le disponibilita invece di creare una sovrapposizione.

## Apprendimento supervisionato dagli operatori
Le risposte degli operatori alle chat diventano candidati di apprendimento in stato `pending`. Il sistema anonimizza email, telefoni e codici fiscali prima della revisione. Solo un admin puo approvare o rifiutare l'esempio.

Gli esempi `approved` vengono inseriti dinamicamente nel contesto del modello LLM come few-shot examples. Questo consente all'assistente di acquisire metodo, tono e sequenza delle domande senza un fine-tuning automatico non controllato.

## Chiamate CUP e LiveKit
La raccolta voce e disabilitata per default (`TRAINING_CAPTURE_VOICE_ENABLED=false`). Quando viene abilitata, il servizio accetta trascrizioni soltanto se:

- e presente il token server-to-server `TRAINING_SERVICE_TOKEN`;
- `consent_obtained=true`;
- se configurato, il consenso e obbligatorio (`TRAINING_REQUIRE_CONSENT=true`).

Il CUP non deve conservare l'audio per apprendere il metodo: il percorso previsto e audio LiveKit/Asterisk -> STT -> transcript -> anonimizzazione -> esempi pending -> approvazione admin.

Endpoint servizio:

- `POST /api/training/voice-samples`
- `GET /api/training/service-context?q=...`

Il secondo endpoint permette al voice agent LiveKit di recuperare istruzioni ed esempi approvati.

> LiveKit non e il modello da addestrare: e il layer realtime/agent. L'apprendimento viene applicato al modello LLM usato dal voice agent, inizialmente tramite prompt/few-shot/RAG; un eventuale fine-tuning offline puo essere aggiunto in seguito usando soltanto esempi approvati.

## Governance
L'area **Setup piattaforma -> Apprendimento AI supervisionato** e solo admin. Nessun esempio entra automaticamente in produzione senza revisione.

Per le chiamate sanitarie, registrazione/trascrizione e riuso formativo possono coinvolgere dati personali e sanitari: prima dell'attivazione in produzione vanno definite informativa, base giuridica/consenso dove necessario, retention e accessi secondo la normativa applicabile.
