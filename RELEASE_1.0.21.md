# CUP System v1.0.21 - Analytics operativi e amministrativi

## Obiettivo
Rendere misurabile l'efficacia del CUP senza complicare il lavoro quotidiano degli operatori.

## Esperienza operatore
La dashboard Oggi mostra una sola sezione compatta `Salute operativa` con quattro indicatori degli ultimi 30 giorni:
- tasso no-show;
- consegna promemoria;
- tempo medio di presa in carico handoff;
- completamento pre-visita.

Non vengono esposti grafici, configurazioni o analisi avanzate nel menu operativo.

## Esperienza admin
Nuova voce `Amministrazione > Analytics`, accessibile solo agli admin anche lato API.

Indicatori e viste:
- saturazione complessiva e per agenda;
- no-show e attendance rate;
- conversione chatbot -> prenotazione;
- tempo e tasso di accettazione handoff;
- trend giornaliero appuntamenti/completati/cancellati/no-show;
- performance promemoria;
- completamento pre-visita;
- efficienza lista d'attesa;
- conversione recall -> nuova prenotazione;
- canali e conversione per canale;
- carico operatori: handoff accettati, tempo risposta, prenotazioni create.

## API
- `GET /api/analytics/overview?days=30`: admin/operator, sintesi operativa.
- `GET /api/analytics/admin?days=30`: solo admin, dettaglio gestionale.

Intervalli supportati: 1-365 giorni. La UI propone 7, 30 e 90 giorni.

## Dataset demo
Il seeder aggiorna in modo idempotente il dataset con uno storico sintetico di 18 appuntamenti, check-in/no-show, reminder e sessioni chatbot distribuiti nelle settimane precedenti. Questo rende immediatamente visibili grafici e KPI senza duplicare le anagrafiche demo già presenti.

## Note metriche
La conversione mostrata come `Chatbot -> Prenotazione` usa il `booking_id` salvato nel contesto della sessione dal flusso guidato CUP. Non viene attribuita una prenotazione all'AI se non esiste una correlazione esplicita.

La saturazione usa i minuti disponibili definiti dalle regole agenda e le eccezioni configurate, confrontati con i minuti prenotati non cancellati.
