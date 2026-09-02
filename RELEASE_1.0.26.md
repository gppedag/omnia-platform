# CUP System v1.0.26 — Catalogo deduplicato e disponibilità estese

## Prestazioni
- Consolidamento automatico delle prestazioni duplicate per nome normalizzato all'avvio.
- Conservazione della riga meglio configurata (codice non-bootstrap, prezzi, SSN, ricetta).
- Riallineamento dei riferimenti di prenotazioni, pre-visita, recall, waitlist e associazioni agenda.
- Il portale paziente applica anche una deduplicazione difensiva del catalogo.
- La creazione Admin impedisce nuove prestazioni con lo stesso nome normalizzato.

## Prenotazione online
- Privato: ricerca standard fino a 56 giorni / 8 settimane.
- SSN: ricerca standard fino a 240 giorni / 8 mesi.
- Endpoint supporta fino a 365 giorni di orizzonte.
- Ogni slot espone regime e prezzo/ticket.
- UI mostra prezzo/ticket direttamente su ogni disponibilità e rende esplicito l'orizzonte di ricerca.
