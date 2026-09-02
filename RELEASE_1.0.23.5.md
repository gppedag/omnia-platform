# CUP System v1.0.23.5 - Development auth bypass

Questa release elimina il login tradizionale dal percorso di sviluppo.

- La UI salva soltanto il ruolo scelto (`admin` o `operator`) in `localStorage`.
- Non vengono chiamati `/auth/dev-login`, PostgreSQL, bcrypt o JWT per entrare nella piattaforma.
- Ogni richiesta autenticata invia `X-Dev-Role`.
- `get_current_user()` accetta l'header soltanto se `DEV_ROLE_LOGIN_ENABLED=true` e costruisce un'identità effimera con i normali attributi di ruolo/canale.
- `require_role()` e `require_operator_channel()` continuano ad applicare i permessi lato backend.
- Logout elimina sia token eventuali sia il ruolo sviluppo.
- Upload firma e download allegati includono anch'essi l'header sviluppo.

## Produzione

Impostare obbligatoriamente `DEV_ROLE_LOGIN_ENABLED=false`: il bypass viene così disabilitato e resta disponibile il normale percorso JWT/password.
