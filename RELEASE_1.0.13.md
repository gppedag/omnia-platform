# CUP System v1.0.13 - Agende e calendari esterni

## Modulo Agende
- vista settimanale e mensile;
- filtri per medico, tipologia visita e agenda;
- gestione medici e specialita;
- tipologie visita con durata, buffer e colore;
- agende per medico, sede, timezone, granularita slot e regole settimanali;
- calcolo slot disponibili e controllo sovrapposizioni;
- prenotazioni con uno o piu medici associati;
- migrazione retrocompatibile delle prenotazioni precedenti.

## Microsoft 365 e Google Calendar
- credenziali configurabili dal tab Impostazioni;
- test connessione;
- provider calendario configurabile per singolo medico;
- sincronizzazione create/update/cancel verso Google Calendar o Microsoft Graph;
- stato sync ed external event id memorizzati sulla prenotazione.

### Google Calendar
Configurare GOOGLE_CALENDAR_CLIENT_ID, GOOGLE_CALENDAR_CLIENT_SECRET e GOOGLE_CALENDAR_REFRESH_TOKEN. Per ogni medico indicare Calendar ID (es. primary o indirizzo calendario).

### Microsoft 365
Configurare M365_TENANT_ID, M365_CLIENT_ID e M365_CLIENT_SECRET. L'app Azure deve disporre dei permessi applicativi necessari a gestire i calendari via Microsoft Graph. Per ogni medico indicare mailbox/utente e opzionalmente Calendar ID.
