# Handoff — feat/omnia-console-direct-url (Fase 3 roadmap OMNIA, Slice 1)

## Branch
`feat/omnia-console-direct-url` (da `docs/retroactive-release-notes`, che include
già Fase 1 `fix/patient-context-unify` e la documentazione retroattiva di Fase 2)

## Commit
`8a96eec` — *feat(omnia-console): rende Omnia Console raggiungibile da URL diretto*

## Obiettivo di questo slice
Solo instradamento: Omnia Console diventa raggiungibile da URL diretto
(`/omnia-console.html`), senza toccare il tab "Conversazioni" né alcun'altra
parte della shell legacy. Nessun cambio di markup/comportamento nella
modalità `?embedded=1` esistente.

## Scoperta emersa durante l'analisi (prima di scrivere codice)
`omnia-console.html` non è autonoma per i controlli telefono:
`window.OmniaConsolePhone`/`window.OmniaPhone` (client SIP) vivono solo in
`app.js`, con commento esplicito nel codice: *"NON crea una seconda
registrazione SIP"*. Il fallback "aperta standalone" già previsto nel codice
(`omniaPhoneController()`) non era mai stato completato: in accesso diretto
i pulsanti si disabilitano già da soli (`omniaPhoneAvailable()`), ma senza
alcuna spiegazione visibile all'operatore.

Ho segnalato la cosa prima di procedere e concordato con te l'Opzione A:
link diretto con degrado onesto e visibile, nessuna seconda registrazione SIP.

## File modificati
- `frontend/index.html` — aggiunto un link diretto `/omnia-console.html` nella
  topbar (stesso pattern del link esistente per Omnia Voice). 3 righe.
- `frontend/omnia-console.html` — aggiunto un banner persistente (nascosto di
  default) mostrato solo quando non è disponibile alcun bridge telefonico
  (né embedded né standalone). Nessuna riga di codice esistente modificata,
  solo aggiunte. 36 righe.

## Test eseguiti (realmente, in browser)
Ho usato Playwright con Chromium reale (non solo controlli statici):

1. `node --check` su tutti i 15 blocchi `<script>` inline dei due file → OK
2. Accesso standalone (`/omnia-console.html`, senza query string):
   - banner `#omnia-standalone-phone-banner` → `display: block` (visibile)
   - `omniaPhoneAvailable()` → `False`
   - pulsante generato via `omniaPhoneButton('Rispondi','answer')` → contiene
     già l'attributo `disabled`
   - zero errori JS in console
3. Accesso embedded (`/omnia-console.html?embedded=1`, comportamento
   preesistente, non toccato da questa modifica):
   - banner → `display: none` (nascosto, come deve essere)
   - topbar → `display: none` (comportamento invariato)
   - zero errori JS in console
4. Verificato in browser che il link `/omnia-console.html` è presente e
   corretto in `index.html`, zero errori JS sulla pagina

Non eseguito: test con un vero client SIP registrato/telefono attivo
(richiede ambiente DEV con Asterisk/MikoPBX configurato, fuori dalla portata
di un test locale). Il comportamento in presenza di bridge reale non cambia
rispetto a prima (il banner semplicemente non compare, la logica embedded
esistente non è stata toccata).

## Come testare in DEV
1. Applicare la patch (`0003-feat-omnia-console-direct-url.patch`) o
   sostituire i 2 file con le versioni allegate.
2. Da loggato come operatore, cliccare "Omnia Console" nella topbar → deve
   aprirsi `/omnia-console.html` con il banner giallo visibile in alto e i
   pulsanti telefono disabilitati (grigi, non cliccabili).
3. Da dentro l'app principale, aprire una chiamata attiva e verificare che
   Omnia Console incorporata (iframe, `?embedded=1`) continui a funzionare
   esattamente come prima — nessun banner, controlli telefono attivi.

## Rischi
- Nessuna modifica di logica esistente, solo aggiunte condizionali. Il
  rischio residuo è puramente visivo/UX (posizionamento del banner su
  risoluzioni molto piccole non testato).
- Non risolve la mancanza di un vero bridge telefonico standalone — la
  limitiamo esplicitamente e onestamente, come da tua indicazione. Un vero
  utilizzo "solo consultazione" (senza dover rispondere/gestire chiamate da
  lì) è già pienamente funzionante: prenotazioni, documenti, contesto
  paziente restano operativi anche in standalone.

## Rollback
`git revert 8a96eec`, oppure ripristino diretto dei 2 file dalla versione
precedente (`fb62376`).

## Prossimo slice possibile (non iniziato, in attesa di indicazioni)
Slice 2 della Fase 3: migrare la sola vista "Conversazioni" dentro Omnia
Console, lasciando invariato il resto della shell legacy — come indicato
nel piano originale.
