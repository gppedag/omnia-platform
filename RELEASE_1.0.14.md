# CUP System 1.0.14 - Booking mode opzionale

## Setup esercizio
La gestione prenotazioni e ora selezionabile da Impostazioni > Prenotazioni esercizio:

- `internal`: Agende & Prenotazioni CUP con medici, tipologie visita, Microsoft 365 e Google Calendar.
- `external`: usa il gestionale dell'esercente. La pagina Prenotazioni mostra il gestionale nel frame CUP se consentito dal sito remoto, con fallback Apri gestionale.
- `chatbot_only`: disabilita il modulo prenotazioni; CUP viene usato per chatbot, omnicanale, Journey, documenti e Chatwoot.

## Parametri
- `BOOKING_MODE`
- `EXTERNAL_BOOKING_NAME`
- `EXTERNAL_BOOKING_URL`
- `EXTERNAL_BOOKING_EMBED_ENABLED`

Nota: un gestionale esterno puo vietare l'iframe tramite `Content-Security-Policy frame-ancestors` o `X-Frame-Options`; in quel caso usare il pulsante Apri gestionale o configurare il gestionale affinche autorizzi il dominio CUP.
