# CUP System v1.0.18 - Pazienti, Chatwoot nelle Impostazioni e lista d'attesa automatica

## Correzioni
- Rimossa la voce Chatwoot dalla sidebar: configurazione, stato, test, webhook e accesso console sono ora nella card Chatwoot di Impostazioni.
- Resa più robusta l'API Pazienti: compatibilità con email legacy e riparazione automatica di seed demo parziali.
- Il dataset demo include pazienti, tre voci di lista d'attesa e una proposta dimostrativa aperta.

## Lista d'attesa automatica
- Nuovo menu Lista d'attesa con KPI, filtri/preferenze, priorità e stato.
- Preferenze per tipologia visita, agenda, medico, intervallo date e fascia oraria.
- Quando un appuntamento viene cancellato da operatore o paziente, il motore cerca automaticamente i candidati compatibili.
- Invio della proposta su SMS, WhatsApp, email o Telegram usando i recapiti/preferenze esistenti.
- Proposta configurabile con TTL e numero massimo di candidati.
- Pagina pubblica `waitlist.html` con conferma one-click.
- Lock transazionale: lo slot viene assegnato al primo che accetta; tutte le altre proposte decadono.
- Alla conferma viene creata la nuova prenotazione e vengono programmati i normali promemoria appuntamento.

## Parametri
- WAITLIST_ENABLED
- WAITLIST_OFFER_TTL_MINUTES
- WAITLIST_MAX_CANDIDATES
