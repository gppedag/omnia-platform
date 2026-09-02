# CUP System v1.0.17 - UX refresh, demo data e benchmark prodotto

## UX
- Nuovo cockpit operativo in Dashboard.
- KPI con gerarchia visiva, prossimi appuntamenti e priorita operative.
- Sidebar, topbar, card, tabelle, modali, calendario e Journey rivisti con design system uniforme.
- Responsive migliorato per notebook e tablet.

## Dataset demo
La release include un seeder idempotente che genera solo record sintetici contrassegnati come demo:
- 8 pazienti;
- 3 medici e 3 agende;
- 5 tipologie visita;
- 13 appuntamenti tra completati, confermati, pending, urgenti e cancellati;
- reminder inviati, pending e falliti;
- chiamata LiveKit/Asterisk attiva con handoff operatore;
- Journey telefono -> web e conversazioni WhatsApp/Telegram.

Configurazione:
- `DEMO_DATA_ENABLED=true`
- `DEMO_AUTO_SEED=true`

API manuale (admin/operator): `POST /api/demo/seed`.

## Benchmark 2026
Analizzati pattern di Doctolib, NexHealth e Phreesia. Gap prioritari individuati:
1. waitlist automatica / riempimento cancellazioni;
2. intake digitale, consensi e moduli pre-visita;
3. self check-in;
4. recall / richiami periodici;
5. pagamenti e pre-autorizzazioni;
6. insurance eligibility ove applicabile;
7. analytics/no-show risk e capacity management;
8. referral management;
9. activity feed paziente unificata;
10. telehealth nativa e follow-up post visita.
