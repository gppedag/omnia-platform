# CUP System v1.0.12 - Journey operatore

La console operatore mostra ora il percorso multicanale della richiesta.

## Percorso visualizzato
- origine della richiesta e canale corrente;
- chiamata Asterisk in ingresso;
- Telegram / WhatsApp / Web;
- handoff AI -> operatore;
- SMS di continuazione;
- apertura pagina web dal link SMS;
- caricamento documenti;
- associazione e accesso diretto alla conversazione Chatwoot.

## Telefono -> SMS -> Web
Una chiamata AMI con CallerID crea/riusa una sessione `phone`. Dalla console l'operatore usa **Invia link SMS**.
Il link contiene un token firmato e a scadenza; quando il cliente lo apre, il chatbot riprende esattamente lo stesso `session_id`.

## Chatwoot
Quando esiste un binding, compare **Apri Chatwoot** con deep-link alla conversazione. Se Chatwoot e' configurato ma il binding non esiste, compare **Crea/aggiorna Chatwoot**.

## SMS gateway
Configurare `SMS_GATEWAY_URL`, `SMS_GATEWAY_TOKEN` e `SMS_SENDER`. Il gateway deve accettare POST JSON `{to, text, sender}`. Senza gateway il sistema opera in modalita mock e mostra il link generato all'operatore.
