# LiveKit / LLM -> Operatore umano (v1.0.15)

## Principio
La voce AI rimane proprietaria della chiamata finché un operatore non accetta esplicitamente la richiesta. L'handoff non equivale a un trasferimento immediato.

## Flusso
1. Asterisk registra la chiamata e crea/riusa il Journey telefonico.
2. LiveKit/LLM gestisce STT -> LLM -> TTS.
3. Alla richiesta umana, il voice agent chiama `POST /api/handoffs/request`.
4. CUP crea `waiting_operator`, poi `ringing` quando esistono operatori disponibili.
5. La console mostra badge, coda, segnale sonoro e notifica browser.
6. Il primo operatore che preme **Accetta** acquisisce atomicamente la richiesta.
7. Solo dopo l'accettazione CUP esegue l'Originate AMI configurato.
8. Gli altri operatori vedono scomparire la richiesta.
9. Se nessuno accetta entro `HANDOFF_TIMEOUT_SECONDS`, viene applicata `HANDOFF_TIMEOUT_ACTION`.

## API voice agent
`POST /api/handoffs/request`

Header obbligatorio se configurato (consigliato e richiesto dalla release):
`X-Handoff-Token: <HANDOFF_SERVICE_TOKEN>`

Esempio payload:
```json
{
  "call_id": 123,
  "caller_number": "+390212345678",
  "source": "livekit",
  "reason": "Il cliente chiede un operatore umano",
  "summary": "Cliente identificato. Richiede informazioni sulla prenotazione cardiologica."
}
```

Per correlare il Journey è sufficiente almeno uno tra `session_id`, `call_id`, `caller_number`.

## Modalità
- `manual`: tutti vedono la coda, acquisizione manuale.
- `ring_group`: tutti gli operatori disponibili vengono notificati; vince il primo che accetta.
- `auto_answer`: il primo operatore disponibile viene assegnato automaticamente.

## Timeout
- `callback`: genera richiesta di richiamata.
- `return_ai`: restituisce la sessione al LLM.
- `keep_waiting`: rinnova la permanenza in coda.
- `voicemail`: registra lo stato di messaggio/voicemail da gestire.

## Asterisk
La release effettua l'Originate AMI dopo l'accettazione. Il bridging finale verso il canale telefonico corrente dipende dal dialplan/NethVoice del cliente e deve usare le variabili `CUP_CONVERSATION_ID` e `CUP_CALLER` già inviate dall'Originate.
