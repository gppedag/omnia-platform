# CUP System 1.0.8 - Omnichannel integration

## Architecture
All channels converge on the same `ChatSession` conversation. Messages and attachments therefore remain visible when ownership moves between the LLM and a human operator.

Supported adapters in this build:
- Web chat: `/chatbot.html`
- WhatsApp Business Cloud API: `/api/omnichannel/whatsapp/webhook`
- Telegram Bot API: `/api/omnichannel/telegram/webhook`
- Asterisk AMI handoff/originate
- OpenAI-compatible LLM endpoint (OpenAI, OpenRouter, LiteLLM, etc.)

## LLM
Set in `.env`:

```env
LLM_ENABLED=true
LLM_BASE_URL=http://host.docker.internal:4000/v1
LLM_API_KEY=...
LLM_MODEL=local-general
```

The bot can emit `[[HANDOFF]]`; CUP removes the token from the visible reply and changes ownership to the operator queue. The deterministic booking flow is still available with `PRENOTAZIONE`.

## WhatsApp Business
Configure:

```env
WHATSAPP_VERIFY_TOKEN=...
WHATSAPP_API_TOKEN=...
WHATSAPP_PHONE_NUMBER_ID=...
WHATSAPP_APP_SECRET=...
```

Webhook URL:
`https://<domain>/api/omnichannel/whatsapp/webhook`

Text messages are persisted in the unified conversation. Documents/images are downloaded into the same persistent document store used by the web chat. Operator replies are sent back through the Cloud API when credentials are configured.

## Telegram
Configure:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_WEBHOOK_SECRET=...
```

Webhook URL:
`https://<domain>/api/omnichannel/telegram/webhook`

When registering the webhook with Telegram, configure the same secret token. Text and document/photo messages are associated with the same conversation and document history.

## Asterisk
Configure the real PBX AMI endpoint:

```env
ASTERISK_HANDOFF_ENABLED=true
AMI_HOST=192.168.x.x
AMI_PORT=5038
AMI_USER=cup_ami
AMI_PASSWORD=...
OPERATOR_EXTENSION=201
ASTERISK_CONTEXT=from-internal
AMI_ORIGINATE_CHANNEL=Local/{extension}@from-internal
ASTERISK_CALLER_ID=CUP AI <700>
```

When a handoff is requested the conversation status becomes `handoff`; an AMI Originate can notify/call the configured operator extension. The dashboard can also explicitly take ownership, return a conversation to the AI, or trigger a phone escalation.

The exact Originate channel/context must be adapted to the customer's Asterisk/FreePBX/NethVoice dialplan.

## Security notes
Use real secrets, HTTPS and provider webhook signature/secret validation. The included document storage is suitable for a PoC, not for production clinical documents without retention, malware scanning, access auditing, encryption and privacy controls.
