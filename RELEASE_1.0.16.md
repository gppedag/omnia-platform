# CUP System 1.0.16 - Promemoria appuntamenti

## Workflow

1. Alla creazione di una prenotazione confermata il sistema genera, se abilitato, una conferma immediata.
2. Per ogni offset configurato in `REMINDER_OFFSETS_HOURS` vengono create righe persistenti per ciascun canale.
3. Il worker controlla la coda ogni `REMINDER_POLL_SECONDS` e invia i reminder scaduti.
4. Se l'invio fallisce, viene riprovato dopo `REMINDER_RETRY_MINUTES` fino a `REMINDER_MAX_ATTEMPTS`.
5. Il link firmato apre `/reminder.html` e consente al paziente di confermare o annullare.
6. L'annullamento invalida i reminder futuri e prova a cancellare anche l'evento Google/Microsoft 365.
7. Se l'appuntamento viene riprogrammato, i reminder non ancora inviati vengono ricostruiti sui nuovi orari.

## Canali

- SMS: usa il gateway configurato in `SMS_GATEWAY_*`.
- WhatsApp: usa WhatsApp Business Cloud API.
- Email: usa SMTP (`SMTP_*`).
- Telegram: usa il Bot configurato e richiede `reminder_telegram_chat_id` sul paziente.

## Sicurezza

Il link di conferma/annullamento contiene un JWT con purpose dedicato e scadenza configurabile. Non espone dati sanitari nel token.
