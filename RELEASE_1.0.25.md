# CUP System v1.0.25 — Patient Portal & Online Booking

Release ispirata alle funzioni pubblicamente documentate dei moderni portali sanitari, implementate in modo nativo nel CUP.

## Nuove funzioni
- Portale paziente demo (`patient-portal.html`) con sessione guest sintetica.
- Prenotazione online per prestazione con ricerca testuale.
- Regime Privato / SSN configurabile per tipologia visita.
- Tariffa privata, ticket SSN e indicazione ricetta/richiesta necessaria.
- Ricerca delle prime disponibilità reali sulle agende CUP.
- Blocco atomico dello slot per 15 minuti e richiesta in stato `pending` per conferma operatore.
- Cruscotto paziente con stato prenotazioni.
- Ritiro referti/documenti PDF demo protetti dalla sessione portale.
- Condivisione temporanea del documento con il medico tramite link + codice, validità 24 ore.
- Numeri coda e check-in con ticket e attesa stimata.
- Pagamenti: visualizzazione richieste e apertura checkout se disponibile.
- Assistenza: richiesta di ricontatto registrata nel backend.
- Collegamento dalla homepage clinica, dal chatbot e dal pannello operatore.
- Configurazione Admin delle tariffe e dell'abilitazione SSN per ogni tipologia visita.

## Sicurezza demo
L'accesso guest è consentito solo quando `DEMO_DATA_ENABLED=true` o `DEV_ROLE_LOGIN_ENABLED=true`. I documenti generati nel dataset sono sintetici e non contengono dati sanitari reali.

## Deploy
Richiede rebuild del backend per le nuove tabelle/colonne. Le migrazioni additive sono eseguite allo startup con `ADD COLUMN IF NOT EXISTS`.
