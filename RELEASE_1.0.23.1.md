# CUP System v1.0.23.1 - Demo login hotfix

Hotfix del bootstrap degli account demo.

Gli account di collaudo non dipendono piu' dal seed completo di pazienti/appuntamenti. Quando `DEMO_LOGIN_USERS_ENABLED=true`, ad ogni startup il backend crea o riallinea ruolo, stato, permessi e password dei due utenti:

- Admin: `admin@demo.cup` / `AdminDemo123!`
- Operatore: `operatore@demo.cup` / `OperatorDemo123!`

L'operatore e' abilitato a chat e telefono. In produzione impostare `DEMO_LOGIN_USERS_ENABLED=false`.
