# CUP System v1.0.19 - Pre-visita digitale e check-in

Questa release implementa la seconda priorita della roadmap dopo la lista d attesa automatica.

## Workflow
1. La prenotazione crea automaticamente una pratica pre-visita coerente con la tipologia di visita.
2. I promemoria contengono il link sicuro alla pre-visita.
3. Il paziente compila questionario e consenso; l esito viene tracciato sulla prenotazione.
4. In prossimita dell appuntamento viene reso disponibile il check-in digitale.
5. L operatore gestisce la coda accoglienza con stati arrived/waiting/in_visit/completed/no_show.

## Dataset demo
Il seeder v1.0.19 aggiorna anche dataset creati dalle release precedenti creando submission e check-in mancanti senza duplicare le anagrafiche.
