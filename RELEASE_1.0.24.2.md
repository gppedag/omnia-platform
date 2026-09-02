# CUP System v1.0.24.2

Fix UX configurazione agende e accesso chatbot paziente.

- Inserimento rapido inline di Medico e Tipologia visita per profilo Admin.
- Errori di salvataggio mostrati direttamente nella UI e tramite toast.
- Fallback nativo per i tab di configurazione quando Bootstrap JS non e disponibile.
- Nuova voce `Chatbot paziente` nel menu operatore/admin.
- `/chatbot.html` integrato nella console tramite iframe same-origin, con apertura in nuova scheda disponibile.
- Permessi invariati: creazione/modifica medici, tipologie e agende resta Admin-only.
