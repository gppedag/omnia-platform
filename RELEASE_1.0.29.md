# CUP System v1.0.29 — Booking redirect + multichannel test

- Il chatbot non esegue più nuove prenotazioni: riconosce l’intento e indirizza alla funzione Prenota del Portale Paziente.
- Le vecchie sessioni chatbot rimaste negli step di prenotazione vengono riportate al dialogo informativo.
- Telegram/WhatsApp applicano la stessa regola e inviano il link assoluto quando CUP_PUBLIC_BASE_URL è configurato.
- Rimossi i conflitti di route webhook legacy Telegram/WhatsApp/Facebook: i webhook omnicanale sono ora quelli canonici.
- Aggiunto pannello Admin “Test comunicazioni paziente” con invio Telegram reale e originate telefonico Asterisk opzionale.
- Aggiunto PATIENT_BOOKING_PATH e configurazione del contesto/chiamata test Asterisk.
- LLM generale ulteriormente vincolato al dominio CUP; non decide prenotazioni, slot o prezzi.
