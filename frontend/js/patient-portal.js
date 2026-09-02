const state={token:null,patient:null,catalog:[],dashboard:null};
const SEARCH_HORIZON={private:{days:56,label:'8 settimane'},ssn:{days:240,label:'8 mesi'}};
const euro=c=>new Intl.NumberFormat('it-IT',{style:'currency',currency:'EUR'}).format((Number(c)||0)/100);
const fmt=d=>new Intl.DateTimeFormat('it-IT',{dateStyle:'medium',timeStyle:'short'}).format(new Date(d));
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
function toast(m){const e=document.getElementById('toast');e.textContent=m;e.hidden=false;setTimeout(()=>e.hidden=true,3500)}
async function api(path,opt={}){const r=await fetch(path,{headers:{'Content-Type':'application/json',...(opt.headers||{})},...opt});let j=null;try{j=await r.json()}catch{}if(!r.ok)throw new Error(j?.detail||`Errore ${r.status}`);return j}
let authState={
  phone:null,
  challengeId:null,
  registrationToken:null
};

const PORTAL_SESSION_KEY='clinicaSanMichelePortalSession';

function savePortalSession(session){
  const expiresIn=Number(session.expires_in||43200);

  localStorage.setItem(
    PORTAL_SESSION_KEY,
    JSON.stringify({
      token:session.token,
      patient:session.patient,
      expiresAt:Date.now()+(expiresIn*1000)
    })
  );
}

function clearPortalSession(){
  localStorage.removeItem(PORTAL_SESSION_KEY);
  state.token=null;
  state.patient=null;
}

function getSavedPortalSession(){
  try{
    const raw=localStorage.getItem(PORTAL_SESSION_KEY);

    if(!raw)return null;

    const session=JSON.parse(raw);

    if(
      !session.token ||
      !session.expiresAt ||
      Date.now()>=session.expiresAt
    ){
      clearPortalSession();
      return null;
    }

    return session;

  }catch{
    clearPortalSession();
    return null;
  }
}

function loginError(message){
  const box=document.getElementById('login-error');
  box.textContent=message||'Si è verificato un errore.';
  box.hidden=false;
}

function clearLoginError(){
  document.getElementById('login-error').hidden=true;
}

function showLoginStep(step){
  document.getElementById('login-phone-step').hidden=step!=='phone';
  document.getElementById('login-otp-step').hidden=step!=='otp';
  document.getElementById('login-registration-step').hidden=step!=='registration';
  clearLoginError();
}

function normalizedLoginPhone(){
  let value=document.getElementById('login-phone').value
    .replace(/[^\d+]/g,'')
    .trim();

  if(value.startsWith('+39')){
    value=value.slice(3);
  }else if(value.startsWith('0039')){
    value=value.slice(4);
  }

  return value;
}

async function openPortal(accessToken){
  const session=await api('/api/portal/session',{
    method:'POST',
    headers:{
      Authorization:`Bearer ${accessToken}`
    }
  });

  state.token=session.token;
  state.patient=session.patient;

  savePortalSession(session);

  document.getElementById('patient-name').textContent=
    session.patient.full_name||'Area Paziente';

  document.getElementById('support-phone').value=
    session.patient.phone||authState.phone||'';

  state.catalog=await api('/api/portal/catalog');
  renderCatalog();

  await refreshDashboard();

  document.getElementById('login-overlay').style.display='none';
}

async function requestOtp(){
  clearLoginError();

  const phone=normalizedLoginPhone();

  if(!phone || phone.length<9){
    loginError('Inserisci un numero di cellulare valido.');
    return;
  }

  const button=document.getElementById('request-otp');
  button.disabled=true;
  button.textContent='Invio codice...';

  try{
    const out=await api('/api/auth/patient/start',{
      method:'POST',
      body:JSON.stringify({phone})
    });

    authState.phone=phone;
    authState.challengeId=out.challenge_id;

    document.getElementById('otp-description').textContent=
      `Inserisci il codice inviato al numero +39 ${phone}.`;

    const demo=document.getElementById('demo-otp-box');

    if(out.demo_code){
      demo.hidden=false;
      demo.textContent=`Modalità demo · Codice OTP: ${out.demo_code}`;
    }else{
      demo.hidden=true;
    }

    showLoginStep('otp');

    setTimeout(()=>{
      document.getElementById('login-otp').focus();
    },100);

  }catch(e){
    loginError(e.message);
  }finally{
    button.disabled=false;
    button.textContent='Ricevi codice';
  }
}

