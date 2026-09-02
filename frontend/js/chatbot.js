
function cupLocalDate(value){
  if(!value)return null;
  const raw=String(value).trim();
  const normalized=/(?:Z|[+-]\\d{2}:?\\d{2})$/i.test(raw)?raw:raw+'Z';
  const d=new Date(normalized);
  return Number.isNaN(d.getTime())?null:d;
}
const messagesEl=document.getElementById('messages');const form=document.getElementById('chat-form');const input=document.getElementById('chat-input');const sendButton=document.getElementById('send-button');const statusEl=document.getElementById('chat-status');const chatAvatar=document.getElementById('chat-avatar');const chatTitle=document.getElementById('chat-title');const chatRole=document.getElementById('chat-role');const mainEl=document.getElementById('chat-main');const attachmentInput=document.getElementById('attachment-input');const attachmentButton=document.getElementById('attachment-button');const uploadStatus=document.getElementById('upload-status');const quickActionsEl=document.getElementById('quick-actions');const widget=document.getElementById('chat-widget');const launcher=document.getElementById('chat-launcher');
let sessionId=localStorage.getItem('cup_chat_session')||'';let lastMessageId=0;let renderedAttachmentIds=new Set();let currentContext={};const journeyToken=new URLSearchParams(location.search).get('journey_token')||'';
function openChat(){widget.classList.remove('minimized');launcher.style.display='none';setTimeout(()=>input?.focus(),80)}function closeChat(){widget.classList.add('minimized');launcher.style.display='flex'}
document.getElementById('chat-toggle')?.addEventListener('click',closeChat);launcher?.addEventListener('click',openChat);document.querySelectorAll('.js-open-chat').forEach(b=>b.addEventListener('click',async()=>{const m=(b.dataset.message||'').toUpperCase();if(m.includes('PRENOTAZ')){window.location.href='patient-portal.html?view=booking';return}openChat();if(m) await sendMessage(m)}));
document.getElementById('menu-toggle')?.addEventListener('click',()=>document.querySelector('.main-nav')?.classList.toggle('mobile-open'));
const checkinModal=document.getElementById('checkin-modal');const presenceStatus=document.getElementById('presence-status');function openCheckin(){checkinModal.hidden=false}function closeCheckin(){checkinModal.hidden=true}document.getElementById('show-checkin')?.addEventListener('click',openCheckin);document.getElementById('close-checkin')?.addEventListener('click',closeCheckin);checkinModal?.addEventListener('click',e=>{if(e.target===checkinModal)closeCheckin()});
function registerPresence(){const now=new Date().toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'});localStorage.setItem('cup_demo_waiting_room_presence',new Date().toISOString());presenceStatus.classList.add('present');presenceStatus.innerHTML=`<span class="status-icon"><i class="bi bi-check2"></i></span><h3>Presenza registrata</h3><p>Sei stato inserito nella sala d'attesa demo alle <strong>${now}</strong>.</p><button class="btn btn-outline" onclick="document.getElementById('checkin-modal').hidden=true">Chiudi</button>`}
document.getElementById('confirm-presence')?.addEventListener('click',registerPresence);if(new URLSearchParams(location.search).get('checkin')==='waiting-room'){openCheckin();registerPresence();history.replaceState({},'',location.pathname+'#sala-attesa')}
async function resumeJourneyFromToken(){if(!journeyToken)return false;const r=await fetch(`/api/omnichannel/continue/${encodeURIComponent(journeyToken)}`);const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||'Link non valido o scaduto');sessionId=d.session_id;localStorage.setItem('cup_chat_session',sessionId);history.replaceState({},'',location.pathname);return true}

/* OMNIA_CHAT_GUIDED_V2 */

function setChatIdentity(mode='ai'){

  if(!chatAvatar || !chatTitle || !chatRole)
    return;

  chatAvatar.classList.remove(
    'ai',
    'waiting',
    'human'
  );

  if(mode==='human'){

    chatAvatar.classList.add('human');
    chatAvatar.innerHTML =
      '<i class="bi bi-person-fill"></i>';

    chatTitle.textContent =
      'Operatore CUP';

    chatRole.textContent =
      'Assistenza umana';

    return;
  }

  if(mode==='waiting'){

    chatAvatar.classList.add('waiting');
    chatAvatar.innerHTML =
      '<i class="bi bi-headset"></i>';

    chatTitle.textContent =
      'Assistenza CUP';

    chatRole.textContent =
      'Passaggio a un operatore';

    return;
  }

  chatAvatar.classList.add('ai');
  chatAvatar.innerHTML =
    '<i class="bi bi-stars"></i>';

  chatTitle.textContent =
    'Omnia';

  chatRole.textContent =
    'Assistente virtuale AI';
}


function updateChatIdentity(payload={}){

  const messages =
    Array.isArray(payload.messages)
      ? payload.messages
      : [];

  const hasHuman =
    messages.some(
      message=>message.role==='operator'
    );

  if(hasHuman){
    setChatIdentity('human');
    return;
  }

  if(payload.status==='handoff'){
    setChatIdentity('waiting');
    return;
  }

  setChatIdentity('ai');
}


function quickButton(label,value,action='send'){const b=document.createElement('button');b.type='button';b.className='quick-btn';b.textContent=label;b.addEventListener('click',async()=>{openChat();if(action==='upload'){await sendMessage(value||'CARICA RICETTA/RICHIESTA');attachmentInput.click()}else if(action==='portal'){window.location.href='patient-portal.html'}else if(action==='booking'){window.location.href='patient-portal.html?view=booking'}else await sendMessage(value||label)});return b}


/* OMNIA_QUICK_ACTIONS_V3 */

function renderQuickReplies(c={}){

  if(!quickActionsEl)
    return;

  quickActionsEl.innerHTML='';

  const stage =
    c.stage || 'welcome';

  let buttons=[];


  if(stage==='service_discovery'){

    buttons=[
      [
        'Ho già una prescrizione',
        'Ho già una prescrizione'
      ],
      [
        'Voglio orientarmi',
        'Voglio orientarmi'
      ],
      [
        'Operatore',
        'OPERATORE'
      ]
    ];

  }

  else if(stage==='service_found'){

    buttons=[
      ['Prenotare','Vorrei prenotare'],
      [
        'Informazioni',
        'Vorrei informazioni sulla prestazione'
      ],
      ['Operatore','OPERATORE']
    ];

  }

  else if(stage==='booking_regime'){

    buttons=[
      ['SSN','SSN'],
      ['Privato','Privato']
    ];

  }

  else if(stage==='booking_availability'){

    buttons=[
      [
        'Verifica disponibilità',
        '',
        'booking'
      ],
      ['Operatore','OPERATORE']
    ];

  }

  else if(stage==='booking_manage_action'){

    buttons=[
      ['Consultare','Consultare'],
      ['Modificare','Modificare'],
      ['Annullare','Annullare']
    ];

  }

  else if(stage==='booking_manage_portal'){

    buttons=[
      [
        'Apri Area Paziente',
        '',
        'portal'
      ],
      ['Operatore','OPERATORE']
    ];

  }

  else if(stage==='service_info_topic'){

    buttons=[
      ['Preparazione','Preparazione'],
      ['Durata','Durata'],
      ['Sedi','Sedi']
    ];

  }

  else if(stage==='facility_info_topic'){

    buttons=[
      ['Orari','Orari'],
      ['Dove siete','Dove siete'],
      ['Contatti','Contatti']
    ];

  }

  else if(
    stage==='booking_service' ||
    stage==='service_info_service'
  ){

    buttons=[
      ['Operatore','OPERATORE']
    ];

  }

  else{

    buttons=[
      [
        'Prenotare visita o esame',
        'Vorrei prenotare una visita o un esame'
      ],
      [
        'Informazioni',
        'Vorrei informazioni su una prestazione'
      ],
      [
        'Gestire una prenotazione',
        'Vorrei gestire una mia prenotazione'
      ]
    ];

  }


  buttons
    .slice(0,3)
    .forEach(
      item=>
        quickActionsEl.appendChild(
          quickButton(...item)
        )
    );
}


function esc(v){return String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;')}function linkify(v){return esc(v).replace(/(https?:\/\/[^\s<]+)/g,u=>`<a href="${u}" target="_blank" rel="noopener noreferrer">${u}</a>`)}function fmtBytes(n){n=Number(n||0);if(n<1024)return `${n} B`;if(n<1048576)return `${(n/1024).toFixed(1)} KB`;return `${(n/1048576).toFixed(1)} MB`}
function addMessage(role,content,createdAt=null,id=null){if(id&&Number(id)<=lastMessageId)return;if(id)lastMessageId=Math.max(lastMessageId,Number(id));const d=document.createElement('div');d.className='message '+role;const label=role==='user'?'Tu':role==='operator'?'Operatore':'Assistente';d.innerHTML=`${linkify(content)}<span class="meta">${label}${createdAt?' · '+(cupLocalDate(createdAt)?.toLocaleTimeString('it-IT',{timeZone:'Europe/Rome',hour:'2-digit',minute:'2-digit'})||''):''}</span>`;messagesEl.appendChild(d);mainEl.scrollTop=mainEl.scrollHeight}
function addAttachment(a){if(renderedAttachmentIds.has(Number(a.id)))return;renderedAttachmentIds.add(Number(a.id));const d=document.createElement('div');d.className='attachment-card user';d.innerHTML=`<i class="bi bi-file-earmark-text"></i><div class="attachment-info"><strong>${esc(a.filename)}</strong><span>${esc(fmtBytes(a.size_bytes))}</span></div><a class="attachment-download" href="${esc(a.url)}" target="_blank" rel="noopener"><i class="bi bi-box-arrow-up-right"></i></a>`;messagesEl.appendChild(d);mainEl.scrollTop=mainEl.scrollHeight}
async function startSession(){statusEl.textContent='Connessione...';const r=await fetch('/api/chatbot/web/start',{method:'POST'});if(!r.ok)throw new Error('Impossibile avviare la chat');const d=await r.json();sessionId=d.session_id;localStorage.setItem('cup_chat_session',sessionId);messagesEl.innerHTML='';lastMessageId=0;renderedAttachmentIds=new Set();currentContext={};renderQuickReplies(currentContext);await restoreSession()}
async function restoreSession(){if(!sessionId)return startSession();const r=await fetch(`/api/chatbot/web/${encodeURIComponent(sessionId)}/messages`);if(r.status===404){localStorage.removeItem('cup_chat_session');sessionId='';return startSession()}if(!r.ok)throw new Error('Errore recupero conversazione');const d=await r.json();messagesEl.innerHTML='';lastMessageId=0;renderedAttachmentIds=new Set();d.messages.forEach(m=>addMessage(m.role,m.content,m.created_at,m.id));(d.attachments||[]).forEach(addAttachment);currentContext=d.context||{};renderQuickReplies(currentContext);updateChatIdentity(d);statusEl.textContent=d.status==='handoff'?'Operatore richiesto':d.status==='closed'?'Chiusa':'Online'}
async function sendMessage(text){if(!String(text||'').trim())return;openChat();sendButton.disabled=true;input.disabled=true;try{const r=await fetch('/api/chatbot/web',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sessionId||null,text})});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Errore invio messaggio');sessionId=d.session_id;localStorage.setItem('cup_chat_session',sessionId);statusEl.textContent=d.status==='handoff'?'Operatore richiesto':'Online';currentContext=d.context||{};renderQuickReplies(currentContext);if(d.status==='handoff')setChatIdentity('waiting');else setChatIdentity('ai');await pollMessages()}catch(e){addMessage('assistant','Si è verificato un errore: '+e.message);statusEl.textContent='Errore'}finally{sendButton.disabled=false;input.disabled=false;input.focus()}}
async function ensureSession(){if(!sessionId)await startSession()}async function uploadAttachments(files){if(!files.length)return;await ensureSession();attachmentButton.disabled=true;uploadStatus.textContent=`Caricamento di ${files.length} file...`;try{for(const file of files){const fd=new FormData();fd.append('file',file);const r=await fetch(`/api/chatbot/web/${encodeURIComponent(sessionId)}/attachments`,{method:'POST',body:fd});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(`${file.name}: ${d.detail||'upload fallito'}`);addAttachment(d.attachment)}uploadStatus.textContent='Documento/i caricato/i correttamente.';await pollMessages()}catch(e){uploadStatus.textContent='Errore: '+e.message}finally{attachmentButton.disabled=false;attachmentInput.value=''}}
async function pollMessages(){if(!sessionId)return;try{const r=await fetch(`/api/chatbot/web/${encodeURIComponent(sessionId)}/messages`);if(!r.ok)return;const d=await r.json();d.messages.forEach(m=>addMessage(m.role,m.content,m.created_at,m.id));(d.attachments||[]).forEach(addAttachment);currentContext=d.context||currentContext||{};renderQuickReplies(currentContext);updateChatIdentity(d);statusEl.textContent=d.status==='handoff'?'Operatore richiesto':d.status==='closed'?'Chiusa':'Online'}catch(_){}}
form.addEventListener('submit',e=>{e.preventDefault();const text=input.value.trim();if(!text)return;input.value='';sendMessage(text)});attachmentButton.addEventListener('click',()=>attachmentInput.click());attachmentInput.addEventListener('change',()=>uploadAttachments(Array.from(attachmentInput.files||[])));renderQuickReplies(currentContext);
(async()=>{try{if(journeyToken)await resumeJourneyFromToken();await restoreSession();setInterval(pollMessages,3000);if(!messagesEl.children.length)addMessage('assistant','Ciao! Sono il tuo assistente virtuale. Come posso aiutarti oggi?')}catch(e){statusEl.textContent='Errore';addMessage('assistant','Non riesco a collegarmi al servizio CUP. Riprova più tardi.')}})();
window.addEventListener('DOMContentLoaded',()=>{const q=new URLSearchParams(location.search).get('prefill');if(q&&input&&!input.value){openChat();input.value=q;input.focus()}});


document.getElementById('chat-new-session')?.addEventListener('click', async () => {
  const ok = window.confirm(
    'Iniziare una nuova chat? La conversazione precedente resterà salvata.'
  );

  if (!ok) return;

  try {
    localStorage.removeItem('cup_chat_session');

    sessionId = '';
    lastMessageId = 0;
    renderedAttachmentIds = new Set();
    currentContext = {};

    messagesEl.innerHTML = '';
    statusEl.textContent = 'Nuova chat...';

    await startSession();

    openChat();
  } catch (e) {
    statusEl.textContent = 'Errore';
    addMessage(
      'assistant',
      'Impossibile avviare una nuova conversazione.'
    );
  }
});
