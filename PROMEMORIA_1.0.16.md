# Promemoria appuntamenti - v1.0.16

## Stati

Ogni invio e' persistito in `appointment_reminders` con stato:

- `pending`: pianificato/in retry;
- `sent`: consegnato al provider;
- `failed`: tentativi esauriti;
- `skipped`: recapito o appuntamento non utilizzabile;
- `cancelled`: invalidato da annullamento/riprogrammazione.

## Pianificazione

Gli offset sono configurati in `REMINDER_OFFSETS_HOURS`, ad esempio `48,24,2`.
Il worker gira ogni `REMINDER_POLL_SECONDS` e usa orari UTC per la coda, interpretando l'orario della prenotazione secondo la timezone dell'agenda (default `Europe/Rome`).

## Canali

- SMS: gateway `SMS_GATEWAY_*`.
- WhatsApp: WhatsApp Business Cloud API.
- Email: SMTP `SMTP_*`.
- Telegram: Bot API, se sul paziente e' impostato `reminder_telegram_chat_id`.

I canali globali si impostano con `REMINDER_CHANNELS`. Il paziente puo' avere un override tramite `reminder_channels` e puo' essere escluso con `reminder_enabled=false`.

## Conferma e annullamento

Se `REMINDER_ALLOW_CONFIRM_CANCEL=true`, il messaggio contiene un link JWT firmato verso `/reminder.html`.
Il paziente puo' confermare o annullare senza login. La risposta viene salvata in `booking_reminder_responses`.
L'annullamento cancella i reminder futuri e prova a rimuovere l'evento esterno Google Calendar/Microsoft 365.

## Gestionale esterno

Il reminder engine CUP opera sulle prenotazioni presenti nel database CUP. Se `BOOKING_MODE=external`, il gestionale resta la fonte primaria; i promemoria CUP possono essere usati solo se gli appuntamenti vengono sincronizzati/importati nel CUP. Con `BOOKING_MODE=chatbot_only` non esiste un flusso appuntamento interno da ricordare.
