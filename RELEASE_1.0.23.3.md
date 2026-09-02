# Release 1.0.23.4 — Development role login

## Obiettivo
Rimuovere temporaneamente la complessità di email/password durante lo sviluppo, mantenendo intatta la separazione dei permessi.

## Accesso
La pagina principale mostra una sola selezione:

- **Admin**
- **Operatore**

Il pulsante **Entra nella piattaforma** chiama `POST /api/auth/dev-login` con il ruolo scelto. Non viene richiesta alcuna password.

Il backend crea o riallinea l'account demo corrispondente e restituisce un JWT standard. Le dipendenze `get_current_user`, `require_role` e `require_operator_channel` continuano quindi a proteggere tutte le API.

## Sicurezza / produzione
Questa modalità è intenzionalmente destinata allo sviluppo. È controllata da:

```env
DEV_ROLE_LOGIN_ENABLED=true
```

Prima di un rilascio di produzione impostare `DEV_ROLE_LOGIN_ENABLED=false` e ripristinare un meccanismo di autenticazione forte.

## Versione
`1.0.23.4`