async function verifyOtp(){
  clearLoginError();

  const code=document.getElementById('login-otp').value
    .replace(/\D/g,'')
    .trim();

  if(code.length!==6){
    loginError('Inserisci il codice di 6 cifre.');
    return;
  }

  const button=document.getElementById('verify-otp');
  button.disabled=true;
  button.textContent='Verifica...';

  try{
    const out=await api('/api/auth/patient/verify',{
      method:'POST',
      body:JSON.stringify({
        phone:authState.phone,
        challenge_id:authState.challengeId,
        code
      })
    });

    if(out.status==='authenticated' && out.access_token){
      await openPortal(out.access_token);
      return;
    }

    if(out.status==='registration_required' && out.registration_token){
      authState.registrationToken=out.registration_token;
      showLoginStep('registration');
      return;
    }

    throw new Error('Risposta di autenticazione non riconosciuta.');

  }catch(e){
    loginError(e.message);
  }finally{
    button.disabled=false;
    button.textContent='Accedi';
  }
}

async function completeRegistration(){
  clearLoginError();

  const firstName=document.getElementById('registration-first-name').value.trim();
    const lastName=document.getElementById('registration-last-name').value.trim();
  const fiscalCode=document.getElementById('reg-fiscal-code').value
    .trim()
    .toUpperCase();
  const dateOfBirth=document.getElementById('reg-birth-date').value;
  const email=document.getElementById('reg-email').value.trim();

  if(!fullName || !fiscalCode || !dateOfBirth){
    loginError('Compila nome, codice fiscale e data di nascita.');
    return;
  }

  const button=document.getElementById('complete-registration');
  button.disabled=true;
  button.textContent='Verifica dati...';

  try{
    const out=await api('/api/auth/patient/complete-registration',{
      method:'POST',
      body:JSON.stringify({
        registration_token:authState.registrationToken,
        first_name:firstName,
        last_name:lastName,
        fiscal_code:fiscalCode,
        date_of_birth:dateOfBirth,
        email:email||null
      })
    });

    if(!out.access_token){
      throw new Error('Registrazione completata ma accesso non disponibile.');
    }

    await openPortal(out.access_token);

  }catch(e){
    loginError(e.message);
  }finally{
    button.disabled=false;
    button.textContent='Continua';
  }
}

