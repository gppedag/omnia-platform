# CUP System v1.0.24.1

Base: restyle UX v1.0.24 fornito dal team.

## Modifiche
- Training voce abilitato di default (`TRAINING_CAPTURE_VOICE_ENABLED=true`).
- Il requisito di consenso resta attivo: l’IVR/voice agent deve inviare `consent_obtained=true`.
- Risposte rapide contestuali nel chatbot, incluse selezione slot, `CONFERMA APPUNTAMENTO`, cambio appuntamento e operatore.
- Dopo la conferma il chatbot chiede se il paziente deve caricare ricetta/richiesta medica.
- CTA `Carica ricetta/richiesta` apre direttamente il selettore allegati dopo aver registrato la scelta.
- Se il paziente carica direttamente un documento nella fase dedicata, il flusso viene completato automaticamente.
- Disponibilità appuntamenti continua a essere calcolata sugli slot realmente liberi e ricontrollata al momento della conferma.
