# Deploy DGX - CUP v1.0.12

La v1.0.12 è full-stack: frontend Nginx, backend FastAPI, PostgreSQL e volume
persistente per i documenti caricati dal chatbot.

## Deploy

1. Caricare lo ZIP nel Workspace.
2. Selezionare `demo-cup`.
3. Premere `Deploy`.
4. Il deployer generico valida Compose, esegue backup, build, health check e i test
   dichiarati in `deploy.conf`.

## Container core

- `cup-postgres`
- `cup-backend`
- `cup-frontend`

## Volumi persistenti

- `pg_data`: database PostgreSQL
- `cup_uploads`: allegati delle conversazioni

Non eliminare i volumi durante gli aggiornamenti.

## Verifica

```bash
curl -sS https://demo-cup.ai.basidiai.it/api/health
curl -I https://demo-cup.ai.basidiai.it/chatbot.html
```

L'health deve restituire versione `1.0.12`.