async function start(){
  const saved=getSavedPortalSession();

  if(saved){
    try{
      state.token=saved.token;
      state.patient=saved.patient;

      state.dashboard=await api(
        `/api/portal/dashboard?token=${encodeURIComponent(state.token)}`
      );

      document.getElementById('patient-name').textContent=
        saved.patient?.full_name||'Area Paziente';

      document.getElementById('support-phone').value=
        saved.patient?.phone||'';

      state.catalog=await api('/api/portal/catalog');

      renderCatalog();
      renderBookings();
      renderDocuments();
      renderQueue();
      renderPayments();

      document.getElementById('login-overlay').style.display='none';

      return;

    }catch(e){
      clearPortalSession();
    }
  }

  showLoginStep('phone');

  document.getElementById('request-otp').onclick=requestOtp;
  document.getElementById('verify-otp').onclick=verifyOtp;
  document.getElementById('complete-registration').onclick=completeRegistration;

  document.getElementById('change-phone').onclick=()=>{
    authState={phone:null,challengeId:null,registrationToken:null};
    document.getElementById('login-otp').value='';
    showLoginStep('phone');
  };

  document.getElementById('registration-back').onclick=()=>{
    showLoginStep('phone');
  };

  document.getElementById('login-phone').addEventListener('keydown',e=>{
    if(e.key==='Enter')requestOtp();
  });

  document.getElementById('login-otp').addEventListener('keydown',e=>{
    if(e.key==='Enter')verifyOtp();
  });
}
function renderCatalog(){const sel=document.getElementById('service-select');sel.innerHTML=state.catalog.map(v=>`<option value="${v.id}">${esc(v.name)}</option>`).join('');renderSummary()}
function selectedVisit(){return state.catalog.find(v=>v.id===Number(document.getElementById('service-select').value))}
function regime(){return document.querySelector('input[name="regime"]:checked')?.value||'private'}
function renderSummary(){const v=selectedVisit();if(!v)return;const r=regime();const price=r==='ssn'?(v.ssn_enabled?v.ssn_ticket_cents:null):v.private_price_cents;const horizon=SEARCH_HORIZON[r];document.getElementById('service-summary').innerHTML=`<strong>${esc(v.name)}</strong><br><span>${v.duration_minutes} min · ${r==='ssn'?'Regime SSN':'Privato'}</span><div class="price">${price===null?'Non disponibile':euro(price)}</div><small><i class="bi bi-calendar-range"></i> Ricerca disponibilità fino a ${horizon.label}</small>${v.requires_prescription?'<small><i class="bi bi-file-earmark-medical"></i> Richiesta/ricetta necessaria</small>':''}`}
async function searchSlots(){const v=selectedVisit();if(!v)return;const r=regime();const horizon=SEARCH_HORIZON[r];const list=document.getElementById('slot-list');list.innerHTML=`<div class="empty">Ricerca disponibilità fino a ${horizon.label}...</div>`;try{const slots=await api(`/api/portal/next-slots?visit_type_id=${v.id}&regime=${encodeURIComponent(r)}&days=${horizon.days}&limit=18`);list.innerHTML=slots.length?slots.map(x=>`<article class="slot"><div><strong>${fmt(x.start)}</strong><small>${esc(x.doctor_name||'Medico')} · ${esc(x.location||'Clinica')}</small><small><b>${r==='ssn'?'SSN · Ticket':'Privato'} ${euro(x.price_cents)}</b></small></div><button data-slot='${JSON.stringify(x).replace(/'/g,"&#39;")}'>Scegli</button></article>`).join(''):`<div class="empty">Nessuna disponibilità trovata nei prossimi ${horizon.label}. Prova un'altra prestazione o contatta il CUP.</div>`;list.querySelectorAll('[data-slot]').forEach(b=>b.onclick=()=>hold(JSON.parse(b.dataset.slot)))}catch(e){list.innerHTML=`<div class="empty">${esc(e.message)}</div>`}}
async function hold(slot){const v=selectedVisit();if(!confirm(`Bloccare ${v.name} per ${fmt(slot.start)}?`))return;try{const out=await api('/api/portal/bookings/hold',{method:'POST',body:JSON.stringify({token:state.token,visit_type_id:v.id,agenda_id:slot.agenda_id,scheduled_at:slot.start,regime:regime()})});toast(out.message);await refreshDashboard();showView('bookings');await searchSlots()}catch(e){toast(e.message);await searchSlots()}}
async function refreshDashboard(){state.dashboard=await api(`/api/portal/dashboard?token=${encodeURIComponent(state.token)}`);renderBookings();renderDocuments();renderQueue();renderPayments()}
function renderBookings(){const box=document.getElementById('bookings-list');const rows=state.dashboard?.bookings||[];box.innerHTML=rows.length?rows.map(b=>`<article class="data-row"><div><strong>${esc(b.service_name)}</strong><small>${fmt(b.scheduled_at)} · ${esc(b.doctor_name||'Da assegnare')} · ${esc(b.location||'')}</small></div><div><span class="status ${esc(b.status)}">${b.status==='pending'?'In attesa conferma':b.status}</span><small>${b.regime==='ssn'?'SSN':'Privato'} · ${euro(b.price_cents)}</small></div><div>${b.requires_prescription?'<span><i class="bi bi-paperclip"></i> Ricetta richiesta</span>':''}</div></article>`).join(''):'<div class="empty">Non risultano prenotazioni.</div>'}
function renderDocuments(){const box=document.getElementById('documents-list');const rows=state.dashboard?.documents||[];box.innerHTML=rows.length?rows.map(d=>`<article class="data-row"><div><strong>${esc(d.title)}</strong><small>${esc(d.category)} · ${fmt(d.created_at)}</small></div><div><span class="status confirmed">Disponibile</span></div><div><a class="download" href="/api/portal/documents/${d.id}/download?token=${encodeURIComponent(state.token)}"><i class="bi bi-download"></i> Scarica</a> <button class="ghost" data-share="${d.id}"><i class="bi bi-share"></i> Condividi</button></div></article>`).join(''):'<div class="empty">Nessun documento disponibile.</div>';box.querySelectorAll('[data-share]').forEach(b=>b.onclick=()=>shareDocument(Number(b.dataset.share)))}
async function shareDocument(id){try{const out=await api(`/api/portal/documents/${id}/share?token=${encodeURIComponent(state.token)}`,{method:'POST'});const full=location.origin+out.url;prompt(`Link valido 24 ore. Comunica separatamente il codice ${out.access_code}`,`${full}?code=${out.access_code}`)}catch(e){toast(e.message)}}
function renderQueue(){const box=document.getElementById('queue-bookings');const bookings=(state.dashboard?.bookings||[]).filter(b=>b.status==='confirmed'||b.status==='pending').slice(0,5);box.innerHTML=bookings.length?bookings.map(b=>`<article class="data-row"><div><strong>${esc(b.service_name)}</strong><small>${fmt(b.scheduled_at)}</small></div><div>${esc(b.location||'Clinica')}</div><div><button class="primary" data-checkin="${b.id}"><i class="bi bi-qr-code-scan"></i> Registra presenza</button></div></article>`).join(''):'<div class="empty">Nessuna prenotazione disponibile per il check-in demo.</div>';box.querySelectorAll('[data-checkin]').forEach(b=>b.onclick=()=>checkin(Number(b.dataset.checkin)));const tickets=state.dashboard?.queue||[];document.getElementById('queue-status').innerHTML=tickets.length?`<div class="ticket"><span>Il tuo numero</span><b>${esc(tickets[0].code)}</b><span>${esc(tickets[0].status)} · attesa stimata ${tickets[0].estimated_wait_minutes} min</span></div>`:''}
async function checkin(id){try{const q=await api('/api/portal/queue/check-in',{method:'POST',body:JSON.stringify({token:state.token,booking_id:id})});toast(`Presenza registrata. Numero ${q.code}`);await refreshDashboard()}catch(e){toast(e.message)}}

