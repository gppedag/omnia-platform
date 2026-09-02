# CUP System v1.0.22

## Operatori per canale
- Nuovi flag persistenti `can_chat` e `can_phone` sugli operatori.
- Setup operatori solo admin con creazione account, attivazione/disattivazione e scelta Chat / Telefono / Entrambi.
- La UI nasconde Conversazioni o Chiamate quando l'operatore non e' abilitato.
- Le API chat e telefonia applicano i permessi anche lato backend.
- La coda handoff filtra le richieste per canale e l'auto-answer considera solo operatori compatibili.

## Barra NethVoice
- Rimossa completamente dal frontend.
- Resta il backend Asterisk/AMI e la coda telefonica CUP.

## Pagamenti
- Nuova area operativa `Pagamenti & documenti`.
- Richiesta pagamento associabile a paziente e appuntamento.
- Invio tramite SMS, WhatsApp, email o Telegram.
- Provider: manuale, Stripe Checkout ospitato, URL provider esterno.
- Webhook Stripe firmato per aggiornamento automatico dello stato `paid`.
- Il CUP non raccoglie ne' memorizza dati carta.

## Firma documentale
- Upload PDF da parte dell'operatore e invio link sicuro al paziente.
- Pagina paziente mobile con visualizzazione PDF, firma grafica e accettazione esplicita.
- Audit trail: hash SHA-256 del PDF, hash della firma, nome firmatario, data/ora, IP e user-agent.
- Stati: pending, sent, viewed, signed, declined, expired.
- La firma interna e' una firma elettronica semplice; per casi che richiedono firma qualificata serve un provider qualificato esterno.

## Demo
- Il seed aggiunge richieste di pagamento e documenti firma demo in modo idempotente.
