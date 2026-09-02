# CUP System v1.0.20 - Continuità di cura e UX per ruoli

## Obiettivo
La piattaforma separa nettamente tre esperienze: operatore, amministratore e paziente. Le funzionalità tecniche non devono appesantire il lavoro quotidiano.

## Operatore
La navigazione è organizzata in Operatività, Comunicazioni e Percorso paziente. Gli operatori non possono accedere al setup tecnico, modificare credenziali, configurare agende/medici/tipologie visita o rigenerare il dataset demo.

## Amministratore
`Setup piattaforma` è visibile solo agli admin e raggruppa il setup in cinque aree guidate: Esercizio, Canali paziente, Voce & AI, Percorso paziente e Calendari. Le API di settings e i CRUD di configurazione delle agende sono protetti lato backend con ruolo admin.

## Follow-up post-visita
Alla chiusura di un appuntamento come `completed` viene creato un follow-up automatico. Il paziente riceve un link sicuro e può indicare valutazione, stato percepito, commento e richiesta di ricontatto. Le risposte critiche diventano `needs_contact` e sono evidenziate all'operatore.

## Recall periodici
Ogni tipologia visita può abilitare/disabilitare il recall e definire i giorni del richiamo. Se non impostati, viene usata la policy globale. Il sistema invia il richiamo tramite i canali configurati e riconosce automaticamente una nuova prenotazione compatibile, chiudendo il recall come `booked`.

## Esperienza paziente
Sono aggiunte `followup.html` e `recall.html`: pagine mobile-first, minimali e senza funzioni amministrative.

## Demo
Il seeder aggiorna in modo idempotente i dataset delle release precedenti aggiungendo esempi di follow-up da ricontattare e recall pianificati/inviati.
