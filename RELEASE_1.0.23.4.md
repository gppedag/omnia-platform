# CUP System v1.0.23.4 - Login runtime fix

Hotfix di sviluppo per il login a selezione ruolo.

## Causa reale individuata
Il frontend inizializzava `booking-modal`, `doctor-modal`, `visit-type-modal` e `agenda-modal` all'avvio, ma i relativi elementi HTML erano stati persi durante una precedente riorganizzazione della UI. Bootstrap generava un'eccezione JavaScript prima che il listener del form di login venisse registrato. Per questo non funzionavano ne il login password ne la droplist.

## Correzioni
- Ripristinati i modali Prenotazione, Medico, Tipologia visita, Agenda e Lista d'attesa.
- Inizializzazione modali resa null-safe.
- Aggiunto fallback minimale se Bootstrap JS CDN non e disponibile.
- Il login sviluppo verifica `/api/health` e segnala chiaramente un mismatch di versione frontend/backend.
- `docker-compose.yml` include `cup.release=1.0.23.4` su backend e frontend per forzare la ricreazione dei container negli aggiornamenti dello stack.
- Il backend riceve esplicitamente `APP_VERSION=1.0.23.4` e `DEV_ROLE_LOGIN_ENABLED=true` durante questa fase di sviluppo.

## Login sviluppo
La UI richiede soltanto la scelta tra `Admin` e `Operatore`. Il backend emette comunque un JWT reale e mantiene i controlli di ruolo/canale sulle API.

## Deploy
Per aggiornamenti manuali e consigliato eseguire una volta:

    docker compose up -d --build --force-recreate backend frontend

Dalle release successive il label `cup.release` consente a un normale aggiornamento dello stack di rilevare il cambio configurazione.