function renderPayments(){const box=document.getElementById('payments-list');const rows=state.dashboard?.payments||[];box.innerHTML=rows.length?rows.map(x=>`<article class="data-row"><div><strong>${esc(x.description)}</strong><small>${x.provider} · ${fmt(x.created_at)}</small></div><div><span class="status ${x.status==='paid'?'confirmed':x.status==='pending'||x.status==='sent'?'pending':'cancelled'}">${esc(x.status)}</span><small>${euro(x.amount_cents)}</small></div><div>${x.checkout_url&&x.status!=='paid'?`<a class="download" href="${esc(x.checkout_url)}" target="_blank" rel="noopener"><i class="bi bi-credit-card"></i> Paga online</a>`:''}</div></article>`).join(''):'<div class="empty">Nessuna richiesta di pagamento presente.</div>'}
function showView(name){document.querySelectorAll('.portal-view').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.service').forEach(x=>x.classList.toggle('active',x.dataset.view===name));document.getElementById(`view-${name}`).classList.add('active')}
document.querySelectorAll('.service').forEach(b=>b.onclick=()=>showView(b.dataset.view));document.getElementById('search-slots').onclick=searchSlots;document.getElementById('service-select').onchange=renderSummary;document.querySelectorAll('input[name="regime"]').forEach(x=>x.onchange=renderSummary);document.getElementById('service-search').oninput=e=>{const q=e.target.value.toLowerCase();const v=state.catalog.find(x=>x.name.toLowerCase().includes(q)||String(x.code||'').toLowerCase().includes(q));if(v){document.getElementById('service-select').value=v.id;renderSummary()}};document.getElementById('refresh-dashboard').onclick=refreshDashboard;document.getElementById('support-form').onsubmit=async e=>{e.preventDefault();const box=document.getElementById('support-result');try{const out=await api('/api/portal/support',{method:'POST',body:JSON.stringify({token:state.token,phone:document.getElementById('support-phone').value,message:document.getElementById('support-message').value})});box.textContent=out.message;document.getElementById('support-message').value=''}catch(err){box.textContent=err.message}};
const requestedView=new URLSearchParams(location.search).get('view');if(requestedView&&document.getElementById(`view-${requestedView}`))showView(requestedView);
start().catch(e=>{document.getElementById('patient-name').textContent='Portale non disponibile';toast(e.message)});
