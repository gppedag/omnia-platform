# CUP System v1.0.23.2 - Demo login hardening

Hotfix autenticazione demo:
- rimosso Passlib dal percorso password; uso diretto di bcrypt 4.0.1;
- provisioning/riallineamento account demo durante la chiamata POST /api/auth/login;
- account demo indipendenti da seed e ordine di startup;
- endpoint diagnostico pubblico GET /api/auth/demo-status (non espone password/hash);
- mantiene admin@demo.cup / AdminDemo123! e operatore@demo.cup / OperatorDemo123!.
