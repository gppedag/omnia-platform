document.getElementById("version-badge").textContent = "v" + window.CUP_CONFIG.APP_VERSION;
document.querySelectorAll(".app-version").forEach((el) => el.textContent = window.CUP_CONFIG.APP_VERSION);

// --- Notifiche toast (sostituiscono i banner alert() nativi del browser) ---
const TOAST_ICONS = { success: "bi-check-circle-fill", error: "bi-exclamation-octagon-fill", info: "bi-info-circle-fill" };
function ensureToastStack() {
  let stack = document.getElementById("cup-toast-stack");
  if (!stack) {
    stack = document.createElement("div");
    stack.id = "cup-toast-stack";
    stack.className = "cup-toast-stack";
    stack.setAttribute("aria-live", "polite");
    stack.setAttribute("aria-atomic", "true");
    document.body.appendChild(stack);
  }
  return stack;
}
function showToast(message, type = "info", timeout = 5000) {
  const stack = ensureToastStack();
  const el = document.createElement("div");
  el.className = `cup-toast cup-toast-${type}`;
  el.setAttribute("role", "status");
  el.innerHTML = `<i class="bi ${TOAST_ICONS[type] || TOAST_ICONS.info}"></i><span class="cup-toast-msg"></span><button type="button" class="cup-toast-close" aria-label="Chiudi">&times;</button>`;
  el.querySelector(".cup-toast-msg").textContent = message;
  const close = () => { el.classList.add("cup-toast-out"); setTimeout(() => el.remove(), 180); };
  el.querySelector(".cup-toast-close").addEventListener("click", close);
  stack.appendChild(el);
  requestAnimationFrame(() => el.classList.add("cup-toast-in"));
  if (timeout) setTimeout(close, timeout);
  return el;
}

const loginScreen = document.getElementById("login-screen");
const operatorApp = document.getElementById("operator-app");
function makeModal(id) {
  const el = document.getElementById(id);
  if (!el) {
    console.warn(`[CUP] Modal mancante: ${id}`);
    return { show() {}, hide() {} };
  }
  if (window.bootstrap && window.bootstrap.Modal) return new window.bootstrap.Modal(el);
  // Fallback minimale per ambienti di sviluppo dove il CDN Bootstrap JS non e raggiungibile.
  return {
    show() { el.style.display = "block"; el.classList.add("show"); el.removeAttribute("aria-hidden"); document.body.classList.add("modal-open"); },
    hide() { el.style.display = "none"; el.classList.remove("show"); el.setAttribute("aria-hidden", "true"); document.body.classList.remove("modal-open"); },
  };
}

const bookingModal = makeModal("booking-modal");
const doctorModal = makeModal("doctor-modal");
const visitTypeModal = makeModal("visit-type-modal");
const agendaModal = makeModal("agenda-modal");

if (!(window.bootstrap && window.bootstrap.Modal)) {
  document.addEventListener("click", (event) => {
    const dismiss = event.target.closest('[data-bs-dismiss="modal"]');
    if (!dismiss) return;
    const modal = dismiss.closest(".modal");
    if (modal) { modal.style.display = "none"; modal.classList.remove("show"); document.body.classList.remove("modal-open"); }
  });
}
let currentChatSessionId = null;
let chatRefreshTimer = null;
let currentUser = null;

/*
 * Stato iniziale sempre non autenticato.
 * bootstrapAuth abiliterà l'interfaccia solo dopo /auth/me.
 */
document.body.classList.remove("cup-authenticated");
let callWs = null;
let callsWs = null;
let callsWsReconnectTimer = null;
let bookingRuntime = { mode: "internal", externalName: "Gestionale prenotazioni", externalUrl: "", embed: true };
let handoffQueueIds = new Set();
let handoffQueueTimer = null;
let handoffWs = null;

async function loadBookingRuntime() {
  try {
    const data = await CupApi.getRuntimeSettings();
    bookingRuntime = {
      mode: data.booking_mode || "internal",
      externalName: data.external_booking_name || "Gestionale prenotazioni",
      externalUrl: data.external_booking_url || "",
      embed: data.external_booking_embed_enabled !== false,
    };
  } catch (_) { bookingRuntime = { mode: "internal", externalName: "Gestionale prenotazioni", externalUrl: "", embed: true }; }
  applyBookingModeUi();
  return bookingRuntime;
}

function applyBookingModeUi() {
  const mode = bookingRuntime.mode || "internal";
  const nav = document.getElementById("calendar-nav-item");
  const navLabel = document.getElementById("calendar-nav-label");
  const statCard = document.getElementById("dashboard-bookings-stat");
  const statLabel = document.getElementById("dashboard-bookings-label");
  if (mode === "chatbot_only") {
    if (navLabel) navLabel.textContent = "Prenotazioni";
    if (statCard) statCard.classList.add("d-none");
  } else if (mode === "external") {
    if (nav) nav.classList.remove("d-none");
    if (navLabel) navLabel.textContent = bookingRuntime.externalName || "Gestionale prenotazioni";
    if (statCard) statCard.classList.remove("d-none");
    if (statLabel) statLabel.textContent = "Sistema prenotazioni";
    const val = document.getElementById("stat-bookings-today"); if (val) { val.textContent = "Esterno"; val.classList.add("fs-6"); }
  } else {
    if (nav) nav.classList.remove("d-none");
    if (navLabel) navLabel.textContent = "Agende Prenotazioni";
    if (statCard) statCard.classList.remove("d-none");
    if (statLabel) statLabel.textContent = "Prenotazioni oggi";
    const val = document.getElementById("stat-bookings-today"); if (val) val.classList.remove("fs-6");
  }
}

function renderBookingModule() {
  const internal = document.getElementById("internal-booking-panel");
  const external = document.getElementById("external-booking-panel");
  const chatbotOnly = document.getElementById("chatbot-only-booking-panel");
  const alertBox = document.getElementById("booking-mode-alert");
  [internal, external, chatbotOnly].forEach(x => x?.classList.add("d-none"));
  alertBox?.classList.add("d-none");
  if (bookingRuntime.mode === "external") {
    external?.classList.remove("d-none");
    const title = document.getElementById("external-booking-title"); if (title) title.textContent = bookingRuntime.externalName || "Gestionale prenotazioni";
    const open = document.getElementById("external-booking-open");
    const frame = document.getElementById("external-booking-frame");
    const noembed = document.getElementById("external-booking-noembed");
    if (!bookingRuntime.externalUrl) {
      if (alertBox) { alertBox.textContent = "Gestionale esterno selezionato, ma URL non configurato. Apri Impostazioni > Prenotazioni esercizio."; alertBox.classList.remove("d-none"); }
      if (open) open.classList.add("disabled");
      frame?.classList.add("d-none"); noembed?.classList.remove("d-none");
      return;
    }
    if (open) { open.href = bookingRuntime.externalUrl; open.classList.remove("disabled"); }
    if (bookingRuntime.embed) {
      if (frame) { if (frame.src !== bookingRuntime.externalUrl) frame.src = bookingRuntime.externalUrl; frame.classList.remove("d-none"); }
      noembed?.classList.add("d-none");
    } else { frame?.classList.add("d-none"); noembed?.classList.remove("d-none"); }
    return;
  }
  if (bookingRuntime.mode === "chatbot_only") { chatbotOnly?.classList.remove("d-none"); return; }
  internal?.classList.remove("d-none");
  loadCupCalendar();
}


/* CUP_LOGIN_BRANDING_V1 */

async function loadLoginBranding(){

  const wrap =
    document.getElementById(
      "login-clinic-logo-wrap"
    );

  const logo =
    document.getElementById(
      "login-clinic-logo"
    );

  const fallback =
    document.getElementById(
      "login-clinic-logo-fallback"
    );

  const clinicName =
    document.getElementById(
      "login-clinic-name"
    );

  try{

    const branding =
      await CupApi.getPublicBranding();

    if(
      clinicName
      &&branding?.clinic_name
    ){
      clinicName.textContent =
        branding.clinic_name;
    }

    if(
      logo
      &&branding?.logo_url
    ){

      logo.onload=()=>{
        wrap?.classList.remove(
          "d-none"
        );

        fallback?.classList.add(
          "d-none"
        );
      };

      logo.onerror=()=>{
        wrap?.classList.add(
          "d-none"
        );

        fallback?.classList.remove(
          "d-none"
        );
      };

      /*
       * Evita una vecchia immagine mantenuta
       * dalla cache del browser.
       */
      const separator =
        branding.logo_url.includes("?")
          ?"&"
          :"?";

      logo.src =
        branding.logo_url
        +separator
        +"v="
        +Date.now();

    }else{

      wrap?.classList.add(
        "d-none"
      );

      fallback?.classList.remove(
        "d-none"
      );
    }

  }catch(error){

    console.warn(
      "[CUP] branding login non disponibile",
      error
    );

    wrap?.classList.add(
      "d-none"
    );

    fallback?.classList.remove(
      "d-none"
    );
  }
}

/* /CUP_LOGIN_BRANDING_V1 */


function showLogin() {

  /*
   * Stato non autenticato.
   * Oltre all'applicazione nascondiamo qualsiasi
   * UI telefonica eventualmente creata fuori
   * da #operator-app.
   */
  document.body.classList.remove(
    "cup-authenticated"
  );

  operatorApp.classList.add(
    "d-none"
  );

  loginScreen.classList.remove(
    "d-none"
  );

  loadLoginBranding();
}


function showApp() {

  loginScreen.classList.add(
    "d-none"
  );

  operatorApp.classList.remove(
    "d-none"
  );

  /*
   * La Phone Island diventa visibile solamente
   * dopo che /auth/me ha validato la sessione.
   */
  document.body.classList.add(
    "cup-authenticated"
  );
}

function applyOperatorChannelUi() {
  if (!currentUser) return;
  const isAdmin = currentUser.role === "admin";
  const canChat = isAdmin || currentUser.can_chat !== false;
  const canPhone = isAdmin || currentUser.can_phone !== false;
  document.getElementById("chat-nav-item")?.classList.toggle("d-none", !canChat);
  document.getElementById("calls-nav-item")?.classList.toggle("d-none", !canPhone);
  document.getElementById("handoff-nav-item")?.classList.toggle("d-none", !(canChat || canPhone));
  document.getElementById("dashboard-calls-stat")?.classList.toggle("d-none", !canPhone);
  const presence = document.getElementById("operator-presence");
  if (presence) presence.classList.toggle("d-none", !(canChat || canPhone));
}

let omniaOperatorVoip = null;

/* OMNIA_REAL_VOIP_STATUS_V1 */

let omniaVoipStatusTimer = null;

let omniaSipRegisteredState = null;
let omniaSipRegisteredExtension = null;



function applyRealVoipStatus(data){

  const phone =
    document.querySelector(
      ".cup-phone-island-v3"
    );

  if(!phone)
    return;

  const dot =
    phone.querySelector(
      ".cup-phone-island-status-dot"
    );

  const title =
    phone.querySelector(
      ".cup-phone-island-title"
    );

  const subtitle =
    phone.querySelector(
      ".cup-phone-island-subtitle"
    );

  if(title){
    title.textContent =
      data?.extension
        ? `Telefono CUP · ${data.extension}`
        : "Telefono CUP";
  }

  if(dot){

    dot.className =
      "cup-phone-island-status-dot";

    if(data?.status === "registered"){
      dot.classList.add(
        "registered"
      );
    }

    if(data?.status === "active"){
      dot.classList.add(
        "active"
      );
    }
  }

  if(subtitle){

    if(data?.status === "registered"){
      subtitle.textContent =
        "Registrato";
    }
    else if(data?.status === "active"){
      subtitle.textContent =
        "In chiamata";
    }
    else if(data?.status === "unavailable"){
      subtitle.textContent =
        "Non registrato";
    }
    else if(data?.status === "not_configured"){
      subtitle.textContent =
        "Non configurato";
    }
    else{
      subtitle.textContent =
        "Stato non disponibile";
    }
  }

  phone.classList.toggle(
    "island-idle",
    data?.status !== "active"
  );
}


async function refreshRealVoipStatus(){

  if(
    !currentUser
    || !["admin", "operator"].includes(currentUser.role)
    || currentUser.can_phone === false
  ){
    return;
  }

  try{

    const status =
      await CupApi.getMyVoipStatus();

    /*
     * Lo stato di registrazione SIP del WebPhone è autorevole.
     * Il polling backend non deve sovrascriverlo con l'hint
     * aggregato Asterisk, che può risultare Unavailable anche
     * quando PJSIP/<interno>-WS è registrato.
     */
    if(
      omniaSipRegisteredState !== null &&
      omniaSipRegisteredExtension &&
      String(status?.extension || "") ===
        String(omniaSipRegisteredExtension)
    ){
      if(status?.in_call === true){
        applyRealVoipStatus({
          ...status,
          registered: true,
          status: "active",
          status_text: "In chiamata"
        });
      }

      return;
    }

    applyRealVoipStatus(
      status
    );

  }catch(error){

    console.warn(
      "[OMNIA PHONE] stato SIP",
      error
    );
  }
}


function startRealVoipStatus(){

  if(omniaVoipStatusTimer){
    clearInterval(
      omniaVoipStatusTimer
    );
  }

  refreshRealVoipStatus();

  omniaVoipStatusTimer =
    setInterval(
      refreshRealVoipStatus,
      5000
    );
}

/* /OMNIA_REAL_VOIP_STATUS_V1 */


function sendVoipToPhone(){
  const frame =
    document.getElementById(
      "cup-phone-frame"
    );

  if(
    !frame ||
    !frame.contentWindow ||
    !omniaOperatorVoip
  ) return;

  frame.contentWindow.postMessage(
    {
      type:
        "OMNIA_VOIP_CREDENTIALS",

      extension:
        omniaOperatorVoip.extension,

      password:
        omniaOperatorVoip.password
    },
    "https://phone.ai.basidiai.it"
  );
}


async function configureOperatorVoip(me){

  omniaOperatorVoip = null;

  if(
    !["admin", "operator"].includes(me?.role) ||
    me?.can_phone === false
  ){
    return;
  }

  try{

    omniaOperatorVoip =
      await CupApi.getMyVoip();

    sendVoipToPhone();

    const frame =
      document.getElementById(
        "cup-phone-frame"
      );

    frame?.addEventListener(
      "load",
      sendVoipToPhone,
      { once:false }
    );

  }catch(error){

    console.warn(
      "[OMNIA PHONE] VoIP non configurato",
      error
    );
  }
}


window.addEventListener(
  "message",
  event => {

    if(
      event.origin !==
      "https://phone.ai.basidiai.it"
    ){
      return;
    }

    if(
      event.data?.type ===
      "OMNIA_PHONE_READY"
    ){
      sendVoipToPhone();
      return;
    }

    /* OMNIA_SIP_STATUS_BRIDGE_V1 */
    if(
      event.data?.type ===
      "OMNIA_SIP_STATUS"
    ){
      const extension =
        String(
          event.data?.extension || ""
        ).trim();

      if(
        omniaOperatorVoip?.extension &&
        extension !==
          String(omniaOperatorVoip.extension)
      ){
        return;
      }

      omniaSipRegisteredState =
        event.data?.registered === true;

      omniaSipRegisteredExtension =
        extension;

      if(omniaSipRegisteredState){
        applyRealVoipStatus({
          extension,
          registered: true,
          in_call: false,
          status: "registered",
          status_text: "Registrato"
        });
      }else{
        applyRealVoipStatus({
          extension,
          registered: false,
          in_call: false,
          status: "unavailable",
          status_text: "Non registrato"
        });
      }
    }
  }
);




async function bootstrapAuth() {

  if (!CupApi.token()) {
    showLogin();
    return;
  }

  try {

    const me = await CupApi.me();

    if (
      !["admin", "operator"]
        .includes(me.role)
    ) {
      CupApi.setToken("");
      showLogin();
      return;
    }

    currentUser = me;

    initCallsRealtime();

    document
      .getElementById("current-user")
      .textContent = me.full_name;

    const dun =
      document.getElementById(
        "dashboard-user-name"
      );

    if(dun){
      dun.textContent =
        me.full_name.split(" ")[0]
        || me.full_name;
    }

    const isAdmin =
      me.role === "admin";

    document
      .querySelectorAll(".admin-only")
      .forEach(
        el =>
          el.classList.toggle(
            "d-none",
            !isAdmin
          )
      );

    [
      "btn-seed-demo",
      "btn-calendar-config",
      "btn-reminders-settings",
      "btn-external-booking-settings",
      "btn-chatbot-only-settings"
    ].forEach(id=>{
      const el =
        document.getElementById(id);

      if(el){
        el.classList.toggle(
          "d-none",
          !isAdmin
        );
      }
    });

    document
      .querySelectorAll(
        "[data-open-settings]"
      )
      .forEach(
        el =>
          el.classList.toggle(
            "d-none",
            !isAdmin
          )
      );

    applyOperatorChannelUi();

    showApp();

    await configureOperatorVoip(me);

    startRealVoipStatus();

    try {
      if (
        isAdmin ||
        me.can_chat !== false ||
        me.can_phone !== false
      ) {
        const savedPresence =
          localStorage.getItem(
            "cup_operator_presence"
          ) || "available";

        document
          .getElementById(
            "operator-presence"
          ).value = savedPresence;

        await CupApi
          .setOperatorPresence(
            savedPresence
          );
      }
    } catch (_) {}

    await loadBookingRuntime();

    loadDashboardStats();
    refreshChatBadge();
    initHandoffRealtime();
    loadHandoffQueue();
    loadWaitlist();

  } catch (err) {

    console.error(
      "[CUP] bootstrap auth",
      err
    );

    CupApi.setToken("");
    showLogin();
  }
}


document
  .getElementById("login-form")
  .addEventListener(
    "submit",
    async e => {

      e.preventDefault();

      const errorEl =
        document.getElementById(
          "login-error"
        );

      errorEl.classList.add(
        "d-none"
      );

      try {

        const email =
          document
            .getElementById(
              "login-email"
            )
            .value
            .trim();

        const password =
          document
            .getElementById(
              "login-password"
            )
            .value;

        CupApi.setToken("");
        CupApi.setDevRole("");

        const auth =
          await CupApi.login(
            email,
            password
          );

        CupApi.setToken(
          auth.access_token
        );

        await bootstrapAuth();

      } catch (err) {

        errorEl.textContent =
          err.message ||
          "Email o password non valide";

        errorEl.classList.remove(
          "d-none"
        );
      }
    }
  );


document
  .getElementById("btn-logout")
  .addEventListener(
    "click",
    () => {

      omniaOperatorVoip = null;

      if(omniaVoipStatusTimer){
        clearInterval(omniaVoipStatusTimer);
        omniaVoipStatusTimer = null;
      }

      if(omniaVoipStatusTimer){
        clearInterval(
          omniaVoipStatusTimer
        );
        omniaVoipStatusTimer=null;
      }

      CupApi.setToken("");
      CupApi.setDevRole("");

      location.reload();
    }
  );


document.querySelectorAll("[data-tab]").forEach((link) => {
  link.addEventListener("click", (e) => {
    e.preventDefault();
    document.querySelectorAll(".tab-content").forEach((t) => t.classList.add("d-none"));
    document.querySelectorAll("[data-tab]").forEach((l) => l.classList.remove("active"));
    document.getElementById("tab-" + link.dataset.tab).classList.remove("d-none");
    link.classList.add("active");

    if (link.dataset.tab === "dashboard") loadDashboardStats();
    if (link.dataset.tab === "calendar") renderBookingModule();
    if (link.dataset.tab === "patients") loadPatients();
    if (link.dataset.tab === "previsit") loadPrevisit();
    if (link.dataset.tab === "waitlist") loadWaitlist();
    if (link.dataset.tab === "care") loadCare();
    if (link.dataset.tab === "calls") loadCalls();
    if (link.dataset.tab === "reminders") loadReminders();
    if (link.dataset.tab === "handoffs") { loadHandoffQueue(); loadOperatorPresence(); }
    if (link.dataset.tab === "chatbot") loadChatSessions();
    if (link.dataset.tab === "commerce") loadCommerce();
    if (link.dataset.tab === "analytics") { if(currentUser?.role!=="admin") return; loadAnalytics(); }
    if (link.dataset.tab === "settings") { if(currentUser?.role!=="admin") return; loadSettings(); }
    closeMobileSidebar();
  });
});

// --- Menu mobile a scomparsa ---
function openMobileSidebar() {
  document.getElementById("app-sidebar").classList.add("is-open");
  document.getElementById("sidebar-backdrop").classList.add("is-open");
  document.getElementById("btn-sidebar-toggle")?.setAttribute("aria-expanded", "true");
}
function closeMobileSidebar() {
  document.getElementById("app-sidebar").classList.remove("is-open");
  document.getElementById("sidebar-backdrop").classList.remove("is-open");
  document.getElementById("btn-sidebar-toggle")?.setAttribute("aria-expanded", "false");
}
document.getElementById("btn-sidebar-toggle")?.addEventListener("click", () => {
  document.getElementById("app-sidebar").classList.contains("is-open") ? closeMobileSidebar() : openMobileSidebar();
});
document.getElementById("sidebar-backdrop")?.addEventListener("click", closeMobileSidebar);

function fmtDate(value) {
  if (!value) return "-";

  const raw = String(value).trim();

  // PostgreSQL restituisce DateTime UTC senza timezone.
  // Se manca Z/+HH:MM, lo interpretiamo esplicitamente come UTC.
  const normalized =
    /(?:Z|[+-]\\d{2}:?\\d{2})$/i.test(raw)
      ? raw
      : raw + "Z";

  const date = new Date(normalized);

  if (Number.isNaN(date.getTime())) {
    return raw;
  }

  return date.toLocaleString("it-IT", {
    timeZone: "Europe/Rome",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

function statusColor(status) {
  return {
    pending: "warning",
    confirmed: "success",
    cancelled: "secondary",
    completed: "primary",
    ringing: "warning",
    active: "success",
    held: "info",
    ended: "secondary",
    missed: "danger",
  }[status] || "secondary";
}

async function loadBookings() { return renderBookingModule(); }

async function setBookingStatus(id, status) {
  try { await CupApi.updateCalendarBooking(id, { status }); await loadCupCalendar(); await loadDashboardStats(); }
  catch (e) { showToast(e.message, "error"); }
}

async function cancelBooking(id) {
  if (!confirm("Annullare questa prenotazione?")) return;
  try { await CupApi.updateCalendarBooking(id, { status: "cancelled" }); await loadCupCalendar(); await loadDashboardStats(); }
  catch (e) { showToast(e.message, "error"); }
}


const patientBrowserState = {
  page: 1,
  pageSize: 50,
  total: 0,
  pages: 1,
  query: "",
  reminder: "all",
  channel: "all",
  sort: "name",
  direction: "asc",
  timer: null
};


function patientApiHeaders(){

  const headers = {
    "Accept": "application/json"
  };

  /*
   * Riutilizza la sessione applicativa esistente.
   * CupApi gestisce normalmente token/dev-role;
   * queste chiavi coprono entrambe le modalita'
   * senza alterare CupApi.getPatients().
   */

  const token =
    localStorage.getItem("cup_token")
    || localStorage.getItem("token")
    || sessionStorage.getItem("cup_token")
    || "";

  const devRole =
    localStorage.getItem("cup_dev_role")
    || localStorage.getItem("dev_role")
    || "";

  if(token){
    headers["Authorization"] =
      token.startsWith("Bearer ")
        ? token
        : `Bearer ${token}`;
  }

  if(devRole){
    headers["X-Dev-Role"] = devRole;
  }

  return headers;
}


async function fetchPatientsPage(){

  const params = new URLSearchParams({
    page: String(patientBrowserState.page),
    page_size: String(patientBrowserState.pageSize),
    q: patientBrowserState.query,
    reminder: patientBrowserState.reminder,
    channel: patientBrowserState.channel,
    sort: patientBrowserState.sort,
    direction: patientBrowserState.direction
  });

  /*
   * Prima proviamo fetch con la sessione cookie corrente.
   * credentials:same-origin mantiene l'autenticazione
   * gia' utilizzata dalla console CUP.
   */

  const response = await fetch(
    `/api/patients/search?${params.toString()}`,
    {
      method: "GET",
      credentials: "same-origin",
      headers: patientApiHeaders()
    }
  );

  if(!response.ok){

    let message =
      `Errore caricamento pazienti (${response.status})`;

    try{
      const body=await response.json();

      message=
        body.detail
        ||body.message
        ||message;

    }catch(_){}

    const error=new Error(message);
    error.status=response.status;

    throw error;
  }

  return response.json();
}


function patientChannelBadges(value, telegramChatId){

  const channels = String(value || "")
    .split(",")
    .map(x => x.trim().toLowerCase())
    .filter(Boolean);

  const telegramLinked =
    !!String(telegramChatId || "").trim();

  const labels = {
    sms: "SMS",
    whatsapp: "WhatsApp",
    email: "Email"
  };

  const visible =
    channels.filter(ch => ch !== "telegram");

  const normalBadges =
    visible.map(ch => `
      <span class="patient-channel-badge">
        ${escapeHtml(labels[ch] || ch)}
      </span>
    `).join("");

  let telegramBadge = "";

  if(telegramLinked){

    const active =
      channels.includes("telegram");

    telegramBadge = `
      <span
        class="patient-channel-badge ${
          active
            ? "border border-success text-success"
            : "border text-muted"
        }"
        title="${
          active
            ? "Telegram collegato e attivo per i promemoria"
            : "Telegram collegato ma non abilitato nei promemoria"
        }">

        <i class="bi bi-telegram me-1"></i>
        Telegram
        ${active ? '<i class="bi bi-check-lg ms-1"></i>' : ""}

      </span>
    `;

  }else{

    telegramBadge = `
      <span
        class="patient-channel-badge border text-muted opacity-50"
        title="Telegram non collegato">

        <i class="bi bi-telegram me-1"></i>
        Telegram —

      </span>
    `;

  }

  if(
    !normalBadges
    && !telegramLinked
    && !channels.length
  ){
    return `
      <div class="patient-channel-badges">
        <span class="text-muted small">Predefiniti</span>
        ${telegramBadge}
      </div>
    `;
  }

  return `
    <div class="patient-channel-badges">
      ${normalBadges}
      ${telegramBadge}
    </div>
  `;
}

function patientPageNumbers(page,pages){

  if(pages<=1)
    return [1];

  const values=new Set([
    1,
    pages,
    page-2,
    page-1,
    page,
    page+1,
    page+2
  ]);

  return [...values]
    .filter(x=>x>=1 && x<=pages)
    .sort((a,b)=>a-b);
}


function renderPatientPagination(){

  const total=patientBrowserState.total;
  const page=patientBrowserState.page;
  const size=patientBrowserState.pageSize;
  const pages=patientBrowserState.pages;

  const first=
    total===0
      ?0
      :((page-1)*size)+1;

  const last=
    Math.min(
      page*size,
      total
    );

  const totalEl=
    document.getElementById("patients-total");

  const rangeEl=
    document.getElementById("patients-range");

  const infoEl=
    document.getElementById("patients-page-info");

  if(totalEl)
    totalEl.textContent=
      total.toLocaleString("it-IT");

  if(rangeEl)
    rangeEl.textContent=
      total
        ?`${first.toLocaleString("it-IT")}–${last.toLocaleString("it-IT")} di ${total.toLocaleString("it-IT")}`
        :"0 risultati";

  if(infoEl)
    infoEl.textContent=
      `Pagina ${page.toLocaleString("it-IT")} di ${pages.toLocaleString("it-IT")}`;

  const buttons=
    document.getElementById("patients-page-buttons");

  if(buttons){

    const numbers=
      patientPageNumbers(page,pages);

    let previous=null;

    buttons.innerHTML=
      numbers.map(n=>{

        let gap="";

        if(
          previous!==null &&
          n-previous>1
        ){
          gap='<span class="px-1 text-muted">…</span>';
        }

        previous=n;

        return `
          ${gap}
          <button
            class="btn btn-sm ${
              n===page
                ?"btn-primary"
                :"btn-outline-secondary"
            }"
            data-patient-page="${n}">
            ${n}
          </button>
        `;
      }).join("");

    buttons
      .querySelectorAll(
        "[data-patient-page]"
      )
      .forEach(btn=>{

        btn.addEventListener(
          "click",
          ()=>{
            patientBrowserState.page=
              Number(btn.dataset.patientPage);

            loadPatients();
          }
        );

      });
  }

  const firstBtn=
    document.getElementById("patients-first");

  const prevBtn=
    document.getElementById("patients-prev");

  const nextBtn=
    document.getElementById("patients-next");

  const lastBtn=
    document.getElementById("patients-last");

  if(firstBtn)
    firstBtn.disabled=page<=1;

  if(prevBtn)
    prevBtn.disabled=page<=1;

  if(nextBtn)
    nextBtn.disabled=page>=pages;

  if(lastBtn)
    lastBtn.disabled=page>=pages;
}


async function loadPatients(){

  const tbody=
    document.getElementById(
      "patients-table-body"
    );

  if(!tbody)
    return [];

  tbody.innerHTML=`
    <tr>
      <td colspan="5" class="text-muted p-4">
        <span
          class="spinner-border spinner-border-sm me-2">
        </span>
        Ricerca pazienti...
      </td>
    </tr>
  `;

  try{

    const data=
      await fetchPatientsPage();

    const patients=
      data.items||[];

    patientBrowserState.total=
      Number(data.total)||0;

    patientBrowserState.page=
      Number(data.page)||1;

    patientBrowserState.pageSize=
      Number(data.page_size)||50;

    patientBrowserState.pages=
      Math.max(
        1,
        Number(data.pages)||1
      );

    if(!patients.length){

      tbody.innerHTML=`
        <tr>
          <td colspan="5" class="text-muted p-4 text-center">
            <i class="bi bi-search me-1"></i>
            Nessun paziente corrisponde ai criteri di ricerca.
          </td>
        </tr>
      `;

      renderPatientPagination();

      return [];
    }

    tbody.innerHTML=
      patients.map(p=>{

        const name=
          [
            String(p.last_name||"").trim(),
            String(p.first_name||"").trim()
          ]
            .filter(Boolean)
            .join(" ")
          ||p.full_name
          ||`Paziente #${p.id}`;

        const email=
          p.email||"";

        const phone=
          p.phone||"";

        return `
          <tr data-patient-id="${p.id}">

            <td class="patient-name-cell">

              <div class="patient-name-main">
                ${escapeHtml(name)}
              </div>

              <div class="patient-name-meta">
                ID ${p.id}
              </div>

            </td>


            <td>

              <div class="patient-contact">

                ${
                  phone
                  ?`
                    <a href="tel:${escapeHtml(phone)}">
                      <i class="bi bi-telephone me-1"></i>
                      ${escapeHtml(phone)}
                    </a>
                  `
                  :'<span class="text-muted">Nessun telefono</span>'
                }

                ${
                  email
                  ?`
                    <a href="mailto:${escapeHtml(email)}">
                      <i class="bi bi-envelope me-1"></i>
                      ${escapeHtml(email)}
                    </a>
                  `
                  :""
                }

              </div>

            </td>


            <td>

              ${
                p.fiscal_code
                ?`<code>${escapeHtml(p.fiscal_code)}</code>`
                :'<span class="text-muted">-</span>'
              }

            </td>


            <td>

              <div class="patient-reminder-cell">

                <div class="form-check form-switch mb-0">

                  <input
                    class="form-check-input patient-reminder-toggle"
                    type="checkbox"
                    data-patient-id="${p.id}"
                    ${p.reminder_enabled!==false?"checked":""}>

                </div>

                ${patientChannelBadges(
                  p.reminder_channels,
                  p.reminder_telegram_chat_id
                )}

              </div>

            </td>


            <td class="text-end">

              <button
                type="button"
                class="btn btn-sm btn-outline-primary patient-open-btn"
                data-open-patient="${p.id}"
                title="Apri paziente">

                <i class="bi bi-chevron-right"></i>

              </button>

            </td>

          </tr>
        `;

      }).join("");


    tbody
      .querySelectorAll(
        ".patient-reminder-toggle"
      )
      .forEach(toggle=>{

        toggle.addEventListener(
          "change",
          async()=>{

            try{

              await CupApi.updatePatientReminders(
                Number(toggle.dataset.patientId),
                {
                  enabled:toggle.checked
                }
              );

            }catch(e){

              showToast(
                e.message,
                "error"
              );

              toggle.checked=
                !toggle.checked;
            }

          }
        );

      });


    tbody
      .querySelectorAll(
        "[data-open-patient]"
      )
      .forEach(btn=>{

        btn.addEventListener(
          "click",
          ()=>{

            const id=
              Number(
                btn.dataset.openPatient
              );

            /*
             * Preparazione al dettaglio paziente.
             * Se esiste gia' una funzione dedicata
             * la utilizziamo; altrimenti mostriamo
             * l'identificativo senza rompere la UI.
             */

            if(
              typeof window.OmniaPatientCardOpen===
              "function"
            ){
              window.OmniaPatientCardOpen(id);
            }
            else{
              showToast(
                `Paziente #${id}`,
                "info"
              );
            }

          }
        );

      });


    renderPatientPagination();

    return patients;

  }
  catch(e){

    tbody.innerHTML=`
      <tr>
        <td colspan="5" class="p-4">

          <div class="alert alert-danger mb-0">

            <strong>
              Impossibile caricare i pazienti.
            </strong>

            <div class="small mt-1">
              ${escapeHtml(
                e.message||"Errore imprevisto"
              )}
            </div>

          </div>

        </td>
      </tr>
    `;

    return [];
  }
}


/* CUP_PATIENT_BROWSER_EVENTS_V1 */

function initPatientBrowserEvents(){

  const search=
    document.getElementById(
      "patient-search"
    );

  if(
    search &&
    !search.dataset.patientBound
  ){

    search.dataset.patientBound="1";

    search.addEventListener(
      "input",
      ()=>{

        clearTimeout(
          patientBrowserState.timer
        );

        patientBrowserState.timer=
          setTimeout(
            ()=>{

              patientBrowserState.query=
                search.value.trim();

              patientBrowserState.page=1;

              loadPatients();

            },
            300
          );

      }
    );

  }


  const reminder=
    document.getElementById(
      "patient-reminder-filter"
    );

  if(
    reminder &&
    !reminder.dataset.patientBound
  ){

    reminder.dataset.patientBound="1";

    reminder.addEventListener(
      "change",
      ()=>{

        patientBrowserState.reminder=
          reminder.value;

        patientBrowserState.page=1;

        loadPatients();

      }
    );

  }


  const channel=
    document.getElementById(
      "patient-channel-filter"
    );

  if(
    channel &&
    !channel.dataset.patientBound
  ){

    channel.dataset.patientBound="1";

    channel.addEventListener(
      "change",
      ()=>{

        patientBrowserState.channel=
          channel.value;

        patientBrowserState.page=1;

        loadPatients();

      }
    );

  }


  const size=
    document.getElementById(
      "patient-page-size"
    );

  if(
    size &&
    !size.dataset.patientBound
  ){

    size.dataset.patientBound="1";

    size.addEventListener(
      "change",
      ()=>{

        patientBrowserState.pageSize=
          Number(size.value)||50;

        patientBrowserState.page=1;

        loadPatients();

      }
    );

  }


  const refresh=
    document.getElementById(
      "btn-refresh-patients"
    );

  if(
    refresh &&
    !refresh.dataset.patientBound
  ){

    refresh.dataset.patientBound="1";

    refresh.addEventListener(
      "click",
      loadPatients
    );

  }


  const first=
    document.getElementById(
      "patients-first"
    );

  const prev=
    document.getElementById(
      "patients-prev"
    );

  const next=
    document.getElementById(
      "patients-next"
    );

  const last=
    document.getElementById(
      "patients-last"
    );


  if(first && !first.dataset.patientBound){

    first.dataset.patientBound="1";

    first.addEventListener(
      "click",
      ()=>{

        patientBrowserState.page=1;
        loadPatients();

      }
    );
  }


  if(prev && !prev.dataset.patientBound){

    prev.dataset.patientBound="1";

    prev.addEventListener(
      "click",
      ()=>{

        if(patientBrowserState.page>1){

          patientBrowserState.page--;

          loadPatients();
        }

      }
    );
  }


  if(next && !next.dataset.patientBound){

    next.dataset.patientBound="1";

    next.addEventListener(
      "click",
      ()=>{

        if(
          patientBrowserState.page<
          patientBrowserState.pages
        ){

          patientBrowserState.page++;

          loadPatients();
        }

      }
    );
  }


  if(last && !last.dataset.patientBound){

    last.dataset.patientBound="1";

    last.addEventListener(
      "click",
      ()=>{

        patientBrowserState.page=
          patientBrowserState.pages;

        loadPatients();

      }
    );
  }


  document
    .querySelectorAll(
      "[data-patient-sort]"
    )
    .forEach(th=>{

      if(th.dataset.patientBound)
        return;

      th.dataset.patientBound="1";

      th.addEventListener(
        "click",
        ()=>{

          const field=
            th.dataset.patientSort;

          if(
            patientBrowserState.sort===
            field
          ){

            patientBrowserState.direction=
              patientBrowserState.direction==="asc"
                ?"desc"
                :"asc";
          }
          else{

            patientBrowserState.sort=
              field;

            patientBrowserState.direction=
              "asc";
          }

          patientBrowserState.page=1;

          loadPatients();

        }
      );

    });

}


/*
 * HTML esiste gia' al caricamento dello script.
 */
initPatientBrowserEvents();


async function loadCalls() {
  const tbody = document.getElementById("calls-table-body");
  try {
    const calls = await CupApi.getCalls();
    if (!calls.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="text-muted">Nessuna chiamata.</td></tr>';
      return;
    }
    tbody.innerHTML = calls.map((c) => `
      <tr>
        <td>${fmtDate(c.started_at)}</td>
        <td>${escapeHtml(c.caller_number || "-")}</td>
        <td>${escapeHtml(c.callee_number || "-")}</td>
        <td><span class="badge bg-${statusColor(c.status)}">${escapeHtml(c.status)}</span></td>
        <td>${escapeHtml(c.ai_intent || "-")}</td>
        <td>${c.ai_sentiment ? `<span class="badge ${c.ai_sentiment === "critical" ? "bg-danger" : c.ai_sentiment === "frustrated" ? "bg-warning text-dark" : c.ai_sentiment === "positive" ? "bg-success" : c.ai_sentiment === "confused" ? "bg-info text-dark" : "bg-secondary"}">${escapeHtml(c.ai_sentiment)}</span>` : "-"}</td>
        <td>${c.ai_confidence != null ? `${c.ai_confidence}%` : "-"}</td>
        <td>${c.duration_seconds ?? "-"}</td>
      </tr>`).join("");
  } catch (e) {
    handleApiError(e, tbody, 8);
  }
}

async function loadDashboardStats() {
  try {
    const useInternalBookings = bookingRuntime.mode === "internal";
    const [bookings, calls, patientsCount] = await Promise.all([
      useInternalBookings
        ? CupApi.getBookings()
        : Promise.resolve([]),

      (currentUser?.role === "admin" || currentUser?.can_phone !== false)
        ? CupApi.getCalls()
        : Promise.resolve([]),

      CupApi.getPatientsCount()
    ]);
    const today = new Date().toDateString();
    if (useInternalBookings) {
      const todayBookings = bookings.filter((b) => new Date(b.scheduled_at).toDateString() === today);
      document.getElementById("stat-bookings-today").textContent = todayBookings.length;
      document.getElementById("stat-pending").textContent = bookings.filter((b) => b.status === "pending").length;
      const confirmedToday = todayBookings.filter((b) => b.status === "confirmed" || b.status === "completed").length;
      const confirmedBox = document.getElementById("stat-bookings-confirmed"); if (confirmedBox) confirmedBox.textContent = `${confirmedToday} confermate`;
      const unconfirmed = document.getElementById("dashboard-unconfirmed"); if (unconfirmed) unconfirmed.textContent = bookings.filter((b)=>b.status === "pending").length;
      renderDashboardTodayBookings(todayBookings);
    } else if (bookingRuntime.mode === "external") {
      document.getElementById("stat-bookings-today").textContent = "Esterno";
      document.getElementById("stat-pending").textContent = "-";
    } else {
      document.getElementById("stat-pending").textContent = "-";
    }
    document.getElementById("stat-calls-active").textContent = calls.filter((c) => c.status === "active").length;
    document.getElementById("stat-patients").textContent =
      Number(patientsCount?.total)||0;
    try { const reminders = await CupApi.getReminders("failed"); const f=document.getElementById("dashboard-failed-reminders"); if(f) f.textContent=reminders.length; } catch (_) {}
    try { const followups = await CupApi.getFollowups(); const f=document.getElementById("dashboard-followup-contact"); if(f) f.textContent=followups.filter(x=>x.status==="needs_contact").length; } catch (_) {}
    await loadOperationalAnalytics();
    await loadDashboardJourneys();
  } catch (e) {
    if (e.status === 401) {
      CupApi.setToken("");
      showLogin();
    }
  }
}


function renderDashboardTodayBookings(items) {
  const box = document.getElementById("dashboard-today-bookings"); if (!box) return;
  const sorted = [...items].sort((a,b)=>new Date(a.scheduled_at)-new Date(b.scheduled_at)).slice(0,6);
  if (!sorted.length) { box.innerHTML='<div class="p-4 text-muted">Nessun appuntamento previsto oggi.</div>'; return; }
  box.innerHTML = sorted.map(b=>{
    const d=new Date(b.scheduled_at); const time=d.toLocaleTimeString("it-IT",{hour:"2-digit",minute:"2-digit"});
    const statusClass=b.status==="confirmed"?"status-confirmed":(b.status==="pending"?"status-pending":"status-confirmed");
    return `<div class="today-booking-row"><div class="today-time">${time}</div><div><div class="today-patient">${escapeHtml(b.service_name||"Appuntamento")}</div><div class="today-meta">Paziente #${b.patient_id}${b.priority==="urgent"?" · Priorità urgente":""}</div></div><div class="today-status"><span class="status-chip ${statusClass}">${escapeHtml(b.status||"-")}</span>${b.priority==="urgent"?'<span class="status-chip status-urgent">Urgente</span>':""}</div></div>`;
  }).join("");
}

const journeyLabels = {
  phone: "Telefono", sms: "SMS", web: "Web", whatsapp: "WhatsApp", telegram: "Telegram",
  handoff: "Handoff", operator: "Operatore", documents: "Documenti", chatwoot: "Chatwoot",
};
const journeyIcons = {
  phone: "bi-telephone-fill", sms: "bi-chat-square-text", web: "bi-globe2", whatsapp: "bi-whatsapp",
  telegram: "bi-telegram", handoff: "bi-arrow-left-right", operator: "bi-person-headset",
  documents: "bi-paperclip", chatwoot: "bi-headset",
};

function compactJourneySteps(steps) {
  return (steps || []).map((step, idx) => `
    <span class="dashboard-journey-step">
      <span class="dashboard-journey-icon"><i class="bi ${journeyIcons[step] || "bi-circle"}"></i></span>
      <span>${escapeHtml(journeyLabels[step] || step)}</span>
      ${idx < steps.length - 1 ? '<i class="bi bi-chevron-right dashboard-journey-arrow"></i>' : ''}
    </span>`).join("");
}

async function loadDashboardJourneys() {
  const box = document.getElementById("dashboard-journeys");
  if (!box) return;
  try {
    const journeys = await CupApi.getActiveJourneys();
    document.getElementById("stat-active-journeys").textContent = journeys.length;
    if (!journeys.length) {
      box.innerHTML = '<div class="p-3 text-muted">Nessun Journey attivo.</div>';
      return;
    }
    box.innerHTML = journeys.map((j) => `
      <div class="dashboard-journey-row">
        <div class="dashboard-journey-main">
          <div class="d-flex align-items-center gap-2 flex-wrap">
            <strong>Journey ${escapeHtml(j.id.slice(0, 8))}</strong>
            <span class="badge bg-${j.owner === "operator" ? "success" : "primary"}">${j.owner === "operator" ? "Operatore" : "AI"}</span>
            <span class="small text-muted">Origine: ${escapeHtml(journeyLabels[j.origin_channel] || j.origin_channel || "-")}</span>
          </div>
          <div class="dashboard-journey-track mt-2">${compactJourneySteps(j.steps)}</div>
          <div class="small text-muted mt-1 text-truncate">${escapeHtml(j.last_message || "Nessun messaggio")}</div>
        </div>
        <div class="dashboard-journey-actions">
          <button class="btn btn-sm btn-outline-primary" data-open-journey="${j.id}"><i class="bi bi-diagram-3"></i> Apri Journey</button>
          ${j.chatwoot?.url ? `<a class="btn btn-sm btn-warning" href="${escapeHtml(j.chatwoot.url)}" target="_blank" rel="noopener"><i class="bi bi-box-arrow-up-right"></i> Chatwoot</a>` : ""}
        </div>
      </div>`).join("");
    box.querySelectorAll("[data-open-journey]").forEach((btn) => btn.addEventListener("click", () => openJourneyFromDashboard(btn.dataset.openJourney)));
  } catch (e) {
    box.innerHTML = `<div class="p-3 text-danger">Journey non disponibili: ${escapeHtml(e.message)}</div>`;
  }
}

async function openJourneyFromDashboard(id) {
  const tab = document.querySelector('[data-tab="chatbot"]');
  if (tab) tab.click();
  await openChatSession(id);
}

document.getElementById("btn-refresh-dashboard").addEventListener("click", loadDashboardStats);
// Eventi del modulo Agende sono registrati piu avanti.

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function handleApiError(error, tbody, colspan) {
  if (error.status === 401) {
    CupApi.setToken("");
    showLogin();
  }
  tbody.innerHTML = `<tr><td colspan="${colspan}" class="text-danger">Errore: ${escapeHtml(error.message)}</td></tr>`;
}

// --- Inbox chatbot operatori ---

/*
 * Stato LIVE autorevole per le conversazioni.
 *
 * LIVE significa:
 * - sessione in handoff operatore
 * - attività recente (max 10 minuti)
 *
 * Una sessione AI/bot, chiusa o un vecchio handoff
 * non deve essere mostrata come LIVE.
 */
function cupChatSessionIsLive(session) {

  if (!session)
    return false;

  const status =
    String(session.status || "")
      .trim()
      .toLowerCase();

  if (status !== "handoff")
    return false;

  const raw =
    session.updated_at ||
    session.created_at;

  if (!raw)
    return false;

  let value =
    String(raw).trim();

  if (
    !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)
  ) {
    value += "Z";
  }

  const updated =
    new Date(value);

  if (Number.isNaN(updated.getTime()))
    return false;

  const ageMs =
    Date.now() - updated.getTime();

  return (
    ageMs >= 0 &&
    ageMs <= 10 * 60 * 1000
  );
}


async function loadChatSessions() {
  const list = document.getElementById("chat-session-list");
  try {
    try {
      const ai = await CupApi.getChatbotStatus();
      const badge = document.getElementById("chat-ai-status");
      if (badge) {
        badge.className = `badge ${ai.llm_enabled ? "bg-success" : "bg-secondary"}`;
        badge.textContent = ai.llm_enabled ? `LLM attivo${ai.model ? " · " + ai.model : ""}` : "LLM non attivo · flusso CUP";
      }
    } catch (_) {}
    const allSessions = await CupApi.getChatSessions();

    // La inbox conversazioni mostra chat reali.
    // Le sessioni telefoniche senza messaggi restano nella sezione Telefonia.
    const sessions = allSessions.filter((s) =>
      s.channel !== "phone" || Boolean((s.last_message || "").trim())
    );

    const handoff =
      sessions.filter(
        cupChatSessionIsLive
      ).length;

    updateHandoffBadge(handoff);

    if (!sessions.length) {
      list.innerHTML =
        '<div class="p-3 text-muted">Nessuna conversazione attiva.</div>';
      return;
    }

    const channelInfo = {
      web: {
        label: "Chat Web",
        icon: "bi-globe2"
      },
      whatsapp: {
        label: "WhatsApp",
        icon: "bi-whatsapp"
      },
      telegram: {
        label: "Telegram",
        icon: "bi-telegram"
      },
      sms: {
        label: "SMS",
        icon: "bi-chat-square-text"
      },
      phone: {
        label: "Telefono",
        icon: "bi-telephone"
      }
    };

    list.innerHTML = sessions.map((s) => {
      const info =
        channelInfo[s.channel] ||
        {
          label: s.channel || "Chat",
          icon: "bi-chat-dots"
        };

      const ownerLabel =
        s.status === "handoff"
          ? "OPERATORE"
          : s.status === "closed"
            ? "CHIUSA"
            : "AI";

      const ownerClass =
        s.status === "handoff"
          ? "bg-warning text-dark"
          : s.status === "closed"
            ? "bg-secondary"
            : "bg-success";

      return `
        <button
          type="button"
          class="list-group-item list-group-item-action chat-session-item ${s.id === currentChatSessionId ? "active" : ""}"
          data-chat-id="${s.id}">

          <div class="d-flex justify-content-between align-items-center">

            <strong>
              <i class="bi ${info.icon} me-1"></i>
              ${escapeHtml(info.label)}
            </strong>

            <div class="d-flex align-items-center gap-1">

              ${
                cupChatSessionIsLive(s)
                  ? `<span class="cup-session-live-badge">
                       <span class="cup-session-live-dot"></span>
                       LIVE
                     </span>`
                  : ""
              }

              <span class="badge ${ownerClass}">
                ${ownerLabel}
              </span>

            </div>

          </div>

          <div class="small text-truncate mt-2">
            ${escapeHtml(s.last_message || "Conversazione avviata")}
          </div>

          <div class="text-muted small mt-1">
            ${fmtDate(s.updated_at || s.created_at)}
          </div>

        </button>`;
    }).join("");

    list.querySelectorAll("[data-chat-id]").forEach((btn) => {
      btn.addEventListener("click", () => openChatSession(btn.dataset.chatId));
    });
  } catch (e) {
    list.innerHTML = `<div class="p-3 text-danger">${escapeHtml(e.message)}</div>`;
  }
}

async function openChatSession(id) {
  currentChatSessionId = id;
  document.getElementById("operator-reply-form").classList.add("d-none");
  document.getElementById("btn-close-chat").classList.remove("d-none");
  document.getElementById("btn-take-chat").classList.add("d-none");
  document.getElementById("btn-return-ai").classList.add("d-none");
  document.getElementById("btn-call-operator").classList.toggle("d-none", !(currentUser?.role === "admin" || currentUser?.can_phone !== false));
  document.getElementById("btn-send-sms-link").classList.remove("d-none");
  const deleteChatBtn = document.getElementById("btn-delete-chat");
  if (deleteChatBtn) {
    deleteChatBtn.disabled = currentUser?.role !== "admin";
    deleteChatBtn.classList.toggle("d-none", currentUser?.role !== "admin");
  }
  document.getElementById("chat-session-title").textContent = "Conversazione " + id.slice(0, 8);
  await loadConversationDetail();
  await loadChatMessages();
  await loadChatSessions();
}

async function loadChatMessages() {
  if (!currentChatSessionId) return;
  const box = document.getElementById("chat-operator-messages");
  try {
    const data = await CupApi.getChatMessages(currentChatSessionId);
    const messages = data.messages || [];
    const attachments = data.attachments || [];
    const items = [
      ...messages.map((m) => ({ type: "message", created_at: m.created_at, data: m })),
      ...attachments.map((a) => ({ type: "attachment", created_at: a.created_at, data: a })),
    ].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

    box.innerHTML = items.map((item) => {
      if (item.type === "attachment") {
        const a = item.data;
        return `
          <div class="operator-message user operator-attachment">
            <div><i class="bi bi-paperclip"></i> <strong>${escapeHtml(a.filename)}</strong></div>
            <div class="small text-muted">${formatBytes(a.size_bytes)} · ${fmtDate(a.created_at)}</div>
            <button class="btn btn-sm btn-outline-primary mt-2" data-download-attachment="${a.id}" data-download-filename="${escapeHtml(a.filename)}">
              <i class="bi bi-download"></i> Scarica documento
            </button>
          </div>`;
      }
      const m = item.data;
      return `
        <div class="operator-message ${escapeHtml(m.role)}">
          ${escapeHtml(m.content)}
          <span class="meta">${escapeHtml(m.role)} · ${fmtDate(m.created_at)}</span>
        </div>`;
    }).join("");

    box.querySelectorAll("[data-download-attachment]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await CupApi.downloadChatAttachment(
            currentChatSessionId,
            btn.dataset.downloadAttachment,
            btn.dataset.downloadFilename
          );
        } catch (e) {
          showToast(e.message, "error");
        }
      });
    });
    box.scrollTop = box.scrollHeight;
  } catch (e) {
    box.innerHTML = `<div class="text-danger">${escapeHtml(e.message)}</div>`;
  }
}


function journeyIcon(node) {
  const ch = node.channel || node.type;
  return ({
    phone: "bi-telephone-fill", sms: "bi-chat-square-text-fill", web: "bi-globe2",
    whatsapp: "bi-whatsapp", telegram: "bi-telegram", chatwoot: "bi-headset",
    attachment: "bi-paperclip", handoff: "bi-person-arms-up", call: "bi-telephone-forward-fill",
    session: "bi-play-circle-fill",
  })[ch] || "bi-circle-fill";
}

function journeyClass(node) {
  const ch = node.channel || node.type || "default";
  return `journey-${String(ch).replace(/[^a-z0-9_-]/gi, "-")}`;
}

function renderJourney(data) {
  const panel = document.getElementById("chat-journey-panel");
  const track = document.getElementById("journey-track");
  document.getElementById("journey-origin").textContent = data.origin_channel || "-";
  document.getElementById("journey-current").textContent = data.current_channel || "-";
  document.getElementById("journey-id").textContent = data.id || "-";
  const nodes = data.journey || [];
  if (!nodes.length) {
    panel.classList.add("d-none");
    return;
  }
  panel.classList.remove("d-none");
  track.innerHTML = nodes.map((node, index) => `
    <div class="journey-node ${journeyClass(node)}">
      <div class="journey-dot"><i class="bi ${journeyIcon(node)}"></i></div>
      ${index < nodes.length - 1 ? '<div class="journey-line"></div>' : ''}
      <div class="journey-node-body">
        <strong>${escapeHtml(node.label || node.type)}</strong>
        <span>${escapeHtml(node.detail || "")}</span>
        <small>${node.created_at ? fmtDate(node.created_at) : ""}</small>
      </div>
    </div>`).join("");
}

function updateConversationSupervisor(data) {
  const strip = document.getElementById("chat-control-strip");
  const dot = document.getElementById("chat-control-dot");
  const title = document.getElementById("chat-control-title");
  const description = document.getElementById("chat-control-description");

  if (!strip || !title || !description) return;

  if (!currentChatSessionId || !data) {
    strip.classList.add("d-none");
    return;
  }

  strip.classList.remove("d-none");

  const owner = String(data.owner || "llm").toLowerCase();

  if (owner === "operator") {
    strip.classList.add("operator-control");
    strip.classList.remove("ai-control");

    if (dot) dot.className = "chat-control-dot operator";

    title.textContent = "Operatore in controllo";
    description.textContent =
      "L'AI è sospesa per questa conversazione";
  } else {
    strip.classList.add("ai-control");
    strip.classList.remove("operator-control");

    if (dot) dot.className = "chat-control-dot ai";

    title.textContent = "AI in controllo";
    description.textContent =
      "Conversazione gestita automaticamente";
  }

  const take = document.getElementById("btn-take-chat");
  const give = document.getElementById("btn-return-ai");
  const replyForm = document.getElementById("operator-reply-form");

  const operatorControl =
    owner === "operator" ||
    owner === "human";

  if (take) {
    take.classList.toggle("d-none", operatorControl);
  }

  if (give) {
    give.classList.toggle("d-none", !operatorControl);
  }

  if (replyForm) {
    replyForm.classList.toggle("d-none", !operatorControl);
  }

  console.log(
    "[CUP Supervisor]",
    currentChatSessionId,
    "owner=",
    owner,
    "operatorControl=",
    operatorControl
  );
}


function applyConversationLiveState(data){

  const closed =
    String(data?.status || "").toLowerCase()
    === "closed";

  const stateHost =
    document.getElementById(
      "chat-channel-summary"
    );

  if(stateHost){

    let badge =
      document.getElementById(
        "conversation-live-badge"
      );

    if(!badge){

      badge =
        document.createElement("span");

      badge.id =
        "conversation-live-badge";

      badge.className =
        "cup-conversation-state-badge ms-2";

      stateHost.appendChild(
        badge
      );
    }

    if(closed){

      badge.className =
        "cup-conversation-state-badge closed ms-2";

      badge.innerHTML =
        '<span>CHIUSA</span>';

    }else{

      badge.className =
        "cup-conversation-state-badge live ms-2";

      badge.innerHTML =
        '<span class="cup-live-dot"></span><span>LIVE</span>';
    }
  }

  const actionIds = [
    "btn-take-chat",
    "btn-return-ai",
    "btn-call-operator",
    "btn-send-sms-link",
    "btn-sync-chatwoot",
    "btn-close-chat"
  ];

  actionIds.forEach(id=>{

    const el =
      document.getElementById(id);

    if(!el)
      return;

    if(closed){
      el.classList.add("d-none");
      el.disabled = true;
    }else{
      el.disabled = false;
    }

  });


  const replyForm =
    document.getElementById(
      "operator-reply-form"
    );

  if(replyForm){
    replyForm.classList.toggle(
      "d-none",
      closed
    );
  }


  const summary =
    document.getElementById(
      "chat-channel-summary"
    );

  if(closed && summary){

    const current =
      String(summary.textContent || "");

    if(
      !current.includes(
        "Conversazione chiusa"
      )
    ){
      summary.textContent =
        "Conversazione chiusa · sola consultazione · "
        + current;
    }
  }
}


async function loadConversationDetail() {
  if (!currentChatSessionId) return;
  const summary = document.getElementById("chat-channel-summary");
  const openCw = document.getElementById("btn-open-chatwoot");
  const syncCw = document.getElementById("btn-sync-chatwoot");
  try {
    const data = await CupApi.getConversationDetail(currentChatSessionId);

    updateConversationSupervisor(data);

    const channels = (data.channels || []).map((c) => `${c.channel}${c.display_name ? ` · ${c.display_name}` : ""}`).join(" | ");
    summary.textContent = `Owner: ${data.owner} · Origine: ${data.origin_channel || "-"} · Corrente: ${data.current_channel || "-"} · Canali: ${channels || "web"}`;
    renderJourney(data);

    applyConversationLiveState(data);

    if (data.chatwoot && data.chatwoot.url) {
      openCw.href = data.chatwoot.url;
      openCw.classList.remove("d-none");
      syncCw.classList.add("d-none");
    } else {
      openCw.classList.add("d-none");
      if (data.chatwoot_enabled) syncCw.classList.remove("d-none");
      else syncCw.classList.add("d-none");
    }
  } catch (e) {
    updateConversationSupervisor(null);
    summary.textContent = "Dettaglio omnichannel non disponibile";
    document.getElementById("chat-journey-panel").classList.add("d-none");
    openCw.classList.add("d-none");
    syncCw.classList.add("d-none");
  }
}

document.getElementById("btn-take-chat").addEventListener("click", async () => {
  if (!currentChatSessionId) return;
  try {
    await CupApi.setConversationOwner(currentChatSessionId, "operator");
    await loadConversationDetail();
    await loadChatMessages();
    await loadChatSessions();
  } catch (e) { showToast(e.message, "error"); }
});

document.getElementById("btn-return-ai").addEventListener("click", async () => {
  if (!currentChatSessionId) return;
  try {
    await CupApi.setConversationOwner(currentChatSessionId, "llm");
    await loadConversationDetail();
    await loadChatMessages();
    await loadChatSessions();
  } catch (e) { showToast(e.message, "error"); }
});

document.getElementById("btn-call-operator").addEventListener("click", async () => {
  if (!currentChatSessionId) return;
  try {
    await CupApi.requestHandoff(currentChatSessionId, "Escalation telefonica da dashboard", true);
    await loadConversationDetail();
    await loadChatMessages();
    await loadChatSessions();
  } catch (e) { showToast(e.message, "error"); }
});

document.getElementById("btn-send-sms-link").addEventListener("click", async () => {
  if (!currentChatSessionId) return;
  try {
    const detail = await CupApi.getConversationDetail(currentChatSessionId);
    const autoPhone = (detail.channels || []).find((c) => c.channel === "phone")?.external_id
      || (detail.channels || []).find((c) => c.channel === "whatsapp")?.external_id || "";
    const phone = autoPhone || window.prompt("Numero telefonico a cui inviare il link SMS:", "") || "";
    if (!phone) return;
    const result = await CupApi.sendSmsLink(currentChatSessionId, phone);
    if (result.sent) {
      showToast(`SMS inviato a ${result.phone}.`, "success");
    } else {
      alert(`Gateway SMS non configurato: link generato per collaudo:\n${result.url}`);
    }
    await loadConversationDetail();
    await loadChatMessages();
  } catch (e) { showToast(e.message, "error"); }
});

document.getElementById("btn-sync-chatwoot").addEventListener("click", async () => {
  if (!currentChatSessionId) return;
  try {
    await CupApi.syncChatwoot(currentChatSessionId);
    await loadConversationDetail();
  } catch (e) { showToast(e.message, "error"); }
});

function formatBytes(bytes) {
  const n = Number(bytes || 0);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

document.getElementById("operator-reply-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!currentChatSessionId) return;
  const input = document.getElementById("operator-reply-text");
  const text = input.value.trim();
  if (!text) return;
  try {
    await CupApi.replyChat(currentChatSessionId, text);
    input.value = "";
    await loadChatMessages();
    await loadChatSessions();
  } catch (e) {
    showToast(e.message, "error");
  }
});

function resetChatSelection() {
  currentChatSessionId = null;
  updateConversationSupervisor(null);
  document.getElementById("chat-session-title").textContent = "Seleziona una conversazione";
  document.getElementById("chat-channel-summary").textContent = "";
  document.getElementById("chat-operator-messages").innerHTML = '<div class="p-4 text-muted">Seleziona una conversazione dalla lista.</div>';
  document.getElementById("chat-journey-panel").classList.add("d-none");
  document.getElementById("operator-reply-form").classList.add("d-none");
  ["btn-close-chat","btn-take-chat","btn-return-ai","btn-call-operator","btn-send-sms-link","btn-open-chatwoot","btn-sync-chatwoot"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.classList.add("d-none");
  });
  const del = document.getElementById("btn-delete-chat");
  if (del) { del.disabled = true; del.classList.add("d-none"); }
}

document.getElementById("btn-delete-chat")?.addEventListener("click", async () => {
  if (!currentChatSessionId || currentUser?.role !== "admin") return;
  const shortId = currentChatSessionId.slice(0, 8);
  if (!window.confirm(`Cancellare definitivamente la conversazione ${shortId} e i relativi allegati?`)) return;
  try {
    await CupApi.deleteChat(currentChatSessionId);
    resetChatSelection();
    await loadChatSessions();
    showToast("Conversazione cancellata.", "success");
  } catch (e) {
    showToast(e.message, "error");
  }
});



document.getElementById("btn-close-chat").addEventListener("click", async () => {
  if (!currentChatSessionId) return;
  try {
    await CupApi.closeChat(currentChatSessionId);
    await loadChatSessions();
  } catch (e) {
    showToast(e.message, "error");
  }
});

document.getElementById("btn-refresh-chats").addEventListener("click", async () => {
  await loadChatSessions();
  await loadChatMessages();
});

async function refreshChatBadge() {
  if (!CupApi.token()) return;
  try {
    const sessions = await CupApi.getChatSessions();
    updateHandoffBadge(
      sessions.filter(
        cupChatSessionIsLive
      ).length
    );
  } catch (_) {}
}

function updateHandoffBadge(count) {
  const badge = document.getElementById("chat-handoff-badge");
  badge.textContent = count;
  badge.classList.toggle("d-none", !count);
}

chatRefreshTimer = setInterval(() => {
  if (!operatorApp.classList.contains("d-none")) {
    refreshChatBadge();
    if (!document.getElementById("tab-chatbot").classList.contains("d-none")) {
      loadChatSessions();
      loadChatMessages();
    }
  }
}, 5000);

function handoffStatusBadge(status) {
  return { waiting_operator:"warning", ringing:"danger", accepted:"success", callback_requested:"info", returned_to_ai:"primary", voicemail:"secondary" }[status] || "secondary";
}
function handoffSourceLabel(source) { return ({livekit:"LiveKit / Voice AI",phone:"Telefono",voice:"Voce AI",web:"Web",whatsapp:"WhatsApp",telegram:"Telegram",chat:"Chat"})[source] || source || "Canale"; }
function handoffCard(h, compact=false) {
  const expires = h.expires_at ? Math.max(0, Math.round((new Date(h.expires_at)-Date.now())/1000)) : null;
  return `<div class="handoff-row" data-handoff-row="${h.id}"><div class="handoff-main"><div class="d-flex gap-2 align-items-center flex-wrap"><strong>${escapeHtml(h.caller_number || "Utente")}</strong><span class="badge bg-${handoffStatusBadge(h.status)}">${escapeHtml(h.status)}</span><span class="badge bg-light text-dark">${escapeHtml(handoffSourceLabel(h.source))}</span>${expires!==null?`<span class="small text-danger"><i class="bi bi-hourglass-split"></i> ${expires}s</span>`:""}</div><div class="small mt-1">${escapeHtml(h.reason || "Richiesta operatore")}</div>${!compact && h.summary?`<div class="small text-muted handoff-summary mt-1">${escapeHtml(h.summary)}</div>`:""}<div class="small text-muted mt-1">Journey ${escapeHtml((h.session_id||"").slice(0,8))}${h.call_id?` · Chiamata #${h.call_id}`:""} · ${fmtDate(h.requested_at)}</div></div><div class="handoff-actions"><button class="btn btn-sm btn-success" data-handoff-accept="${h.id}"><i class="bi bi-telephone-inbound"></i> Accetta</button><button class="btn btn-sm btn-outline-secondary" data-handoff-reject="${h.id}">Rifiuta</button><button class="btn btn-sm btn-outline-info" data-handoff-callback="${h.id}">Callback</button><button class="btn btn-sm btn-outline-primary" data-open-handoff-journey="${h.session_id}">Journey</button></div></div>`;
}
function wireHandoffActions(root) {
  root.querySelectorAll("[data-handoff-accept]").forEach(b=>b.onclick=()=>actOnHandoff("accept",b.dataset.handoffAccept));
  root.querySelectorAll("[data-handoff-reject]").forEach(b=>b.onclick=()=>actOnHandoff("reject",b.dataset.handoffReject));
  root.querySelectorAll("[data-handoff-callback]").forEach(b=>b.onclick=()=>actOnHandoff("callback",b.dataset.handoffCallback));
  root.querySelectorAll("[data-open-handoff-journey]").forEach(b=>b.onclick=()=>openJourneyFromDashboard(b.dataset.openHandoffJourney));
}
async function actOnHandoff(action, id) {
  try {
    let result = null;

    if (action === "accept") {
      result = await CupApi.acceptHandoff(id);
    } else if (action === "reject") {
      await CupApi.rejectHandoff(id);
    } else if (action === "callback") {
      await CupApi.callbackHandoff(id);
    }

    await loadHandoffQueue();
    await loadOperatorPresence();
    await loadDashboardJourneys();

    // Dopo ACCETTA apri subito la conversazione corretta.
    if (action === "accept" && result?.handoff?.session_id) {
      const sessionId = result.handoff.session_id;

      currentChatSessionId = sessionId;

      // Attiva tab Conversazioni
      document.querySelectorAll(".tab-content").forEach((t) =>
        t.classList.add("d-none")
      );

      document.querySelectorAll("[data-tab]").forEach((l) =>
        l.classList.remove("active")
      );

      document
        .getElementById("tab-chatbot")
        ?.classList.remove("d-none");

      document
        .querySelector('[data-tab="chatbot"]')
        ?.classList.add("active");

      // Carica lista, messaggi e stato owner.
      await loadChatSessions();
      await loadChatMessages();
      await loadConversationDetail();

      // Porta il composer in primo piano.
      const input = document.getElementById("operator-reply-text");
      const form = document.getElementById("operator-reply-form");

      form?.classList.remove("d-none");

      setTimeout(() => {
        input?.focus();
      }, 100);

      showToast("Richiesta presa in carico.", "success");
    }

  } catch (e) {
    showToast(e.message, "error");
  }
}

const cupSeenHandoffAlerts = new Set();

function cupPlayHandoffAlert() {
  try {
    const AudioContext =
      window.AudioContext || window.webkitAudioContext;

    if (!AudioContext) return;

    const ctx = new AudioContext();

    const playTone = (frequency, start, duration) => {
      const oscillator = ctx.createOscillator();
      const gain = ctx.createGain();

      oscillator.type = "sine";
      oscillator.frequency.value = frequency;

      gain.gain.setValueAtTime(0.0001, ctx.currentTime + start);
      gain.gain.exponentialRampToValueAtTime(
        0.18,
        ctx.currentTime + start + 0.02
      );
      gain.gain.exponentialRampToValueAtTime(
        0.0001,
        ctx.currentTime + start + duration
      );

      oscillator.connect(gain);
      gain.connect(ctx.destination);

      oscillator.start(ctx.currentTime + start);
      oscillator.stop(ctx.currentTime + start + duration);
    };

    // Doppio tono breve, riconoscibile ma non invasivo.
    playTone(740, 0.00, 0.18);
    playTone(980, 0.24, 0.22);

    setTimeout(() => {
      try { ctx.close(); } catch (_) {}
    }, 1000);

  } catch (e) {
    console.warn("Alert acustico handoff non disponibile", e);
  }
}

async function loadHandoffQueue() {
  // Funziona sia con JWT sia con login DEV tramite X-Dev-Role.
  // CupApi.getHandoffQueue() applica gia' gli header di autenticazione.
  try {
    const rows = await CupApi.getHandoffQueue();
    const firstHandoffLoad = handoffQueueIds.size === 0;
    const previous = new Set(handoffQueueIds);

    handoffQueueIds = new Set(rows.map(x => x.id));

    // Al primo caricamento memorizziamo la coda senza generare allarmi.
    // Dai caricamenti successivi individuiamo soltanto i nuovi handoff.
    const newRows = firstHandoffLoad
      ? []
      : rows.filter(x => !previous.has(x.id));
    const count = rows.length;
    ["handoff-queue-badge"].forEach(id=>{const e=document.getElementById(id); if(e){e.textContent=count;e.classList.toggle("d-none",!count);}});
    ["dashboard-handoff-count","handoff-tab-count","notif-badge","dashboard-priority-handoffs"].forEach(id=>{const e=document.getElementById(id);if(e){e.textContent=count;if(id==="notif-badge")e.style.display=count?"inline-block":"none";}});
    const dash=document.getElementById("dashboard-handoff-queue"), list=document.getElementById("handoff-queue-list");
    if(dash){dash.innerHTML=count?rows.slice(0,4).map(h=>handoffCard(h,true)).join(""):'<div class="p-3 text-muted">Nessuna richiesta in attesa.</div>';wireHandoffActions(dash);}
    if(list){list.innerHTML=count?rows.map(h=>handoffCard(h,false)).join(""):'<div class="p-3 text-muted">Nessuna richiesta in attesa.</div>';wireHandoffActions(list);}
    newRows.forEach(h => {
      // Ulteriore protezione contro notifiche duplicate.
      if (cupSeenHandoffAlerts.has(h.id)) return;

      cupSeenHandoffAlerts.add(h.id);

      // Segnale acustico operatore.
      cupPlayHandoffAlert();

      // Notifica desktop, se autorizzata.
      if ("Notification" in window &&
          Notification.permission === "granted") {
        new Notification("CUP · richiesta operatore", {
          body:
            `${handoffSourceLabel(h.source)} · ` +
            `${h.caller_number || "utente"}\n` +
            `${h.reason || "Richiesta assistenza"}`
        });
      }
    });
  } catch(_) {}
}
async function loadOperatorPresence(){const box=document.getElementById("operator-presence-list");if(!box)return;try{const rows=await CupApi.getOperatorPresence();box.innerHTML=rows.length?rows.map(p=>`<div class="list-group-item d-flex justify-content-between align-items-center"><span>${escapeHtml(p.full_name)}</span><span class="badge bg-${p.status==="available"?"success":p.status==="busy"?"warning":"secondary"}">${escapeHtml(p.status)}</span></div>`).join(""):'<div class="p-3 text-muted">Nessun operatore con presenza impostata.</div>';}catch(e){box.innerHTML=`<div class="p-3 text-danger">${escapeHtml(e.message)}</div>`;}}
function beepHandoff(){try{const ctx=new (window.AudioContext||window.webkitAudioContext)();const o=ctx.createOscillator(),g=ctx.createGain();o.connect(g);g.connect(ctx.destination);o.frequency.value=880;g.gain.value=.08;o.start();setTimeout(()=>{o.stop();ctx.close();},220);}catch(_){} }
function notifyHandoff(h){beepHandoff();if("Notification" in window && Notification.permission==="granted"){new Notification("CUP · richiesta operatore",{body:`${handoffSourceLabel(h.source)} · ${h.caller_number||"utente"}\n${h.reason||"Richiesta assistenza"}`});}}
function initHandoffRealtime(){
  if(handoffQueueTimer) clearInterval(handoffQueueTimer);

  // Il polling HTTP funziona anche con X-Dev-Role.
  handoffQueueTimer = setInterval(loadHandoffQueue, 3000);

  // Caricamento immediato: non aspettiamo i primi 3 secondi.
  loadHandoffQueue();

  // Il WebSocket attuale autentica esclusivamente tramite JWT.
  // In modalita' DEV lasciamo lavorare il polling.
  const token = CupApi.token();

  if (!token) {
    try { handoffWs?.close(); } catch (_) {}
    handoffWs = null;
    return;
  }

  try {
    handoffWs?.close();

    handoffWs = new WebSocket(
      window.CUP_CONFIG.WS_HANDOFFS_URL +
      "?token=" +
      encodeURIComponent(token)
    );

    handoffWs.onmessage = () => loadHandoffQueue();

    handoffWs.onclose = () =>
      setTimeout(() => {
        if (CupApi.token()) initHandoffRealtime();
      }, 4000);

  } catch (_) {}
}
document.getElementById("btn-refresh-handoffs")?.addEventListener("click",()=>{loadHandoffQueue();loadOperatorPresence();});
document.getElementById("btn-enable-handoff-notifications")?.addEventListener("click",async()=>{if("Notification" in window)await Notification.requestPermission();});
document.getElementById("operator-presence")?.addEventListener("change",async(e)=>{try{localStorage.setItem("cup_operator_presence",e.target.value);await CupApi.setOperatorPresence(e.target.value);loadOperatorPresence();}catch(err){showToast(err.message, "error");}});






document.getElementById("btn-clear-chat-history")?.addEventListener("click", async () => {
  if (currentUser?.role !== "admin") return;

  if (!window.confirm(
    "Vuoi cancellare tutte le conversazioni omnicanale?\n\n" +
    "Saranno eliminati chat, messaggi e allegati associati."
  )) {
    return;
  }

  if (!window.confirm(
    "Conferma definitiva: cancellare tutte le conversazioni?"
  )) {
    return;
  }

  try {
    const result = await CupApi.clearChatHistory();

    resetChatSelection();

    await loadChatSessions();
    await loadHandoffQueue();

    showToast(
      `Conversazioni cancellate: ${result?.deleted ?? 0}`,
      "success"
    );

  } catch (e) {
    showToast(
      e.message || "Errore durante la cancellazione.",
      "error"
    );
  }
});



document.getElementById("btn-refresh-calls")?.addEventListener(
  "click",
  () => loadCalls()
);


document.getElementById("btn-clear-call-history")?.addEventListener(
  "click",
  async () => {

    if (currentUser?.role !== "admin") {
      showToast(
        "Operazione consentita solo agli amministratori.",
        "error"
      );
      return;
    }

    const confirmed = window.confirm(
      "Vuoi cancellare tutto lo storico chiamate?\n\n" +
      "Le chiamate registrate verranno eliminate definitivamente."
    );

    if (!confirmed) return;

    const finalConfirmed = window.confirm(
      "Conferma definitiva: cancellare tutte le chiamate?"
    );

    if (!finalConfirmed) return;

    try {

      const result = await CupApi.clearCallHistory();

      await loadCalls();

      showToast(
        `Chiamate cancellate: ${result?.deleted ?? 0}`,
        "success"
      );

    } catch (e) {

      showToast(
        e.message || "Errore durante la cancellazione.",
        "error"
      );

    }
  }
);


bootstrapAuth();


// --- Impostazioni centralizzate v1.0.12 ---
const settingsSectionTitles = {
  general: ["Generale", "URL pubblico, catalogo, upload e durata link"],
  asterisk: ["Asterisk / AMI", "Telefonia, handoff e interno operatore"],
  telegram: ["Telegram", "Bot API e sicurezza webhook"],
  whatsapp: ["WhatsApp", "Meta WhatsApp Business Cloud API"],
  chatwoot: ["Chatwoot", "Inbox operatore e sincronizzazione conversazioni"],
  sms: ["SMS", "Gateway per il passaggio telefono → web"],
  reminders: ["Promemoria appuntamenti", "Invii automatici, conferma paziente, retry e canali"],
  previsit: ["Pre-visita & Check-in", "Questionari, consensi e accoglienza digitale"],
  care: ["Follow-up & Recall", "Continuità di cura dopo la visita e richiami periodici"],
  payments: ["Pagamenti", "Richieste di pagamento e provider esterno"],
  signatures: ["Firma documentale", "Invio PDF, firma semplice e audit trail"],
  llm: ["LLM / AI", "Endpoint OpenAI-compatible e modello"],
  livekit: ["LiveKit", "Canale voce AI"],
  booking: ["Prenotazioni esercizio", "Scegli modulo CUP, gestionale esterno oppure solo chatbot"],
  calendar_google: ["Google Calendar", "OAuth 2.0 per sincronizzazione agende mediche"],
  calendar_microsoft365: ["Microsoft 365", "Microsoft Graph per sincronizzazione agende mediche"],
};
const settingsSectionIcons = {
  general: "bi-sliders", asterisk: "bi-telephone", telegram: "bi-telegram", whatsapp: "bi-whatsapp",
  chatwoot: "bi-headset", sms: "bi-chat-square-text", reminders: "bi-alarm", previsit: "bi-person-check", care: "bi-arrow-repeat", payments: "bi-credit-card", signatures: "bi-pen", llm: "bi-stars", livekit: "bi-mic",
  booking: "bi-calendar2-check", calendar_google: "bi-google", calendar_microsoft365: "bi-microsoft",
};

function settingControl(field) {
  const id = `setting-${field.key}`;

  if(field.key === "CLINIC_LOGO_PATH"){
    const configured = !!field.value;

    return `
      <div class="mb-3 clinic-logo-setting">

        <label class="form-label">
          Logo struttura sanitaria
        </label>

        <div
          id="clinic-logo-preview-wrap"
          class="${configured ? "" : "d-none"} mb-2">

          <div
            class="border rounded bg-light p-3 text-center">

            <img
              id="clinic-logo-preview"
              src="/api/settings/public/logo?v=${Date.now()}"
              alt="Logo struttura"
              style="max-width:260px;max-height:90px;object-fit:contain">

          </div>

        </div>

        <div class="input-group">

          <input
            id="clinic-logo-file"
            class="form-control"
            type="file"
            accept="image/png,image/jpeg,image/webp,image/svg+xml">

          <button
            id="btn-upload-clinic-logo"
            type="button"
            class="btn btn-outline-primary">
            <i class="bi bi-upload"></i>
            Carica
          </button>

        </div>

        <div class="form-text">
          PNG, JPG, WEBP o SVG. Massimo 2 MB.
        </div>

        <button
          id="btn-delete-clinic-logo"
          type="button"
          class="btn btn-sm btn-outline-danger mt-2
                 ${configured ? "" : "d-none"}">
          <i class="bi bi-trash"></i>
          Rimuovi logo
        </button>

      </div>
    `;
  }
  if (field.key === "HANDOFF_MODE") {
    const options = [["manual","Manuale · accettazione obbligatoria"],["auto_answer","Auto-answer · primo disponibile"],["ring_group","Ring group · notifica tutti, vince il primo"]];
    return `<div class="mb-3"><label class="form-label" for="${id}">${escapeHtml(field.label)}</label><select class="form-select setting-input" id="${id}" data-setting-key="${field.key}" data-setting-type="string">${options.map(([v,l])=>`<option value="${v}" ${field.value===v?"selected":""}>${l}</option>`).join("")}</select><div class="form-text font-monospace">${escapeHtml(field.key)}</div></div>`;
  }
  if (field.key === "HANDOFF_TIMEOUT_ACTION") {
    const options = [["callback","Richiedi callback"],["return_ai","Torna all'AI"],["keep_waiting","Resta in coda"],["voicemail","Messaggio / voicemail"]];
    return `<div class="mb-3"><label class="form-label" for="${id}">${escapeHtml(field.label)}</label><select class="form-select setting-input" id="${id}" data-setting-key="${field.key}" data-setting-type="string">${options.map(([v,l])=>`<option value="${v}" ${field.value===v?"selected":""}>${l}</option>`).join("")}</select><div class="form-text font-monospace">${escapeHtml(field.key)}</div></div>`;
  }
  if (field.key === "BOOKING_MODE") {
    const options = [
      ["internal", "Modulo Agende CUP interno"],
      ["external", "Gestionale prenotazioni esterno"],
      ["chatbot_only", "Solo chatbot · nessun modulo prenotazioni"],
    ];
    return `<div class="mb-3"><label class="form-label" for="${id}">${escapeHtml(field.label)}</label><select class="form-select setting-input" id="${id}" data-setting-key="${field.key}" data-setting-type="string">${options.map(([v,l])=>`<option value="${v}" ${field.value===v?"selected":""}>${l}</option>`).join("")}</select><div class="form-text font-monospace">${escapeHtml(field.key)}</div></div>`;
  }
  if (field.key === "PAYMENT_PROVIDER") {
    const options = [["manual","Manuale · nessun dato carta nel CUP"],["stripe","Stripe Checkout ospitato"],["external","Provider esterno tramite URL"]];
    return `<div class="mb-3"><label class="form-label" for="${id}">${escapeHtml(field.label)}</label><select class="form-select setting-input" id="${id}" data-setting-key="${field.key}" data-setting-type="string">${options.map(([v,l])=>`<option value="${v}" ${field.value===v?"selected":""}>${l}</option>`).join("")}</select><div class="form-text font-monospace">${escapeHtml(field.key)}</div></div>`;
  }
  if (field.type === "boolean") {
    return `<div class="form-check form-switch mt-2"><input class="form-check-input setting-input" type="checkbox" id="${id}" data-setting-key="${field.key}" ${field.value ? "checked" : ""}><label class="form-check-label" for="${id}">${escapeHtml(field.label)}</label></div>`;
  }
  const type = field.secret ? "password" : (field.type === "integer" || field.type === "number") ? "number" : "text";
  const step = field.type === "number" ? ' step="0.1"' : "";
  const placeholder = field.secret && field.configured ? "Configurato · lascia vuoto per mantenere" : "";
  return `<div class="mb-3"><label class="form-label" for="${id}">${escapeHtml(field.label)}</label><div class="input-group"><input class="form-control setting-input" id="${id}" type="${type}"${step} data-setting-key="${field.key}" data-setting-type="${field.type}" value="${field.secret ? "" : escapeHtml(field.value ?? "")}" placeholder="${escapeHtml(placeholder)}">${field.secret ? `<button class="btn btn-outline-secondary" type="button" data-toggle-secret="${id}" title="Mostra/nascondi"><i class="bi bi-eye"></i></button>` : ""}</div><div class="form-text font-monospace">${escapeHtml(field.key)}${field.secret && field.configured ? " · valore presente" : ""}</div></div>`;
}

async function loadSettings() {
  const container = document.getElementById("settings-container");
  if (!container || currentUser?.role !== "admin") return;
  try {
    const data = await CupApi.getSettings();
    const sectionMap = Object.fromEntries(data.sections.map(x=>[x.section,x]));
    const groups = [
      ["1. Esercizio", "Identità, modalità prenotazioni e regole generali", ["general","booking"]],
      ["2. Canali paziente", "WhatsApp, Telegram, SMS e inbox Chatwoot", ["whatsapp","telegram","sms","chatwoot"]],
      ["3. Voce & AI", "Asterisk, LiveKit, LLM e passaggio all'operatore", ["asterisk","livekit","llm"]],
      ["4. Percorso paziente", "Promemoria, pre-visita, check-in, follow-up e recall", ["reminders","previsit","care"]],
      ["5. Calendari", "Sincronizzazione Google Calendar e Microsoft 365", ["calendar_google","calendar_microsoft365"]],
      ["6. Pagamenti & documenti", "Provider di pagamento e firma documentale", ["payments","signatures"]],
    ];
    const card=(section)=>{const meta=settingsSectionTitles[section.section]||[section.section,""];return `<div class="card settings-card" data-settings-section="${section.section}"><div class="card-header settings-card-header"><div><i class="bi ${settingsSectionIcons[section.section]||"bi-gear"}"></i><strong>${escapeHtml(meta[0])}</strong><div class="small text-muted">${escapeHtml(meta[1])}</div></div><button class="btn btn-sm btn-outline-primary" type="button" data-test-settings="${section.section}"><i class="bi bi-activity"></i> Test</button></div><div class="card-body">${section.fields.map(settingControl).join("")}${section.section==="chatwoot"?`<div class="border rounded-3 p-3 mt-3 bg-light" id="chatwoot-inline-panel"><div class="d-flex justify-content-between align-items-center mb-2"><strong>Console Chatwoot</strong><span class="badge bg-secondary" id="chatwoot-inline-status">Verifica...</span></div><div class="small text-muted mb-3" id="chatwoot-inline-info">Controllo configurazione in corso...</div><div class="d-flex flex-wrap gap-2"><a class="btn btn-sm btn-warning d-none" target="_blank" rel="noopener" id="chatwoot-inline-open"><i class="bi bi-box-arrow-up-right"></i> Apri Chatwoot</a><button class="btn btn-sm btn-outline-primary" type="button" id="chatwoot-inline-refresh"><i class="bi bi-arrow-clockwise"></i> Stato</button><button class="btn btn-sm btn-outline-secondary" type="button" id="chatwoot-inline-webhook"><i class="bi bi-link-45deg"></i> Configura webhook</button></div></div>`:""}<div class="settings-test-result small" data-test-result="${section.section}"></div></div></div>`};
    container.innerHTML = groups.map(([title,desc,keys],idx)=>`<div class="setup-group"><div class="setup-group-heading"><span class="setup-step">${idx+1}</span><div><h5 class="mb-0">${title.replace(/^\d+\.\s*/,"")}</h5><div class="small text-muted">${desc}</div></div></div><div class="settings-grid">${keys.filter(k=>sectionMap[k]).map(k=>card(sectionMap[k])).join("")}</div></div>`).join("");
    container.querySelectorAll("[data-toggle-secret]").forEach((btn) => btn.addEventListener("click", () => {
      const input = document.getElementById(btn.dataset.toggleSecret);
      input.type = input.type === "password" ? "text" : "password";
      btn.querySelector("i").className = `bi ${input.type === "password" ? "bi-eye" : "bi-eye-slash"}`;
    }));
    container.querySelectorAll("[data-test-settings]").forEach((btn) => btn.addEventListener("click", () => testSettingsSection(btn.dataset.testSettings, btn)));
    wireChatwootInlineSettings();
    wireClinicLogoSettings();
    loadOperatorsAdmin();
    loadTrainingSamplesAdmin();
  } catch (e) {
    container.innerHTML = `<div class="alert alert-danger">${escapeHtml(e.message)}</div>`;
  }
}

async function testSettingsSection(section, button) {
  const result = document.querySelector(`[data-test-result="${section}"]`);
  button.disabled = true;
  result.className = "settings-test-result small text-muted";
  result.textContent = "Test in corso...";
  try {
    const data = await CupApi.testSettings(section);
    result.className = `settings-test-result small ${data.ok ? "text-success" : "text-danger"}`;
    result.innerHTML = `<i class="bi ${data.ok ? "bi-check-circle" : "bi-x-circle"}"></i> ${escapeHtml(data.message || (data.ok ? "OK" : "Errore"))}`;
  } catch (e) {
    result.className = "settings-test-result small text-danger";
    result.textContent = e.message;
  } finally { button.disabled = false; }
}

const saveSettingsButton = document.getElementById("btn-save-settings");
if (saveSettingsButton) saveSettingsButton.addEventListener("click", async () => {
  const alertBox = document.getElementById("settings-alert");
  const values = {};
  document.querySelectorAll(".setting-input").forEach((input) => {
    const key = input.dataset.settingKey;
    if (!key) return;
    if (input.type === "checkbox") values[key] = input.checked;
    else if (input.type === "password" && !input.value) return;
    else values[key] = input.value;
  });
  saveSettingsButton.disabled = true;
  try {
    const data = await CupApi.saveSettings(values);
    alertBox.className = "alert alert-success";
    alertBox.textContent = `Impostazioni salvate (${data.changed.length} parametri).${data.restart_recommended ? " Per AMI è consigliato riavviare il backend per forzare la riconnessione." : ""}`;
    await loadSettings();
    await loadBookingRuntime();
    if (!document.getElementById("tab-calendar")?.classList.contains("d-none")) renderBookingModule();
  } catch (e) {
    alertBox.className = "alert alert-danger";
    alertBox.textContent = e.message;
  } finally {
    alertBox.classList.remove("d-none");
    saveSettingsButton.disabled = false;
  }
});


async function loadChatwootInlineSettings(){const badge=document.getElementById("chatwoot-inline-status"),info=document.getElementById("chatwoot-inline-info"),open=document.getElementById("chatwoot-inline-open");if(!badge)return;try{const d=await CupApi.getChatwootStatus();badge.textContent=d.enabled?"Configurato":"Non configurato";badge.className=`badge ${d.enabled?"bg-success":"bg-secondary"}`;info.textContent=`${d.base_url||"URL non configurato"} · Account ${d.account_id||"-"} · Inbox ${d.inbox_identifier_configured?"OK":"non configurata"}`;if(d.console_url){open.href=d.console_url;open.classList.remove("d-none");}else open.classList.add("d-none");}catch(e){badge.textContent="Errore";badge.className="badge bg-danger";info.textContent=e.message;}}
function wireChatwootInlineSettings(){document.getElementById("chatwoot-inline-refresh")?.addEventListener("click",loadChatwootInlineSettings);document.getElementById("chatwoot-inline-webhook")?.addEventListener("click",async()=>{try{const d=await CupApi.setupChatwootWebhook();alert(`Webhook configurato: ${d.callback}`);loadChatwootInlineSettings();}catch(e){showToast(e.message, "error");}});loadChatwootInlineSettings();}

// --- Chatwoot console/setup v1.0.12 ---
async function loadChatwootPage() {
  const badge = document.getElementById("chatwoot-enabled-badge");
  const navBadge = document.getElementById("chatwoot-nav-status");
  const alertBox = document.getElementById("chatwoot-page-alert");
  try {
    const data = await CupApi.getChatwootStatus();
    const enabled = !!data.enabled;
    badge.textContent = enabled ? "Configurato" : "Non configurato";
    badge.className = `badge ${enabled ? "bg-success" : "bg-secondary"}`;
    if(navBadge){ navBadge.textContent = enabled ? "ON" : "OFF"; navBadge.className = `badge ms-1 ${enabled ? "bg-success" : "bg-secondary"}`; }
    document.getElementById("chatwoot-status-url").textContent = data.base_url || "Non configurato";
    document.getElementById("chatwoot-status-account").textContent = data.account_id || "-";
    document.getElementById("chatwoot-status-inbox").textContent = data.inbox_identifier_configured ? "Configurata" : "Non configurata";
    document.getElementById("chatwoot-status-team").textContent = data.team_id || "-";
    document.getElementById("chatwoot-webhook-url").textContent = data.webhook_url || "Configura CUP_PUBLIC_BASE_URL";
    const consoleBtn = document.getElementById("btn-chatwoot-console");
    if (data.console_url) { consoleBtn.href = data.console_url; consoleBtn.classList.remove("d-none"); } else { consoleBtn.classList.add("d-none"); }
    alertBox.classList.add("d-none");
  } catch (e) {
    badge.textContent = "Errore"; badge.className = "badge bg-danger";
    if(navBadge){navBadge.textContent = "!"; navBadge.className = "badge bg-danger ms-1";}
    alertBox.className = "alert alert-danger"; alertBox.textContent = e.message; alertBox.classList.remove("d-none");
  }
}

function openSettingsSection(section) {
  if (currentUser?.role !== "admin") return;
  const settingsLink = document.querySelector('[data-tab="settings"]');
  if (settingsLink) settingsLink.click();
  setTimeout(() => {
    const card = document.querySelector(`[data-settings-section="${section}"]`);
    if (card) { card.scrollIntoView({ behavior: "smooth", block: "start" }); card.classList.add("settings-highlight"); setTimeout(() => card.classList.remove("settings-highlight"), 1800); }
  }, 250);
}

document.getElementById("btn-chatwoot-refresh")?.addEventListener("click", loadChatwootPage);
document.getElementById("btn-chatwoot-test")?.addEventListener("click", async (e) => {
  const btn = e.currentTarget; btn.disabled = true;
  const alertBox = document.getElementById("chatwoot-page-alert");
  try {
    const data = await CupApi.testSettings("chatwoot");
    alertBox.className = `alert ${data.ok ? "alert-success" : "alert-danger"}`;
    alertBox.textContent = data.message || (data.ok ? "Connessione Chatwoot riuscita" : "Test Chatwoot fallito");
  } catch (err) { alertBox.className = "alert alert-danger"; alertBox.textContent = err.message; }
  alertBox.classList.remove("d-none"); btn.disabled = false;
});
document.getElementById("btn-chatwoot-webhook")?.addEventListener("click", async (e) => {
  const btn = e.currentTarget; btn.disabled = true;
  const alertBox = document.getElementById("chatwoot-page-alert");
  try {
    const data = await CupApi.setupChatwootWebhook();
    alertBox.className = "alert alert-success"; alertBox.textContent = `Webhook configurato: ${data.callback}`;
    await loadChatwootPage();
  } catch (err) { alertBox.className = "alert alert-danger"; alertBox.textContent = err.message; }
  alertBox.classList.remove("d-none"); btn.disabled = false;
});
document.getElementById("btn-chatwoot-settings")?.addEventListener("click", () => openSettingsSection("chatwoot"));

// --- Agende e prenotazioni v1.0.13 ---
const cupCalendarState = { view: "week", cursor: new Date(), doctors: [], visitTypes: [], agendas: [], events: [], exceptions: [] };

/* CUP_FRONTEND_CACHE_V1 */
const cupFrontendCache = {
  calendarMetadataAt: 0,
  bookingPatients: null,
  bookingPatientsAt: 0
};

const CUP_CALENDAR_METADATA_TTL = 5 * 60 * 1000;
const CUP_BOOKING_PATIENTS_TTL = 60 * 1000;
/* /CUP_FRONTEND_CACHE_V1 */

const dayNames = ["Lunedì","Martedì","Mercoledì","Giovedì","Venerdì","Sabato","Domenica"];

function localISODate(d) {
  const x = new Date(d); x.setMinutes(x.getMinutes() - x.getTimezoneOffset()); return x.toISOString().slice(0,10);
}
function mondayOf(d) { const x=new Date(d); const w=(x.getDay()+6)%7; x.setHours(0,0,0,0); x.setDate(x.getDate()-w); return x; }
function addDays(d,n) { const x=new Date(d); x.setDate(x.getDate()+n); return x; }
function monthStart(d) { return new Date(d.getFullYear(),d.getMonth(),1); }
function monthEnd(d) { return new Date(d.getFullYear(),d.getMonth()+1,1); }
function selectedValues(select) { return [...select.selectedOptions].map(o=>Number(o.value)).filter(Boolean); }

async function ensureCalendarMetadata(force=false) {

  const now=Date.now();

  const cacheValid=
    !force
    &&cupFrontendCache.calendarMetadataAt
    &&(now-cupFrontendCache.calendarMetadataAt)<CUP_CALENDAR_METADATA_TTL
    &&cupCalendarState.doctors.length
    &&cupCalendarState.visitTypes.length
    &&cupCalendarState.agendas.length;

  if(cacheValid)
    return;

  const [doctors, visitTypes, agendas] =
    await Promise.all([
      CupApi.getDoctors(),
      CupApi.getVisitTypes(),
      CupApi.getAgendas()
    ]);

  cupCalendarState.doctors=doctors;
  cupCalendarState.visitTypes=visitTypes;
  cupCalendarState.agendas=agendas;

  cupFrontendCache.calendarMetadataAt=Date.now();
  const fill=(id,items,labelFn,first)=>{ const el=document.getElementById(id); if(!el)return; const old=el.value; el.innerHTML=first+items.map(x=>`<option value="${x.id}">${escapeHtml(labelFn(x))}</option>`).join(""); if([...el.options].some(o=>o.value===old))el.value=old; };
  const ad=document.getElementById("agenda-doctor"); if(ad) ad.innerHTML=doctors.filter(d=>d.active).map(d=>`<option value="${d.id}">${escapeHtml(d.full_name)}</option>`).join("");
  const av=document.getElementById("agenda-visit-types"); if(av) av.innerHTML=visitTypes.filter(v=>v.active).map(v=>`<option value="${v.id}">${escapeHtml(v.name)}</option>`).join("");

  if(typeof cupCascadeV2Init === "function")
    cupCascadeV2Init();
}

function calendarRange() {
  if(cupCalendarState.view==="month") { const first=monthStart(cupCalendarState.cursor); const gridStart=mondayOf(first); return [gridStart,addDays(gridStart,42)]; }
  const start=mondayOf(cupCalendarState.cursor); return [start,addDays(start,7)];
}
async function loadCupCalendar() {
  const root=document.getElementById("cup-calendar"); if(!root)return;
  root.innerHTML='<div class="p-4 text-muted"><span class="spinner-border spinner-border-sm me-2"></span>Caricamento agende...</div>';
  try {
    await ensureCalendarMetadata();
    const [start,end]=calendarRange();
    const filters={doctor_id:document.getElementById("calendar-doctor-filter")?.value,visit_type_id:document.getElementById("calendar-visit-filter")?.value,agenda_id:document.getElementById("calendar-agenda-filter")?.value};
    const eventsPromise =
      CupApi.getCalendarEvents(
        start.toISOString(),
        end.toISOString(),
        filters
      );

    const exceptionsPromise =
      CupApi.getCalendarExceptions(
        localISODate(start),
        localISODate(addDays(end,-1)),
        Number(filters.agenda_id) || null
      ).catch(error=>{
        console.error("Calendar exceptions:",error);
        return [];
      });

    const [events,exceptions] =
      await Promise.all([
        eventsPromise,
        exceptionsPromise
      ]);

    cupCalendarState.events=events;
    cupCalendarState.exceptions=exceptions;

    renderCupCalendar(start,end);
    await renderCalendarConfigTables();
  } catch(e) { root.innerHTML=`<div class="alert alert-danger m-3">${escapeHtml(e.message)}</div>`; }
}


function renderCupCalendarLegend(){
  const root=document.getElementById("cup-calendar-legend");
  if(!root) return;

  const doctors=(cupCalendarState.doctors||[])
    .filter(d=>d.active!==false);

  const visits=(cupCalendarState.visitTypes||[])
    .filter(v=>v.active!==false);

  const agendas=(cupCalendarState.agendas||[])
    .filter(a=>a.active!==false);

  const selectedAgendaId=
    Number(document.getElementById("calendar-agenda-filter")?.value)||null;

  const selectedDoctorId=
    Number(document.getElementById("calendar-doctor-filter")?.value)||null;

  const selectedVisitId=
    Number(document.getElementById("calendar-visit-filter")?.value)||null;

  const doctorById=new Map(
    doctors.map(d=>[Number(d.id),d])
  );

  const visitById=new Map(
    visits.map(v=>[Number(v.id),v])
  );

  function getAgendaVisitIds(agenda){
    const candidates=[
      agenda.visit_type_ids,
      agenda.allowed_visit_type_ids,
      agenda.visitTypeIds,
      agenda.visit_types,
      agenda.agenda_visit_types
    ];

    for(const value of candidates){
      if(!Array.isArray(value))
        continue;

      return value
        .map(x=>
          typeof x==="object"
            ? Number(x.id ?? x.visit_type_id)
            : Number(x)
        )
        .filter(Boolean);
    }

    return [];
  }

  const filteredAgendas=agendas.filter(a=>{
    if(
      selectedDoctorId &&
      Number(a.doctor_id)!==selectedDoctorId
    )
      return false;

    return true;
  });

  const specialtyGroups=new Map();

  for(const agenda of filteredAgendas){
    const doctor=
      doctorById.get(Number(agenda.doctor_id));

    const specialty=
      doctor?.specialty ||
      agenda.specialty ||
      "Altre agende";

    let agendaVisits=
      getAgendaVisitIds(agenda)
        .map(id=>visitById.get(id))
        .filter(Boolean);

    if(selectedVisitId){
      agendaVisits=agendaVisits.filter(
        v=>Number(v.id)===selectedVisitId
      );
    }

    agendaVisits.sort(
      (a,b)=>
        String(a.name||"")
          .localeCompare(
            String(b.name||""),
            "it"
          )
    );

    if(
      !agendaVisits.length &&
      Number(agenda.id)!==selectedAgendaId
    )
      continue;

    if(!specialtyGroups.has(specialty))
      specialtyGroups.set(specialty,[]);

    specialtyGroups.get(specialty).push({
      agenda,
      doctor,
      visits:agendaVisits
    });
  }

  const groups=[
    ...specialtyGroups.entries()
  ]
  .map(([specialty,items])=>({
    specialty,
    items:items.sort(
      (a,b)=>
        String(a.agenda.name||"")
          .localeCompare(
            String(b.agenda.name||""),
            "it"
          )
    )
  }))
  .sort(
    (a,b)=>
      a.specialty.localeCompare(
        b.specialty,
        "it"
      )
  );

  root.innerHTML=`
    <div class="cup-specialty-legend">

      <div class="cup-specialty-toolbar">
        <div>
          <strong>Prestazioni per agenda</strong>
          <div class="cup-specialty-subtitle">
            ${groups.length} specialità ·
            ${filteredAgendas.length} agende
          </div>
        </div>

        <div class="cup-specialty-search-wrap">
          <i class="bi bi-search"></i>
          <input
            id="cup-agenda-legend-search"
            type="search"
            placeholder="Cerca agenda, medico o prestazione..."
            autocomplete="off"
          >
        </div>
      </div>

      <div
        id="cup-specialty-groups"
        class="cup-specialty-groups"
      >

        ${groups.map(group=>{

          const specialtyOpen=
            group.items.some(
              x=>Number(x.agenda.id)===selectedAgendaId
            )
            ? "open"
            : "";

          const totalVisits=
            group.items.reduce(
              (sum,x)=>sum+x.visits.length,
              0
            );

          return `
            <details
              class="cup-specialty-group"
              data-search-specialty="${escapeHtml(
                group.specialty.toLowerCase()
              )}"
              ${specialtyOpen}
            >

              <summary>
                <span class="cup-specialty-name">
                  ${escapeHtml(group.specialty)}
                </span>

                <span class="cup-specialty-count">
                  ${group.items.length}
                  ${group.items.length===1
                    ?"agenda"
                    :"agende"}
                  ·
                  ${totalVisits}
                  ${totalVisits===1
                    ?"prestazione"
                    :"prestazioni"}
                </span>
              </summary>

              <div class="cup-specialty-agendas">

                ${group.items.map(item=>{

                  const agenda=item.agenda;
                  const doctor=item.doctor;

                  const agendaOpen=
                    Number(agenda.id)===selectedAgendaId
                    ? "open"
                    : "";

                  const searchable=[
                    group.specialty,
                    agenda.name,
                    doctor?.full_name||"",
                    ...item.visits.map(v=>v.name)
                  ]
                  .join(" ")
                  .toLowerCase();

                  return `
                    <details
                      class="cup-specialty-agenda"
                      data-search="${escapeHtml(searchable)}"
                      ${agendaOpen}
                    >

                      <summary>

                        <span class="cup-agenda-name">
                          ${escapeHtml(
                            agenda.name||"Agenda"
                          )}
                        </span>

                        ${
                          doctor?.full_name
                          ? `
                            <span class="cup-agenda-doctor">
                              ${escapeHtml(
                                doctor.full_name
                              )}
                            </span>
                          `
                          :""
                        }

                        <span class="cup-agenda-badge">
                          ${item.visits.length}
                          ${item.visits.length===1
                            ?"prestazione"
                            :"prestazioni"}
                        </span>

                      </summary>

                      <div class="cup-agenda-visit-list">

                        ${
                          item.visits.length
                          ? item.visits.map(v=>`
                              <div class="cup-agenda-visit-row">

                                <span
                                  class="cup-agenda-visit-color"
                                  style="
                                    background:
                                    ${escapeHtml(
                                      v.color_hex||
                                      v.color||
                                      "#3B82F6"
                                    )}
                                  "
                                ></span>

                                <span>
                                  ${escapeHtml(v.name)}
                                </span>

                                <span class="cup-agenda-visit-duration">
                                  ${Number(v.duration_minutes)||60} min
                                </span>

                              </div>
                            `).join("")
                          : `
                            <div class="cup-agenda-empty">
                              Nessuna prestazione associata
                            </div>
                          `
                        }

                      </div>

                    </details>
                  `;
                }).join("")}

              </div>

            </details>
          `;
        }).join("")}

      </div>

    </div>
  `;

  const search=
    document.getElementById(
      "cup-agenda-legend-search"
    );

  const groupsRoot=
    document.getElementById(
      "cup-specialty-groups"
    );

  search?.addEventListener(
    "input",
    ()=>{
      const q=
        search.value
          .trim()
          .toLowerCase();

      groupsRoot
        ?.querySelectorAll(
          ".cup-specialty-group"
        )
        .forEach(specialtyEl=>{

          let visibleCount=0;

          specialtyEl
            .querySelectorAll(
              ".cup-specialty-agenda"
            )
            .forEach(agendaEl=>{

              const text=
                agendaEl.dataset.search||"";

              const visible=
                !q ||
                text.includes(q);

              agendaEl.style.display=
                visible
                ?""
                :"none";

              if(visible)
                visibleCount++;
            });

          specialtyEl.style.display=
            visibleCount
            ?""
            :"none";

          if(q && visibleCount)
            specialtyEl.open=true;
        });
    }
  );
}



function calendarEventEnd(event){
  if(event.end_at) return new Date(event.end_at);
  const start=new Date(event.scheduled_at);
  const visit=cupCalendarState.visitTypes.find(
    v=>Number(v.id)===Number(event.visit_type_id)
  );
  const duration=Number(visit?.duration_minutes)||60;
  return new Date(start.getTime()+duration*60000);
}

function groupOverlappingEvents(events){
  const sorted=[...events].sort(
    (a,b)=>new Date(a.scheduled_at)-new Date(b.scheduled_at)
  );
  const groups=[];
  let current=[];
  let groupEnd=null;

  for(const event of sorted){
    const start=new Date(event.scheduled_at);
    const end=calendarEventEnd(event);

    if(current.length===0 || start < groupEnd){
      current.push(event);
      if(!groupEnd || end > groupEnd) groupEnd=end;
      continue;
    }

    groups.push(current);
    current=[event];
    groupEnd=end;
  }

  if(current.length) groups.push(current);
  return groups;
}

function renderOverlappingDayEvents(events){
  if(!events.length)
    return '<div class="cup-empty-day">Nessuna prenotazione</div>';

  return groupOverlappingEvents(events)
    .map(group=>{
      if(group.length===1)
        return calendarEventCard(group[0]);

      const columns=Math.min(group.length,3);

      return `
        <div class="cup-overlap-group" style="--overlap-columns:${columns}">
          ${group.map(event=>`
            <div class="cup-overlap-item">
              ${calendarEventCard(event)}
            </div>
          `).join("")}
        </div>
      `;
    })
    .join("");
}


/* CUP_MOVE_LEGEND_AFTER_CALENDAR_START */

function moveCalendarLegendAfterCalendar(){

  const calendar=
    document.getElementById(
      "cup-calendar"
    );

  const legend=
    document.getElementById(
      "cup-calendar-legend"
    );

  if(!calendar || !legend)
    return;

  /*
   * Posiziona la legenda immediatamente
   * dopo il calendario.
   */
  if(calendar.nextElementSibling!==legend){
    calendar.insertAdjacentElement(
      "afterend",
      legend
    );
  }
}

/* CUP_MOVE_LEGEND_AFTER_CALENDAR_END */


/* CUP_WORKING_TIME_CALENDAR_V1 */

function cupCalendarFilteredAgendas(){
  const agendas =
    (cupCalendarState.agendas || [])
      .filter(a => a.active !== false);

  const doctors =
    (cupCalendarState.doctors || [])
      .filter(d => d.active !== false);

  const doctorById =
    new Map(
      doctors.map(d => [Number(d.id), d])
    );

  const specialty =
    document.getElementById(
      "calendar-specialty-filter"
    )?.value || "";

  const visitId =
    Number(
      document.getElementById(
        "calendar-visit-filter"
      )?.value
    ) || null;

  const doctorId =
    Number(
      document.getElementById(
        "calendar-doctor-filter"
      )?.value
    ) || null;

  const agendaId =
    Number(
      document.getElementById(
        "calendar-agenda-filter"
      )?.value
    ) || null;

  return agendas.filter(a => {

    const doctor =
      doctorById.get(
        Number(a.doctor_id)
      );

    if(
      specialty &&
      doctor?.specialty !== specialty
    )
      return false;

    if(
      visitId &&
      !cupV2VisitIds(a)
        .includes(visitId)
    )
      return false;

    if(
      doctorId &&
      Number(a.doctor_id) !== doctorId
    )
      return false;

    if(
      agendaId &&
      Number(a.id) !== agendaId
    )
      return false;

    return true;
  });
}


function cupRuleValidForDate(rule, day){

  if(!rule || rule.active === false)
    return false;

  /*
   * JS: Domenica=0
   * CUP: Lunedi=0 ... Domenica=6
   */
  const weekday =
    (day.getDay() + 6) % 7;

  if(Number(rule.weekday) !== weekday)
    return false;

  const iso =
    localISODate(day);

  if(
    rule.valid_from &&
    iso < String(rule.valid_from)
  )
    return false;

  if(
    rule.valid_to &&
    iso > String(rule.valid_to)
  )
    return false;

  return true;
}


function cupWorkingWindows(day){

  const agendas =
    cupCalendarFilteredAgendas();

  const intervals = [];

  for(const agenda of agendas){

    for(const rule of (agenda.rules || [])){

      if(!cupRuleValidForDate(rule, day))
        continue;

      intervals.push({
        start: rule.start_time,
        end: rule.end_time
      });
    }
  }

  return intervals;
}


function cupMinutes(value){

  const parts =
    String(value || "00:00")
      .split(":")
      .map(Number);

  return (
    (parts[0] || 0) * 60 +
    (parts[1] || 0)
  );
}


function cupMinuteIsWorking(minute, windows){

  return windows.some(w =>
    minute >= cupMinutes(w.start) &&
    minute < cupMinutes(w.end)
  );
}


function cupDayIsWorking(day){

  return cupWorkingWindows(day)
    .length > 0;
}


function cupWorkingTimeStrip(day){

  const windows =
    cupWorkingWindows(day);

  if(!windows.length){

    return `
      <div
        class="cup-working-strip cup-working-strip-off"
        title="Giorno non lavorativo">
        <span>Non lavorativo</span>
      </div>
    `;
  }

  /*
   * Rappresentazione compatta 07:00-20:00
   * con segmenti da 30 minuti.
   */
  const START = 7 * 60;
  const END   = 20 * 60;
  const STEP  = 30;

  const cells = [];

  for(
    let minute = START;
    minute < END;
    minute += STEP
  ){

    const working =
      cupMinuteIsWorking(
        minute,
        windows
      );

    const hh =
      String(
        Math.floor(minute / 60)
      ).padStart(2, "0");

    const mm =
      String(
        minute % 60
      ).padStart(2, "0");

    cells.push(`
      <span
        class="cup-working-segment ${
          working
            ? "is-working"
            : "is-off"
        }"
        title="${hh}:${mm} · ${
          working
            ? "orario lavorativo"
            : "non lavorativo"
        }">
      </span>
    `);
  }

  return `
    <div class="cup-working-strip">
      ${cells.join("")}
    </div>
  `;
}



/* CUP_CALENDAR_BLOCKED_EVENTS_V1 */

function cupCalendarExceptionsForDay(day) {
  const key = localISODate(day);

  return (cupCalendarState.exceptions || [])
    .filter(x => String(x.date).slice(0,10) === key);
}

function cupCalendarBlockedCards(day) {
  const rows = cupCalendarExceptionsForDay(day);

  if (!rows.length) return "";

  return rows.map(ex => {
    const from = ex.start_time
      ? String(ex.start_time).slice(0,5)
      : "";

    const to = ex.end_time
      ? String(ex.end_time).slice(0,5)
      : "";

    const timeLabel =
      from && to
        ? `${from}–${to}`
        : from
          ? `dalle ${from}`
          : to
            ? `fino alle ${to}`
            : "Intera giornata";

    const description =
      ex.title ||
      ex.description ||
      ex.note ||
      "Agenda indisponibile";

    return `
      <div
        class="cup-calendar-blocked-event"
        title="${escapeHtml(description)}">

        <div class="cup-calendar-blocked-icon">
          <i class="bi bi-exclamation-triangle-fill"></i>
        </div>

        <div class="cup-calendar-blocked-content">
          <div class="cup-calendar-blocked-time">
            ${escapeHtml(timeLabel)}
          </div>
          <div class="cup-calendar-blocked-title">
            ${escapeHtml(description)}
          </div>
        </div>

      </div>
    `;
  }).join("");
}

/* /CUP_CALENDAR_BLOCKED_EVENTS_V1 */


function renderCupCalendar(start,end) {

  renderCupCalendarLegend();

  const root =
    document.getElementById(
      "cup-calendar"
    );

  const events =
    cupCalendarState.events;

  const label =
    document.getElementById(
      "calendar-period-label"
    );

  document.getElementById(
    "calendar-summary"
  ).textContent =
    `${events.length} ${
      events.length === 1
        ? "appuntamento"
        : "appuntamenti"
    } · ${
      cupCalendarState.doctors
        .filter(d => d.active).length
    } medici · ${
      cupCalendarState.agendas
        .filter(a => a.active).length
    } agende`;

  if(cupCalendarState.view === "week") {

    const finish =
      addDays(start,6);

    label.textContent =
      `${start.toLocaleDateString(
        "it-IT",
        {
          day:"2-digit",
          month:"long"
        }
      )} – ${
        finish.toLocaleDateString(
          "it-IT",
          {
            day:"2-digit",
            month:"long",
            year:"numeric"
          }
        )
      }`;

    root.innerHTML =
      '<div class="cup-week-grid">' +
      [0,1,2,3,4,5,6]
        .map(i => {

          const day =
            addDays(start,i);

          const key =
            localISODate(day);

          const working =
            cupDayIsWorking(day);

          const dayEvents =
            events.filter(
              e =>
                localISODate(
                  new Date(
                    e.scheduled_at
                  )
                ) === key
            );

          return `
            <div
              class="cup-day-column ${
                key === localISODate(
                  new Date()
                )
                  ? "is-today"
                  : ""
              } ${
                working
                  ? ""
                  : "cup-day-nonworking"
              }">

              <div class="cup-day-header">
                <strong>${dayNames[i]}</strong>
                <span>${day.getDate()}</span>
              </div>

              ${cupWorkingTimeStrip(day)}

              ${
                !working
                ? `
                  <div class="cup-nonworking-label">
                    Giorno non lavorativo
                  </div>
                `
                : ""
              }

              <div class="cup-day-events">

                ${cupCalendarBlockedCards(day)}

                ${
                  renderOverlappingDayEvents(
                    dayEvents
                  )
                }

              </div>

              ${
                working
                ? `
                  <button
                    class="btn btn-sm btn-link cup-add-day"
                    data-new-booking-date="${key}">
                    <i class="bi bi-plus"></i>
                    Prenota
                  </button>
                `
                : ""
              }

            </div>
          `;
        })
        .join("") +
      '</div>';

  }
  else {

    label.textContent =
      cupCalendarState.cursor
        .toLocaleDateString(
          "it-IT",
          {
            month:"long",
            year:"numeric"
          }
        );

    root.innerHTML =
      '<div class="cup-month-head">' +
      dayNames
        .map(
          x => `<div>${x.slice(0,3)}</div>`
        )
        .join("") +
      '</div>' +

      '<div class="cup-month-grid">' +

      [...Array(42)]
        .map((_,i) => {

          const day =
            addDays(start,i);

          const key =
            localISODate(day);

          const inMonth =
            day.getMonth() ===
            cupCalendarState.cursor
              .getMonth();

          const working =
            cupDayIsWorking(day);

          const dayEvents =
            events.filter(
              e =>
                localISODate(
                  new Date(
                    e.scheduled_at
                  )
                ) === key
            );

          return `
            <div
              class="cup-month-day ${
                inMonth
                  ? ""
                  : "outside"
              } ${
                key === localISODate(
                  new Date()
                )
                  ? "is-today"
                  : ""
              } ${
                working
                  ? ""
                  : "cup-month-nonworking"
              }"
              ${
                working
                  ? `data-new-booking-date="${key}"`
                  : ""
              }>

              <div class="cup-month-number">
                ${day.getDate()}
              </div>

              ${
                !working
                ? `
                  <div class="cup-month-off-label">
                    Non lavorativo
                  </div>
                `
                : ""
              }

              ${
                dayEvents
                  .slice(0,4)
                  .map(e => `
                    <button
                      class="cup-month-event"
                      style="
                        background:${escapeHtml(
                          e.visit_color ||
                          "#0d6efd"
                        )}18;
                        border-left:6px solid ${
                          escapeHtml(
                            e.visit_color ||
                            "#0d6efd"
                          )
                        };
                        border-top:1px solid ${
                          escapeHtml(
                            e.visit_color ||
                            "#0d6efd"
                          )
                        }55;
                      "
                      data-booking-id="${e.id}">
                      <strong>${
                        new Date(
                          e.scheduled_at
                        ).toLocaleTimeString(
                          "it-IT",
                          {
                            hour:"2-digit",
                            minute:"2-digit"
                          }
                        )
                      }</strong>
                      ${escapeHtml(
                        e.patient_name ||
                        "Paziente"
                      )}
                    </button>
                  `)
                  .join("")
              }

              ${
                dayEvents.length > 4
                  ? `
                    <div class="small text-muted">
                      +${dayEvents.length-4} altri
                    </div>
                  `
                  : ""
              }

            </div>
          `;
        })
        .join("") +

      '</div>';
  }

  moveCalendarLegendAfterCalendar();

  root
    .querySelectorAll(
      "[data-booking-id]"
    )
    .forEach(el =>
      el.addEventListener(
        "click",
        ev => {
          ev.stopPropagation();

          openBookingEditor(
            Number(
              el.dataset.bookingId
            )
          );
        }
      )
    );

  root
    .querySelectorAll(
      "[data-new-booking-date]"
    )
    .forEach(el =>
      el.addEventListener(
        "click",
        ev => {

          if(el.dataset.bookingId)
            return;

          ev.stopPropagation();

          openNewBooking(
            el.dataset.newBookingDate
          );
        }
      )
    );
}

/* /CUP_WORKING_TIME_CALENDAR_V1 */

function calendarEventCard(e) {
  const start=new Date(e.scheduled_at);
  const end=e.end_at?new Date(e.end_at):null;

  const startText=start.toLocaleTimeString("it-IT",{hour:"2-digit",minute:"2-digit"});
  const endText=end?end.toLocaleTimeString("it-IT",{hour:"2-digit",minute:"2-digit"}):"";

  const visitColor=e.visit_color||"#3B82F6";
  const doctorColor=e.visit_color||"#2563EB";

  const visitName=e.service_name||e.visit_name||"Visita";
  const patientName=e.patient_name||"Paziente";

  const doctorName=
    (Array.isArray(e.doctor_names)&&e.doctor_names.length)
      ? e.doctor_names.join(", ")
      : (e.doctor_name||"Medico da assegnare");

  const provider=e.external_provider||e.calendar_provider||"";

  const providerHtml=
    provider&&provider!=="none"
      ? `<div class="cup-event-provider"><i class="bi bi-cloud-check"></i> ${escapeHtml(provider)}</div>`
      : "";

  return `
    <button
      class="cup-event-card"
      data-booking-id="${e.id}"
      style="--visit-color:${escapeHtml(visitColor)};--doctor-color:${escapeHtml(doctorColor)};"
      title="${escapeHtml(`${startText}${endText?`–${endText}`:""} · ${visitName} · ${patientName} · ${doctorName}`)}"
    >
      <div class="cup-event-time">
        ${startText}${endText?`–${endText}`:""}
      </div>

      <div class="cup-event-service">
        ${escapeHtml(visitName)}
      </div>

      <div class="cup-event-patient">
        ${escapeHtml(patientName)}
      </div>

      <div class="cup-event-doctor">
        <span class="cup-doctor-dot"></span>
        <span>${escapeHtml(doctorName)}</span>
      </div>

      <div class="cup-event-visit">
        <span class="cup-visit-square"></span>
        <span>${escapeHtml(visitName)}</span>
      </div>

      ${providerHtml}
    </button>
  `;
}


function syncBookingDoctorsFromAgenda() { const a=cupCalendarState.agendas.find(x=>String(x.id)===document.getElementById("booking-agenda").value); if(!a)return; [...document.getElementById("booking-doctors").options].forEach(o=>o.selected=Number(o.value)===a.doctor_id); }
async function refreshBookingSlots() {
  const day=document.getElementById("booking-date").value, agenda=document.getElementById("booking-agenda").value, visit=document.getElementById("booking-visit-type").value, sel=document.getElementById("booking-slot");
  if(!day||!agenda){sel.innerHTML='<option value="">Inserisci ora manualmente</option>';return;}
  try { const slots=await CupApi.getAvailableSlots(day,agenda,visit||null); sel.innerHTML='<option value="">Ora manuale</option>'+slots.map(s=>`<option value="${new Date(s.start).toTimeString().slice(0,5)}">${new Date(s.start).toLocaleTimeString("it-IT",{hour:"2-digit",minute:"2-digit"})} – ${new Date(s.end).toLocaleTimeString("it-IT",{hour:"2-digit",minute:"2-digit"})}</option>`).join(""); }
  catch(e){sel.innerHTML=`<option value="">${escapeHtml(e.message)}</option>`;}
}


async function openNewBooking(day=null) {
  await ensureCalendarMetadata();
  document.getElementById("booking-form").reset(); document.getElementById("booking-id").value=""; document.getElementById("booking-sync-external").checked=true;
  document.getElementById("booking-date").value=day||localISODate(new Date());
  const af=document.getElementById("calendar-agenda-filter").value; if(af)document.getElementById("booking-agenda").value=af;
  const vf=document.getElementById("calendar-visit-filter").value; if(vf)document.getElementById("booking-visit-type").value=vf;
  document.getElementById("btn-send-reminder-now")?.classList.add("d-none");
  const rs=document.getElementById("booking-reminders-summary"); if(rs) rs.textContent="Verranno pianificati automaticamente al salvataggio.";
  const rl=document.getElementById("booking-reminders-list"); if(rl) rl.innerHTML="";
  syncBookingDoctorsFromAgenda(); await refreshBookingSlots(); bookingModal.show();
}

let bookingPatientSearchTimer=null;

function clearBookingPatientSearch(){
  const hidden=document.getElementById("booking-patient");
  const input=document.getElementById("booking-patient-search");
  const results=document.getElementById("booking-patient-results");
  const selected=document.getElementById("booking-patient-selected");

  if(hidden) hidden.value="";
  if(input) input.value="";
  if(results){
    results.innerHTML="";
    results.classList.add("d-none");
  }
  if(selected)
    selected.textContent="Cerca per nome, telefono, email o codice fiscale.";
}

function selectBookingPatient(patient){
  const hidden=document.getElementById("booking-patient");
  const input=document.getElementById("booking-patient-search");
  const results=document.getElementById("booking-patient-results");
  const selected=document.getElementById("booking-patient-selected");

  if(hidden) hidden.value=patient.id;
  if(input) input.value=patient.full_name||("Paziente #"+patient.id);

  if(results){
    results.innerHTML="";
    results.classList.add("d-none");
  }

  const details=[
    patient.phone,
    patient.email,
    patient.fiscal_code ? "CF "+patient.fiscal_code : null
  ].filter(Boolean);

  if(selected)
    selected.textContent=details.join(" · ")||"Paziente selezionato";
}

async function searchBookingPatients(query){
  const results=document.getElementById("booking-patient-results");
  if(!results) return;

  const q=(query||"").trim();

  if(q.length<2){
    results.innerHTML="";
    results.classList.add("d-none");
    return;
  }

  results.innerHTML='<div class="list-group-item text-muted">Ricerca...</div>';
  results.classList.remove("d-none");

  try{
    const response=await fetch(
      `/api/patients/search?q=${encodeURIComponent(q)}&limit=20`,
      {
        headers: typeof patientApiHeaders==="function"
          ? patientApiHeaders()
          : {
              "Authorization":
                "Bearer "+(localStorage.getItem("cup_token")||"")
            }
      }
    );

    if(!response.ok)
      throw new Error("Ricerca pazienti non disponibile");

    const data=await response.json();
    const patients=Array.isArray(data) ? data : (data.items||[]);

    if(!patients.length){
      results.innerHTML=
        '<div class="list-group-item text-muted">Nessun paziente trovato</div>';
      return;
    }

    results.innerHTML=patients.map(patient=>{
      const details=[
        patient.phone,
        patient.email,
        patient.fiscal_code
      ].filter(Boolean).join(" · ");

      return `
        <button
          type="button"
          class="list-group-item list-group-item-action"
          data-booking-patient-id="${patient.id}">
          <strong>${escapeHtml(patient.full_name||("Paziente #"+patient.id))}</strong>
          ${details
            ? `<div class="small text-muted">${escapeHtml(details)}</div>`
            : ""}
        </button>
      `;
    }).join("");

    results.querySelectorAll("[data-booking-patient-id]")
      .forEach(button=>{
        button.addEventListener("click",()=>{
          const patient=patients.find(
            p=>Number(p.id)===Number(button.dataset.bookingPatientId)
          );
          if(patient) selectBookingPatient(patient);
        });
      });

  }catch(error){
    console.error("Ricerca paziente:",error);
    results.innerHTML=
      `<div class="list-group-item text-danger">${escapeHtml(error.message)}</div>`;
  }
}

async function loadBookingPatients(selectedPatientId=null){
  clearBookingPatientSearch();

  if(selectedPatientId){
    try{
      const response=await fetch(
        `/api/patients/${selectedPatientId}`,
        {
          headers: typeof patientApiHeaders==="function"
            ? patientApiHeaders()
            : {
                "Authorization":
                  "Bearer "+(localStorage.getItem("cup_token")||"")
              }
        }
      );

      if(response.ok){
        selectBookingPatient(await response.json());
      }
    }catch(error){
      console.error("Caricamento paziente prenotazione:",error);
    }
  }

  return [];
}

document.getElementById("booking-patient-search")
  ?.addEventListener("input",event=>{
    const value=event.target.value;

    const hidden=document.getElementById("booking-patient");
    if(hidden) hidden.value="";

    clearTimeout(bookingPatientSearchTimer);

    bookingPatientSearchTimer=setTimeout(
      ()=>searchBookingPatients(value),
      250
    );
  });

document.getElementById("btn-new-booking")?.addEventListener("click",async()=>{
  try{
    await openNewBooking();
  }catch(err){
    console.error("Apertura nuova prenotazione fallita",err);
    if(typeof showToast==="function"){
      showToast(err?.message||"Impossibile aprire la nuova prenotazione.","error");
    }else{
      alert(err?.message||"Impossibile aprire la nuova prenotazione.");
    }
  }
});
/* legacy booking-agenda listener removed */
/* legacy booking date/visit listeners removed */
document.getElementById("booking-slot")?.addEventListener("change",e=>{if(e.target.value)document.getElementById("booking-time").value=e.target.value;});
async function openBookingEditor(id) {
  const e=cupCalendarState.events.find(x=>x.id===id); if(!e)return;
  await Promise.all([ensureCalendarMetadata(),loadBookingPatients(e.patient_id)]);
  document.getElementById("booking-id").value=e.id; document.getElementById("booking-patient").value=e.patient_id; document.getElementById("booking-visit-type").value=e.visit_type_id||""; document.getElementById("booking-agenda").value=e.agenda_id||""; document.getElementById("booking-date").value=localISODate(new Date(e.scheduled_at)); document.getElementById("booking-time").value=new Date(e.scheduled_at).toTimeString().slice(0,5); document.getElementById("booking-priority").value=e.priority; document.getElementById("booking-notes").value=e.notes||""; document.getElementById("booking-sync-external").checked=true;
  [...document.getElementById("booking-doctors").options].forEach(o=>o.selected=(e.doctor_ids||[]).includes(Number(o.value)));
  await refreshBookingSlots(); await loadBookingReminderStatus(e.id); bookingModal.show();
}

document.getElementById("booking-form")?.addEventListener("submit",async e=>{e.preventDefault();const err=document.getElementById("booking-form-error");err.classList.add("d-none");try{const day=document.getElementById("booking-date").value,timeValue=document.getElementById("booking-slot").value||document.getElementById("booking-time").value;if(!timeValue)throw new Error("Seleziona uno slot o indica l'ora");const payload={patient_id:Number(document.getElementById("booking-patient").value),agenda_id:Number(document.getElementById("booking-agenda").value)||null,visit_type_id:Number(document.getElementById("booking-visit-type").value)||null,doctor_ids:selectedValues(document.getElementById("booking-doctors")),scheduled_at:`${day}T${timeValue}:00`,duration_minutes:selectedBookingDuration(),priority:document.getElementById("booking-priority").value,notes:document.getElementById("booking-notes").value.trim()||null,sync_external:document.getElementById("booking-sync-external").checked};const id=Number(document.getElementById("booking-id").value)||null;if(id) await CupApi.updateCalendarBooking(id,payload); else await CupApi.createCalendarBooking(payload);bookingModal.hide();await loadCupCalendar();await loadDashboardStats();}catch(ex){err.textContent=ex.message;err.classList.remove("d-none");}});

function shiftCalendar(dir){ if(cupCalendarState.view==="week")cupCalendarState.cursor=addDays(cupCalendarState.cursor,7*dir);else cupCalendarState.cursor=new Date(cupCalendarState.cursor.getFullYear(),cupCalendarState.cursor.getMonth()+dir,1);document.getElementById("calendar-date").value=localISODate(cupCalendarState.cursor);loadCupCalendar(); }
document.getElementById("calendar-prev")?.addEventListener("click",()=>shiftCalendar(-1)); document.getElementById("calendar-next")?.addEventListener("click",()=>shiftCalendar(1)); document.getElementById("calendar-today")?.addEventListener("click",()=>{cupCalendarState.cursor=new Date();document.getElementById("calendar-date").value=localISODate(new Date());loadCupCalendar();});
document.getElementById("calendar-date")?.addEventListener("change",e=>{if(e.target.value){cupCalendarState.cursor=new Date(e.target.value+"T12:00:00");loadCupCalendar();}});
/* legacy calendar listeners removed */
document.querySelectorAll("[data-calendar-view]").forEach(btn=>btn.addEventListener("click",()=>{document.querySelectorAll("[data-calendar-view]").forEach(x=>x.classList.remove("active"));btn.classList.add("active");cupCalendarState.view=btn.dataset.calendarView;loadCupCalendar();}));


async function loadBookingReminderStatus(bookingId) {
  const btn=document.getElementById("btn-send-reminder-now"), summary=document.getElementById("booking-reminders-summary"), list=document.getElementById("booking-reminders-list");
  if(btn){btn.classList.remove("d-none");btn.dataset.bookingId=bookingId;}
  try{
    const data=await CupApi.getBookingReminders(bookingId), items=data.items||[], pending=items.filter(x=>x.status==="pending").length, sent=items.filter(x=>x.status==="sent").length;
    if(summary) summary.textContent=`${pending} programmati · ${sent} inviati`;
    if(list) list.innerHTML=items.slice(-8).map(x=>`<div class="d-flex justify-content-between border-top py-1"><span><i class="bi bi-${x.channel==="email"?"envelope":x.channel==="whatsapp"?"whatsapp":x.channel==="telegram"?"telegram":"chat-square-text"}"></i> ${escapeHtml(x.channel)} · ${x.kind==="confirmation"?"conferma":"promemoria"}</span><span>${fmtDate(x.scheduled_for)} · <span class="badge bg-${x.status==="sent"?"success":x.status==="pending"?"warning text-dark":x.status==="failed"?"danger":"secondary"}">${escapeHtml(x.status)}</span></span></div>`).join("")||'<div class="text-muted">Nessun promemoria pianificato.</div>';
  }catch(e){if(summary)summary.textContent=e.message;}
}
document.getElementById("btn-send-reminder-now")?.addEventListener("click",async e=>{const id=Number(e.currentTarget.dataset.bookingId);if(!id)return;e.currentTarget.disabled=true;try{await CupApi.sendBookingReminderNow(id);await loadBookingReminderStatus(id);showToast("Invio promemoria avviato.", "success");}catch(err){showToast(err.message, "error");}finally{e.currentTarget.disabled=false;}});

async function loadReminders(){
  const tbody=document.getElementById("reminders-table"); if(!tbody)return;
  tbody.innerHTML='<tr><td colspan="7" class="text-muted p-3"><span class="spinner-border spinner-border-sm me-2"></span>Caricamento...</td></tr>';
  try{
    const rows=await CupApi.getReminders();
    const counts={pending:0,sent:0,failed:0,skipped:0}; rows.forEach(r=>{if(counts[r.status]!==undefined)counts[r.status]++});
    Object.entries(counts).forEach(([k,v])=>{const el=document.getElementById(`rem-stat-${k}`);if(el)el.textContent=v;});
    const badge=document.getElementById("reminders-nav-badge"); if(badge){badge.textContent=counts.failed+counts.pending;badge.classList.toggle("d-none",!(counts.failed+counts.pending));}
    tbody.innerHTML=rows.slice(0,200).map(r=>`<tr><td>${fmtDate(r.scheduled_for)}</td><td><strong>${escapeHtml(r.service_name||("#"+r.booking_id))}</strong><div class="small text-muted">${fmtDate(r.scheduled_at)}</div></td><td><span class="badge bg-light text-dark border">${escapeHtml(r.channel)}</span></td><td>${escapeHtml(r.target||"-")}</td><td><span class="badge bg-${r.status==="sent"?"success":r.status==="pending"?"warning text-dark":r.status==="failed"?"danger":"secondary"}">${escapeHtml(r.status)}</span></td><td>${r.attempts||0}</td><td>${r.status==="failed"?`<button class="btn btn-sm btn-outline-primary" data-retry-reminder="${r.id}">Riprova</button>`:""}</td></tr>`).join("")||'<tr><td colspan="7" class="text-muted p-3">Nessun promemoria.</td></tr>';
    tbody.querySelectorAll("[data-retry-reminder]").forEach(b=>b.addEventListener("click",async()=>{b.disabled=true;try{await CupApi.retryReminder(Number(b.dataset.retryReminder));await loadReminders();}catch(e){showToast(e.message, "error");b.disabled=false;}}));
  }catch(e){tbody.innerHTML=`<tr><td colspan="7" class="text-danger p-3">${escapeHtml(e.message)}</td></tr>`;}
}
document.getElementById("btn-refresh-reminders")?.addEventListener("click",loadReminders);
document.getElementById("btn-reminders-settings")?.addEventListener("click",()=>openSettingsSection("reminders"));

// Configurazione medici / prestazioni / agende
function agendaRulesEditor(rules=[]) { const box=document.getElementById("agenda-rules-editor");box.innerHTML=dayNames.map((name,i)=>{const r=rules.find(x=>x.weekday===i);return `<div class="agenda-rule-row"><div class="form-check"><input class="form-check-input agenda-rule-enabled" type="checkbox" data-day="${i}" ${r?"checked":""}><label class="form-check-label">${name}</label></div><input class="form-control form-control-sm agenda-rule-start" type="time" data-day="${i}" value="${r?.start_time||"08:00"}"><span>–</span><input class="form-control form-control-sm agenda-rule-end" type="time" data-day="${i}" value="${r?.end_time||"13:00"}"></div>`;}).join(""); }
async function renderCalendarConfigTables(){ const dt=document.getElementById("doctors-table-body"),vt=document.getElementById("visit-types-table-body"),at=document.getElementById("agendas-table-body"); if(!dt)return;dt.innerHTML=cupCalendarState.doctors.map(d=>`<tr><td><strong>${escapeHtml(d.full_name)}</strong></td><td>${escapeHtml(d.specialty||"-")}</td><td>${escapeHtml(d.email||"-")}</td><td>${d.external_provider!=="none"?`<span class="badge bg-info text-dark">${escapeHtml(d.external_provider)}</span>`:"Locale"}</td><td><button class="btn btn-sm btn-outline-secondary" data-edit-doctor="${d.id}">Modifica</button></td></tr>`).join("")||'<tr><td colspan="5" class="text-muted">Nessun medico configurato.</td></tr>';vt.innerHTML=cupCalendarState.visitTypes.map(v=>`<tr><td><span class="visit-color-dot" style="background:${escapeHtml(v.color_hex||v.color||"#0d6efd")}"></span><strong>${escapeHtml(v.name)}</strong></td><td>${v.duration_minutes} min</td><td>€ ${((v.private_price_cents||0)/100).toFixed(2)}</td><td>${v.ssn_enabled?`€ ${((v.ssn_ticket_cents||0)/100).toFixed(2)}`:'No'}</td><td>${v.active?'<span class="badge bg-success">Attiva</span>':'<span class="badge bg-secondary">Off</span>'}</td><td><button class="btn btn-sm btn-outline-secondary" data-edit-visit="${v.id}">Modifica</button></td></tr>`).join("")||'<tr><td colspan="6" class="text-muted">Nessuna tipologia visita.</td></tr>';at.innerHTML=cupCalendarState.agendas.map(a=>`<tr><td><strong>${escapeHtml(a.name)}</strong></td><td>${escapeHtml(a.doctor_name||"-")}</td><td>${escapeHtml(a.location||"-")}</td><td>${(a.rules||[]).map(r=>`${dayNames[r.weekday].slice(0,3)} ${r.start_time}-${r.end_time}`).join(" · ")||"-"}</td><td><button class="btn btn-sm btn-outline-secondary" data-edit-agenda="${a.id}">Modifica</button></td></tr>`).join("")||'<tr><td colspan="5" class="text-muted">Nessuna agenda.</td></tr>';dt.querySelectorAll("[data-edit-doctor]").forEach(b=>b.addEventListener("click",()=>openDoctor(Number(b.dataset.editDoctor))));vt.querySelectorAll("[data-edit-visit]").forEach(b=>b.addEventListener("click",()=>openVisitType(Number(b.dataset.editVisit))));at.querySelectorAll("[data-edit-agenda]").forEach(b=>b.addEventListener("click",()=>openAgenda(Number(b.dataset.editAgenda)))); }
document.getElementById("btn-calendar-config")?.addEventListener("click",async()=>{document.getElementById("calendar-config-panel").classList.remove("d-none");await ensureCalendarMetadata();await renderCalendarConfigTables();document.getElementById("calendar-config-panel").scrollIntoView({behavior:"smooth"});});document.getElementById("btn-close-calendar-config")?.addEventListener("click",()=>document.getElementById("calendar-config-panel").classList.add("d-none"));


// Inserimento rapido configurazione agenda: non dipende dai modali Bootstrap.
function showInlineError(id, message) {
  const el = document.getElementById(id);
  if (!el) return;
  if (message) { el.textContent = message; el.classList.remove("d-none"); }
  else { el.textContent = ""; el.classList.add("d-none"); }
}

document.getElementById("quick-doctor-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  showInlineError("quick-doctor-error", "");
  const btn = e.currentTarget.querySelector('button[type="submit"]');
  if (currentUser?.role !== "admin") { showInlineError("quick-doctor-error", "Solo il profilo Admin può inserire medici."); return; }
  try {
    if (btn) btn.disabled = true;
    await CupApi.saveDoctor({
      full_name: document.getElementById("quick-doctor-name").value.trim(),
      specialty: document.getElementById("quick-doctor-specialty").value.trim() || null,
      email: document.getElementById("quick-doctor-email").value.trim() || null,
      phone: null, active: true, external_provider: "none", external_calendar_id: null, external_calendar_user: null
    });
    e.currentTarget.reset();
    await ensureCalendarMetadata(true);
    await renderCalendarConfigTables();
    await loadCupCalendar();
    showToast("Medico aggiunto.", "success");
  } catch (err) { showInlineError("quick-doctor-error", err.message || "Impossibile aggiungere il medico"); }
  finally { if (btn) btn.disabled = false; }
});

document.getElementById("quick-visit-type-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  showInlineError("quick-visit-type-error", "");
  const btn = e.currentTarget.querySelector('button[type="submit"]');
  if (currentUser?.role !== "admin") { showInlineError("quick-visit-type-error", "Solo il profilo Admin può inserire tipologie visita."); return; }
  try {
    if (btn) btn.disabled = true;
    await CupApi.saveVisitType({
      code: null, name: document.getElementById("quick-visit-type-name").value.trim(),
      duration_minutes: Number(document.getElementById("quick-visit-type-duration").value) || 60,
      buffer_before_minutes: 0, buffer_after_minutes: 0, color: "#0d6efd", active: true, notes: null,
      recall_enabled: true, recall_days: null, followup_enabled: true
    });
    e.currentTarget.reset();
    document.getElementById("quick-visit-type-duration").value = 60;
    await ensureCalendarMetadata(true);
    await renderCalendarConfigTables();
    await loadCupCalendar();
    showToast("Tipologia visita aggiunta.", "success");
  } catch (err) { showInlineError("quick-visit-type-error", err.message || "Impossibile aggiungere la tipologia visita"); }
  finally { if (btn) btn.disabled = false; }
});

// Fallback per i tab della configurazione agenda quando Bootstrap JS non è disponibile.
if (!(window.bootstrap && window.bootstrap.Tab)) {
  document.querySelectorAll('#calendar-config-panel [data-bs-toggle="tab"]').forEach((button) => {
    button.addEventListener("click", (e) => {
      e.preventDefault();
      const target = document.querySelector(button.getAttribute("data-bs-target"));
      if (!target) return;
      document.querySelectorAll('#calendar-config-panel [data-bs-toggle="tab"]').forEach(x => x.classList.remove("active"));
      document.querySelectorAll('#calendar-config-panel .tab-pane').forEach(x => { x.classList.remove("show", "active"); });
      button.classList.add("active"); target.classList.add("show", "active");
    });
  });
}

function openDoctor(id=null){document.getElementById("doctor-form").reset();const d=cupCalendarState.doctors.find(x=>x.id===id);document.getElementById("doctor-id").value=d?.id||"";document.getElementById("doctor-name").value=d?.full_name||"";document.getElementById("doctor-specialty").value=d?.specialty||"";document.getElementById("doctor-email").value=d?.email||"";document.getElementById("doctor-phone").value=d?.phone||"";document.getElementById("doctor-provider").value=d?.external_provider||"none";document.getElementById("doctor-calendar-id").value=d?.external_calendar_id||"";document.getElementById("doctor-calendar-user").value=d?.external_calendar_user||"";document.getElementById("doctor-active").checked=d?.active??true;doctorModal.show();}
document.getElementById("btn-new-doctor")?.addEventListener("click",()=>openDoctor());document.getElementById("doctor-form")?.addEventListener("submit",async e=>{e.preventDefault();try{const id=Number(document.getElementById("doctor-id").value)||null;await CupApi.saveDoctor({full_name:document.getElementById("doctor-name").value.trim(),specialty:document.getElementById("doctor-specialty").value.trim()||null,email:document.getElementById("doctor-email").value.trim()||null,phone:document.getElementById("doctor-phone").value.trim()||null,active:document.getElementById("doctor-active").checked,external_provider:document.getElementById("doctor-provider").value,external_calendar_id:document.getElementById("doctor-calendar-id").value.trim()||null,external_calendar_user:document.getElementById("doctor-calendar-user").value.trim()||null},id);doctorModal.hide();await loadCupCalendar();showToast("Medico salvato.","success");}catch(err){showToast(err.message||"Errore salvataggio medico","error");}});
function openVisitType(id=null){document.getElementById("visit-type-form").reset();const v=cupCalendarState.visitTypes.find(x=>x.id===id);document.getElementById("visit-type-id").value=v?.id||"";document.getElementById("visit-type-code").value=v?.code||"";document.getElementById("visit-type-name").value=v?.name||"";document.getElementById("visit-type-duration").value=v?.duration_minutes||60;document.getElementById("visit-type-buffer-before").value=v?.buffer_before_minutes||0;document.getElementById("visit-type-buffer-after").value=v?.buffer_after_minutes||0;document.getElementById("visit-type-color").value=v?.color_hex||v?.color||"#0d6efd";document.getElementById("visit-type-notes").value=v?.notes||"";document.getElementById("visit-type-followup-enabled").checked=v?.followup_enabled??true;document.getElementById("visit-type-recall-enabled").checked=v?.recall_enabled??true;document.getElementById("visit-type-recall-days").value=v?.recall_days??"";document.getElementById("visit-type-private-price").value=((v?.private_price_cents||0)/100).toFixed(2);document.getElementById("visit-type-ssn-ticket").value=((v?.ssn_ticket_cents||0)/100).toFixed(2);document.getElementById("visit-type-ssn-enabled").checked=v?.ssn_enabled??false;document.getElementById("visit-type-requires-prescription").checked=v?.requires_prescription??false;document.getElementById("visit-type-active").checked=v?.active??true;visitTypeModal.show();}
document.getElementById("btn-new-visit-type")?.addEventListener("click",()=>openVisitType());document.getElementById("visit-type-form")?.addEventListener("submit",async e=>{e.preventDefault();try{const id=Number(document.getElementById("visit-type-id").value)||null;await CupApi.saveVisitType({code:document.getElementById("visit-type-code").value.trim()||null,name:document.getElementById("visit-type-name").value.trim(),duration_minutes:Number(document.getElementById("visit-type-duration").value),buffer_before_minutes:Number(document.getElementById("visit-type-buffer-before").value),buffer_after_minutes:Number(document.getElementById("visit-type-buffer-after").value),color:document.getElementById("visit-type-color").value,active:document.getElementById("visit-type-active").checked,notes:document.getElementById("visit-type-notes").value.trim()||null,followup_enabled:document.getElementById("visit-type-followup-enabled").checked,recall_enabled:document.getElementById("visit-type-recall-enabled").checked,recall_days:Number(document.getElementById("visit-type-recall-days").value)||null,private_price_cents:Math.round((Number(document.getElementById("visit-type-private-price").value)||0)*100),ssn_enabled:document.getElementById("visit-type-ssn-enabled").checked,ssn_ticket_cents:Math.round((Number(document.getElementById("visit-type-ssn-ticket").value)||0)*100),requires_prescription:document.getElementById("visit-type-requires-prescription").checked},id);visitTypeModal.hide();await loadCupCalendar();showToast("Tipologia visita salvata.","success");}catch(err){showToast(err.message||"Errore salvataggio tipologia visita","error");}});
function openAgenda(id=null){document.getElementById("agenda-form").reset();const a=cupCalendarState.agendas.find(x=>x.id===id);document.getElementById("agenda-id").value=a?.id||"";document.getElementById("agenda-name").value=a?.name||"";document.getElementById("agenda-doctor").value=a?.doctor_id||"";document.getElementById("agenda-location").value=a?.location||"";document.getElementById("agenda-slot-minutes").value=a?.slot_minutes||15;document.getElementById("agenda-timezone").value=a?.timezone||"Europe/Rome";document.getElementById("agenda-active").checked=a?.active??true;[...document.getElementById("agenda-visit-types").options].forEach(o=>o.selected=(a?.visit_type_ids||[]).includes(Number(o.value)));agendaRulesEditor(a?.rules||[]);agendaModal.show();}
document.getElementById("btn-new-agenda")?.addEventListener("click",()=>openAgenda());document.getElementById("agenda-form")?.addEventListener("submit",async e=>{e.preventDefault();const id=Number(document.getElementById("agenda-id").value)||null;const rules=[...document.querySelectorAll(".agenda-rule-enabled:checked")].map(c=>({weekday:Number(c.dataset.day),start_time:document.querySelector(`.agenda-rule-start[data-day="${c.dataset.day}"]`).value,end_time:document.querySelector(`.agenda-rule-end[data-day="${c.dataset.day}"]`).value,active:true}));await CupApi.saveAgenda({name:document.getElementById("agenda-name").value.trim(),doctor_id:Number(document.getElementById("agenda-doctor").value),location:document.getElementById("agenda-location").value.trim()||null,timezone:document.getElementById("agenda-timezone").value.trim()||"Europe/Rome",slot_minutes:Number(document.getElementById("agenda-slot-minutes").value),active:document.getElementById("agenda-active").checked,visit_type_ids:selectedValues(document.getElementById("agenda-visit-types")),rules},id);agendaModal.hide();await loadCupCalendar();});

async function testCalendarUi(provider,resultId){const box=document.getElementById(resultId);box.textContent="Test in corso...";try{const r=await CupApi.testCalendarProvider(provider);box.className=`small mt-2 ${r.ok?"text-success":"text-danger"}`;box.textContent=r.message;}catch(e){box.className="small mt-2 text-danger";box.textContent=e.message;}}
document.getElementById("btn-test-google-calendar")?.addEventListener("click",()=>testCalendarUi("google","google-calendar-test"));document.getElementById("btn-test-m365-calendar")?.addEventListener("click",()=>testCalendarUi("microsoft365","m365-calendar-test"));document.querySelectorAll("[data-open-settings]").forEach(b=>b.addEventListener("click",()=>openSettingsSection(b.dataset.openSettings)));

document.getElementById("btn-external-booking-settings")?.addEventListener("click",()=>openSettingsSection("booking"));
document.getElementById("btn-chatbot-only-settings")?.addEventListener("click",()=>openSettingsSection("booking"));
document.getElementById("btn-open-conversations-from-booking")?.addEventListener("click",()=>document.querySelector('[data-tab="chatbot"]')?.click());

// Stato iniziale del calendario.
const calendarDateInput=document.getElementById("calendar-date"); if(calendarDateInput) calendarDateInput.value=localISODate(new Date());


document.getElementById("btn-dashboard-new-booking")?.addEventListener("click",async()=>{
  try{
    await openNewBooking();
  }catch(err){
    console.error("Apertura nuova prenotazione fallita",err);
    if(typeof showToast==="function"){
      showToast(err?.message||"Impossibile aprire la nuova prenotazione.","error");
    }else{
      alert(err?.message||"Impossibile aprire la nuova prenotazione.");
    }
  }
});
document.getElementById("btn-open-calendar-dashboard")?.addEventListener("click",()=>document.querySelector('[data-tab="calendar"]')?.click());
document.getElementById("btn-seed-demo")?.addEventListener("click",async()=>{
  const btn=document.getElementById("btn-seed-demo"),box=document.getElementById("demo-seed-result");
  btn.disabled=true; btn.innerHTML='<span class="spinner-border spinner-border-sm"></span> Caricamento';
  try { const r=await CupApi.seedDemo(false); box.className="alert alert-success mt-3"; box.textContent=r.message||"Dataset demo pronto"; await loadDashboardStats(); }
  catch(e){ box.className="alert alert-danger mt-3"; box.textContent=e.message; }
  finally { btn.disabled=false; btn.innerHTML='<i class="bi bi-stars"></i> Dataset demo'; }
});

// --- Lista d'attesa automatica v1.0.18 ---
const waitlistModalEl = document.getElementById('waitlist-modal');
const waitlistModal = waitlistModalEl ? makeModal('waitlist-modal') : null;

async function loadWaitlist(){
  const tbody=document.getElementById('waitlist-table-body'); if(!tbody)return;
  try{
    const [rows,offers]=await Promise.all([CupApi.getWaitlist(),CupApi.getWaitlistOffers()]);
    const waiting=rows.filter(x=>x.status==='waiting'||x.status==='offered').length;
    const booked=rows.filter(x=>x.status==='booked').length;
    const openOffers=offers.filter(x=>x.status==='open').length;
    document.getElementById('waitlist-kpi-waiting').textContent=waiting;
    document.getElementById('waitlist-kpi-booked').textContent=booked;
    document.getElementById('waitlist-kpi-offers').textContent=openOffers;
    const badge=document.getElementById('waitlist-nav-badge'); if(badge){badge.textContent=waiting;badge.classList.toggle('d-none',!waiting);}
    tbody.innerHTML=rows.length?rows.map(x=>`<tr><td><strong>${escapeHtml(x.patient_name||('#'+x.patient_id))}</strong></td><td>${escapeHtml(x.visit_type_name||'Qualsiasi visita')}</td><td>${escapeHtml(x.agenda_name||x.doctor_name||'Qualsiasi')}</td><td><div class="small">${x.preferred_from?new Date(x.preferred_from).toLocaleDateString('it-IT'):'da subito'} → ${x.preferred_to?new Date(x.preferred_to).toLocaleDateString('it-IT'):'senza limite'}</div><div class="small text-muted">${escapeHtml(x.preferred_time_from||'--:--')} – ${escapeHtml(x.preferred_time_to||'--:--')}</div></td><td><span class="badge ${x.priority>=20?'bg-danger':x.priority>=10?'bg-warning text-dark':'bg-secondary'}">${x.priority>=20?'Urgente':x.priority>=10?'Alta':'Normale'}</span></td><td><span class="badge ${x.status==='booked'?'bg-success':x.status==='offered'?'bg-primary':x.status==='waiting'?'bg-info text-dark':'bg-secondary'}">${escapeHtml(x.status)}</span></td><td class="text-end">${['waiting','offered'].includes(x.status)?`<button class="btn btn-sm btn-outline-secondary" data-waitlist-pause="${x.id}">${x.status==='waiting'?'Pausa':'Rimetti in attesa'}</button> <button class="btn btn-sm btn-outline-danger" data-waitlist-cancel="${x.id}">Rimuovi</button>`:''}</td></tr>`).join(''):'<tr><td colspan="7" class="text-muted p-4">Nessun paziente in lista d’attesa.</td></tr>';
    tbody.querySelectorAll('[data-waitlist-cancel]').forEach(b=>b.addEventListener('click',async()=>{await CupApi.setWaitlistStatus(Number(b.dataset.waitlistCancel),'cancelled');loadWaitlist();}));
    tbody.querySelectorAll('[data-waitlist-pause]').forEach(b=>b.addEventListener('click',async()=>{const row=rows.find(x=>x.id===Number(b.dataset.waitlistPause));await CupApi.setWaitlistStatus(row.id,row.status==='waiting'?'paused':'waiting');loadWaitlist();}));
    const box=document.getElementById('waitlist-offers-list');
    box.innerHTML=offers.length?offers.slice(0,10).map(o=>`<div class="list-group-item d-flex justify-content-between align-items-center gap-3"><div><strong>${new Date(o.scheduled_at).toLocaleString('it-IT')}</strong><div class="small text-muted">${o.recipients} pazienti contattati · scade ${new Date(o.expires_at).toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'})}</div></div><span class="badge ${o.status==='booked'?'bg-success':o.status==='open'?'bg-primary':'bg-secondary'}">${escapeHtml(o.status)}</span></div>`).join(''):'<div class="p-3 text-muted">Nessuna proposta automatica.</div>';
  }catch(e){tbody.innerHTML=`<tr><td colspan="7"><div class="alert alert-danger m-2"><strong>Errore lista d’attesa:</strong> ${escapeHtml(e.message)}</div></td></tr>`;}
}

async function openWaitlistForm(){
  try{
    const [patients,visits,agendas,doctors]=await Promise.all([CupApi.getPatients(),CupApi.getVisitTypes(),CupApi.getAgendas(),CupApi.getDoctors()]);
    document.getElementById('waitlist-patient').innerHTML=patients.map(p=>`<option value="${p.id}">${escapeHtml(p.full_name||('#'+p.id))}</option>`).join('');
    document.getElementById('waitlist-visit').innerHTML='<option value="">Qualsiasi compatibile</option>'+visits.map(v=>`<option value="${v.id}">${escapeHtml(v.name)}</option>`).join('');
    document.getElementById('waitlist-agenda').innerHTML='<option value="">Qualsiasi agenda</option>'+agendas.map(a=>`<option value="${a.id}">${escapeHtml(a.name)}</option>`).join('');
    document.getElementById('waitlist-doctor').innerHTML='<option value="">Qualsiasi medico</option>'+doctors.map(d=>`<option value="${d.id}">${escapeHtml(d.full_name)}</option>`).join('');
    waitlistModal.show();
  }catch(e){showToast(e.message, "error");}
}
document.getElementById('btn-new-waitlist')?.addEventListener('click',openWaitlistForm);
document.getElementById('btn-refresh-waitlist')?.addEventListener('click',loadWaitlist);
document.getElementById('waitlist-form')?.addEventListener('submit',async e=>{e.preventDefault();const err=document.getElementById('waitlist-form-error');err.classList.add('d-none');try{const dateValue=id=>document.getElementById(id).value?document.getElementById(id).value+'T00:00:00':null;await CupApi.createWaitlistEntry({patient_id:Number(document.getElementById('waitlist-patient').value),visit_type_id:Number(document.getElementById('waitlist-visit').value)||null,agenda_id:Number(document.getElementById('waitlist-agenda').value)||null,doctor_id:Number(document.getElementById('waitlist-doctor').value)||null,preferred_from:dateValue('waitlist-from'),preferred_to:document.getElementById('waitlist-to').value?document.getElementById('waitlist-to').value+'T23:59:59':null,preferred_time_from:document.getElementById('waitlist-time-from').value||null,preferred_time_to:document.getElementById('waitlist-time-to').value||null,priority:Number(document.getElementById('waitlist-priority').value),channels:document.getElementById('waitlist-channels').value.trim()||null,notes:document.getElementById('waitlist-notes').value.trim()||null});waitlistModal.hide();e.target.reset();loadWaitlist();}catch(ex){err.textContent=ex.message;err.classList.remove('d-none');}});

// --- Pre-visita digitale e check-in v1.0.19 ---
async function loadPrevisit(){

  const tbody =
    document.getElementById(
      "previsit-table-body"
    );

  const list =
    document.getElementById(
      "checkin-list"
    );

  if(!tbody || !list)
    return;


  tbody.innerHTML =
    '<tr><td colspan="5" class="text-muted">Caricamento...</td></tr>';

  list.innerHTML =
    '<div class="p-3 text-muted">Caricamento...</div>';


  try{

    /*
     * Accoglienza è una vista operativa giornaliera:
     * vengono mostrate esclusivamente le pre-visite
     * relative agli appuntamenti di oggi.
     */
    const today =
      typeof localISODate === "function"
        ? localISODate(new Date())
        : new Date().toISOString().slice(0,10);


    const [allRows,checks] =
      await Promise.all([
        CupApi.getPrevisitSubmissions(),
        CupApi.getCheckins(today)
      ]);


    const rows =
      (allRows || [])
        .filter(x => {

          if(!x.scheduled_at)
            return false;

          const d =
            new Date(x.scheduled_at);

          const key =
            typeof localISODate === "function"
              ? localISODate(d)
              : d.toISOString().slice(0,10);

          return key === today;

        })
        .sort(
          (a,b) =>
            new Date(a.scheduled_at)
            - new Date(b.scheduled_at)
        );


    const pending =
      rows.filter(
        x => x.status === "pending"
      ).length;


    const completed =
      rows.filter(
        x => x.status === "completed"
      ).length;


    document.getElementById(
      "pv-kpi-pending"
    ).textContent = pending;


    document.getElementById(
      "pv-kpi-completed"
    ).textContent = completed;


    document.getElementById(
      "pv-kpi-arrived"
    ).textContent =
      checks.filter(
        x =>
          [
            "checked_in",
            "waiting"
          ].includes(x.status)
      ).length;


    document.getElementById(
      "pv-kpi-invisit"
    ).textContent =
      checks.filter(
        x =>
          x.status === "in_visit"
      ).length;


    const badge =
      document.getElementById(
        "previsit-nav-badge"
      );


    if(badge){

      badge.textContent =
        pending;

      badge.classList.toggle(
        "d-none",
        pending === 0
      );

    }


    tbody.innerHTML =
      rows.length
        ? rows.map(x=>{

            const completedRow =
              x.status === "completed";

            const action =
              completedRow
                ? `
                  <button
                    class="btn btn-sm btn-outline-success"
                    type="button"
                    data-pv-view="${x.id}"
                    title="Visualizza pre-visita compilata">

                    <i class="bi bi-eye"></i>
                    <span class="d-none d-xl-inline ms-1">
                      Visualizza
                    </span>

                  </button>
                `
                : `
                  <button
                    class="btn btn-sm btn-outline-primary"
                    type="button"
                    data-pv-prepare="${x.booking_id}">

                    <i class="bi bi-link-45deg"></i>
                    Link

                  </button>
                `;

            return `
              <tr>

                <td>
                  <strong>
                    ${escapeHtml(
                      x.patient_name || "-"
                    )}
                  </strong>
                </td>

                <td>
                  ${escapeHtml(
                    x.service_name || "-"
                  )}
                </td>

                <td>
                  ${fmtDate(
                    x.scheduled_at
                  )}
                </td>

                <td>
                  <span class="badge ${
                    completedRow
                      ? "bg-success"
                      : "bg-warning text-dark"
                  }">

                    ${
                      completedRow
                        ? "Completata"
                        : "Da compilare"
                    }

                  </span>
                </td>

                <td class="text-end">
                  ${action}
                </td>

              </tr>
            `;

          }).join("")
        : `
          <tr>
            <td
              colspan="5"
              class="text-muted p-3">

              Nessuna pre-visita prevista oggi.

            </td>
          </tr>
        `;


    tbody
      .querySelectorAll(
        "[data-pv-prepare]"
      )
      .forEach(button=>{

        button.onclick =
          async()=>{

            try{

              const result =
                await CupApi.preparePrevisit(
                  Number(
                    button.dataset.pvPrepare
                  )
                );

              prompt(
                "Link pre-visita paziente",
                result.previsit_url
              );

            }
            catch(error){

              showToast(
                error.message,
                "error"
              );

            }

          };

      });


    tbody
      .querySelectorAll(
        "[data-pv-view]"
      )
      .forEach(button=>{

        button.onclick =
          ()=>openPrevisitDetail(
            Number(
              button.dataset.pvView
            )
          );

      });


    const label = {
      not_arrived:"Non arrivato",
      checked_in:"Arrivato",
      waiting:"In attesa",
      in_visit:"In visita",
      completed:"Completato",
      no_show:"No-show"
    };


    list.innerHTML =
      checks.length
        ? checks.map(x=>`
          <div class="list-group-item">

            <div
              class="d-flex justify-content-between gap-2">

              <div>

                <strong>
                  ${escapeHtml(
                    x.patient_name || "-"
                  )}
                </strong>

                <div class="small text-muted">

                  ${escapeHtml(
                    x.service_name || "-"
                  )}

                  ·

                  ${new Date(
                    x.scheduled_at
                  ).toLocaleTimeString(
                    "it-IT",
                    {
                      hour:"2-digit",
                      minute:"2-digit"
                    }
                  )}

                </div>

              </div>

              <span
                class="badge bg-light text-dark border">

                ${label[x.status] || x.status}

              </span>

            </div>


            <div
              class="btn-group btn-group-sm mt-2"
              role="group">

              <button
                class="btn btn-outline-success"
                data-ci="${x.id}"
                data-status="checked_in">
                Arrivato
              </button>

              <button
                class="btn btn-outline-warning"
                data-ci="${x.id}"
                data-status="waiting">
                In attesa
              </button>

              <button
                class="btn btn-outline-primary"
                data-ci="${x.id}"
                data-status="in_visit">
                In visita
              </button>

              <button
                class="btn btn-outline-secondary"
                data-ci="${x.id}"
                data-status="completed">
                Completa
              </button>

            </div>

          </div>
        `).join("")
        : `
          <div class="p-3 text-muted">
            Nessun appuntamento oggi.
          </div>
        `;


    list
      .querySelectorAll(
        "[data-ci]"
      )
      .forEach(button=>{

        button.onclick =
          async()=>{

            button.disabled = true;

            try{

              await CupApi.setCheckinStatus(
                Number(
                  button.dataset.ci
                ),
                button.dataset.status
              );

              await loadPrevisit();

            }
            catch(error){

              showToast(
                error.message,
                "error"
              );

              button.disabled = false;

            }

          };

      });


  }
  catch(error){

    tbody.innerHTML =
      `<tr>
        <td colspan="5" class="text-danger">
          ${escapeHtml(error.message)}
        </td>
      </tr>`;

    list.innerHTML =
      `<div class="p-3 text-danger">
        ${escapeHtml(error.message)}
      </div>`;

  }

}


document
  .getElementById(
    "btn-refresh-previsit"
  )
  ?.addEventListener(
    "click",
    loadPrevisit
  );


// --- Continuità di cura v1.0.20 ---
async function loadCare(){
  const ft=document.getElementById("followup-table"), rt=document.getElementById("recall-table"); if(!ft||!rt)return;
  try{
    const [followups,recalls]=await Promise.all([CupApi.getFollowups(),CupApi.getRecalls()]);
    const needs=followups.filter(x=>x.status==="needs_contact").length, fpending=followups.filter(x=>["scheduled","sent","failed"].includes(x.status)).length;
    const due=recalls.filter(x=>["due","sent","failed"].includes(x.status)).length, booked=recalls.filter(x=>x.status==="booked").length;
    document.getElementById("care-needs-contact").textContent=needs;document.getElementById("care-followup-pending").textContent=fpending;document.getElementById("care-recall-due").textContent=due;document.getElementById("care-recall-booked").textContent=booked;
    const badge=document.getElementById("care-nav-badge");if(badge){badge.textContent=needs+due;badge.classList.toggle("d-none",needs+due===0)}
    const fs={scheduled:"Pianificato",sent:"Inviato",completed:"Completato",needs_contact:"Da ricontattare",failed:"Errore",skipped:"Saltato"};
    ft.innerHTML=followups.length?followups.sort((a,b)=>(a.status==="needs_contact"?-1:1)).map(x=>`<tr><td><strong>${escapeHtml(x.patient_name||"-")}</strong></td><td>${escapeHtml(x.service_name||"-")}</td><td>${x.rating?`${x.rating}/5 · ${escapeHtml(x.wellbeing||"")}`:"-"}${x.comment?`<div class="small text-muted">${escapeHtml(x.comment)}</div>`:""}</td><td><span class="badge ${x.status==="needs_contact"?"bg-danger":x.status==="completed"?"bg-success":"bg-light text-dark border"}">${fs[x.status]||x.status}</span></td><td><div class="btn-group btn-group-sm">${["scheduled","failed"].includes(x.status)?`<button class="btn btn-outline-primary" data-followup-send="${x.id}">Invia</button>`:""}${x.status==="needs_contact"?`<button class="btn btn-success" data-followup-resolve="${x.id}">Gestito</button>`:""}</div></td></tr>`).join(""):'<tr><td colspan="5" class="text-muted p-3">Nessun follow-up.</td></tr>';
    const rs={scheduled:"Pianificato",due:"Da inviare",sent:"Contattato",booked:"Prenotato",completed:"Completato",snoozed:"Posticipato",failed:"Errore",cancelled:"Annullato"};
    rt.innerHTML=recalls.length?recalls.map(x=>`<tr><td><strong>${escapeHtml(x.patient_name||"-")}</strong></td><td>${escapeHtml(x.service_name||"Controllo")}</td><td>${new Date(x.due_at).toLocaleDateString("it-IT")}</td><td><span class="badge ${x.status==="booked"?"bg-success":x.status==="due"||x.status==="failed"?"bg-warning text-dark":"bg-light text-dark border"}">${rs[x.status]||x.status}</span></td><td><div class="btn-group btn-group-sm">${["scheduled","due","failed"].includes(x.status)?`<button class="btn btn-outline-primary" data-recall-send="${x.id}">Invia</button>`:""}${!["booked","completed","cancelled"].includes(x.status)?`<button class="btn btn-outline-secondary" data-recall-snooze="${x.id}">+30 gg</button>`:""}</div></td></tr>`).join(""):'<tr><td colspan="5" class="text-muted p-3">Nessun recall.</td></tr>';
    ft.querySelectorAll("[data-followup-send]").forEach(b=>b.onclick=async()=>{try{await CupApi.sendFollowup(Number(b.dataset.followupSend));loadCare()}catch(e){showToast(e.message, "error")}});
    ft.querySelectorAll("[data-followup-resolve]").forEach(b=>b.onclick=async()=>{try{await CupApi.resolveFollowup(Number(b.dataset.followupResolve));loadCare();loadDashboardStats()}catch(e){showToast(e.message, "error")}});
    rt.querySelectorAll("[data-recall-send]").forEach(b=>b.onclick=async()=>{try{await CupApi.sendRecall(Number(b.dataset.recallSend));loadCare()}catch(e){showToast(e.message, "error")}});
    rt.querySelectorAll("[data-recall-snooze]").forEach(b=>b.onclick=async()=>{try{await CupApi.snoozeRecall(Number(b.dataset.recallSnooze),30);loadCare()}catch(e){showToast(e.message, "error")}});
  }catch(e){ft.innerHTML=`<tr><td colspan="5" class="text-danger p-3">${escapeHtml(e.message)}</td></tr>`;rt.innerHTML=`<tr><td colspan="5" class="text-danger p-3">${escapeHtml(e.message)}</td></tr>`}
}
document.getElementById("btn-refresh-care")?.addEventListener("click",loadCare);

// --- Analytics v1.0.21 ---
function fmtPct(v){ return `${Number(v||0).toFixed(1)}%`; }
function fmtSeconds(v){
  const s=Number(v||0); if(!s) return "-";
  if(s<60) return `${Math.round(s)}s`;
  const m=Math.floor(s/60), r=Math.round(s%60); return `${m}m ${r}s`;
}

async function loadOperationalAnalytics(){
  try{
    const d=await CupApi.getAnalyticsOverview(30);
    const n=document.getElementById("op-metric-noshow"); if(n)n.textContent=fmtPct(d.bookings?.no_show_rate);
    const r=document.getElementById("op-metric-reminders"); if(r)r.textContent=fmtPct(d.reminders?.delivery_rate);
    const h=document.getElementById("op-metric-handoff"); if(h)h.textContent=fmtSeconds(d.handoffs?.avg_response_seconds);
    const p=document.getElementById("op-metric-previsit"); if(p)p.textContent=fmtPct(d.previsit?.completion_rate);
  }catch(_){ /* i KPI operativi non devono bloccare la dashboard */ }
}

function renderAnalyticsTrend(rows){
  const box=document.getElementById("analytics-trend"); if(!box)return;
  if(!rows?.length){box.innerHTML='<div class="text-muted">Nessun dato nel periodo.</div>';return;}
  const max=Math.max(1,...rows.map(x=>x.bookings||0));
  const visible=rows.length>45?rows.filter((_,i)=>i%Math.ceil(rows.length/45)===0):rows;
  box.innerHTML=visible.map(x=>{
    const total=Math.max(4,(x.bookings/max)*100), completed=(x.completed/max)*100, cancelled=(x.cancelled/max)*100, noShow=(x.no_show/max)*100;
    const label=new Date(x.date+'T12:00:00').toLocaleDateString('it-IT',{day:'2-digit',month:'2-digit'});
    return `<div class="trend-day" title="${label}: ${x.bookings} appuntamenti, ${x.completed} completati, ${x.cancelled} cancellati, ${x.no_show} no-show"><div class="trend-stack"><span class="trend-bar bookings" style="height:${total}%"></span><span class="trend-bar completed" style="height:${completed}%"></span><span class="trend-bar cancelled" style="height:${cancelled}%"></span><span class="trend-bar noshow" style="height:${noShow}%"></span></div><small>${label}</small></div>`;
  }).join('');
}

function analyticsProgress(label,value,meta=''){
  const n=Math.max(0,Math.min(100,Number(value||0)));
  return `<div class="analytics-progress-row"><div class="d-flex justify-content-between gap-2"><span>${escapeHtml(label)}</span><strong>${fmtPct(n)}</strong></div><div class="progress"><div class="progress-bar" style="width:${n}%"></div></div>${meta?`<div class="small text-muted mt-1">${escapeHtml(meta)}</div>`:''}</div>`;
}

async function loadAnalytics(){
  if(currentUser?.role!=="admin") return;
  const days=Number(document.getElementById("analytics-period")?.value||30);
  try{
    const d=await CupApi.getAdminAnalytics(days);
    document.getElementById("an-occupancy").textContent=fmtPct(d.occupancy?.overall_rate);
    document.getElementById("an-noshow").textContent=fmtPct(d.bookings?.no_show_rate);
    document.getElementById("an-conversion").textContent=fmtPct(d.channels?.conversion_rate);
    document.getElementById("an-handoff-time").textContent=fmtSeconds(d.handoffs?.avg_response_seconds);
    renderAnalyticsTrend(d.trend||[]);

    const funnel=document.getElementById("analytics-funnel");
    if(funnel) funnel.innerHTML=[
      analyticsProgress("Promemoria consegnati",d.reminders?.delivery_rate,`${d.reminders?.sent||0} inviati · ${d.reminders?.failed||0} falliti`),
      analyticsProgress("Pre-visita completata",d.previsit?.completion_rate,`${d.previsit?.completed||0} su ${d.previsit?.total||0}`),
      analyticsProgress("Handoff accettati",d.handoffs?.acceptance_rate,`${d.handoffs?.accepted||0} su ${d.handoffs?.requested||0}`),
      analyticsProgress("Lista d'attesa riempita",d.waitlist?.fill_rate,`${d.waitlist?.booked_offers||0} slot recuperati`),
      analyticsProgress("Recall → nuova prenotazione",d.care?.recall_conversion_rate,`${d.care?.recalls_booked||0} richiami convertiti`),
    ].join('');

    const agendas=document.getElementById("analytics-agendas");
    agendas.innerHTML=(d.occupancy?.agendas||[]).length?(d.occupancy.agendas.map(x=>`<tr><td><strong>${escapeHtml(x.name)}</strong><div class="small text-muted">${escapeHtml(x.location||'')}</div></td><td>${escapeHtml(x.doctor||'-')}</td><td><div class="d-flex align-items-center gap-2"><div class="progress flex-grow-1"><div class="progress-bar ${x.occupancy_rate>95?'bg-danger':x.occupancy_rate>80?'bg-warning':''}" style="width:${Math.min(100,x.occupancy_rate)}%"></div></div><strong>${fmtPct(x.occupancy_rate)}</strong></div></td></tr>`).join('')):'<tr><td colspan="3" class="text-muted p-3">Nessuna agenda configurata.</td></tr>';

    const channels=document.getElementById("analytics-channels");
    channels.innerHTML=(d.channels?.items||[]).length?d.channels.items.map(x=>`<tr><td><span class="channel-pill">${escapeHtml(x.channel)}</span></td><td>${x.sessions}</td><td>${x.bookings}</td><td><strong>${fmtPct(x.conversion_rate)}</strong></td></tr>`).join(''):'<tr><td colspan="4" class="text-muted p-3">Nessuna sessione nel periodo.</td></tr>';

    const ops=document.getElementById("analytics-operators");
    ops.innerHTML=(d.operators||[]).length?d.operators.map(x=>`<tr><td><strong>${escapeHtml(x.name)}</strong></td><td>${x.handoffs_accepted}</td><td>${fmtSeconds(x.avg_response_seconds)}</td><td>${x.bookings_created}</td></tr>`).join(''):'<tr><td colspan="4" class="text-muted p-3">Nessuna attività operatore nel periodo.</td></tr>';
  }catch(e){
    ["analytics-agendas","analytics-channels","analytics-operators"].forEach(id=>{const el=document.getElementById(id);if(el)el.innerHTML=`<tr><td colspan="4" class="text-danger p-3">${escapeHtml(e.message)}</td></tr>`;});
  }
}

document.getElementById("btn-refresh-analytics")?.addEventListener("click",loadAnalytics);
document.getElementById("analytics-period")?.addEventListener("change",loadAnalytics);

// --- Operatori, pagamenti e firma documentale v1.0.23.1 ---
let commercePatients = [];
let commerceBookings = [];

async function loadOperatorsAdmin() {
  if (currentUser?.role !== "admin") return;
  const tbody = document.getElementById("operators-table");
  if (!tbody) return;
  try {
    const rows = await CupApi.getOperators();
    tbody.innerHTML = rows.length ? rows.map(o => `
      <tr data-operator-row="${o.id}">
        <td><strong>${escapeHtml(o.full_name)}</strong><div class="small text-muted">${escapeHtml(o.email)}</div></td>
        <td><div class="form-check form-switch"><input class="form-check-input" type="checkbox" data-op-chat="${o.id}" ${o.can_chat ? "checked" : ""}></div></td>
        <td><div class="form-check form-switch"><input class="form-check-input" type="checkbox" data-op-phone="${o.id}" ${o.can_phone ? "checked" : ""}></div></td>

        <td style="min-width:210px">
          <input
            class="form-control form-control-sm mb-1"
            data-op-voip-extension="${o.id}"
            value="${escapeHtml(o.voip_extension||"")}"
            placeholder="Interno">

          <input
            class="form-control form-control-sm"
            type="password"
            data-op-voip-password="${o.id}"
            placeholder="${
              o.voip_configured
                ?"Password SIP configurata"
                :"Password SIP"
            }">
        </td>

        <td><div class="form-check form-switch"><input class="form-check-input" type="checkbox" data-op-active="${o.id}" ${o.is_active ? "checked" : ""}></div></td>
        <td><button class="btn btn-sm btn-outline-primary" data-op-save="${o.id}">Salva</button></td>
      </tr>`).join("") : '<tr><td colspan="6" class="text-muted">Nessun operatore configurato.</td></tr>';
    tbody.querySelectorAll("[data-op-save]").forEach(btn => btn.addEventListener("click", async () => {
      const id = btn.dataset.opSave;
      btn.disabled = true;
      try {
        await CupApi.updateOperator(id, {
          can_chat: document.querySelector(`[data-op-chat="${id}"]`).checked,
          can_phone: document.querySelector(`[data-op-phone="${id}"]`).checked,
          is_active: document.querySelector(`[data-op-active="${id}"]`).checked,
          voip_extension:
            document.querySelector(
              `[data-op-voip-extension="${id}"]`
            ).value.trim(),
          voip_password:
            document.querySelector(
              `[data-op-voip-password="${id}"]`
            ).value || null,
        });
        btn.textContent = "Salvato";
        setTimeout(() => btn.textContent = "Salva", 1200);
      } catch (e) { showToast(e.message, "error"); }
      finally { btn.disabled = false; }
    }));
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-danger">${escapeHtml(e.message)}</td></tr>`;
  }
}

document.getElementById("btn-refresh-operators")?.addEventListener("click", loadOperatorsAdmin);
document.getElementById("operator-create-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await CupApi.createOperator({
      full_name: document.getElementById("operator-create-name").value.trim(),
      email: document.getElementById("operator-create-email").value.trim(),
      password: document.getElementById("operator-create-password").value,
      voip_extension:
        document.getElementById(
          "operator-create-voip-extension"
        ).value.trim() || null,
      voip_password:
        document.getElementById(
          "operator-create-voip-password"
        ).value || null,
      can_chat: document.getElementById("operator-create-chat").checked,
      can_phone: document.getElementById("operator-create-phone").checked,
    });
    e.target.reset();
    document.getElementById("operator-create-chat").checked = true;
    document.getElementById("operator-create-phone").checked = true;
    loadOperatorsAdmin();
  } catch (err) { showToast(err.message, "error"); }
});

function commerceBookingOptions(patientId) {
  const options = commerceBookings.filter(b => !patientId || String(b.patient_id) === String(patientId))
    .sort((a,b)=>new Date(b.scheduled_at)-new Date(a.scheduled_at))
    .slice(0,60)
    .map(b => `<option value="${b.id}">#${b.id} · ${escapeHtml(b.service_name)} · ${new Date(b.scheduled_at).toLocaleString("it-IT",{dateStyle:"short",timeStyle:"short"})}</option>`).join("");
  return '<option value="">Nessun appuntamento specifico</option>' + options;
}

function refreshCommerceBookingSelects() {
  const pp = document.getElementById("payment-patient"), sp = document.getElementById("signature-patient");
  const pb = document.getElementById("payment-booking"), sb = document.getElementById("signature-booking");
  if (pb) pb.innerHTML = commerceBookingOptions(pp?.value);
  if (sb) sb.innerHTML = commerceBookingOptions(sp?.value);
}

function paymentStatusBadge(status) {
  const m = { pending:"bg-secondary", sent:"bg-warning text-dark", paid:"bg-success", cancelled:"bg-light text-dark border", failed:"bg-danger", expired:"bg-dark" };
  return `<span class="badge ${m[status]||"bg-secondary"}">${escapeHtml(status||"-")}</span>`;
}
function signatureStatusBadge(status) {
  const m = { pending:"bg-secondary", sent:"bg-info text-dark", viewed:"bg-warning text-dark", signed:"bg-success", declined:"bg-danger", expired:"bg-dark", failed:"bg-danger" };
  return `<span class="badge ${m[status]||"bg-secondary"}">${escapeHtml(status||"-")}</span>`;
}

async function loadCommerce() {
  const pt = document.getElementById("payments-table"), st = document.getElementById("signatures-table");
  if (!pt || !st) return;
  try {
    const [patients, bookings, payments, signatures] = await Promise.all([
      CupApi.getPatients(), CupApi.getBookings(), CupApi.getPayments(), CupApi.getSignatures()
    ]);
    commercePatients = patients; commerceBookings = bookings;
    const patientOptions = patients.map(p=>`<option value="${p.id}">${escapeHtml(p.full_name||`Paziente #${p.id}`)}</option>`).join("");
    ["payment-patient","signature-patient"].forEach(id=>{const el=document.getElementById(id); if(el){const old=el.value;el.innerHTML=patientOptions;if(old)el.value=old;}});
    refreshCommerceBookingSelects();
    pt.innerHTML = payments.length ? payments.map(x=>`<tr><td><strong>${escapeHtml(x.patient_name||`#${x.patient_id}`)}</strong></td><td>${escapeHtml(x.description)}</td><td>${Number(x.amount||0).toLocaleString("it-IT",{style:"currency",currency:x.currency||"EUR"})}</td><td>${paymentStatusBadge(x.status)}<div class="small text-muted">${escapeHtml(x.provider||"")}</div></td><td><div class="btn-group btn-group-sm">${!['paid','cancelled'].includes(x.status)?`<button class="btn btn-outline-primary" data-payment-send="${x.id}">Reinvia</button>`:""}${x.status!=="paid"?`<button class="btn btn-outline-success" data-payment-paid="${x.id}">Pagato</button>`:""}</div></td></tr>`).join("") : '<tr><td colspan="5" class="text-muted p-3">Nessuna richiesta di pagamento.</td></tr>';
    st.innerHTML = signatures.length ? signatures.map(x=>`<tr><td><strong>${escapeHtml(x.patient_name||`#${x.patient_id}`)}</strong></td><td>${escapeHtml(x.title)}<div class="small text-muted">${escapeHtml(x.original_filename||"")}</div></td><td>${signatureStatusBadge(x.status)}</td><td>${x.signed_at?new Date(x.signed_at).toLocaleString("it-IT"):"-"}</td><td><div class="btn-group btn-group-sm">${!['signed','declined','expired'].includes(x.status)?`<button class="btn btn-outline-primary" data-sign-send="${x.id}">Reinvia</button>`:""}<button class="btn btn-outline-secondary" data-sign-audit="${x.id}">Audit</button></div></td></tr>`).join("") : '<tr><td colspan="5" class="text-muted p-3">Nessun documento inviato.</td></tr>';
    const pending = payments.filter(x=>['pending','sent','failed'].includes(x.status)).length + signatures.filter(x=>['pending','sent','viewed','failed'].includes(x.status)).length;
    const badge=document.getElementById("commerce-nav-badge"); if(badge){badge.textContent=pending;badge.classList.toggle("d-none",!pending);}
    pt.querySelectorAll("[data-payment-send]").forEach(b=>b.addEventListener("click",async()=>{try{await CupApi.sendPayment(b.dataset.paymentSend);loadCommerce();}catch(e){showToast(e.message, "error");}}));
    pt.querySelectorAll("[data-payment-paid]").forEach(b=>b.addEventListener("click",async()=>{if(!confirm("Confermi che il pagamento è stato ricevuto?"))return;try{await CupApi.updatePaymentStatus(b.dataset.paymentPaid,"paid");loadCommerce();}catch(e){showToast(e.message, "error");}}));
    st.querySelectorAll("[data-sign-send]").forEach(b=>b.addEventListener("click",async()=>{try{await CupApi.sendSignature(b.dataset.signSend);loadCommerce();}catch(e){showToast(e.message, "error");}}));
    st.querySelectorAll("[data-sign-audit]").forEach(b=>b.addEventListener("click",async()=>{try{const a=await CupApi.getSignatureAudit(b.dataset.signAudit);alert(`Audit firma #${a.request_id}\nStato: ${a.status}\nFirmatario: ${a.signer_name||'-'}\nFirmato: ${a.signed_at||'-'}\nDocumento SHA-256: ${a.document_sha256}\nFirma SHA-256: ${a.signature_sha256||'-'}`);}catch(e){showToast(e.message, "error");}}));
  } catch (e) {
    pt.innerHTML = `<tr><td colspan="5" class="text-danger p-3">${escapeHtml(e.message)}</td></tr>`;
    st.innerHTML = `<tr><td colspan="5" class="text-danger p-3">${escapeHtml(e.message)}</td></tr>`;
  }
}

document.getElementById("payment-patient")?.addEventListener("change", refreshCommerceBookingSelects);
document.getElementById("signature-patient")?.addEventListener("change", refreshCommerceBookingSelects);
document.getElementById("btn-refresh-commerce")?.addEventListener("click", loadCommerce);
document.getElementById("payment-request-form")?.addEventListener("submit", async (e)=>{
  e.preventDefault(); const out=document.getElementById("payment-form-result");
  try {
    const data=await CupApi.createPayment({patient_id:Number(document.getElementById("payment-patient").value),booking_id:Number(document.getElementById("payment-booking").value)||null,description:document.getElementById("payment-description").value.trim(),amount:Number(document.getElementById("payment-amount").value),currency:"EUR",channels:document.getElementById("payment-channels").value.trim()||null,send_now:document.getElementById("payment-send-now").checked});
    out.className="small mt-3 text-success";out.textContent=`Richiesta #${data.id} creata.`;e.target.reset();document.getElementById("payment-send-now").checked=true;loadCommerce();
  } catch(err){out.className="small mt-3 text-danger";out.textContent=err.message;}
});
document.getElementById("signature-request-form")?.addEventListener("submit", async (e)=>{
  e.preventDefault(); const out=document.getElementById("signature-form-result");
  try {
    const fd=new FormData();fd.append("patient_id",document.getElementById("signature-patient").value);const booking=document.getElementById("signature-booking").value;if(booking)fd.append("booking_id",booking);fd.append("title",document.getElementById("signature-title").value.trim());fd.append("message",document.getElementById("signature-message").value.trim());fd.append("channels",document.getElementById("signature-channels").value.trim());fd.append("send_now",document.getElementById("signature-send-now").checked?"true":"false");fd.append("document",document.getElementById("signature-file").files[0]);
    const data=await CupApi.createSignatureRequest(fd);out.className="small mt-2 text-success";out.textContent=`Documento #${data.id} creato.`;e.target.reset();document.getElementById("signature-send-now").checked=true;loadCommerce();
  } catch(err){out.className="small mt-2 text-danger";out.textContent=err.message;}
});


// --- Apprendimento AI supervisionato v1.0.23.1 ---
async function loadTrainingSamplesAdmin() {
  if (currentUser?.role !== "admin") return;
  const tbody = document.getElementById("training-samples-table");
  if (!tbody) return;
  try {
    const rows = await CupApi.getTrainingSamples();
    tbody.innerHTML = rows.length ? rows.slice(0,100).map(x => `
      <tr>
        <td><span class="badge ${x.source_type==='voice'?'bg-primary':'bg-info text-dark'}">${escapeHtml(x.source_type)}</span>${x.consent_obtained?'<div class="small text-success">consenso OK</div>':''}</td>
        <td class="small">${escapeHtml(x.user_text)}</td>
        <td class="small">${escapeHtml(x.operator_text)}</td>
        <td><span class="badge ${x.status==='approved'?'bg-success':x.status==='rejected'?'bg-secondary':'bg-warning text-dark'}">${escapeHtml(x.status)}</span></td>
        <td>${x.status==='pending'?`<div class="btn-group btn-group-sm"><button class="btn btn-outline-success" data-training-approve="${x.id}">Approva</button><button class="btn btn-outline-secondary" data-training-reject="${x.id}">Scarta</button></div>`:''}</td>
      </tr>`).join("") : '<tr><td colspan="5" class="text-muted">Nessun esempio raccolto.</td></tr>';
    tbody.querySelectorAll("[data-training-approve]").forEach(b=>b.addEventListener("click",async()=>{await CupApi.reviewTrainingSample(b.dataset.trainingApprove,"approved");loadTrainingSamplesAdmin();}));
    tbody.querySelectorAll("[data-training-reject]").forEach(b=>b.addEventListener("click",async()=>{await CupApi.reviewTrainingSample(b.dataset.trainingReject,"rejected");loadTrainingSamplesAdmin();}));
  } catch (e) { tbody.innerHTML=`<tr><td colspan="5" class="text-danger">${escapeHtml(e.message)}</td></tr>`; }
}
document.getElementById("btn-refresh-training")?.addEventListener("click", loadTrainingSamplesAdmin);


// --- Test comunicazioni paziente v1.0.29 ---
async function runPatientChannelTest(channel){
  const destId=channel==="telegram"?"test-telegram-chat-id":"test-phone-number";
  const resultId=channel==="telegram"?"test-telegram-result":"test-phone-result";
  const btnId=channel==="telegram"?"btn-test-telegram-message":"btn-test-phone-call";
  const destination=document.getElementById(destId)?.value.trim();
  const message=document.getElementById("test-channel-message")?.value.trim()||"Test CUP AI";
  const result=document.getElementById(resultId), btn=document.getElementById(btnId);
  if(!destination){if(result){result.className="form-text text-danger";result.textContent="Inserisci la destinazione di test.";}return;}
  if(btn)btn.disabled=true;if(result){result.className="form-text";result.textContent="Test in corso...";}
  try{const data=await CupApi.testChannelMessage(channel,destination,message);if(result){result.className=`form-text ${data.ok?"text-success":"text-danger"}`;result.textContent=data.message|| (data.ok?"OK":"Errore");}}
  catch(e){if(result){result.className="form-text text-danger";result.textContent=e.message;}}finally{if(btn)btn.disabled=false;}
}

document.getElementById("btn-test-telegram-message")?.addEventListener("click",()=>runPatientChannelTest("telegram"));
document.getElementById("btn-test-phone-call")?.addEventListener("click",()=>runPatientChannelTest("phone"));
// ============================================================
// CALLS REALTIME - Asterisk / MikoPBX
// ============================================================



function initCallsRealtime() {

  if (!window.CUP_CONFIG?.WS_CALLS_URL) {
    console.warn("WS_CALLS_URL non configurato");
    return;
  }

  if (callsWsReconnectTimer) {
    clearTimeout(callsWsReconnectTimer);
    callsWsReconnectTimer = null;
  }

  try {
    if (callsWs) {
      callsWs.onclose = null;
      callsWs.close();
    }

    console.log(
      "CUP: connessione WebSocket chiamate",
      window.CUP_CONFIG.WS_CALLS_URL
    );

    callsWs = new WebSocket(window.CUP_CONFIG.WS_CALLS_URL);

    callsWs.onopen = () => {
      console.log("CUP: WebSocket chiamate connesso");
    };

    callsWs.onmessage = async (event) => {

      console.log("CUP: evento chiamata", event.data);

      try {
        const payload = JSON.parse(event.data);

        // Aggiorna tabella chiamate.
        if (
          currentUser?.role === "admin" ||
          currentUser?.can_phone !== false
        ) {
          await loadCalls();
        }

        // Manteniamo disponibile l'evento per la futura Call Island.
        window.dispatchEvent(
          new CustomEvent("cup-call-event", {
            detail: payload
          })
        );

      } catch (err) {
        console.error(
          "CUP: errore gestione evento chiamata",
          err
        );
      }
    };

    callsWs.onerror = (event) => {
      console.error("CUP: errore WebSocket chiamate", event);
    };

    callsWs.onclose = () => {

      console.warn(
        "CUP: WebSocket chiamate disconnesso - riconnessione..."
      );

      callsWsReconnectTimer = setTimeout(
        initCallsRealtime,
        4000
      );
    };

  } catch (err) {

    console.error(
      "CUP: impossibile inizializzare WebSocket chiamate",
      err
    );

    callsWsReconnectTimer = setTimeout(
      initCallsRealtime,
      4000
    );
  }
}
// ============================================================
// CUP CALL ISLAND
// Realtime UI collegata a /api/calls/ws
// ============================================================

let cupCallIslandTimer = null;
let cupCallIslandStartedAt = null;
let cupCallIslandCurrentId = null;

function cupFormatPhone(number) {
  if (!number) return "Numero sconosciuto";

  const n = String(number).replace(/\s+/g, "");

  if (n.startsWith("+39") && n.length >= 12) {
    return `${n.slice(0, 3)} ${n.slice(3, 6)} ${n.slice(6, 9)} ${n.slice(9)}`;
  }

  return number;
}

function cupEnsureCallIsland() {

  if (document.getElementById("cup-call-island")) return;

  const style = document.createElement("style");

  style.textContent = `
    #cup-call-island {
      position: fixed;
      right: 24px;
      bottom: 24px;
      width: 350px;
      z-index: 1085;
      background: rgba(20, 25, 32, .97);
      color: #fff;
      border-radius: 22px;
      box-shadow: 0 18px 55px rgba(0,0,0,.28);
      padding: 18px;
      transform: translateY(30px);
      opacity: 0;
      pointer-events: none;
      transition: all .25s ease;
      backdrop-filter: blur(16px);
    }

    #cup-call-island.visible {
      transform: translateY(0);
      opacity: 1;
      pointer-events: auto;
    }

    .cup-call-island-top {
      display: flex;
      align-items: center;
      gap: 13px;
    }

    .cup-call-avatar {
      width: 48px;
      height: 48px;
      border-radius: 50%;
      background: rgba(255,255,255,.12);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 21px;
      flex-shrink: 0;
    }

    .cup-call-info {
      flex: 1;
      min-width: 0;
    }

    .cup-call-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .09em;
      opacity: .65;
      margin-bottom: 2px;
    }

    .cup-call-number {
      font-size: 18px;
      font-weight: 650;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .cup-call-destination {
      font-size: 12px;
      opacity: .65;
      margin-top: 2px;
    }

    .cup-call-status-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-top: 17px;
      padding-top: 14px;
      border-top: 1px solid rgba(255,255,255,.1);
      font-size: 13px;
    }

    .cup-call-status {
      display: flex;
      align-items: center;
      gap: 7px;
    }

    .cup-call-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #ffc107;
      box-shadow: 0 0 0 4px rgba(255,193,7,.12);
    }

    #cup-call-island.active .cup-call-dot {
      background: #36d17c;
      box-shadow: 0 0 0 4px rgba(54,209,124,.13);
    }

    #cup-call-duration {
      font-variant-numeric: tabular-nums;
      opacity: .8;
    }

    .cup-call-actions {
      display: flex;
      gap: 8px;
      margin-top: 15px;
    }

    .cup-call-actions button {
      flex: 1;
      border-radius: 12px;
    }

    @media (max-width: 576px) {
      #cup-call-island {
        left: 12px;
        right: 12px;
        bottom: 12px;
        width: auto;
      }
    }
  `;

  document.head.appendChild(style);

  const island = document.createElement("div");

  island.id = "cup-call-island";

  island.innerHTML = `
    <div class="cup-call-island-top">

      <div class="cup-call-avatar">
        <i class="bi bi-telephone-fill"></i>
      </div>

      <div class="cup-call-info">

        <div class="cup-call-label">
          Chiamata in arrivo
        </div>

        <div
          class="cup-call-number"
          id="cup-call-number">
          -
        </div>

        <div
          class="cup-call-destination"
          id="cup-call-destination">
        </div>

      </div>

    </div>

    <div class="cup-call-status-row">

      <div class="cup-call-status">
        <span class="cup-call-dot"></span>
        <span id="cup-call-status-text">
          In arrivo
        </span>
      </div>

      <div id="cup-call-duration">
        00:00
      </div>

    </div>

    <div class="cup-call-actions">

      <button
        type="button"
        class="btn btn-light btn-sm"
        id="cup-call-open">

        <i class="bi bi-person-vcard me-1"></i>
        Scheda

      </button>

      <button
        type="button"
        class="btn btn-outline-light btn-sm"
        id="cup-call-hide">

        <i class="bi bi-chevron-down"></i>

      </button>

    </div>
  `;

  document.body.appendChild(island);

  document
    .getElementById("cup-call-hide")
    ?.addEventListener("click", () => {

      island.classList.remove("visible");

    });

  document
    .getElementById("cup-call-open")
    ?.addEventListener("click", () => {

      const callsTab =
        document.querySelector('[data-tab="calls"]');

      if (callsTab) {
        callsTab.click();
      }

    });
}


function cupStartCallTimer() {

  clearInterval(cupCallIslandTimer);

  cupCallIslandStartedAt = Date.now();

  cupCallIslandTimer = setInterval(() => {

    const seconds = Math.floor(
      (Date.now() - cupCallIslandStartedAt) / 1000
    );

    const mm = String(
      Math.floor(seconds / 60)
    ).padStart(2, "0");

    const ss = String(
      seconds % 60
    ).padStart(2, "0");

    const el =
      document.getElementById("cup-call-duration");

    if (el) {
      el.textContent = `${mm}:${ss}`;
    }

  }, 1000);
}


function cupShowIncomingCall(payload) {

  cupEnsureCallIsland();

  cupCallIslandCurrentId = payload.call_id;

  const island =
    document.getElementById("cup-call-island");

  island.classList.remove("active");

  document.getElementById(
    "cup-call-number"
  ).textContent =
    cupFormatPhone(payload.caller_number);

  document.getElementById(
    "cup-call-destination"
  ).textContent =
    payload.callee_number
      ? `Destinazione ${payload.callee_number}`
      : "";

  document.getElementById(
    "cup-call-status-text"
  ).textContent = "In arrivo";

  document.getElementById(
    "cup-call-duration"
  ).textContent = "00:00";

  island.classList.add("visible");

  cupStartCallTimer();
}


function cupUpdateCall(payload) {

  if (
    cupCallIslandCurrentId !== payload.call_id
  ) return;

  if (payload.caller_number) {

    document.getElementById(
      "cup-call-number"
    ).textContent =
      cupFormatPhone(payload.caller_number);

  }

  if (payload.callee_number) {

    document.getElementById(
      "cup-call-destination"
    ).textContent =
      `Interno ${payload.callee_number}`;

  }
}


function cupActivateCall(payload) {

  if (
    cupCallIslandCurrentId !== payload.call_id
  ) return;

  const island =
    document.getElementById("cup-call-island");

  island?.classList.add("active");

  document.getElementById(
    "cup-call-status-text"
  ).textContent = "In conversazione";
}


function cupEndCall(payload) {

  if (
    cupCallIslandCurrentId !== payload.call_id
  ) return;

  clearInterval(cupCallIslandTimer);

  const status =
    document.getElementById("cup-call-status-text");

  if (status) {
    status.textContent = "Chiamata terminata";
  }

  const island =
    document.getElementById("cup-call-island");

  island?.classList.remove("active");

  setTimeout(() => {

    island?.classList.remove("visible");

    cupCallIslandCurrentId = null;

  }, 3500);
}


window.addEventListener(
  "cup-call-event",
  event => {

    const payload = event.detail || {};

    console.log(
      "CUP Call Island:",
      payload.type,
      payload
    );

    switch (payload.type) {

      case "call_created":
        cupShowIncomingCall(payload);
        break;

      case "call_updated":
        cupUpdateCall(payload);
        break;

      case "call_active":
        cupActivateCall(payload);
        break;

      case "call_ended":
        cupEndCall(payload);
        break;
    }

  }
);

cupEnsureCallIsland();


function selectedBookingDuration(){
  const select=document.getElementById("booking-duration");

  if(!select)
    return 60;

  if(select.value==="custom"){
    return Math.max(
      5,
      Number(
        document.getElementById("booking-custom-duration")?.value
      ) || 60
    );
  }

  return Number(select.value) || 60;
}

document.getElementById("booking-duration")
  ?.addEventListener("change",e=>{
    document
      .getElementById("booking-custom-duration-wrap")
      ?.classList.toggle(
        "d-none",
        e.target.value!=="custom"
      );
  });

document.getElementById("booking-visit-type")
  ?.addEventListener("change",e=>{

    const visit=cupCalendarState.visitTypes.find(
      v=>v.id===Number(e.target.value)
    );

    if(!visit)
      return;

    const duration=
      Number(visit.duration_minutes) || 60;

    const select=
      document.getElementById("booking-duration");

    const supported=[
      15,30,45,60,90,120
    ];

    if(supported.includes(duration)){
      select.value=String(duration);

      document
        .getElementById("booking-custom-duration-wrap")
        ?.classList.add("d-none");
    }
    else{
      select.value="custom";

      document.getElementById(
        "booking-custom-duration"
      ).value=duration;

      document
        .getElementById("booking-custom-duration-wrap")
        ?.classList.remove("d-none");
    }
  });


/*
 * CUP_SAFE_ELIGIBILITY_REMOVED_V1
 *
 * Vecchio filtro Prestazione -> Medico -> Agenda rimosso.
 * La prenotazione usa ora CUP_VISIT_FIRST_BOOKING_LOGIC_V1.
 */



/* CUP_BOOKING_EDITOR_EVENTS_START */
document.addEventListener("click",async(event)=>{
  const item=event.target.closest("[data-booking-id]");
  if(!item) return;

  const id=Number(item.dataset.bookingId);
  if(!id) return;

  event.stopPropagation();

  try{
    await openBookingEditor(id);
  }catch(error){
    console.error("Errore apertura appuntamento:",error);
    if(typeof showToast==="function"){
      showToast(
        error?.message||"Impossibile aprire l'appuntamento.",
        "error"
      );
    }
  }
});

document.addEventListener("dblclick",async(event)=>{
  const item=event.target.closest("[data-booking-id]");
  if(!item) return;

  event.preventDefault();
  event.stopPropagation();

  const id=Number(item.dataset.bookingId);
  if(!id) return;

  try{
    await openBookingEditor(id);
  }catch(error){
    console.error("Errore apertura appuntamento:",error);
  }
});
/* CUP_BOOKING_EDITOR_EVENTS_END */



/* CUP_PATIENT_EDITOR_V1 */

let patientEditorModal=null;


function getPatientEditorModal(){

  if(!patientEditorModal){

    patientEditorModal=
      new bootstrap.Modal(
        document.getElementById(
          "patient-editor-modal"
        )
      );

  }

  return patientEditorModal;
}


async function patientFetchJson(url,options={}){

  const response=await fetch(
    url,
    {
      credentials:"same-origin",
      headers:{
        ...patientApiHeaders(),
        "Content-Type":"application/json",
        ...(options.headers||{})
      },
      ...options
    }
  );

  let body=null;

  try{
    body=await response.json();
  }catch(_){}

  if(!response.ok){

    const message=
      body?.detail
      ||body?.message
      ||`Errore HTTP ${response.status}`;

    const error=new Error(message);

    error.status=response.status;

    throw error;
  }

  return body;
}



function openNewPatient(){

  const form =
    document.getElementById(
      "patient-editor-form"
    );

  if(!form)
    return;

  form.reset();
  form.dataset.addDelegateAfterSave = "0";

  const error =
    document.getElementById(
      "patient-editor-error"
    );

  error?.classList.add(
    "d-none"
  );

  document.getElementById(
    "patient-editor-id"
  ).value="";

  document.getElementById(
    "patient-editor-reminder-enabled"
  ).checked=true;

  document.getElementById(
    "patient-editor-reminder-channels"
  ).value="email";

  document.getElementById(
    "patient-editor-reminder-channels"
  ).dataset.telegramLinked="0";

  const title =
    document.getElementById(
      "patient-editor-title"
    );

  if(title){
    title.textContent =
      "Nuovo paziente";
  }

  const subtitle =
    document.getElementById(
      "patient-editor-subtitle"
    );

  if(subtitle){
    subtitle.textContent =
      "Inserimento anagrafica da operatore";
  }

  const delegateSave =
    document.getElementById(
      "patient-editor-save-delegate"
    );

  if(delegateSave)
    delegateSave.classList.remove("d-none");

  const history =
    document.getElementById(
      "btn-patient-history"
    );

  if(history){
    history.classList.add(
      "d-none"
    );
  }

  const badge =
    document.getElementById(
      "patient-editor-telegram-badge"
    );

  if(badge){
    badge.className =
      "badge bg-secondary";

    badge.textContent =
      "Non collegato";
  }

  const text =
    document.getElementById(
      "patient-editor-telegram-text"
    );

  if(text){
    text.textContent =
      "Il paziente potrà collegare Telegram successivamente avviando il bot.";
  }

  const icon =
    document.getElementById(
      "patient-editor-telegram-icon"
    );

  if(icon){
    icon.className =
      "bi bi-telegram fs-5 text-muted";
  }

  getPatientEditorModal().show();
}


document
  .getElementById(
    "btn-new-patient"
  )
  ?.addEventListener(
    "click",
    openNewPatient
  );


async function openPatientDetail(patientId){

  const error=
    document.getElementById(
      "patient-editor-error"
    );

  error?.classList.add("d-none");

  const patient=
    await patientFetchJson(
      `/api/patients/${patientId}`
    );

  document.getElementById(
    "patient-editor-id"
  ).value=patient.id;

  const patientEditorTitle =
    document.getElementById(
      "patient-editor-title"
    );

  if(patientEditorTitle){
    patientEditorTitle.textContent =
      "Modifica paziente";
  }

  const delegateSave =
    document.getElementById(
      "patient-editor-save-delegate"
    );

  if(delegateSave)
    delegateSave.classList.add("d-none");

  const historyButton =
    document.getElementById(
      "btn-patient-history"
    );

  if(historyButton){
    historyButton.classList.remove(
      "d-none"
    );
  }


  document.getElementById(
    "patient-editor-first-name"
  ).value=patient.first_name||"";

  document.getElementById(
    "patient-editor-last-name"
  ).value=patient.last_name||"";

  document.getElementById(
    "patient-editor-email"
  ).value=patient.email||"";

  document.getElementById(
    "patient-editor-phone"
  ).value=patient.phone||"";

  document.getElementById(
    "patient-editor-fiscal-code"
  ).value=patient.fiscal_code||"";

  document.getElementById(
    "patient-editor-dob"
  ).value=patient.date_of_birth||"";

  document.getElementById(
    "patient-editor-notes"
  ).value=patient.notes||"";

  document.getElementById(
    "patient-editor-reminder-enabled"
  ).checked=
    patient.reminder_enabled!==false;

  document.getElementById(
    "patient-editor-reminder-channels"
  ).value=
    patient.reminder_channels||"";

  const telegramLinked =
    !!String(
      patient.reminder_telegram_chat_id || ""
    ).trim();

  const telegramChannels =
    String(
      patient.reminder_channels || ""
    )
      .split(",")
      .map(x => x.trim().toLowerCase())
      .filter(Boolean);

  const telegramActive =
    telegramLinked
    && telegramChannels.includes("telegram");

  const reminderChannelsInput =
    document.getElementById(
      "patient-editor-reminder-channels"
    );

  if(reminderChannelsInput){
    reminderChannelsInput.dataset.telegramLinked =
      telegramLinked ? "1" : "0";
  }

  const telegramBadge =
    document.getElementById(
      "patient-editor-telegram-badge"
    );

  const telegramText =
    document.getElementById(
      "patient-editor-telegram-text"
    );

  const telegramIcon =
    document.getElementById(
      "patient-editor-telegram-icon"
    );

  if(telegramBadge){

    telegramBadge.className =
      telegramLinked
        ? (
            telegramActive
              ? "badge bg-success"
              : "badge bg-warning text-dark"
          )
        : "badge bg-secondary";

    telegramBadge.textContent =
      telegramLinked
        ? (
            telegramActive
              ? "Collegato · attivo"
              : "Collegato"
          )
        : "Non collegato";
  }

  if(telegramText){

    telegramText.textContent =
      telegramLinked
        ? (
            telegramActive
              ? "Il paziente può ricevere promemoria Telegram."
              : "Bot collegato; Telegram non è selezionato nei canali promemoria."
          )
        : "Il paziente deve avviare il bot Telegram prima di poter ricevere messaggi.";
  }

  if(telegramIcon){

    telegramIcon.className =
      telegramLinked
        ? "bi bi-telegram fs-5 text-success"
        : "bi bi-telegram fs-5 text-muted";
  }


  document.getElementById(
    "patient-editor-subtitle"
  ).textContent=
    `Paziente #${patient.id}`;

  getPatientEditorModal().show();

  /*
   * PATIENT 360:
   * carica prenotazioni, conversazioni
   * e cartella nella stessa scheda paziente.
   */
  if(
    typeof window.OmniaPatient360Load ===
    "function"
  ){
    try{

      await window.OmniaPatient360Load(
        Number(patient.id)
      );

    }catch(error){

      console.error(
        "[CUP] Patient 360 load error",
        error
      );
    }
  }
}


document.addEventListener(
  "click",
  event => {

    const button =
      event.target.closest(
        "#patient-editor-save, #patient-editor-save-delegate"
      );

    if(!button)
      return;

    const form =
      document.getElementById(
        "patient-editor-form"
      );

    if(!form)
      return;

    if(!form.reportValidity())
      return;

    form.dataset.addDelegateAfterSave =
      button.id === "patient-editor-save-delegate"
        ? "1"
        : "0";

    form.dispatchEvent(
      new Event(
        "submit",
        {
          bubbles:true,
          cancelable:true
        }
      )
    );
  }
);


document.addEventListener(
  "submit",
  async e => {

      if(e.target?.id !== "patient-editor-form")
        return;

      e.preventDefault();

      const form =
        e.target;

      const addDelegateAfterSave =
        form?.dataset.addDelegateAfterSave === "1";

      if(form)
        form.dataset.addDelegateAfterSave = "0";

      const error=
        document.getElementById(
          "patient-editor-error"
        );

      error.classList.add("d-none");

      const id=
        Number(
          document.getElementById(
            "patient-editor-id"
          ).value
        );

      const payload={

        first_name:
          document.getElementById(
            "patient-editor-first-name"
          ).value.trim(),

        last_name:
          document.getElementById(
            "patient-editor-last-name"
          ).value.trim(),

        email:
          document.getElementById(
            "patient-editor-email"
          ).value.trim(),

        phone:
          document.getElementById(
            "patient-editor-phone"
          ).value.trim(),

        fiscal_code:
          document.getElementById(
            "patient-editor-fiscal-code"
          ).value.trim(),

        date_of_birth:
          document.getElementById(
            "patient-editor-dob"
          ).value,

        notes:
          document.getElementById(
            "patient-editor-notes"
          ).value.trim(),

        reminder_enabled:
          document.getElementById(
            "patient-editor-reminder-enabled"
          ).checked,

        reminder_channels:
          document.getElementById(
            "patient-editor-reminder-channels"
          ).value.trim()
      };

      const channelsInput =
        document.getElementById(
          "patient-editor-reminder-channels"
        );

      const requestedChannels =
        String(channelsInput?.value || "")
          .split(",")
          .map(x => x.trim().toLowerCase())
          .filter(Boolean);

      if(
        requestedChannels.includes("telegram")
        && channelsInput?.dataset.telegramLinked !== "1"
      ){
        error.textContent =
          "Telegram non disponibile: il paziente non ha ancora collegato il bot.";

        error.classList.remove("d-none");
        return;
      }

      try{

        const save=
          document.getElementById(
            "patient-editor-save"
          );

        save.disabled=true;

        const savedPatient =
          await patientFetchJson(
            id
              ? `/api/patients/${id}`
              : `/api/patients/`,
            {
              method:
                id
                  ? "PATCH"
                  : "POST",
              body:JSON.stringify(payload)
            }
          );

        getPatientEditorModal().hide();

        showToast(
          id
            ? "Paziente aggiornato"
            : "Paziente creato",
          "success"
        );

        await loadPatients();

        if(
          !id
          && addDelegateAfterSave
          && savedPatient?.id
        ){
          setTimeout(
            async () => {

              await window.OmniaPatientCardOpen(
                savedPatient.id
              );

              setTimeout(
                () => {
                  document
                    .querySelector(
                      '#omnia-patient-card-modal [data-pcard-tab="relationships"]'
                    )
                    ?.click();

                  document
                    .querySelector(
                      '#omnia-patient-card-modal [data-rel-add]'
                    )
                    ?.click();
                },
                250
              );

            },
            250
          );
        }

      }
      catch(ex){

        error.textContent=
          ex.message||
          "Errore durante il salvataggio";

        error.classList.remove("d-none");

      }
      finally{

        document.getElementById(
          "patient-editor-save"
        ).disabled=false;

      }

  }
);



/* CUP_PATIENT_HISTORY_JS_V1 */

let patientHistoryModal=null;
let patientHistoryData=null;
let patientHistoryCurrentFilter="all";


function getPatientHistoryModal(){

  if(!patientHistoryModal){

    patientHistoryModal=
      new bootstrap.Modal(
        document.getElementById(
          "patient-history-modal"
        )
      );

  }

  return patientHistoryModal;
}


function historyEuro(cents,currency="EUR"){

  return new Intl.NumberFormat(
    "it-IT",
    {
      style:"currency",
      currency:currency||"EUR"
    }
  ).format(
    (Number(cents)||0)/100
  );
}


function historyStatusLabel(status){

  const labels={
    pending:"In attesa",
    confirmed:"Confermato",
    completed:"Eseguito",
    cancelled:"Annullato",
    paid:"Pagato",
    failed:"Fallito",
    available:"Disponibile",
    open:"Aperto"
  };

  return labels[
    String(status||"").toLowerCase()
  ] || status || "-";
}


function historyDate(value){

  if(!value)
    return "-";

  const d=new Date(value);

  if(Number.isNaN(d.getTime()))
    return value;

  return d.toLocaleString(
    "it-IT",
    {
      day:"2-digit",
      month:"2-digit",
      year:"numeric",
      hour:"2-digit",
      minute:"2-digit"
    }
  );
}


function renderPatientHistory(filter="all"){

  if(!patientHistoryData)
    return;

  patientHistoryCurrentFilter=filter;

  let items=
    patientHistoryData.timeline||[];

  if(filter!=="all"){

    items=items.filter(
      x=>x.type===filter
    );

  }


  const root=
    document.getElementById(
      "patient-history-timeline"
    );

  const counter=
    document.getElementById(
      "patient-history-count"
    );

  if(counter){

    counter.textContent=
      `${items.length} ${
        items.length===1
          ?"evento"
          :"eventi"
      }`;

  }


  document
    .querySelectorAll(
      "[data-history-filter]"
    )
    .forEach(btn=>{

      const active=
        btn.dataset.historyFilter===
        filter;

      btn.classList.toggle(
        "btn-primary",
        active
      );

      btn.classList.toggle(
        "btn-outline-primary",
        !active
      );

      btn.classList.toggle(
        "active",
        active
      );

    });


  if(!items.length){

    root.innerHTML=`
      <div class="patient-history-empty">

        <i
          class="bi bi-clock-history fs-3 d-block mb-2">
        </i>

        Nessun evento disponibile.

      </div>
    `;

    return;
  }


  root.innerHTML=
    items.map(item=>{

      let icon="bi-calendar3";
      let kind=item.kind||item.type;
      let extra="";
      let action="";

      if(item.type==="booking"){

        if(item.kind==="completed")
          icon="bi-check-circle";

        else if(item.kind==="cancelled")
          icon="bi-x-circle";

        else
          icon="bi-calendar-check";


        const meta=[
          item.doctor_name
            ?`<span>${escapeHtml(item.doctor_name)}</span>`
            :"",

          item.agenda_name
            ?`<span>${escapeHtml(item.agenda_name)}</span>`
            :"",

          item.location
            ?`<span>${escapeHtml(item.location)}</span>`
            :"",

          item.regime
            ?`<span>${
                item.regime==="ssn"
                  ?"SSN"
                  :"Privato"
              }</span>`
            :""
        ].filter(Boolean).join("");


        extra=`
          <div class="patient-history-meta">
            ${meta}
          </div>
        `;


        if(item.booking_id){

          action=`
            <div class="patient-history-actions">

              <button
                type="button"
                class="btn btn-sm btn-outline-primary"
                data-history-booking="${item.booking_id}">

                <i class="bi bi-pencil-square"></i>
                Apri appuntamento

              </button>

            </div>
          `;

        }

      }


      else if(item.type==="document"){

        icon=
          item.kind==="report"
            ?"bi-file-earmark-medical"
            :"bi-file-earmark-text";

        extra=`
          <div class="patient-history-meta">

            <span>
              ${escapeHtml(
                item.category||"documento"
              )}
            </span>

            ${
              item.filename
              ?`
                <span>
                  ${escapeHtml(item.filename)}
                </span>
              `
              :""
            }

          </div>
        `;


        if(item.booking_id){

          action=`
            <div class="patient-history-actions">

              <button
                type="button"
                class="btn btn-sm btn-outline-primary"
                data-history-booking="${item.booking_id}">

                <i class="bi bi-calendar-check"></i>
                Visita collegata

              </button>

            </div>
          `;
        }

      }


      else if(item.type==="payment"){

        icon="bi-credit-card";

        extra=`
          <div class="patient-history-meta">

            <span>
              ${historyEuro(
                item.amount_cents,
                item.currency
              )}
            </span>

            ${
              item.provider
              ?`
                <span>
                  ${escapeHtml(item.provider)}
                </span>
              `
              :""
            }

          </div>
        `;

      }


      return `
        <article
          class="patient-history-item"
          data-history-type="${escapeHtml(item.type)}">

          <span
            class="patient-history-dot ${escapeHtml(kind)}">
          </span>


          <div class="patient-history-item-head">

            <div>

              <div class="patient-history-type">

                <i class="bi ${icon} me-1"></i>

                ${escapeHtml(
                  item.label||item.type
                )}

                <span class="patient-history-status">

                  ${escapeHtml(
                    historyStatusLabel(
                      item.status
                    )
                  )}

                </span>

              </div>


              <div class="patient-history-title">

                ${escapeHtml(
                  item.title||"-"
                )}

              </div>

            </div>


            <div class="patient-history-date">

              ${historyDate(item.date)}

            </div>

          </div>

          ${extra}

          ${
            item.notes
              ?`
                <div class="small mt-2 text-muted">
                  ${escapeHtml(item.notes)}
                </div>
              `
              :""
          }

          ${action}

        </article>
      `;

    }).join("");


  root
    .querySelectorAll(
      "[data-history-booking]"
    )
    .forEach(btn=>{

      btn.addEventListener(
        "click",
        async()=>{

          const bookingId=
            Number(
              btn.dataset.historyBooking
            );

          /*
           * Chiudiamo la cronologia prima
           * di aprire l'editor appuntamento.
           */

          getPatientHistoryModal().hide();

          setTimeout(
            ()=>openBookingEditor(
              bookingId
            ),
            250
          );

        }
      );

    });

}


async function openPatientHistory(patientId){

  const loading=
    document.getElementById(
      "patient-history-loading"
    );

  const content=
    document.getElementById(
      "patient-history-content"
    );

  const error=
    document.getElementById(
      "patient-history-error"
    );


  loading?.classList.remove("d-none");
  content?.classList.add("d-none");
  error?.classList.add("d-none");


  getPatientHistoryModal().show();


  try{

    patientHistoryData=
      await patientFetchJson(
        `/api/patients/${patientId}/history`
      );


    const patient=
      patientHistoryData.patient||{};

    const summary=
      patientHistoryData.summary||{};


    document.getElementById(
      "patient-history-name"
    ).textContent=
      patient.full_name||
      `Paziente #${patientId}`;


    const subtitle=[];

    if(patient.fiscal_code)
      subtitle.push(
        `CF ${patient.fiscal_code}`
      );

    if(patient.phone)
      subtitle.push(
        patient.phone
      );

    if(patient.email)
      subtitle.push(
        patient.email
      );


    document.getElementById(
      "patient-history-subtitle"
    ).textContent=
      subtitle.join(" · ");


    document.getElementById(
      "patient-history-completed"
    ).textContent=
      summary.completed||0;


    document.getElementById(
      "patient-history-future"
    ).textContent=
      summary.future||0;


    document.getElementById(
      "patient-history-reports"
    ).textContent=
      summary.reports||0;


    document.getElementById(
      "patient-history-documents"
    ).textContent=
      summary.documents||0;


    document.getElementById(
      "patient-history-payments"
    ).textContent=
      summary.payments||0;


    loading?.classList.add("d-none");
    content?.classList.remove("d-none");

    renderPatientHistory("all");

  }
  catch(ex){

    loading?.classList.add("d-none");

    error.textContent=
      ex.message||
      "Impossibile caricare la cronologia";

    error.classList.remove("d-none");

  }

}


/*
 * Pulsante presente nell'editor paziente
 */
document
  .getElementById(
    "btn-patient-history"
  )
  ?.addEventListener(
    "click",
    ()=>{

      const id=
        Number(
          document.getElementById(
            "patient-editor-id"
          )?.value
        );

      if(!id)
        return;

      /*
       * Evita due modal Bootstrap sovrapposti.
       */

      if(
        typeof patientEditorModal!=="undefined"
        && patientEditorModal
      ){
        patientEditorModal.hide();
      }

      setTimeout(
        ()=>openPatientHistory(id),
        200
      );

    }
  );


document
  .querySelectorAll(
    "[data-history-filter]"
  )
  .forEach(btn=>{

    btn.addEventListener(
      "click",
      ()=>renderPatientHistory(
        btn.dataset.historyFilter
      )
    );

  });




/* CUP_PATIENT_HISTORY_CLICK_FIX_V2_START */

/*
 * Listener delegato:
 * funziona anche se la modale paziente viene creata
 * o aggiornata dopo il caricamento di app.js.
 */
document.addEventListener("click", async function(ev){

  const button = ev.target.closest("#btn-patient-history");

  if(!button)
    return;

  ev.preventDefault();
  ev.stopPropagation();

  console.log("[CUP] click Cronologia paziente");

  const idEl =
    document.getElementById("patient-editor-id");

  const patientId =
    Number(idEl?.value || 0);

  if(!patientId){

    console.error(
      "[CUP] patient-editor-id assente o non valido",
      idEl?.value
    );

    if(typeof showToast === "function"){
      showToast(
        "Impossibile identificare il paziente.",
        "error"
      );
    }else{
      alert(
        "Impossibile identificare il paziente."
      );
    }

    return;
  }


  /*
   * Verifica immediata che la funzione history
   * sia realmente disponibile.
   */
  if(typeof openPatientHistory !== "function"){

    console.error(
      "[CUP] openPatientHistory non definita"
    );

    if(typeof showToast === "function"){
      showToast(
        "Modulo cronologia non disponibile. Aggiorna la pagina.",
        "error"
      );
    }else{
      alert(
        "Modulo cronologia non disponibile."
      );
    }

    return;
  }


  /*
   * Chiude correttamente la modale anagrafica.
   * Usiamo Bootstrap direttamente, senza dipendere
   * dalla variabile patientEditorModal.
   */
  try{

    const editorEl =
      document.getElementById(
        "patient-editor-modal"
      );

    if(editorEl){

      const editorInstance =
        bootstrap.Modal.getInstance(editorEl);

      if(editorInstance)
        editorInstance.hide();

    }

  }catch(ex){

    console.warn(
      "[CUP] chiusura editor paziente:",
      ex
    );

  }


  /*
   * Aspetta la chiusura della prima modale prima
   * di aprire la cronologia.
   */
  setTimeout(
    async ()=>{

      try{

        console.log(
          "[CUP] apertura history paziente",
          patientId
        );

        await openPatientHistory(
          patientId
        );

      }catch(ex){

        console.error(
          "[CUP] apertura cronologia fallita",
          ex
        );

        if(typeof showToast === "function"){

          showToast(
            ex?.message ||
            "Impossibile aprire la cronologia paziente.",
            "error"
          );

        }else{

          alert(
            ex?.message ||
            "Impossibile aprire la cronologia paziente."
          );

        }

      }

    },
    300
  );

});

/* CUP_PATIENT_HISTORY_CLICK_FIX_V2_END */











/* CUP_CASCADE_V2_LOGIC */

function cupV2VisitIds(agenda){
  const values =
    agenda?.visit_type_ids ||
    agenda?.allowed_visit_type_ids ||
    agenda?.visit_types ||
    [];

  return values
    .map(x =>
      typeof x === "object"
        ? Number(x.id ?? x.visit_type_id)
        : Number(x)
    )
    .filter(Boolean);
}

function cupV2Fill(el, items, first, labelFn, valueFn=x=>x.id){
  if(!el) return;

  const old = el.value;

  el.innerHTML =
    `<option value="">${escapeHtml(first)}</option>` +
    items.map(x =>
      `<option value="${escapeHtml(String(valueFn(x)))}">${escapeHtml(labelFn(x))}</option>`
    ).join("");

  if([...el.options].some(o=>o.value===old))
    el.value=old;
}

function cupV2Data(){
  const doctors =
    (cupCalendarState.doctors||[])
      .filter(d=>d.active!==false);

  const visits =
    (cupCalendarState.visitTypes||[])
      .filter(v=>v.active!==false);

  const agendas =
    (cupCalendarState.agendas||[])
      .filter(a=>a.active!==false);

  return {doctors,visits,agendas};
}

function cupV2Specialties(){
  const {doctors}=cupV2Data();

  return [...new Set(
    doctors
      .map(d=>(d.specialty||"").trim())
      .filter(Boolean)
  )].sort((a,b)=>a.localeCompare(b,"it"));
}

function cupV2Compatible({
  specialty="",
  visitId=null,
  doctorId=null,
  agendaId=null
}={}){
  const {doctors,visits,agendas}=cupV2Data();

  const doctorById=
    new Map(doctors.map(d=>[Number(d.id),d]));

  let candidateAgendas=agendas;

  if(specialty){
    candidateAgendas=
      candidateAgendas.filter(a=>
        doctorById.get(Number(a.doctor_id))?.specialty===specialty
      );
  }

  if(visitId){
    candidateAgendas=
      candidateAgendas.filter(a=>
        cupV2VisitIds(a).includes(Number(visitId))
      );
  }

  if(doctorId){
    candidateAgendas=
      candidateAgendas.filter(a=>
        Number(a.doctor_id)===Number(doctorId)
      );
  }

  if(agendaId){
    candidateAgendas=
      candidateAgendas.filter(a=>
        Number(a.id)===Number(agendaId)
      );
  }

  const visitIds=
    new Set(
      candidateAgendas.flatMap(a=>cupV2VisitIds(a))
    );

  const doctorIds=
    new Set(
      candidateAgendas
        .map(a=>Number(a.doctor_id))
        .filter(Boolean)
    );

  return {
    agendas:candidateAgendas,
    visits:visits.filter(v=>visitIds.has(Number(v.id))),
    doctors:doctors.filter(d=>doctorIds.has(Number(d.id)))
  };
}

/* ---------- CALENDARIO ---------- */

function cupV2CalendarRefresh(from="specialty"){
  const specialtyEl=document.getElementById("calendar-specialty-filter");
  const visitEl=document.getElementById("calendar-visit-filter");
  const doctorEl=document.getElementById("calendar-doctor-filter");
  const agendaEl=document.getElementById("calendar-agenda-filter");

  if(!specialtyEl||!visitEl||!doctorEl||!agendaEl) return;

  const specialty=specialtyEl.value;
  const visitId=Number(visitEl.value)||null;
  const doctorId=Number(doctorEl.value)||null;

  let data=cupV2Compatible({specialty});

  cupV2Fill(
    visitEl,
    data.visits,
    "Tutte le visite",
    v=>`${v.name} · ${v.duration_minutes} min`
  );

  const effectiveVisit=Number(visitEl.value)||null;

  data=cupV2Compatible({
    specialty,
    visitId:effectiveVisit
  });

  cupV2Fill(
    doctorEl,
    data.doctors,
    "Tutti i medici",
    d=>`${d.full_name}${d.specialty?" · "+d.specialty:""}`
  );

  const effectiveDoctor=Number(doctorEl.value)||null;

  data=cupV2Compatible({
    specialty,
    visitId:effectiveVisit,
    doctorId:effectiveDoctor
  });

  cupV2Fill(
    agendaEl,
    data.agendas,
    "Tutte le agende",
    a=>a.name
  );
}

/* ---------- PRENOTAZIONE ---------- */

function cupV2BookingRefresh(){
  const specialtyEl=document.getElementById("booking-specialty");
  const visitEl=document.getElementById("booking-visit-type");
  const doctorEl=document.getElementById("booking-doctors");
  const agendaEl=document.getElementById("booking-agenda");

  if(!specialtyEl||!visitEl||!doctorEl||!agendaEl) return;

  const specialty=specialtyEl.value;

  let data=cupV2Compatible({specialty});

  cupV2Fill(
    visitEl,
    data.visits,
    "Seleziona visita",
    v=>`${v.name} · ${v.duration_minutes} min`
  );

  const visitId=Number(visitEl.value)||null;

  data=cupV2Compatible({
    specialty,
    visitId
  });

  cupV2Fill(
    doctorEl,
    data.doctors,
    "Seleziona medico",
    d=>`${d.full_name}${d.specialty?" · "+d.specialty:""}`
  );

  const doctorId=Number(doctorEl.value)||null;

  data=cupV2Compatible({
    specialty,
    visitId,
    doctorId
  });

  cupV2Fill(
    agendaEl,
    data.agendas,
    "Seleziona agenda",
    a=>a.name
  );

  if(data.agendas.length===1)
    agendaEl.value=String(data.agendas[0].id);

  const visit =
    (cupCalendarState.visitTypes||[])
      .find(v=>Number(v.id)===visitId);

  if(visit){
    const duration=document.getElementById("booking-duration");

    if(duration &&
       ["30","60","120"].includes(String(visit.duration_minutes)))
      duration.value=String(visit.duration_minutes);
  }
}

async function cupV2BookingSlots(){
  const root=document.getElementById("booking-availability");
  if(!root) return;

  const day=document.getElementById("booking-date")?.value;
  const agendaId=Number(document.getElementById("booking-agenda")?.value)||null;
  const visitId=Number(document.getElementById("booking-visit-type")?.value)||null;

  document.getElementById("booking-slot").innerHTML='<option value=""></option>';
  document.getElementById("booking-time").innerHTML='<option value=""></option>';

  if(!day||!agendaId||!visitId){
    root.innerHTML=
      '<div class="booking-availability-empty">Seleziona specialità, visita, medico, agenda e data.</div>';
    return;
  }

  root.innerHTML=
    '<div class="booking-availability-empty">Ricerca disponibilità...</div>';

  try{
    const slots=await CupApi.getAvailableSlots(day,agendaId,visitId);

    if(!slots.length){
      root.innerHTML=
        '<div class="booking-availability-empty">Nessuno slot disponibile in questa data.</div>';
      return;
    }

    root.innerHTML=
      '<div class="booking-slot-list">' +
      slots.map(slot=>{
        const d=new Date(slot.start);
        const hhmm=d.toTimeString().slice(0,5);

        return `
          <button
            type="button"
            class="booking-slot-button"
            data-v2-slot="${hhmm}">
            ${escapeHtml(
              d.toLocaleTimeString("it-IT",{
                hour:"2-digit",
                minute:"2-digit"
              })
            )}
          </button>`;
      }).join("") +
      '</div>';

    root.querySelectorAll("[data-v2-slot]").forEach(btn=>{
      btn.addEventListener("click",()=>{
        const hhmm=btn.dataset.v2Slot;

        root.querySelectorAll("[data-v2-slot]")
          .forEach(x=>x.classList.remove("is-selected"));

        btn.classList.add("is-selected");

        document.getElementById("booking-slot").innerHTML=
          `<option value="${hhmm}" selected>${hhmm}</option>`;

        document.getElementById("booking-time").innerHTML=
          `<option value="${hhmm}" selected>${hhmm}</option>`;
      });
    });

  }catch(error){
    root.innerHTML=
      `<div class="booking-availability-empty text-danger">${escapeHtml(error.message)}</div>`;
  }
}

function cupCascadeV2Init(){

  const specialties=cupV2Specialties();

  cupV2Fill(
    document.getElementById("calendar-specialty-filter"),
    specialties,
    "Tutte le specialità",
    x=>x,
    x=>x
  );

  cupV2Fill(
    document.getElementById("booking-specialty"),
    specialties,
    "Seleziona specialità",
    x=>x,
    x=>x
  );

  cupV2CalendarRefresh();
  cupV2BookingRefresh();
}

/* CALENDARIO */

document.getElementById("calendar-specialty-filter")
  ?.addEventListener("change",async()=>{
    document.getElementById("calendar-visit-filter").value="";
    document.getElementById("calendar-doctor-filter").value="";
    document.getElementById("calendar-agenda-filter").value="";
    cupV2CalendarRefresh();
    await loadCupCalendar();
  });

document.getElementById("calendar-visit-filter")
  ?.addEventListener("change",async()=>{
    document.getElementById("calendar-doctor-filter").value="";
    document.getElementById("calendar-agenda-filter").value="";
    cupV2CalendarRefresh();
    await loadCupCalendar();
  });

document.getElementById("calendar-doctor-filter")
  ?.addEventListener("change",async()=>{
    document.getElementById("calendar-agenda-filter").value="";
    cupV2CalendarRefresh();
    await loadCupCalendar();
  });

document.getElementById("calendar-agenda-filter")
  ?.addEventListener("change",loadCupCalendar);

/* PRENOTAZIONE */

document.getElementById("booking-specialty")
  ?.addEventListener("change",async()=>{
    document.getElementById("booking-visit-type").value="";
    document.getElementById("booking-doctors").value="";
    document.getElementById("booking-agenda").value="";
    cupV2BookingRefresh();
    await cupV2BookingSlots();
  });

document.getElementById("booking-visit-type")
  ?.addEventListener("change",async()=>{
    document.getElementById("booking-doctors").value="";
    document.getElementById("booking-agenda").value="";
    cupV2BookingRefresh();
    await cupV2BookingSlots();
  });

document.getElementById("booking-doctors")
  ?.addEventListener("change",async()=>{
    document.getElementById("booking-agenda").value="";
    cupV2BookingRefresh();
    await cupV2BookingSlots();
  });

document.getElementById("booking-agenda")
  ?.addEventListener("change",cupV2BookingSlots);

document.getElementById("booking-date")
  ?.addEventListener("change",cupV2BookingSlots);

/* /CUP_CASCADE_V2_LOGIC */

/* CUP_SMART_AVAILABILITY_V1 */

let cupAvailabilityRequestId = 0;

function cupAvailabilityDateLabel(isoDate){
  const d = new Date(`${isoDate}T12:00:00`);

  return d.toLocaleDateString(
    "it-IT",
    {
      weekday:"short",
      day:"2-digit",
      month:"2-digit"
    }
  );
}

function cupSelectSmartSlot(day, startValue, button){

  const dateEl =
    document.getElementById("booking-date");

  const slotEl =
    document.getElementById("booking-slot");

  const timeEl =
    document.getElementById("booking-time");

  const selected =
    document.getElementById("booking-selected-slot");

  const d = new Date(startValue);

  const hhmm =
    d.toTimeString().slice(0,5);

  if(dateEl)
    dateEl.value = day;

  if(slotEl)
    slotEl.innerHTML =
      `<option value="${hhmm}" selected>${hhmm}</option>`;

  if(timeEl)
    timeEl.innerHTML =
      `<option value="${hhmm}" selected>${hhmm}</option>`;

  document
    .querySelectorAll("[data-smart-slot]")
    .forEach(x=>
      x.classList.remove("is-selected")
    );

  button?.classList.add("is-selected");

  if(selected){
    selected.innerHTML =
      `<strong>Appuntamento selezionato</strong><br>` +
      `${escapeHtml(
        d.toLocaleDateString("it-IT")
      )} ore <strong>${escapeHtml(hhmm)}</strong>`;

    selected.classList.remove("d-none");
  }
}


async function cupSmartAvailability(
  fromDay="",
  append=false
){

  const root =
    document.getElementById(
      "booking-availability"
    );

  if(!root) return;

  const agendaId =
    Number(
      document.getElementById(
        "booking-agenda"
      )?.value
    ) || null;

  const visitId =
    Number(
      document.getElementById(
        "booking-visit-type"
      )?.value
    ) || null;

  if(!agendaId || !visitId){

    root.innerHTML =
      '<div class="booking-availability-empty">' +
      'Seleziona specialità, visita, medico e agenda.' +
      '</div>';

    return;
  }

  const requestId =
    ++cupAvailabilityRequestId;

  root.innerHTML =
    '<div class="booking-availability-empty">' +
    '<span class="spinner-border spinner-border-sm me-2"></span>' +
    'Ricerca prime disponibilità...' +
    '</div>';

  try{

    const rows =
      await CupApi.getAvailability(
        agendaId,
        visitId,
        fromDay,
        30,
        7
      );

    if(requestId !== cupAvailabilityRequestId)
      return;

    if(!Array.isArray(rows) || !rows.length){

      root.innerHTML =
        '<div class="alert alert-warning mb-0">' +
        'Nessuna disponibilità trovata nei prossimi 30 giorni.' +
        '</div>';

      return;
    }

    root.innerHTML =
      rows.map(row=>{

        const slots =
          (row.slots||[])
            .map(slot=>{

              const d =
                new Date(slot.start);

              const hhmm =
                d.toTimeString().slice(0,5);

              return `
                <button
                  type="button"
                  class="booking-slot-button"
                  data-smart-slot="1"
                  data-smart-day="${escapeHtml(row.date)}"
                  data-smart-start="${escapeHtml(slot.start)}">
                  ${escapeHtml(hhmm)}
                </button>`;
            })
            .join("");

        return `
          <div class="border rounded p-3 mb-2">
            <div class="fw-semibold mb-2 text-capitalize">
              ${escapeHtml(
                cupAvailabilityDateLabel(row.date)
              )}
            </div>

            <div class="d-flex flex-wrap gap-2">
              ${slots}
            </div>
          </div>`;
      }).join("");

    root
      .querySelectorAll("[data-smart-slot]")
      .forEach(button=>{

        button.addEventListener(
          "click",
          ()=>{
            cupSelectSmartSlot(
              button.dataset.smartDay,
              button.dataset.smartStart,
              button
            );
          }
        );

      });

  }catch(error){

    if(requestId !== cupAvailabilityRequestId)
      return;

    console.error(
      "Smart availability",
      error
    );

    root.innerHTML =
      `<div class="alert alert-danger mb-0">
        ${escapeHtml(
          error?.message ||
          "Errore ricerca disponibilità"
        )}
       </div>`;
  }
}


/*
 * La funzione già richiamata dalla cascata V2 viene
 * ridefinita: se l'operatore sceglie manualmente una data
 * continua a vedere soltanto gli slot di quel giorno.
 */
cupV2BookingSlots = async function(){

  const day =
    document.getElementById(
      "booking-date"
    )?.value;

  const agendaId =
    Number(
      document.getElementById(
        "booking-agenda"
      )?.value
    ) || null;

  const visitId =
    Number(
      document.getElementById(
        "booking-visit-type"
      )?.value
    ) || null;

  if(!agendaId || !visitId)
    return cupSmartAvailability();

  /*
   * Nessuna data manuale:
   * mostra automaticamente le prime disponibilità.
   */
  if(!day)
    return cupSmartAvailability();

  const root =
    document.getElementById(
      "booking-availability"
    );

  root.innerHTML =
    '<div class="booking-availability-empty">' +
    'Ricerca disponibilità della data selezionata...' +
    '</div>';

  try{

    const slots =
      await CupApi.getAvailableSlots(
        day,
        agendaId,
        visitId
      );

    if(!slots.length){

      root.innerHTML =
        '<div class="alert alert-warning mb-2">' +
        'Nessuno slot disponibile in questa data.' +
        '</div>' +
        '<button type="button" ' +
        'class="btn btn-outline-primary btn-sm" ' +
        'id="booking-find-next">' +
        'Trova prossime disponibilità' +
        '</button>';

      document
        .getElementById("booking-find-next")
        ?.addEventListener(
          "click",
          ()=>cupSmartAvailability(day)
        );

      return;
    }

    root.innerHTML =
      '<div class="d-flex flex-wrap gap-2">' +
      slots.map(slot=>{

        const d =
          new Date(slot.start);

        const hhmm =
          d.toTimeString().slice(0,5);

        return `
          <button
            type="button"
            class="booking-slot-button"
            data-smart-slot="1"
            data-smart-day="${escapeHtml(day)}"
            data-smart-start="${escapeHtml(slot.start)}">
            ${escapeHtml(hhmm)}
          </button>`;
      }).join("") +
      '</div>';

    root
      .querySelectorAll("[data-smart-slot]")
      .forEach(button=>{

        button.addEventListener(
          "click",
          ()=>cupSelectSmartSlot(
            button.dataset.smartDay,
            button.dataset.smartStart,
            button
          )
        );

      });

  }catch(error){

    root.innerHTML =
      `<div class="alert alert-danger mb-0">
       ${escapeHtml(
         error?.message ||
         "Errore ricerca disponibilità"
       )}
       </div>`;
  }
};


/*
 * L'agenda utilizza già il listener V2.
 * cupV2BookingSlots() è stato ridefinito per
 * usare la ricerca intelligente.
 */

/* /CUP_SMART_AVAILABILITY_V1 */

/* CUP_WORKING_CALENDAR_LEGEND_V1 */

function cupInstallWorkingLegend(){

  const calendar =
    document.getElementById(
      "cup-calendar"
    );

  if(!calendar)
    return;

  let legend =
    document.getElementById(
      "cup-working-time-legend"
    );

  if(!legend){

    legend =
      document.createElement("div");

    legend.id =
      "cup-working-time-legend";

    legend.className =
      "cup-calendar-working-legend";

    calendar.insertAdjacentElement(
      "afterend",
      legend
    );
  }

  legend.innerHTML = `
    <span class="cup-calendar-working-key">
      <span class="cup-calendar-working-box work"></span>
      Orario lavorativo
    </span>

    <span class="cup-calendar-working-key">
      <span class="cup-calendar-working-box off"></span>
      Fuori orario / pausa
    </span>

    <span class="cup-calendar-working-key">
      <span class="cup-calendar-working-box dayoff"></span>
      Giorno non lavorativo
    </span>
  `;
}


/*
 * Wrapping leggero del renderer:
 * mantiene l'implementazione appena installata.
 */
const cupRenderCalendarWithWorkingLegend =
  renderCupCalendar;

renderCupCalendar =
  function(start,end){

    cupRenderCalendarWithWorkingLegend(
      start,
      end
    );

    cupInstallWorkingLegend();
  };

/* /CUP_WORKING_CALENDAR_LEGEND_V1 */

/* CUP_REALLOCATION_UI_LOGIC_V1 */

let cupCurrentReallocationIncident = null;


function cupReallocationMessage(
  text,
  type="success"
){
  const el =
    document.getElementById(
      "reallocation-message"
    );

  if(!el)
    return;

  el.className =
    `alert alert-${type}`;

  el.textContent = text;

  el.classList.remove("d-none");
}


function cupReallocationDateTime(value){

  if(!value)
    return "-";

  const d =
    new Date(value);

  return d.toLocaleString(
    "it-IT",
    {
      day:"2-digit",
      month:"2-digit",
      year:"numeric",
      hour:"2-digit",
      minute:"2-digit"
    }
  );
}


function cupReallocationStatus(status){

  const labels = {
    pending:
      ["Da gestire","secondary"],

    proposal_ready:
      ["Proposta pronta","primary"],

    approved:
      ["Approvata","info"],

    notified:
      ["In attesa paziente","warning"],

    accepted:
      ["Accettata","success"],

    rejected:
      ["Rifiutata","danger"],

    contact_requested:
      ["Richiede contatto","warning"],

    reallocated:
      ["Riallocato","success"],

    cancel_requested:
      ["Cancellazione richiesta","warning"],

    cancel_confirmed:
      ["Cancellato","dark"]
  };

  return (
    labels[status] ||
    [status || "-","secondary"]
  );
}


function cupPopulateReallocationAgendas(){

  const el =
    document.getElementById(
      "reallocation-agenda"
    );

  if(!el)
    return;

  const old = el.value;

  const agendas =
    (cupCalendarState.agendas || [])
      .filter(a => a.active !== false)
      .sort(
        (a,b)=>
          String(a.name)
            .localeCompare(
              String(b.name),
              "it"
            )
      );

  el.innerHTML =
    '<option value="">Seleziona agenda</option>' +
    agendas.map(
      a =>
        `<option value="${a.id}">
          ${escapeHtml(a.name)}
          ${
            a.doctor_name
              ? " · " +
                escapeHtml(a.doctor_name)
              : ""
          }
        </option>`
    ).join("");

  if(
    [...el.options]
      .some(
        x=>x.value === old
      )
  )
    el.value=old;
}


async function cupLoadReallocationIncidents(){

  const root =
    document.getElementById(
      "reallocation-incidents"
    );

  if(!root)
    return;

  root.innerHTML =
    '<div class="p-3 text-muted">Caricamento...</div>';

  try{

    const rows =
      await CupApi.getReallocationIncidents();

    document.getElementById(
      "reallocation-incidents-count"
    ).textContent =
      rows.length;

    if(!rows.length){

      root.innerHTML =
        '<div class="p-3 text-muted">Nessuna indisponibilità registrata.</div>';

      return;
    }

    root.innerHTML =
      rows.map(row=>{

        const kind =
          row.kind === "maintenance"
            ? "Manutenzione"
            : "Guasto tecnico";

        const badge =
          row.status === "active"
            ? "danger"
            : "secondary";

        return `
          <div
            class="list-group-item list-group-item-action"
            role="button"
            tabindex="0"
            data-reallocation-incident="${row.id}">

            <div class="d-flex justify-content-between gap-3">

              <div>

                <div class="fw-semibold">
                  ${escapeHtml(row.title)}
                </div>

                <div class="small text-muted">
                  ${escapeHtml(kind)}
                  · ${escapeHtml(row.agenda_name || "Agenda")}
                </div>

                <div class="small mt-1">
                  ${escapeHtml(String(row.start_date))}
                  ${
                    row.start_time
                    ? " " + escapeHtml(
                        String(row.start_time)
                          .slice(0,5)
                      )
                    : ""
                  }
                  →
                  ${escapeHtml(String(row.end_date))}
                  ${
                    row.end_time
                    ? " " + escapeHtml(
                        String(row.end_time)
                          .slice(0,5)
                      )
                    : ""
                  }
                </div>

              </div>

              <div class="d-flex align-items-center gap-2">

                <span class="badge bg-${badge}">
                  ${escapeHtml(row.status)}
                </span>

                <button
                  type="button"
                  class="btn btn-sm btn-outline-danger"
                  data-delete-reallocation-incident="${row.id}"
                  title="Elimina interruzione">
                  <i class="bi bi-trash"></i>
                </button>

              </div>

            </div>

          </div>
        `;
      }).join("");

    root
      .querySelectorAll(
        "[data-reallocation-incident]"
      )
      .forEach(button=>{

        button.addEventListener(
          "click",
          ()=>cupOpenReallocationIncident(
            Number(
              button.dataset.reallocationIncident
            )
          )
        );

      });

  }
  catch(error){

    root.innerHTML =
      `<div class="alert alert-danger mb-0">
        ${escapeHtml(
          error?.message ||
          "Errore caricamento indisponibilità"
        )}
       </div>`;
  }
}


async function cupOpenReallocationIncident(id){

  const root =
    document.getElementById(
      "reallocation-cases"
    );

  const panel =
    document.getElementById(
      "reallocation-case-panel"
    );

  if(!root || !panel)
    return;

  panel.classList.remove("d-none");

  root.innerHTML =
    '<div class="p-3 text-muted">Analisi appuntamenti...</div>';

  try{

    const data =
      await CupApi.getReallocationIncident(id);

    cupCurrentReallocationIncident =
      data.incident;

    document.getElementById(
      "reallocation-case-title"
    ).textContent =
      data.incident.title;

    document.getElementById(
      "reallocation-case-summary"
    ).textContent =
      `${data.cases.length} appuntamenti coinvolti`;

    if(!data.cases.length){

      root.innerHTML =
        '<div class="alert alert-success">Nessun appuntamento coinvolto.</div>';

      return;
    }

    root.innerHTML =
      data.cases.map(c=>{

        const [statusText,statusColor] =
          cupReallocationStatus(
            c.status
          );

        const urgent =
          c.priority === "urgent";

        return `
          <div
            class="card mb-3 ${
              urgent
                ? "border-danger"
                : ""
            }"
            data-reallocation-case="${c.id}"
            data-reallocation-case-status="${escapeHtml(c.status || "pending")}">

            <div class="card-body">

              <div class="d-flex justify-content-between align-items-start gap-3">

                <div>

                  <div class="d-flex align-items-center gap-2 flex-wrap">

                    ${
                      urgent
                        ? '<span class="badge bg-danger">URGENTE</span>'
                        : '<span class="badge bg-secondary">NORMALE</span>'
                    }

                    <strong>
                      ${escapeHtml(c.patient_name || "Paziente")}
                    </strong>

                    <span class="badge bg-${statusColor}">
                      ${escapeHtml(statusText)}
                    </span>

                  </div>

                  <div class="mt-2">
                    <strong>
                      ${escapeHtml(c.service_name || "Prestazione")}
                    </strong>
                  </div>

                  <div class="small text-muted mt-1">
                    Appuntamento originale:
                    ${escapeHtml(
                      cupReallocationDateTime(
                        c.original_scheduled_at
                      )
                    )}
                  </div>

                  ${
                    c.proposed_scheduled_at
                      ? `
                        <div class="mt-2">
                          <span class="text-muted">
                            Nuova proposta:
                          </span>

                          <strong class="text-primary">
                            ${escapeHtml(
                              cupReallocationDateTime(
                                c.proposed_scheduled_at
                              )
                            )}
                          </strong>

                          ${
                            c.proposed_agenda_name
                              ? " · " +
                                escapeHtml(
                                  c.proposed_agenda_name
                                )
                              : ""
                          }
                        </div>
                      `
                      : `
                        <div class="alert alert-warning py-2 mt-2 mb-0">
                          Nessuna disponibilità automatica trovata.
                        </div>
                      `
                  }

                </div>

              </div>

              <div class="d-flex flex-wrap gap-2 mt-3">

                ${
                  c.proposed_scheduled_at &&
                  ![
                    "reallocated",
                    "cancel_confirmed"
                  ].includes(c.status)
                    ? `
                      <button
                        type="button"
                        class="btn btn-sm btn-primary"
                        data-reallocation-notify="${c.id}">
                        <i class="bi bi-send"></i>
                        Invia proposta al paziente
                      </button>
                    `
                    : ""
                }

                ${
                  ![
                    "reallocated",
                    "cancel_confirmed"
                  ].includes(c.status)
                    ? `
                      <button
                        type="button"
                        class="btn btn-sm btn-outline-success"
                        data-reallocation-accept="${c.id}">
                        <i class="bi bi-check-lg"></i>
                        Conferma operatore
                      </button>

                      <button
                        type="button"
                        class="btn btn-sm btn-outline-danger"
                        data-reallocation-cancel="${c.id}">
                        <i class="bi bi-x-circle"></i>
                        Richiedi cancellazione
                      </button>
                    `
                    : ""
                }

              </div>

            </div>

          </div>
        `;
      }).join("");

    root
      .querySelectorAll(
        "[data-reallocation-notify]"
      )
      .forEach(button=>{

        button.addEventListener(
          "click",
          async ()=>{

            button.disabled=true;

            try{

              await CupApi.notifyReallocationCase(
                Number(
                  button.dataset.reallocationNotify
                )
              );

              cupReallocationMessage(
                "Proposta inviata al paziente."
              );

              await cupOpenReallocationIncident(id);

            }catch(error){

              cupReallocationMessage(
                error.message,
                "danger"
              );

            }finally{
              button.disabled=false;
            }
          }
        );

      });


    root
      .querySelectorAll(
        "[data-reallocation-cancel]"
      )
      .forEach(button=>{

        button.addEventListener(
          "click",
          async ()=>{

            if(
              !confirm(
                "Inviare al paziente la richiesta di cancellazione?"
              )
            )
              return;

            try{

              await CupApi.cancelReallocationCase(
                Number(
                  button.dataset.reallocationCancel
                )
              );

              cupReallocationMessage(
                "Richiesta di cancellazione inviata."
              );

              await cupOpenReallocationIncident(id);

            }catch(error){

              cupReallocationMessage(
                error.message,
                "danger"
              );
            }
          }
        );

      });


    root
      .querySelectorAll(
        "[data-reallocation-accept]"
      )
      .forEach(button=>{

        button.addEventListener(
          "click",
          async ()=>{

            if(
              !confirm(
                "Confermare direttamente questa operazione come operatore?"
              )
            )
              return;

            try{

              await CupApi.acceptReallocationCase(
                Number(
                  button.dataset.reallocationAccept
                )
              );

              cupReallocationMessage(
                "Operazione confermata dall'operatore."
              );

              await cupOpenReallocationIncident(id);

              if(
                typeof loadCupCalendar ===
                "function"
              )
                await loadCupCalendar();

            }catch(error){

              cupReallocationMessage(
                error.message,
                "danger"
              );
            }
          }
        );

      });

  }
  catch(error){

    root.innerHTML =
      `<div class="alert alert-danger">
        ${escapeHtml(error.message)}
       </div>`;
  }
}


document
  .getElementById(
    "btn-reallocation-panel"
  )
  ?.addEventListener(
    "click",
    async ()=>{

      const panel =
        document.getElementById(
          "reallocation-panel"
        );

      panel?.classList.toggle(
        "d-none"
      );

      if(
        panel &&
        !panel.classList.contains("d-none")
      ){
        cupPopulateReallocationAgendas();

        await cupLoadReallocationIncidents();
      }

    }
  );


document
  .getElementById(
    "btn-close-reallocation-panel"
  )
  ?.addEventListener(
    "click",
    ()=>{

      document
        .getElementById(
          "reallocation-panel"
        )
        ?.classList.add(
          "d-none"
        );

    }
  );


document
  .getElementById(
    "btn-refresh-reallocations"
  )
  ?.addEventListener(
    "click",
    cupLoadReallocationIncidents
  );


document
  .getElementById(
    "reallocation-form"
  )
  ?.addEventListener(
    "submit",
    async event=>{

      event.preventDefault();

      const agendaId =
        Number(
          document.getElementById(
            "reallocation-agenda"
          ).value
        );

      const startDate =
        document.getElementById(
          "reallocation-start-date"
        ).value;

      const endDate =
        document.getElementById(
          "reallocation-end-date"
        ).value;

      if(
        !startDate ||
        !endDate
      ){

        cupReallocationMessage(
          "Compila l'intervallo.",
          "danger"
        );

        return;
      }

      const scopeType =
        document.getElementById(
          "reallocation-scope"
        )?.value || "agenda";

      const selectedAgendas =
        [
          ...(
            document.getElementById(
              "reallocation-agendas"
            )?.selectedOptions || []
          )
        ]
        .map(x=>Number(x.value))
        .filter(Boolean);

      const specialty =
        document.getElementById(
          "reallocation-specialty"
        )?.value || null;

      if(
        scopeType === "agenda"
        && !agendaId
      ){
        cupReallocationMessage(
          "Seleziona un'agenda.",
          "danger"
        );
        return;
      }

      if(
        scopeType === "agendas"
        && !selectedAgendas.length
      ){
        cupReallocationMessage(
          "Seleziona almeno un'agenda.",
          "danger"
        );
        return;
      }

      if(
        scopeType === "specialty"
        && !specialty
      ){
        cupReallocationMessage(
          "Seleziona una specialità.",
          "danger"
        );
        return;
      }

      const payload = {

        scope_type: scopeType,

        agenda_id:
          scopeType === "agenda"
            ? agendaId
            : null,

        agenda_ids:
          scopeType === "agendas"
            ? selectedAgendas
            : [],

        specialty:
          scopeType === "specialty"
            ? specialty
            : null,

        kind:
          document.getElementById(
            "reallocation-kind"
          ).value,

        title:
          document.getElementById(
            "reallocation-title"
          ).value.trim(),

        note:
          document.getElementById(
            "reallocation-note"
          ).value.trim() || null,

        start_date:startDate,

        end_date:endDate,

        start_time:
          document.getElementById(
            "reallocation-start-time"
          ).value || null,

        end_time:
          document.getElementById(
            "reallocation-end-time"
          ).value || null
      };

      const button =
        document.getElementById(
          "btn-create-interruption"
        );

      button.disabled=true;

      try{

        const result =
          await CupApi.createReallocationIncident(
            payload
          );

        cupReallocationMessage(
          `Indisponibilità registrata. ` +
          `${result.cases} appuntamenti coinvolti, ` +
          `${result.proposals} proposte automatiche.`
        );

        await cupLoadReallocationIncidents();

        if(result.incident?.id)
          await cupOpenReallocationIncident(
            result.incident.id
          );

        if(
          typeof loadCupCalendar ===
          "function"
        )
          await loadCupCalendar();

      }
      catch(error){

        cupReallocationMessage(
          error.message,
          "danger"
        );

      }
      finally{

        button.disabled=false;
      }

    }
  );


/*
 * Default: oggi.
 */

(function(){

  const today =
    new Date()
      .toISOString()
      .slice(0,10);

  const start =
    document.getElementById(
      "reallocation-start-date"
    );

  const end =
    document.getElementById(
      "reallocation-end-date"
    );

  if(start && !start.value)
    start.value=today;

  if(end && !end.value)
    end.value=today;

})();

/* /CUP_REALLOCATION_UI_LOGIC_V1 */

/* CUP_REALLOCATION_CONFIRM_LOGIC_V1 */

let cupReallocationPreviewCaseId = null;
let cupReallocationPhoneCaseId = null;


async function cupOpenReallocationPreview(caseId){

  try {

    const data =
      await CupApi.previewReallocationMessage(caseId);

    cupReallocationPreviewCaseId = caseId;

    document.getElementById(
      "reallocation-preview-patient"
    ).innerHTML =
      `<strong>${escapeHtml(
        data.patient_name || "Paziente"
      )}</strong>`;

    document.getElementById(
      "reallocation-preview-message"
    ).textContent =
      data.message || "";

    bootstrap.Modal
      .getOrCreateInstance(
        document.getElementById(
          "reallocation-preview-modal"
        )
      )
      .show();

  } catch(error) {

    cupReallocationMessage(
      error.message,
      "danger"
    );
  }
}


function cupOpenPhoneConfirmation(caseData){

  cupReallocationPhoneCaseId =
    Number(caseData.id);

  document.getElementById(
    "reallocation-phone-summary"
  ).innerHTML = `
    <div>
      <strong>${escapeHtml(
        caseData.patient_name || "Paziente"
      )}</strong>
    </div>

    <div class="small mt-2">
      Appuntamento originale:<br>
      <strong>${escapeHtml(
        cupReallocationDateTime(
          caseData.original_scheduled_at
        )
      )}</strong>
    </div>

    <div class="small mt-2">
      Nuova proposta:<br>
      <strong class="text-primary">${escapeHtml(
        cupReallocationDateTime(
          caseData.proposed_scheduled_at
        )
      )}</strong>
    </div>
  `;

  document.getElementById(
    "reallocation-phone-note"
  ).value =
    "Confermato telefonicamente con il paziente";

  bootstrap.Modal
    .getOrCreateInstance(
      document.getElementById(
        "reallocation-phone-modal"
      )
    )
    .show();
}


document
  .getElementById(
    "btn-simulate-send-reallocation"
  )
  ?.addEventListener(
    "click",
    async ()=>{

      if(!cupReallocationPreviewCaseId)
        return;

      const button =
        document.getElementById(
          "btn-simulate-send-reallocation"
        );

      button.disabled=true;

      try {

        /*
         * In questa V1 utilizziamo lo stesso endpoint notify.
         * Il provider potrà essere sostituito successivamente
         * con un vero mock lato backend.
         */
        await CupApi.simulateReallocationNotification(
          cupReallocationPreviewCaseId
        );

        bootstrap.Modal
          .getInstance(
            document.getElementById(
              "reallocation-preview-modal"
            )
          )
          ?.hide();

        cupReallocationMessage(
          "Invio proposta registrato in simulazione."
        );

        if(cupCurrentReallocationIncident?.id)
          await cupOpenReallocationIncident(
            cupCurrentReallocationIncident.id
          );

      } catch(error) {

        cupReallocationMessage(
          error.message,
          "danger"
        );

      } finally {
        button.disabled=false;
      }

    }
  );


document
  .getElementById(
    "btn-confirm-reallocation-phone"
  )
  ?.addEventListener(
    "click",
    async ()=>{

      if(!cupReallocationPhoneCaseId)
        return;

      const note =
        document.getElementById(
          "reallocation-phone-note"
        ).value.trim();

      const button =
        document.getElementById(
          "btn-confirm-reallocation-phone"
        );

      button.disabled=true;

      try {

        await CupApi.confirmReallocationByPhone(
          cupReallocationPhoneCaseId,
          note
        );

        bootstrap.Modal
          .getInstance(
            document.getElementById(
              "reallocation-phone-modal"
            )
          )
          ?.hide();

        cupReallocationMessage(
          "Nuova data confermata telefonicamente."
        );

        if(cupCurrentReallocationIncident?.id)
          await cupOpenReallocationIncident(
            cupCurrentReallocationIncident.id
          );

        if(typeof loadCupCalendar === "function")
          await loadCupCalendar();

      } catch(error) {

        cupReallocationMessage(
          error.message,
          "danger"
        );

      } finally {
        button.disabled=false;
      }

    }
  );


/*
 * Intercettiamo i pulsanti esistenti dopo ogni render.
 */
const cupOriginalOpenReallocationIncident =
  cupOpenReallocationIncident;

cupOpenReallocationIncident =
  async function(id){

    await cupOriginalOpenReallocationIncident(id);

    const data =
      await CupApi.getReallocationIncident(id);

    const byId =
      new Map(
        (data.cases || [])
          .map(c => [Number(c.id),c])
      );

    document
      .querySelectorAll(
        "[data-reallocation-notify]"
      )
      .forEach(button=>{

        button.replaceWith(
          button.cloneNode(true)
        );

      });

    document
      .querySelectorAll(
        "[data-reallocation-notify]"
      )
      .forEach(button=>{

        button.addEventListener(
          "click",
          event=>{

            event.preventDefault();
            event.stopImmediatePropagation();

            cupOpenReallocationPreview(
              Number(
                button.dataset.reallocationNotify
              )
            );
          },
          true
        );

      });

    document
      .querySelectorAll(
        "[data-reallocation-accept]"
      )
      .forEach(button=>{

        const replacement =
          button.cloneNode(true);

        replacement.innerHTML =
          '<i class="bi bi-telephone-check"></i> ' +
          'Conferma telefonicamente';

        button.replaceWith(replacement);
      });

    document
      .querySelectorAll(
        "[data-reallocation-accept]"
      )
      .forEach(button=>{

        button.addEventListener(
          "click",
          event=>{

            event.preventDefault();
            event.stopImmediatePropagation();

            const caseData =
              byId.get(
                Number(
                  button.dataset.reallocationAccept
                )
              );

            if(caseData)
              cupOpenPhoneConfirmation(caseData);
          },
          true
        );

      });

  };

/* /CUP_REALLOCATION_CONFIRM_LOGIC_V1 */

/* CUP_REALLOCATION_DELETE_V2 */

document.addEventListener(
  "click",
  async event => {

    const button =
      event.target.closest(
        "[data-delete-reallocation-incident]"
      );

    if(!button)
      return;

    event.preventDefault();
    event.stopPropagation();

    const id =
      Number(
        button.dataset.deleteReallocationIncident
      );

    if(!id)
      return;

    const ok = confirm(
      "Eliminare questa interruzione?\n\n" +
      "Saranno rimossi anche i blocchi agenda e le " +
      "eventuali proposte non ancora elaborate."
    );

    if(!ok)
      return;

    button.disabled = true;

    try {

      const result =
        await CupApi.deleteReallocationIncident(id);

      console.log(
        "Interruzione eliminata",
        result
      );

      cupReallocationMessage(
        `Interruzione #${id} eliminata.`
      );

      document
        .getElementById(
          "reallocation-case-panel"
        )
        ?.classList.add("d-none");

      await cupLoadReallocationIncidents();

      if(
        typeof loadCupCalendar === "function"
      ){
        await loadCupCalendar();
      }

    }
    catch(error) {

      console.error(
        "Errore eliminazione interruzione",
        error
      );

      cupReallocationMessage(
        error?.message ||
        "Impossibile eliminare l'interruzione.",
        "danger"
      );

      alert(
        error?.message ||
        "Impossibile eliminare l'interruzione."
      );

    }
    finally {
      button.disabled = false;
    }
  },
  true
);

/* /CUP_REALLOCATION_DELETE_V2 */

/* CUP_REALLOCATION_CASE_LISTS_LOGIC_V1 */

let cupReallocationCaseView = "active";

const CUP_REALLOCATION_COMPLETED_STATUSES =
  new Set([
    "reallocated",
    "cancel_confirmed",
    "accepted"
  ]);

function cupReallocationCaseIsCompleted(status){
  return CUP_REALLOCATION_COMPLETED_STATUSES
    .has(String(status || ""));
}


function cupRefreshReallocationCaseLists(){

  const root =
    document.getElementById(
      "reallocation-cases"
    );

  if(!root)
    return;

  const cards = [
    ...root.querySelectorAll(
      "[data-reallocation-case-status]"
    )
  ];

  let activeCount = 0;
  let completedCount = 0;
  let visibleCount = 0;

  cards.forEach(card => {

    const status =
      card.dataset.reallocationCaseStatus || "";

    const completed =
      cupReallocationCaseIsCompleted(status);

    if(completed)
      completedCount++;
    else
      activeCount++;

    const visible =
      cupReallocationCaseView === "completed"
        ? completed
        : !completed;

    card.classList.toggle(
      "d-none",
      !visible
    );

    if(visible)
      visibleCount++;
  });


  const activeBadge =
    document.getElementById(
      "reallocation-active-count"
    );

  const completedBadge =
    document.getElementById(
      "reallocation-completed-count"
    );

  if(activeBadge)
    activeBadge.textContent =
      String(activeCount);

  if(completedBadge)
    completedBadge.textContent =
      String(completedCount);


  const activeButton =
    document.getElementById(
      "reallocation-filter-active"
    );

  const completedButton =
    document.getElementById(
      "reallocation-filter-completed"
    );

  if(activeButton){
    activeButton.className =
      cupReallocationCaseView === "active"
        ? "btn btn-primary"
        : "btn btn-outline-primary";
  }

  if(completedButton){
    completedButton.className =
      cupReallocationCaseView === "completed"
        ? "btn btn-secondary"
        : "btn btn-outline-secondary";
  }


  const empty =
    document.getElementById(
      "reallocation-empty-filter"
    );

  if(empty){

    if(!visibleCount && cards.length){

      empty.textContent =
        cupReallocationCaseView === "completed"
          ? "Nessuna pratica completata."
          : "Nessuna pratica da gestire.";

      empty.classList.remove("d-none");

    } else {

      empty.classList.add("d-none");

    }
  }
}


document
  .getElementById(
    "reallocation-filter-active"
  )
  ?.addEventListener(
    "click",
    ()=>{

      cupReallocationCaseView =
        "active";

      cupRefreshReallocationCaseLists();
    }
  );


document
  .getElementById(
    "reallocation-filter-completed"
  )
  ?.addEventListener(
    "click",
    ()=>{

      cupReallocationCaseView =
        "completed";

      cupRefreshReallocationCaseLists();
    }
  );


/*
 * La lista viene ricostruita dinamicamente ogni volta che
 * cambia una pratica. L'observer aggiorna automaticamente
 * filtri e contatori dopo ogni render.
 */

(function(){

  const root =
    document.getElementById(
      "reallocation-cases"
    );

  if(!root)
    return;

  const observer =
    new MutationObserver(
      ()=>cupRefreshReallocationCaseLists()
    );

  observer.observe(
    root,
    {
      childList:true
    }
  );

})();

/* /CUP_REALLOCATION_CASE_LISTS_LOGIC_V1 */

/* CUP_REALLOCATION_ACTIONS_DELEGATED_V2 */

/*
 * Usiamo delegation sul document perché i modal di riallocazione
 * possono trovarsi nel DOM dopo l'esecuzione iniziale di app.js.
 */

document.addEventListener(
  "click",
  async event => {

    const simulateButton =
      event.target.closest(
        "#btn-simulate-send-reallocation"
      );

    if(simulateButton){

      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();

      if(!cupReallocationPreviewCaseId){
        alert("Nessuna pratica selezionata.");
        return;
      }

      simulateButton.disabled = true;

      try {

        console.log(
          "SIMULATE REALLOCATION",
          cupReallocationPreviewCaseId
        );

        const result =
          await CupApi.simulateReallocationNotification(
            cupReallocationPreviewCaseId
          );

        console.log(
          "SIMULATION RESULT",
          result
        );

        bootstrap.Modal
          .getInstance(
            document.getElementById(
              "reallocation-preview-modal"
            )
          )
          ?.hide();

        cupReallocationMessage(
          "Proposta registrata in modalità simulazione."
        );

        if(cupCurrentReallocationIncident?.id){

          await cupOpenReallocationIncident(
            cupCurrentReallocationIncident.id
          );
        }

      }
      catch(error){

        console.error(
          "SIMULATION ERROR",
          error
        );

        cupReallocationMessage(
          error?.message ||
          "Errore durante la simulazione.",
          "danger"
        );

        alert(
          error?.message ||
          "Errore durante la simulazione."
        );

      }
      finally {

        simulateButton.disabled = false;

      }

      return;
    }


    const phoneButton =
      event.target.closest(
        "#btn-confirm-reallocation-phone"
      );

    if(phoneButton){

      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();

      if(!cupReallocationPhoneCaseId){
        alert("Nessuna pratica selezionata.");
        return;
      }

      const note =
        document.getElementById(
          "reallocation-phone-note"
        )?.value?.trim() || "";

      phoneButton.disabled = true;

      try {

        const result =
          await CupApi.confirmReallocationByPhone(
            cupReallocationPhoneCaseId,
            note
          );

        console.log(
          "PHONE CONFIRM RESULT",
          result
        );

        bootstrap.Modal
          .getInstance(
            document.getElementById(
              "reallocation-phone-modal"
            )
          )
          ?.hide();

        cupReallocationMessage(
          "Nuova data confermata telefonicamente."
        );

        if(
          typeof cupReallocationCaseView !==
          "undefined"
        ){
          cupReallocationCaseView = "active";
        }

        if(cupCurrentReallocationIncident?.id){

          await cupOpenReallocationIncident(
            cupCurrentReallocationIncident.id
          );
        }

        if(
          typeof loadCupCalendar === "function"
        ){
          await loadCupCalendar();
        }

      }
      catch(error){

        console.error(
          "PHONE CONFIRM ERROR",
          error
        );

        cupReallocationMessage(
          error?.message ||
          "Errore conferma telefonica.",
          "danger"
        );

        alert(
          error?.message ||
          "Errore conferma telefonica."
        );

      }
      finally {

        phoneButton.disabled = false;

      }

      return;
    }

  },
  true
);

/* /CUP_REALLOCATION_ACTIONS_DELEGATED_V2 */

/* CUP_PATIENT_REALLOCATION_RESPONSE_V1 */

let cupReallocationPatientToken = null;


/*
 * Recupera il token aggiornato della pratica.
 */
async function cupLoadPatientReallocationToken(){

  if(!cupReallocationPreviewCaseId)
    return null;

  if(!cupCurrentReallocationIncident?.id)
    return null;

  const data =
    await CupApi.getReallocationIncident(
      cupCurrentReallocationIncident.id
    );

  const item =
    (data.cases || [])
      .find(
        x =>
          Number(x.id) ===
          Number(cupReallocationPreviewCaseId)
      );

  cupReallocationPatientToken =
    item?.token_id || null;

  return cupReallocationPatientToken;
}


async function cupSimulatedPatientResponse(action){

  try {

    let token =
      cupReallocationPatientToken;

    if(!token)
      token =
        await cupLoadPatientReallocationToken();

    if(!token){
      throw new Error(
        "Prima esegui Simula invio."
      );
    }

    const labels = {
      accept:
        "Accettare la nuova data proposta?",
      reject:
        "Confermare che la nuova data non è accettabile?",
      contact:
        "Richiedere di essere contattati dal CUP?"
    };

    if(
      !confirm(
        labels[action] ||
        "Confermare la risposta?"
      )
    )
      return;

    const result =
      await CupApi.respondReallocationAsPatient(
        token,
        action
      );

    bootstrap.Modal
      .getInstance(
        document.getElementById(
          "reallocation-preview-modal"
        )
      )
      ?.hide();


    if(action === "accept"){

      cupReallocationMessage(
        "Il paziente ha accettato la nuova data."
      );

    } else if(action === "reject"){

      cupReallocationMessage(
        "Il paziente ha rifiutato la nuova data.",
        "warning"
      );

    } else {

      cupReallocationMessage(
        "Il paziente ha richiesto di essere contattato.",
        "warning"
      );
    }


    if(cupCurrentReallocationIncident?.id){

      await cupOpenReallocationIncident(
        cupCurrentReallocationIncident.id
      );
    }


    if(
      typeof loadCupCalendar ===
      "function"
    ){
      await loadCupCalendar();
    }

    return result;

  }
  catch(error){

    console.error(
      "PATIENT REALLOCATION RESPONSE",
      error
    );

    alert(
      error?.message ||
      "Impossibile registrare la risposta."
    );
  }
}


document.addEventListener(
  "click",
  event => {

    const accept =
      event.target.closest(
        "#btn-reallocation-patient-accept"
      );

    if(accept){

      event.preventDefault();

      cupSimulatedPatientResponse(
        "accept"
      );

      return;
    }


    const reject =
      event.target.closest(
        "#btn-reallocation-patient-reject"
      );

    if(reject){

      event.preventDefault();

      cupSimulatedPatientResponse(
        "reject"
      );

      return;
    }


    const contact =
      event.target.closest(
        "#btn-reallocation-patient-contact"
      );

    if(contact){

      event.preventDefault();

      cupSimulatedPatientResponse(
        "contact"
      );

      return;
    }

  },
  true
);

/* /CUP_PATIENT_REALLOCATION_RESPONSE_V1 */

/* CUP_REALLOCATION_SCOPE_V2 */

function cupPopulateReallocationScopes(){

  const agendas =
    (cupCalendarState.agendas || [])
      .filter(a => a.active !== false)
      .sort(
        (a,b)=>
          String(a.name || "")
          .localeCompare(
            String(b.name || ""),
            "it"
          )
      );

  const multi =
    document.getElementById(
      "reallocation-agendas"
    );

  if(multi){

    multi.innerHTML =
      agendas.map(a=>`
        <option value="${a.id}">
          ${escapeHtml(a.name)}
        </option>
      `).join("");
  }


  const specialty =
    document.getElementById(
      "reallocation-specialty"
    );

  if(specialty){

    const doctors =
      (cupCalendarState.doctors || [])
        .filter(d => d.active !== false);

    const values =
      [...new Set(
        doctors
          .map(d => String(
            d.specialty || ""
          ).trim())
          .filter(Boolean)
      )]
      .sort(
        (a,b)=>a.localeCompare(b,"it")
      );

    specialty.innerHTML =
      '<option value="">Seleziona specialità</option>' +
      values.map(x=>
        `<option value="${escapeHtml(x)}">
          ${escapeHtml(x)}
        </option>`
      ).join("");
  }
}


function cupRefreshReallocationScopeUI(){

  const scope =
    document.getElementById(
      "reallocation-scope"
    )?.value || "agenda";

  const map = {
    agenda:
      "reallocation-agenda-wrap",
    agendas:
      "reallocation-agendas-wrap",
    specialty:
      "reallocation-specialty-wrap",
    facility:
      "reallocation-facility-wrap"
  };

  Object.values(map)
    .forEach(id =>
      document
        .getElementById(id)
        ?.classList.add("d-none")
    );

  document
    .getElementById(map[scope])
    ?.classList.remove("d-none");
}


document.addEventListener(
  "change",
  event => {

    if(
      event.target?.id ===
      "reallocation-scope"
    ){
      cupRefreshReallocationScopeUI();
    }
  }
);


/*
 * Quando si apre il pannello aggiorniamo
 * agende e specialità.
 */
document.addEventListener(
  "click",
  event => {

    if(
      event.target.closest(
        "#btn-reallocation-panel"
      )
    ){
      setTimeout(
        ()=>{
          cupPopulateReallocationScopes();
          cupRefreshReallocationScopeUI();
        },
        0
      );
    }
  },
  true
);

/* /CUP_REALLOCATION_SCOPE_V2 */

/* CUP_REALLOCATED_BOOKING_BADGE_V1 */

let cupReallocatedBookingMap =
  new Map();


async function cupLoadReallocatedBookingFlags(){

  try {

    const rows =
      await CupApi.getReallocatedBookings();

    cupReallocatedBookingMap =
      new Map(
        (rows || []).map(
          row => [
            Number(row.booking_id),
            row
          ]
        )
      );

  }
  catch(error){

    console.error(
      "Reallocated booking flags",
      error
    );

    cupReallocatedBookingMap =
      new Map();
  }
}


function cupDecorateReallocatedBookings(){

  document
    .querySelectorAll(
      "#cup-calendar [data-booking-id]"
    )
    .forEach(el => {

      const bookingId =
        Number(
          el.dataset.bookingId
        );

      const info =
        cupReallocatedBookingMap.get(
          bookingId
        );

      /*
       * Se il booking non è riallocato,
       * rimuoviamo eventuali marker precedenti.
       */
      if(!info){

        el.classList.remove(
          "cup-reallocated-booking"
        );

        el
          .querySelector(
            ".cup-reallocated-marker"
          )
          ?.remove();

        return;
      }


      el.classList.add(
        "cup-reallocated-booking"
      );


      if(
        !el.querySelector(
          ".cup-reallocated-marker"
        )
      ){

        const marker =
          document.createElement("span");

        marker.className =
          "cup-reallocated-marker";

        marker.innerHTML =
          '<i class="bi bi-exclamation-triangle-fill"></i>' +
          '<span>Riallocato</span>';

        /*
         * Inserimento all'inizio dell'appuntamento.
         */
        el.prepend(marker);
      }


      const oldDate =
        info.original_scheduled_at
          ? new Date(
              info.original_scheduled_at
            ).toLocaleString(
              "it-IT",
              {
                day:"2-digit",
                month:"2-digit",
                year:"numeric",
                hour:"2-digit",
                minute:"2-digit"
              }
            )
          : null;


      const detail = [
        "⚠ Appuntamento riallocato",

        info.confirmation_label
          || "Riallocazione confermata",

        oldDate
          ? `Appuntamento originale: ${oldDate}`
          : null,

        info.confirmation_note
          || null
      ]
      .filter(Boolean)
      .join("\n");


      el.title = detail;
    });
}


/*
 * Ricarica i contrassegni quando cambia
 * il calendario.
 */
async function cupRefreshReallocatedBookings(){

  await cupLoadReallocatedBookingFlags();

  cupDecorateReallocatedBookings();
}


/*
 * Il calendario viene ricostruito dinamicamente.
 * L'observer applica automaticamente i marker
 * anche dopo cambio settimana/mese/filtro.
 */
(function(){

  const root =
    document.getElementById(
      "cup-calendar"
    );

  if(!root)
    return;

  let scheduled = false;

  const observer =
    new MutationObserver(
      ()=>{

        if(scheduled)
          return;

        scheduled = true;

        requestAnimationFrame(
          ()=>{

            scheduled = false;

            cupDecorateReallocatedBookings();
          }
        );
      }
    );

  observer.observe(
    root,
    {
      childList:true,
      subtree:true
    }
  );

})();


/*
 * Primo caricamento.
 */
cupRefreshReallocatedBookings();

/* /CUP_REALLOCATED_BOOKING_BADGE_V1 */

/* CUP_PHONE_V2_DISABLED */

/* =========================================================
   CUP PHONE ISLAND V3
   ========================================================= */

(function(){

  const STORAGE =
    "cup_phone_island_v3";


  let phone = null;
  let legacy = null;

  let callStartedAt = null;
  let timerHandle = null;

  let muted = false;
  let held = false;



  /* -------------------------------------------------------
     TROVA TELEFONO ESISTENTE
     ------------------------------------------------------- */

  function findLegacyPhone(){

    const selectors = [

      ".cup-phone-v2",

      "#cup-phone",
      "#phone-panel",
      "#softphone-panel",
      "#webphone-panel",

      ".softphone",
      ".webphone"

    ];


    for(const selector of selectors){

      const el =
        document.querySelector(
          selector
        );

      if(el)
        return el;
    }


    const candidates =
      [
        ...document.querySelectorAll(
          "div,section,aside"
        )
      ]
      .filter(el=>{

        const text =
          String(
            el.textContent || ""
          );

        return (
          text.includes("Telefono CUP")
          &&
          text.length < 5000
        );
      });


    candidates.sort(
      (a,b)=>
        a.getBoundingClientRect().height -
        b.getBoundingClientRect().height
    );


    return candidates[0] || null;
  }



  /* -------------------------------------------------------
     TROVA CONTROLLI LEGACY
     ------------------------------------------------------- */

  function findLegacyControl(type){

    const selectors = {

      number:[

        "#phone-number",
        "#phone-number-input",
        "#softphone-number",
        "#webphone-number",

        "input[placeholder*='Numero']",
        "input[placeholder*='numero']",
        "input[placeholder*='interno']"

      ],


      call:[

        "#phone-call",
        "#btn-phone-call",
        "#softphone-call",

        "[data-phone-action='call']"

      ],


      hangup:[

        "#phone-hangup",
        "#btn-phone-hangup",
        "#phone-end",
        "#btn-phone-end",

        "[data-phone-action='hangup']"

      ],


      mute:[

        "#phone-mute",
        "#btn-phone-mute",

        "[data-phone-action='mute']"

      ],


      hold:[

        "#phone-hold",
        "#btn-phone-hold",

        "[data-phone-action='hold']"

      ],


      transfer:[

        "#phone-transfer",
        "#btn-phone-transfer",

        "[data-phone-action='transfer']"

      ],


      redial:[

        "#phone-redial",
        "#btn-phone-redial",

        "[data-phone-action='redial']"

      ]

    };


    for(
      const selector of
      selectors[type] || []
    ){

      const el =
        legacy?.querySelector(
          selector
        )
        ||
        document.querySelector(
          selector
        );

      if(el)
        return el;
    }


    /*
     * fallback per testo pulsante
     */

    const labels = {

      call:[
        "Chiama"
      ],

      hangup:[
        "Termina",
        "Riaggancia"
      ],

      mute:[
        "Mute"
      ],

      hold:[
        "Hold"
      ],

      transfer:[
        "Trasferisci"
      ],

      redial:[
        "Richiama"
      ]

    };


    const buttons =
      [
        ...(legacy?.querySelectorAll(
          "button"
        ) || [])
      ];


    return buttons.find(
      btn =>
        (labels[type] || [])
          .some(
            label =>
              String(
                btn.textContent || ""
              )
              .trim()
              .includes(label)
          )
    ) || null;

  }



  /* -------------------------------------------------------
     STATO
     ------------------------------------------------------- */

  function savePosition(){

    if(!phone)
      return;

    const rect =
      phone.getBoundingClientRect();


    localStorage.setItem(
      STORAGE,
      JSON.stringify({

        left:rect.left,
        top:rect.top,

        expanded:
          phone.classList.contains(
            "expanded"
          )

      })
    );
  }



  function restorePosition(){

    try{

      const state =
        JSON.parse(
          localStorage.getItem(
            STORAGE
          ) || "{}"
        );


      if(
        Number.isFinite(state.left)
        &&
        Number.isFinite(state.top)
      ){

        phone.style.left =
          Math.min(
            state.left,
            window.innerWidth -
            phone.offsetWidth
          )
          + "px";

        phone.style.top =
          Math.min(
            state.top,
            window.innerHeight -
            50
          )
          + "px";

        phone.style.right =
          "auto";

        phone.style.bottom =
          "auto";
      }


      if(state.expanded)
        phone.classList.add(
          "expanded"
        );

    }
    catch(_){}

  }



  function setStatus(
    status,
    title,
    subtitle
  ){

    const dot =
      phone.querySelector(
        ".cup-phone-island-status-dot"
      );

    dot.className =
      "cup-phone-island-status-dot";

    if(status)
      dot.classList.add(status);


    phone.querySelector(
      ".cup-phone-island-title"
    ).textContent =
      title || "Telefono CUP";


    phone.querySelector(
      ".cup-phone-island-subtitle"
    ).textContent =
      subtitle || "";


    phone.classList.toggle(
      "island-idle",
      status !== "active"
    );

  }



  /* -------------------------------------------------------
     TIMER
     ------------------------------------------------------- */

  function formatDuration(seconds){

    const min =
      Math.floor(
        seconds / 60
      );

    const sec =
      seconds % 60;

    return (
      String(min).padStart(2,"0")
      +
      ":"
      +
      String(sec).padStart(2,"0")
    );
  }



  function startTimer(){

    callStartedAt =
      Date.now();


    clearInterval(
      timerHandle
    );


    timerHandle =
      setInterval(
        ()=>{

          const elapsed =
            Math.floor(
              (
                Date.now() -
                callStartedAt
              )
              /1000
            );


          const el =
            phone.querySelector(
              ".cup-phone-island-time"
            );

          if(el)
            el.textContent =
              formatDuration(
                elapsed
              );

        },
        1000
      );

  }



  function stopTimer(){

    clearInterval(
      timerHandle
    );

    timerHandle = null;

    const el =
      phone.querySelector(
        ".cup-phone-island-time"
      );

    if(el)
      el.textContent = "";

  }



  /* -------------------------------------------------------
     CALL
     ------------------------------------------------------- */

  function dial(){

    const input =
      phone.querySelector(
        ".cup-phone-island-number"
      );

    const number =
      String(
        input.value || ""
      ).trim();


    if(!number)
      return;


    const legacyInput =
      findLegacyControl(
        "number"
      );


    if(legacyInput){

      legacyInput.value =
        number;

      legacyInput.dispatchEvent(
        new Event(
          "input",
          {bubbles:true}
        )
      );

      legacyInput.dispatchEvent(
        new Event(
          "change",
          {bubbles:true}
        )
      );
    }


    const call =
      findLegacyControl(
        "call"
      );


    if(call)
      call.click();


    setStatus(
      "calling",
      number,
      "Chiamata in corso"
    );


    /*
     * Quando il motore SIP sarà collegato
     * direttamente sostituiremo questo stato
     * con gli eventi reali.
     */

    phone.classList.add(
      "expanded"
    );

  }



  function hangup(){

    const hangup =
      findLegacyControl(
        "hangup"
      );


    if(hangup)
      hangup.click();


    stopTimer();


    setStatus(
      "",
      "Telefono CUP",
      "Configurato"
    );

  }



  /* -------------------------------------------------------
     DTMF
     ------------------------------------------------------- */

  function sendDTMF(value){

    /*
     * Prima tentiamo API pubbliche già presenti.
     */

    const candidates = [

      window.CupPhone,
      window.CupSoftphone,
      window.WebPhone,
      window.softphone

    ];


    for(const obj of candidates){

      if(
        obj
        &&
        typeof obj.sendDTMF ===
        "function"
      ){

        obj.sendDTMF(value);
        return;
      }

    }


    /*
     * fallback:
     * cerca tastiera legacy
     */

    const key =
      legacy?.querySelector(
        `[data-dtmf="${CSS.escape(value)}"]`
      );

    if(key)
      key.click();

  }



  /* -------------------------------------------------------
     TOOL
     ------------------------------------------------------- */

  function toggleMute(button){

    muted = !muted;

    button.classList.toggle(
      "active",
      muted
    );


    const legacyMute =
      findLegacyControl(
        "mute"
      );

    if(legacyMute)
      legacyMute.click();

  }



  function toggleHold(button){

    held = !held;

    button.classList.toggle(
      "active",
      held
    );


    const legacyHold =
      findLegacyControl(
        "hold"
      );

    if(legacyHold)
      legacyHold.click();

  }



  /* -------------------------------------------------------
     CREA ISLAND
     ------------------------------------------------------- */

  function build(){

    legacy =
      findLegacyPhone();


    if(!legacy){

      console.warn(
        "Phone Island V3: telefono legacy non trovato"
      );

      return false;
    }


    /*
     * Se V2 esiste, la neutralizziamo.
     */

    legacy.classList.remove(
      "cup-phone-v2",
      "minimized",
      "docked-left",
      "docked-right"
    );


    legacy.style.position =
      "";

    legacy.style.left =
      "";

    legacy.style.right =
      "";

    legacy.style.top =
      "";

    legacy.style.bottom =
      "";


    legacy.classList.add(
      "cup-phone-island-legacy"
    );



    phone =
      document.createElement(
        "div"
      );


    phone.className =
      "cup-phone-island-v3 island-idle";


    phone.innerHTML = `

      <div class="cup-phone-island-bar">

        <span
          class="cup-phone-island-status-dot">
        </span>


        <div class="cup-phone-island-main">

          <div class="cup-phone-island-title">
            Telefono CUP
          </div>

          <div class="cup-phone-island-subtitle">
            Registrato
          </div>

        </div>


        <div class="cup-phone-island-time">
        </div>


        <button
          type="button"
          class="cup-phone-island-icon-button"
          data-island-action="expand"
          title="Apri telefono">

          <i class="bi bi-telephone"></i>

        </button>

      </div>


      <div class="cup-phone-island-content">

        <input
          type="tel"
          class="cup-phone-island-number"
          placeholder="Numero o interno"
          autocomplete="off">


        <button
          type="button"
          class="cup-phone-island-primary"
          data-island-action="call">

          <i class="bi bi-telephone-fill me-1"></i>
          Chiama

        </button>


        <div class="cup-phone-island-patient">

          <div>

            <div class="cup-phone-island-patient-name">
            </div>

            <div class="text-muted">
              Paziente riconosciuto
            </div>

          </div>

          <button
            type="button"
            data-island-action="patient">
            Apri
          </button>

        </div>


        <div class="cup-phone-island-tools">

          <button
            type="button"
            class="cup-phone-island-tool"
            data-island-action="mute">

            <i class="bi bi-mic-mute"></i>
            <span>Mute</span>

          </button>


          <button
            type="button"
            class="cup-phone-island-tool"
            data-island-action="hold">

            <i class="bi bi-pause-circle"></i>
            <span>Hold</span>

          </button>


          <button
            type="button"
            class="cup-phone-island-tool"
            data-island-action="dtmf">

            <i class="bi bi-grid-3x3-gap"></i>
            <span>DTMF</span>

          </button>


          <button
            type="button"
            class="cup-phone-island-tool"
            data-island-action="transfer">

            <i class="bi bi-arrow-right-circle"></i>
            <span>Trasferisci</span>

          </button>


          <button
            type="button"
            class="cup-phone-island-tool"
            data-island-action="redial">

            <i class="bi bi-arrow-repeat"></i>
            <span>Richiama</span>

          </button>

        </div>


        <div class="cup-phone-island-dtmf">

          ${[
            "1","2","3",
            "4","5","6",
            "7","8","9",
            "*","0","#"
          ].map(x=>`
            <button
              type="button"
              data-island-dtmf="${x}">
              ${x}
            </button>
          `).join("")}

        </div>


        <div class="cup-phone-island-transfer">

          <div class="cup-phone-island-transfer-row">

            <input
              type="text"
              placeholder="Interno">

            <button
              type="button"
              data-island-action="transfer-go">

              Trasferisci

            </button>

          </div>

        </div>

      </div>
    `;


    document.body.appendChild(
      phone
    );


    restorePosition();


    installDrag();


    console.log(
      "Telefono CUP Island V3 installato"
    );


    /*
     * Bridge pubblico per collegamento SIP.
     */

    window.CupPhoneIsland = {

      setRegistered(
        extension="202"
      ){

        /*
         * Il softphone non è fonte autorevole dello stato SIP.
         * Verifichiamo sempre il Contact reale tramite Asterisk/AMI.
         */
        setStatus(
          "",
          `Telefono CUP · ${extension}`,
          "Verifica registrazione..."
        );

        refreshRealVoipStatus();
      },


      setCalling(
        name,
        number
      ){

        setStatus(
          "calling",
          name || number || "Chiamata",
          number || ""
        );

        phone.classList.add(
          "expanded"
        );
      },


      setConnected(
        name,
        number
      ){

        setStatus(
          "active",
          name || number || "In chiamata",
          number || ""
        );

        phone.classList.add(
          "expanded"
        );

        startTimer();
      },


      setEnded(){

        hangup();
      }

    };


    return true;

  }



  /* -------------------------------------------------------
     DRAG + SNAP
     ------------------------------------------------------- */

  function installDrag(){

    const bar =
      phone.querySelector(
        ".cup-phone-island-bar"
      );


    let dragging = false;

    let dx = 0;
    let dy = 0;


    bar.addEventListener(
      "pointerdown",
      event=>{

        if(
          event.target.closest(
            "button"
          )
        )
          return;


        const rect =
          phone.getBoundingClientRect();


        dx =
          event.clientX -
          rect.left;

        dy =
          event.clientY -
          rect.top;


        dragging = true;


        phone.classList.add(
          "dragging"
        );


        bar.setPointerCapture(
          event.pointerId
        );

      }
    );


    bar.addEventListener(
      "pointermove",
      event=>{

        if(!dragging)
          return;


        const maxX =
          window.innerWidth -
          phone.offsetWidth;


        const maxY =
          window.innerHeight -
          50;


        const left =
          Math.max(
            0,
            Math.min(
              maxX,
              event.clientX - dx
            )
          );


        const top =
          Math.max(
            0,
            Math.min(
              maxY,
              event.clientY - dy
            )
          );


        phone.style.left =
          left + "px";

        phone.style.top =
          top + "px";

        phone.style.right =
          "auto";

        phone.style.bottom =
          "auto";

      }
    );


    bar.addEventListener(
      "pointerup",
      event=>{

        if(!dragging)
          return;


        dragging = false;


        phone.classList.remove(
          "dragging"
        );


        /*
         * snap leggero ai bordi
         */

        const rect =
          phone.getBoundingClientRect();


        if(rect.left < 35){

          phone.style.left =
            "10px";

        }


        if(
          window.innerWidth -
          rect.right <
          35
        ){

          phone.style.left =
            (
              window.innerWidth -
              phone.offsetWidth -
              10
            )
            + "px";

        }


        savePosition();


        try{

          bar.releasePointerCapture(
            event.pointerId
          );

        }
        catch(_){}

      }
    );

  }



  /* -------------------------------------------------------
     CLICK HANDLER
     ------------------------------------------------------- */

  document.addEventListener(
    "click",
    event=>{

      if(!phone)
        return;


      const dtmf =
        event.target.closest(
          "[data-island-dtmf]"
        );


      if(dtmf){

        sendDTMF(
          dtmf.dataset.islandDtmf
        );

        return;
      }


      const button =
        event.target.closest(
          "[data-island-action]"
        );


      if(!button)
        return;


      const action =
        button.dataset.islandAction;



      if(action === "expand"){

        phone.classList.toggle(
          "expanded"
        );

        savePosition();

        return;
      }



      if(action === "call"){

        dial();

        return;
      }



      if(action === "mute"){

        toggleMute(button);

        return;
      }



      if(action === "hold"){

        toggleHold(button);

        return;
      }



      if(action === "dtmf"){

        phone
          .querySelector(
            ".cup-phone-island-dtmf"
          )
          .classList.toggle(
            "open"
          );

        return;
      }



      if(action === "transfer"){

        phone
          .querySelector(
            ".cup-phone-island-transfer"
          )
          .classList.toggle(
            "open"
          );

        return;
      }



      if(action === "transfer-go"){

        const target =
          phone
            .querySelector(
              ".cup-phone-island-transfer input"
            )
            .value
            .trim();


        if(!target)
          return;


        const legacyTransfer =
          findLegacyControl(
            "transfer"
          );


        if(legacyTransfer){

          const legacyInput =
            findLegacyControl(
              "number"
            );


          if(legacyInput){

            legacyInput.value =
              target;

            legacyInput.dispatchEvent(
              new Event(
                "input",
                {bubbles:true}
              )
            );
          }


          legacyTransfer.click();
        }


        return;
      }



      if(action === "redial"){

        const redial =
          findLegacyControl(
            "redial"
          );


        if(redial)
          redial.click();


        return;
      }

    },
    true
  );



  /* -------------------------------------------------------
     ENTER = CALL
     ------------------------------------------------------- */

  document.addEventListener(
    "keydown",
    event=>{

      if(
        !phone
        ||
        event.key !==
        "Enter"
      )
        return;


      if(
        event.target.matches(
          ".cup-phone-island-number"
        )
      ){

        event.preventDefault();

        dial();
      }

    }
  );



  /* -------------------------------------------------------
     INSTALL RESILIENTE
     ------------------------------------------------------- */

  function install(){

    if(
      document.querySelector(
        ".cup-phone-island-v3"
      )
    )
      return true;


    return build();
  }



  if(!install()){

    const observer =
      new MutationObserver(
        ()=>{

          if(install())
            observer.disconnect();

        }
      );


    observer.observe(
      document.body,
      {
        childList:true,
        subtree:true
      }
    );

  }

})();

/* /CUP PHONE ISLAND V3 */

/* CUP_REMINDER_PROVIDER_HEALTH_UI_V1 */

async function loadReminderProviderStatus(){

  const root =
    document.getElementById(
      "reminder-provider-status"
    );

  if(!root)
    return;

  try{

    const rows =
      await CupApi.getReminderProviderStatus();

    const labels = {
      email:"Email",
      whatsapp:"WhatsApp",
      sms:"SMS",
      telegram:"Telegram"
    };

    const icons = {
      email:"bi-envelope",
      whatsapp:"bi-whatsapp",
      sms:"bi-chat-square-text",
      telegram:"bi-telegram"
    };

    root.innerHTML =
      (rows || []).map(row=>{

        let badgeClass =
          "bg-secondary";

        let label =
          "Da verificare";

        let dot =
          "○";


        if(row.status === "operational"){
          badgeClass = "bg-success";
          label = "Operativo";
          dot = "●";
        }

        else if(row.status === "suspended"){
          badgeClass = "bg-danger";
          label = "Sospeso";
          dot = "●";
        }

        else if(row.status === "degraded"){
          badgeClass = "bg-warning text-dark";
          label = "Errore";
          dot = "●";
        }

        else if(row.status === "not_configured"){
          badgeClass = "bg-light text-dark border";
          label = "Non configurato";
          dot = "○";
        }

        else if(row.configured){
          badgeClass = "bg-info text-dark";
          label = "Configurato";
          dot = "●";
        }


        const error =
          row.last_error
            ? `
              <div
                class="small text-danger mt-1 text-truncate"
                title="${escapeHtml(row.last_error)}">
                ${escapeHtml(row.last_error)}
              </div>
            `
            : "";


        const reactivate =
          row.status === "suspended"
            ? `
              <button
                type="button"
                class="btn btn-sm btn-outline-primary mt-2"
                data-reactivate-reminder-provider="${escapeHtml(row.channel)}">
                Riattiva
              </button>
            `
            : "";


        return `
          <div class="col-xl-3 col-md-6">
            <div class="border rounded p-2 h-100">

              <div class="d-flex justify-content-between align-items-center">

                <div>
                  <i class="bi ${icons[row.channel] || "bi-bell"} me-1"></i>
                  <strong>
                    ${escapeHtml(labels[row.channel] || row.channel)}
                  </strong>
                </div>

                <span class="badge ${badgeClass}">
                  ${dot} ${label}
                </span>

              </div>

              ${error}
              ${reactivate}

            </div>
          </div>
        `;

      }).join("");


    root
      .querySelectorAll(
        "[data-reactivate-reminder-provider]"
      )
      .forEach(button=>{

        button.addEventListener(
          "click",
          async ()=>{

            const channel =
              button.dataset
                .reactivateReminderProvider;

            button.disabled = true;

            try{

              await CupApi
                .reactivateReminderProvider(
                  channel
                );

              await loadReminderProviderStatus();

              showToast(
                `${channel} riattivato. Verrà verificato al prossimo invio.`,
                "success"
              );

            }
            catch(error){

              showToast(
                error.message,
                "error"
              );

              button.disabled = false;
            }

          }
        );

      });

  }
  catch(error){

    root.innerHTML =
      `<div class="col-12 text-danger small">
        Impossibile verificare lo stato dei provider.
      </div>`;

  }

}


/*
 * Aggiorna stato provider insieme alla coda.
 */
document
  .getElementById(
    "btn-refresh-reminders"
  )
  ?.addEventListener(
    "click",
    loadReminderProviderStatus
  );


document.addEventListener(
  "click",
  event=>{

    const link =
      event.target.closest(
        '[data-tab="reminders"]'
      );

    if(link){
      setTimeout(
        loadReminderProviderStatus,
        0
      );
    }

  }
);

/* /CUP_REMINDER_PROVIDER_HEALTH_UI_V1 */

/* CUP_CLINIC_LOGO_SETTINGS_V1 */

function wireClinicLogoSettings(){

  const upload =
    document.getElementById(
      "btn-upload-clinic-logo"
    );

  const input =
    document.getElementById(
      "clinic-logo-file"
    );

  const remove =
    document.getElementById(
      "btn-delete-clinic-logo"
    );

  if(upload && input){

    upload.addEventListener(
      "click",
      async ()=>{

        const file =
          input.files?.[0];

        if(!file){
          showToast(
            "Seleziona prima un logo.",
            "warning"
          );
          return;
        }

        upload.disabled = true;

        try{

          await CupApi.uploadClinicLogo(
            file
          );

          showToast(
            "Logo struttura aggiornato.",
            "success"
          );

          await loadSettings();

        }
        catch(error){

          showToast(
            error.message,
            "error"
          );

          upload.disabled = false;
        }

      }
    );

  }


  if(remove){

    remove.addEventListener(
      "click",
      async ()=>{

        if(
          !confirm(
            "Rimuovere il logo della struttura?"
          )
        )
          return;

        remove.disabled = true;

        try{

          await CupApi
            .deleteClinicLogo();

          showToast(
            "Logo rimosso.",
            "success"
          );

          await loadSettings();

        }
        catch(error){

          showToast(
            error.message,
            "error"
          );

          remove.disabled = false;
        }

      }
    );

  }

}

/* /CUP_CLINIC_LOGO_SETTINGS_V1 */

/* CUP_PREVISIT_DETAIL_UI_V1 */

let previsitDetailModalInstance = null;


function getPrevisitDetailModal(){

  if(
    !previsitDetailModalInstance
  ){

    previsitDetailModalInstance =
      new bootstrap.Modal(
        document.getElementById(
          "previsit-detail-modal"
        )
      );

  }

  return previsitDetailModalInstance;
}


function previsitAnswerText(value){

  if(
    value === null
    || value === undefined
    || value === ""
  )
    return "—";

  if(
    typeof value === "boolean"
  )
    return value ? "Sì" : "No";

  if(
    Array.isArray(value)
  )
    return value.join(", ");

  if(
    typeof value === "object"
  )
    return JSON.stringify(value);

  return String(value);
}


async function openPrevisitDetail(id){

  const loading =
    document.getElementById(
      "previsit-detail-loading"
    );

  const content =
    document.getElementById(
      "previsit-detail-content"
    );

  const error =
    document.getElementById(
      "previsit-detail-error"
    );


  loading.classList.remove(
    "d-none"
  );

  content.classList.add(
    "d-none"
  );

  error.classList.add(
    "d-none"
  );


  getPrevisitDetailModal().show();


  try{

    const data =
      await CupApi.getPrevisitSubmission(
        id
      );


    document.getElementById(
      "previsit-detail-subtitle"
    ).textContent =
      [
        data.patient_name,
        data.service_name
      ]
      .filter(Boolean)
      .join(" · ");


    const when =
      data.scheduled_at
        ? fmtDate(data.scheduled_at)
        : "—";


    const completed =
      data.completed_at
        ? fmtDate(data.completed_at)
        : "—";


    document.getElementById(
      "previsit-detail-meta"
    ).innerHTML = `

      <div class="row g-3">

        <div class="col-md-6">
          <div class="small text-muted">
            Paziente
          </div>
          <strong>
            ${escapeHtml(
              data.patient_name || "—"
            )}
          </strong>
        </div>

        <div class="col-md-6">
          <div class="small text-muted">
            Prestazione
          </div>
          <strong>
            ${escapeHtml(
              data.service_name || "—"
            )}
          </strong>
        </div>

        <div class="col-md-6">
          <div class="small text-muted">
            Appuntamento
          </div>
          <strong>
            ${escapeHtml(when)}
          </strong>
        </div>

        <div class="col-md-6">
          <div class="small text-muted">
            Compilata il
          </div>
          <strong>
            ${escapeHtml(completed)}
          </strong>
        </div>

      </div>
    `;


    const answers =
      data.answers || {};


    const fields =
      Array.isArray(data.fields)
        ? data.fields
        : [];


    const knownKeys =
      new Set(
        fields
          .map(field=>field.key)
          .filter(Boolean)
      );


    const items =
      fields.map(field=>({

        key:
          field.key,

        label:
          field.label
          || field.key
          || "Campo",

        value:
          answers[
            field.key
          ]

      }));


    /*
     * Visualizza anche eventuali risposte
     * non più presenti nel template attuale.
     */
    Object
      .entries(answers)
      .forEach(([key,value])=>{

        if(
          !knownKeys.has(key)
        ){

          items.push({
            key,
            label:key,
            value
          });

        }

      });


    document.getElementById(
      "previsit-detail-answers"
    ).innerHTML =
      items.length
        ? items.map(item=>`

          <div
            class="border-bottom py-3">

            <div
              class="small text-muted mb-1">

              ${escapeHtml(
                item.label
              )}

            </div>

            <div class="fw-semibold">

              ${escapeHtml(
                previsitAnswerText(
                  item.value
                )
              )}

            </div>

          </div>

        `).join("")
        : `
          <div class="text-muted">
            Nessuna risposta registrata.
          </div>
        `;


    document.getElementById(
      "previsit-detail-consent"
    ).innerHTML = `

      <div
        class="d-flex align-items-center gap-2 mb-2">

        <i class="bi ${
          data.consent_accepted
            ? "bi-check-circle-fill text-success"
            : "bi-x-circle text-danger"
        }"></i>

        <strong>
          Consenso ${
            data.consent_accepted
              ? "acquisito"
              : "non acquisito"
          }
        </strong>

      </div>

      ${
        data.consent_name
          ? `
            <div class="small">
              Sottoscritto da
              <strong>
                ${escapeHtml(
                  data.consent_name
                )}
              </strong>
            </div>
          `
          : ""
      }

      ${
        data.consent_at
          ? `
            <div class="small text-muted mt-1">
              ${escapeHtml(
                fmtDate(
                  data.consent_at
                )
              )}
            </div>
          `
          : ""
      }
    `;


    loading.classList.add(
      "d-none"
    );

    content.classList.remove(
      "d-none"
    );


  }
  catch(err){

    loading.classList.add(
      "d-none"
    );

    error.textContent =
      err.message
      || "Impossibile caricare la pre-visita.";

    error.classList.remove(
      "d-none"
    );

  }

}

/* /CUP_PREVISIT_DETAIL_UI_V1 */


/* ============================================================
   OMNIA_PHONE_ISLAND_CONTROLLER_V2

   Phone Island V3 = UI
   phone.ai.basidiai.it = motore SIP
   ============================================================ */

(function(){

  if(
    window.__omniaPhoneIslandControllerV2
  ){
    return;
  }

  window.__omniaPhoneIslandControllerV2 =
    true;


  function omniaPhoneFrame(){

    const frame =
      document.getElementById(
        "cup-phone-frame"
      );

    if(
      !frame ||
      !frame.contentWindow
    ){
      return null;
    }

    return frame;
  }


  function omniaPhoneCommand(
    type,
    payload={}
  ){

    const frame =
      omniaPhoneFrame();

    if(!frame){

      console.error(
        "[OMNIA PHONE] iframe WebPhone non disponibile"
      );

      return false;
    }

    frame.contentWindow.postMessage(
      {
        type,
        ...payload
      },
      "https://phone.ai.basidiai.it"
    );

    return true;
  }


  function normalizeNumber(value){

    return String(value || "")
      .trim()
      .replace(/[^0-9+*#]/g, "");

  }


  /*
   * API pubblica definitiva.
   */
  window.OmniaPhone = {

    call(number){

      const dest =
        normalizeNumber(number);

      if(!dest)
        return false;

      /*
       * Non bloccare qui in base allo stato SIP
       * memorizzato dal frontend.
       *
       * Il WebPhone possiede il Registerer SIP reale
       * ed è l'unica fonte autorevole.
       */
      return omniaPhoneCommand(
        "OMNIA_PHONE_CALL",
        {
          number: dest
        }
      );
    },


    hangup(){

      return omniaPhoneCommand(
        "OMNIA_PHONE_HANGUP"
      );
    },


    mute(){

      return omniaPhoneCommand(
        "OMNIA_PHONE_MUTE"
      );
    },


    hold(){

      return omniaPhoneCommand(
        "OMNIA_PHONE_HOLD"
      );
    },


    answer(){

      return omniaPhoneCommand(
        "OMNIA_PHONE_ANSWER"
      );
    },


    reject(){

      return omniaPhoneCommand(
        "OMNIA_PHONE_REJECT"
      );
    }

  };


  /*
   * Intercetta ESCLUSIVAMENTE i controlli
   * presenti dentro Phone Island V3.
   *
   * Non vengono più cercati/pilotati
   * controlli legacy fuori dall'isola.
   */
  document.addEventListener(
    "click",
    event => {

      const island =
        event.target.closest(
          ".cup-phone-island-v3"
        );

      if(!island)
        return;


      const button =
        event.target.closest(
          "button"
        );

      if(!button)
        return;


      const text =
        String(
          button.textContent || ""
        )
        .trim()
        .toLowerCase();


      /*
       * CHIAMA
       *
       * Handler unico Phone Island.
       * Usa lo stesso OMNIA_PHONE_CALL che
       * sappiamo funzionare nei test manuali.
       */
      if(
        button.dataset.islandAction === "call"
        ||
        text === "chiama"
      ){

        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();

        const input =
          island.querySelector(
            ".cup-phone-island-number"
          );

        const number =
          normalizeNumber(
            input?.value
          );

        console.log(
          "[OMNIA PHONE] UI CALL",
          number
        );

        if(!number){

          input?.focus();

          return;
        }


        const result =
          window.OmniaPhone.call(
            number
          );


        console.log(
          "[OMNIA PHONE] UI CALL SENT",
          result
        );

        return;
      }


      /*
       * TERMINA
       */
      if(
        button.classList.contains(
          "cup-phone-island-end-button"
        )
        ||
        text.includes("termina")
        ||
        text.includes("riaggancia")
      ){

        event.preventDefault();
        event.stopImmediatePropagation();

        window.OmniaPhone.hangup();

        return;
      }


      /*
       * MUTE
       */
      if(
        text === "mute"
        ||
        text === "riattiva"
      ){

        event.preventDefault();
        event.stopImmediatePropagation();

        window.OmniaPhone.mute();

        return;
      }


      /*
       * HOLD
       */
      if(
        text === "hold"
        ||
        text === "riprendi"
        ||
        text.includes("hold")
        ||
        text.includes("riprendi")
      ){

        event.preventDefault();
        event.stopImmediatePropagation();

        /*
         * OMNIA HOLD FEEDBACK:
         * conserviamo il pulsante REALE intercettato
         * dal controller.
         */
        window.__omniaHoldButton = button;

        const activatingHold =
          text === "hold";

        button.disabled = true;

        button.textContent =
          activatingHold
            ? "Attivazione..."
            : "Ripresa...";

        button.setAttribute(
          "aria-busy",
          "true"
        );

        window.OmniaPhone.hold();

        return;
      }


      /*
       * RISPOSTA
       */
      if(text === "rispondi"){

        event.preventDefault();
        event.stopImmediatePropagation();

        window.OmniaPhone.answer();

        return;
      }


      /*
       * RIFIUTA
       */
      if(text === "rifiuta"){

        event.preventDefault();
        event.stopImmediatePropagation();

        window.OmniaPhone.reject();

        return;
      }

    },

    true
  );


  /*
   * Manteniamo compatibilità con eventuale
   * codice esistente che usa CupPhoneIsland.call().
   */
  const timer =
    setInterval(
      ()=>{

        if(!window.CupPhoneIsland)
          return;

        if(
          !window.CupPhoneIsland.call
          ||
          !window.CupPhoneIsland.call
            .__omniaV2
        ){

          const call =
            number =>
              window.OmniaPhone
                .call(number);

          call.__omniaV2 = true;

          window.CupPhoneIsland.call =
            call;
        }

        clearInterval(timer);

      },
      250
    );

})();

/* /OMNIA_PHONE_ISLAND_CONTROLLER_V2 */







/* ============================================================
   OMNIA_PHONE_INCOMING_UI_V1

   WebPhone = motore SIP
   Phone Island = UI operatore + Scheda
   ============================================================ */

(function(){

  if(window.__omniaPhoneIncomingUiV1)
    return;

  window.__omniaPhoneIncomingUiV1 = true;

  let currentNumber = "";
  let currentState = "idle";

  /* OMNIA_PHONE_AUTHORITATIVE_STATE_V8 */
  window.OmniaPhoneUiState = "idle";
  window.OmniaPhoneActiveSince = null;

  function publishOmniaPhoneState(state){
    window.OmniaPhoneUiState = state;

    if(state === "active"){
      if(!window.OmniaPhoneActiveSince){
        window.OmniaPhoneActiveSince = Date.now();
      }
    }

    if(state === "idle"){
      window.OmniaPhoneActiveSince = null;
    }

    window.dispatchEvent(
      new CustomEvent(
        "omnia-phone-state",
        {
          detail:{
            state,
            activeSince:
              window.OmniaPhoneActiveSince
          }
        }
      )
    );
  }
  /* /OMNIA_PHONE_AUTHORITATIVE_STATE_V8 */


  function island(){
    return document.querySelector(
      ".cup-phone-island-v3"
    );
  }


  function phoneCommand(type){

    const frame =
      document.getElementById(
        "cup-phone-frame"
      );

    if(!frame?.contentWindow)
      return false;

    frame.contentWindow.postMessage(
      { type },
      "https://phone.ai.basidiai.it"
    );

    return true;
  }


  function ensureIncomingControls(){

    const root = island();

    if(!root)
      return null;

    let controls =
      root.querySelector(
        ".cup-phone-island-incoming-actions"
      );

    if(controls)
      return controls;

    controls =
      document.createElement("div");

    controls.className =
      "cup-phone-island-incoming-actions";

    controls.innerHTML = `
      <div class="cup-phone-island-incoming-label">
        CHIAMATA IN ARRIVO
      </div>

      <div class="cup-phone-island-incoming-number">
      </div>

      <div class="cup-phone-island-incoming-buttons">

        <button
          type="button"
          class="cup-phone-island-answer"
          data-island-action="answer">
          <i class="bi bi-telephone-fill"></i>
          Rispondi
        </button>

        <button
          type="button"
          class="cup-phone-island-reject"
          data-island-action="reject">
          <i class="bi bi-telephone-x-fill"></i>
          Rifiuta
        </button>

      </div>
    `;

    const content =
      root.querySelector(
        ".cup-phone-island-content"
      );

    if(content){
      content.insertBefore(
        controls,
        content.firstChild
      );
    }

    return controls;
  }


  function showIncoming(number){

    currentState = "incoming";
    publishOmniaPhoneState("incoming");
    currentNumber = String(number || "");

    const root = island();
    if(!root) return;

    const controls =
      ensureIncomingControls();

    controls?.classList.add("visible");

    const numberEl =
      controls?.querySelector(
        ".cup-phone-island-incoming-number"
      );

    if(numberEl)
      numberEl.textContent =
        currentNumber || "Numero sconosciuto";

    root.classList.add(
      "expanded",
      "island-incoming"
    );

    root.classList.remove(
      "island-idle",
      "island-active"
    );

    const title =
      root.querySelector(
        ".cup-phone-island-title"
      );

    const subtitle =
      root.querySelector(
        ".cup-phone-island-subtitle"
      );

    if(title)
      title.textContent =
        "Chiamata in arrivo";

    if(subtitle)
      subtitle.textContent =
        currentNumber || "Numero sconosciuto";


    /*
     * La scheda paziente resta dentro
     * la stessa Phone Island.
     *
     * Se la logica CUP l'ha già popolata
     * non la tocchiamo.
     */
    const patient =
      root.querySelector(
        ".cup-phone-island-patient"
      );

    if(patient)
      patient.style.display = "";
  }


  function showConnected(number){

    currentState = "active";
    publishOmniaPhoneState("active");

    const root = island();
    if(!root) return;

    const controls =
      ensureIncomingControls();

    controls?.classList.remove("visible");

    root.classList.remove(
      "island-incoming",
      "island-idle"
    );

    root.classList.add(
      "expanded",
      "island-active"
    );

    const title =
      root.querySelector(
        ".cup-phone-island-title"
      );

    const subtitle =
      root.querySelector(
        ".cup-phone-island-subtitle"
      );

    if(title)
      title.textContent =
        "In chiamata";

    if(subtitle)
      subtitle.textContent =
        String(number || currentNumber || "");

    /*
     * Aggiunge Termina se non esiste.
     */
    let end =
      root.querySelector(
        '[data-island-action="hangup"]'
      );

    if(!end){

      end = document.createElement(
        "button"
      );

      end.type = "button";
      end.className =
        "cup-phone-island-primary cup-phone-island-end-button";

      end.dataset.islandAction =
        "hangup";

      end.innerHTML =
        '<i class="bi bi-telephone-x-fill me-1"></i> Termina';

      const tools =
        root.querySelector(
          ".cup-phone-island-tools"
        );

      tools?.before(end);
    }

    end.style.display = "";
  }


  function showIdle(){

    currentState = "idle";
    publishOmniaPhoneState("idle");
    currentNumber = "";

    const root = island();
    if(!root) return;

    ensureIncomingControls()
      ?.classList.remove("visible");

    root.classList.remove(
      "island-incoming",
      "island-active"
    );

    root.classList.add(
      "island-idle"
    );

    const end =
      root.querySelector(
        '[data-island-action="hangup"]'
      );

    if(end)
      end.style.display = "none";

    const title =
      root.querySelector(
        ".cup-phone-island-title"
      );

    const subtitle =
      root.querySelector(
        ".cup-phone-island-subtitle"
      );

    if(title)
      title.textContent =
        "Telefono CUP";

    if(subtitle)
      subtitle.textContent =
        omniaSipRegisteredState === true
          ? "Registrato"
          : "Non registrato";
  }


  /*
   * Eventi REALI provenienti da SIP.js.
   */
  window.addEventListener(
    "message",
    event => {

      if(
        event.origin !==
        "https://phone.ai.basidiai.it"
      ){
        return;
      }

      if(
        event.data?.type !==
        "OMNIA_PHONE_EVENT"
      ){
        return;
      }

      const action =
        String(event.data?.event || "");

      console.log(
        "[OMNIA PHONE] EVENT",
        action,
        event.data
      );

      if(action === "incoming"){

        showIncoming(
          event.data?.number
        );

        return;
      }

      if(action === "established"){

        showConnected(
          event.data?.number
        );

        return;
      }

      if(
        action === "terminated"
        ||
        action === "rejected"
      ){

        showIdle();
        return;
      }

      if(action === "error"){

        console.error(
          "[OMNIA PHONE] SIP ERROR",
          event.data
        );
      }
    }
  );


  /*
   * Controlli Phone Island -> WebPhone.
   */
  document.addEventListener(
    "click",
    event => {

      const button =
        event.target.closest(
          ".cup-phone-island-v3 [data-island-action]"
        );

      if(!button)
        return;

      const action =
        button.dataset.islandAction;

      if(action === "answer"){

        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();

        button.disabled = true;

        const old =
          button.innerHTML;

        button.innerHTML =
          '<span class="spinner-border spinner-border-sm me-1"></span> Connessione...';

        phoneCommand(
          "OMNIA_PHONE_ANSWER"
        );

        setTimeout(()=>{
          if(currentState === "incoming"){
            button.disabled = false;
            button.innerHTML = old;
          }
        },5000);

        return;
      }


      if(action === "reject"){

        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();

        phoneCommand(
          "OMNIA_PHONE_REJECT"
        );

        return;
      }


      if(action === "hangup"){

        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();

        phoneCommand(
          "OMNIA_PHONE_HANGUP"
        );

        return;
      }

    },
    true
  );


  /*
   * La Phone Island viene costruita dinamicamente.
   */
  const observer =
    new MutationObserver(()=>{

      if(island()){
        ensureIncomingControls();
      }

    });

  observer.observe(
    document.body,
    {
      childList:true,
      subtree:true
    }
  );

})();

/* /OMNIA_PHONE_INCOMING_UI_V1 */





/* ============================================================
   OMNIA_PHONE_ISLAND_STATE_GUARD_V1

   Garantisce:
   - una sola Phone Island
   - answer/reject solo mentre squilla
   - tool solo in chiamata
   - vecchia Call Island sempre nascosta
   ============================================================ */

(function(){

  if(window.__omniaPhoneIslandStateGuardV1)
    return;

  window.__omniaPhoneIslandStateGuardV1 = true;


  function root(){

    return document.querySelector(
      ".cup-phone-island-v3"
    );
  }


  function hideLegacyCallIsland(){

    const legacy =
      document.getElementById(
        "cup-call-island"
      );

    if(legacy){

      legacy.classList.remove(
        "visible"
      );

      legacy.style.display =
        "none";
    }
  }


  function incomingBox(){

    return root()?.querySelector(
      ".cup-phone-island-incoming-actions"
    );
  }


  function resetAnswerButton(){

    const button =
      root()?.querySelector(
        '[data-island-action="answer"]'
      );

    if(!button)
      return;

    button.disabled = false;

    button.innerHTML =
      '<i class="bi bi-telephone-fill me-1"></i> Rispondi';
  }


  function applyState(state){

    const phone = root();

    if(!phone)
      return;

    phone.classList.remove(
      "island-incoming",
      "island-active"
    );

    if(state === "incoming"){

      phone.classList.add(
        "island-incoming",
        "expanded"
      );

    }else if(state === "active"){

      phone.classList.add(
        "island-active",
        "expanded"
      );

    }else{

      phone.classList.add(
        "island-idle"
      );

      incomingBox()
        ?.classList.remove(
          "visible"
        );

      resetAnswerButton();
    }
  }


  hideLegacyCallIsland();


  /*
   * La vecchia Call Island può essere ricreata
   * dinamicamente dagli eventi /api/calls/ws.
   * La neutralizziamo anche in quel caso.
   */
  const observer =
    new MutationObserver(
      hideLegacyCallIsland
    );

  observer.observe(
    document.body,
    {
      childList:true,
      subtree:true
    }
  );


  window.addEventListener(
    "message",
    event => {

      if(
        event.origin !==
        "https://phone.ai.basidiai.it"
      )
        return;

      if(
        event.data?.type !==
        "OMNIA_PHONE_EVENT"
      )
        return;

      const state =
        String(
          event.data?.event || ""
        );


      if(state === "incoming"){

        applyState(
          "incoming"
        );

        return;
      }


      if(state === "established"){

        applyState(
          "active"
        );

        return;
      }


      if(
        state === "terminated"
        ||
        state === "rejected"
        ||
        state === "error"
      ){

        applyState(
          "idle"
        );
      }

    }
  );


  console.log(
    "[OMNIA PHONE] Single Phone Island UI attiva"
  );

})();

/* /OMNIA_PHONE_ISLAND_STATE_GUARD_V1 */



/* ============================================================
   OMNIA_PHONE_PATIENT_LINK_V1

   Numero chiamante -> identità CUP -> Scheda paziente
   ============================================================ */

(function(){

  if(window.__omniaPhonePatientLinkV1)
    return;

  window.__omniaPhonePatientLinkV1 = true;


  let currentPatientId = null;
  let currentCallerNumber = "";
  let resolveSequence = 0;


  function phoneIsland(){

    return document.querySelector(
      ".cup-phone-island-v3"
    );
  }


  function patientBox(){

    return phoneIsland()?.querySelector(
      ".cup-phone-island-patient"
    );
  }


  function patientName(){

    return phoneIsland()?.querySelector(
      ".cup-phone-island-patient-name"
    );
  }


  function patientButton(){

    return phoneIsland()?.querySelector(
      '[data-island-action="patient"]'
    );
  }


  function resetPatient(){

    currentPatientId = null;

    const box =
      patientBox();

    const name =
      patientName();

    const button =
      patientButton();


    if(box){

      delete box.dataset.patientId;

      box.classList.remove(
        "has-patient"
      );
    }


    if(name){

      name.textContent =
        "Ricerca paziente...";
    }


    if(button){

      button.disabled = true;

      button.textContent =
        "Apri";
    }
  }


  function setPatientFound(patient){

    const id =
      Number(
        patient?.patient_id || 0
      );


    if(!id){
      setPatientNotFound();
      return;
    }


    currentPatientId = id;


    const box =
      patientBox();

    const name =
      patientName();

    const button =
      patientButton();


    if(box){

      box.dataset.patientId =
        String(id);

      box.classList.add(
        "has-patient"
      );
    }


    if(name){

      name.textContent =
        patient?.full_name ||
        `Paziente #${id}`;
    }


    if(button){

      button.disabled = false;

      button.textContent =
        "Apri";
    }


    console.log(
      "[OMNIA PHONE] paziente identificato",
      {
        patientId:id,
        name:patient?.full_name,
        phone:patient?.phone
      }
    );
  }


  function setPatientNotFound(){

    currentPatientId = null;


    const box =
      patientBox();

    const name =
      patientName();

    const button =
      patientButton();


    if(box){

      delete box.dataset.patientId;

      box.classList.remove(
        "has-patient"
      );
    }


    if(name){

      name.textContent =
        "Paziente non riconosciuto";
    }


    if(button){

      button.disabled = true;

      button.textContent =
        "Apri";
    }
  }


  async function resolveCallerPatient(
    rawNumber
  ){

    const number =
      String(rawNumber || "")
        .trim();


    if(!number)
      return;


    currentCallerNumber =
      number;


    const sequence =
      ++resolveSequence;


    resetPatient();


    console.log(
      "[OMNIA PHONE] ricerca paziente",
      number
    );


    try{

      const response =
        await fetch(
          "/api/patient-identity/resolve",
          {
            method:"POST",

            credentials:
              "same-origin",

            headers:{
              ...(
                typeof patientApiHeaders ===
                "function"
                  ? patientApiHeaders()
                  : {}
              ),

              "Accept":
                "application/json",

              "Content-Type":
                "application/json"
            },

            body:
              JSON.stringify({
                phone:number,
                source:"operator_phone",
                create_if_missing:false
              })
          }
        );


      if(!response.ok){

        throw new Error(
          `Identity HTTP ${response.status}`
        );
      }


      const data =
        await response.json();


      /*
       * Se nel frattempo è arrivata
       * un'altra chiamata ignoriamo
       * la risposta precedente.
       */
      if(sequence !== resolveSequence)
        return;


      console.log(
        "[OMNIA PHONE] identity result",
        data
      );


      if(
        data?.status === "matched"
        &&
        data?.patient?.patient_id
      ){

        setPatientFound(
          data.patient
        );

        return;
      }


      setPatientNotFound();

    }
    catch(error){

      if(sequence !== resolveSequence)
        return;


      console.error(
        "[OMNIA PHONE] ricerca paziente fallita",
        error
      );


      setPatientNotFound();
    }
  }


  /*
   * Il numero reale arriva dal WebPhone
   * quando SIP.js riceve l'INVITE.
   */
  window.addEventListener(
    "message",
    event => {

      if(
        event.origin !==
        "https://phone.ai.basidiai.it"
      ){
        return;
      }


      if(
        event.data?.type !==
        "OMNIA_PHONE_EVENT"
      ){
        return;
      }


      const action =
        String(
          event.data?.event || ""
        );


      if(action === "incoming"){

        resolveCallerPatient(
          event.data?.number
        );

        return;
      }


      /*
       * Manteniamo la scheda durante
       * la conversazione.
       */
      if(action === "established"){

        if(
          !currentPatientId
          &&
          event.data?.number
        ){
          resolveCallerPatient(
            event.data.number
          );
        }

        return;
      }


      if(
        action === "terminated"
        ||
        action === "rejected"
      ){

        currentCallerNumber = "";

        resolveSequence++;

        /*
         * Non azzeriamo immediatamente
         * il nome per evitare flash visivi.
         * Al prossimo incoming verrà resettato.
         */
      }

    }
  );


  /*
   * APRI SCHEDA
   */
  document.addEventListener(
    "click",
    async event => {

      const button =
        event.target.closest(
          '.cup-phone-island-v3 '
          +'[data-island-action="patient"]'
        );


      if(!button)
        return;


      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();


      const box =
        button.closest(
          ".cup-phone-island-patient"
        );


      const patientId =
        Number(
          box?.dataset.patientId
          ||
          currentPatientId
          ||
          0
        );


      if(!patientId){

        console.warn(
          "[OMNIA PHONE] nessun paziente associato",
          currentCallerNumber
        );

        return;
      }


      if(
        typeof openPatientDetail !==
        "function"
      ){

        console.error(
          "[OMNIA PHONE] openPatientDetail non disponibile"
        );

        return;
      }


      try{

        console.log(
          "[OMNIA PHONE] apertura scheda paziente",
          patientId
        );


        if(
          typeof window.OmniaPatientCardOpen ===
          "function"
        ){
          await window.OmniaPatientCardOpen(
            patientId
          );
        }else{
        if(
          typeof window.OmniaPatientCardOpen ===
          "function"
        ){
          await window.OmniaPatientCardOpen(
            patientId
          );
        }else{
          console.error(
            "[OMNIA PHONE] Patient Card non disponibile"
          );

          if(typeof showToast === "function"){
            showToast(
              "Scheda paziente non disponibile.",
              "error"
            );
          }

          return;
        }
        }

      }
      catch(error){

        console.error(
          "[OMNIA PHONE] apertura scheda fallita",
          error
        );


        if(
          typeof showToast ===
          "function"
        ){

          showToast(
            error?.message ||
            "Impossibile aprire la scheda paziente.",
            "error"
          );
        }
      }

    },

    /*
     * Capture per intercettare il click
     * prima dei controller legacy.
     */
    true
  );


  console.log(
    "[OMNIA PHONE] Patient Link V1 attivo"
  );

})();

/* /OMNIA_PHONE_PATIENT_LINK_V1 */



/* ============================================================
   OMNIA_PATIENT_360_UI_V1
   ============================================================ */

(function(){

  if(window.__omniaPatient360UiV1)
    return;

  window.__omniaPatient360UiV1 = true;


  function esc(value){

    if(typeof escapeHtml === "function")
      return escapeHtml(
        String(value ?? "")
      );

    const el =
      document.createElement("div");

    el.textContent =
      String(value ?? "");

    return el.innerHTML;
  }


  function dateTime(value){

    if(!value)
      return "—";

    if(typeof fmtDate === "function")
      return fmtDate(value);

    try{
      return new Date(value)
        .toLocaleString("it-IT");
    }catch(_){
      return String(value);
    }
  }


  function ensure360(){

    /*
     * Usiamo esclusivamente la modale paziente
     * attiva e il suo form reale.
     */
    const modal =
      document.getElementById(
        "patient-editor-modal"
      );

    if(!modal){
      console.error(
        "[CUP 360] patient-editor-modal non trovata"
      );
      return null;
    }


    const form =
      modal.querySelector(
        "#patient-editor-form"
      );

    if(!form){
      console.error(
        "[CUP 360] patient-editor-form non trovato"
      );
      return null;
    }


    /*
     * Se esiste già, lo riutilizziamo.
     */
    let root =
      modal.querySelector(
        "#omnia-patient-360"
      );

    if(root){

      root.style.display =
        "block";

      return root;
    }


    root =
      document.createElement(
        "section"
      );

    root.id =
      "omnia-patient-360";

    root.className =
      "omnia-patient-360-visible";


    root.innerHTML = `

      <div class="omnia-p360-head">

        <div>

          <div class="omnia-p360-eyebrow">
            SCHEDA PAZIENTE
          </div>

          <strong>
            Percorso completo
          </strong>

        </div>

        <div
          class="omnia-p360-summary"
          id="omnia-p360-summary">
        </div>

      </div>


      <div
        class="omnia-p360-tabs"
        role="tablist">

        <button
          type="button"
          class="active"
          data-p360-tab="bookings">

          <i class="bi bi-calendar3"></i>

          Prenotazioni

          <span
            class="omnia-p360-count"
            data-p360-count="bookings">
            0
          </span>

        </button>


        <button
          type="button"
          data-p360-tab="chat">

          <i class="bi bi-chat-left-text"></i>

          Conversazioni

          <span
            class="omnia-p360-count"
            data-p360-count="chat">
            0
          </span>

        </button>


        <button
          type="button"
          data-p360-tab="record">

          <i class="bi bi-folder2-open"></i>

          Cartella

          <span
            class="omnia-p360-count"
            data-p360-count="record">
            0
          </span>

        </button>

      </div>


      <div
        class="omnia-p360-panel"
        data-p360-panel="bookings">
      </div>


      <div
        class="omnia-p360-panel d-none"
        data-p360-panel="chat">
      </div>


      <div
        class="omnia-p360-panel d-none"
        data-p360-panel="record">
      </div>

    `;


    /*
     * Punto di inserimento deterministico:
     *
     * FORM
     *   modal-body     <- anagrafica
     *   PATIENT 360    <- qui
     *   modal-footer
     */

    const footer =
      form.querySelector(
        ".modal-footer"
      );


    if(footer){

      form.insertBefore(
        root,
        footer
      );

    }else{

      form.appendChild(
        root
      );
    }


    /*
     * Forziamo la visibilità.
     * Questo evita eventuali regole CSS legacy.
     */

    root.style.display =
      "block";

    root.style.visibility =
      "visible";

    root.style.opacity =
      "1";


    console.log(
      "[CUP 360] UI inserita",
      {
        modal:
          modal.id,

        form:
          form.id,

        parent:
          root.parentElement?.id ||
          root.parentElement?.className
      }
    );


    return root;
  }

  function renderBookings(
    root,
    bookings
  ){

    const panel =
      root.querySelector(
        '[data-p360-panel="bookings"]'
      );

    root.querySelector(
      '[data-p360-count="bookings"]'
    ).textContent =
      bookings.length;


    if(!bookings.length){

      panel.innerHTML = `
        <div class="omnia-p360-empty">
          <i class="bi bi-calendar2"></i>
          Nessuna prenotazione presente.
        </div>
      `;

      return;
    }


    const now =
      new Date();


    panel.innerHTML =
      bookings.map(booking=>{

        const when =
          booking.scheduled_at
            ? new Date(
                booking.scheduled_at
              )
            : null;

        const future =
          when &&
          !Number.isNaN(
            when.getTime()
          ) &&
          when >= now;


        return `

          <button
            type="button"
            class="omnia-p360-booking"
            data-booking-id="${Number(
              booking.id
            )}">

            <span
              class="omnia-p360-booking-date">

              <i class="bi bi-calendar-event"></i>

              ${esc(
                dateTime(
                  booking.scheduled_at
                )
              )}

            </span>

            <span
              class="omnia-p360-booking-main">

              <strong>
                ${esc(
                  booking.service_name ||
                  "Prestazione"
                )}
              </strong>

              <small>
                ${future
                  ? "Prossimo appuntamento"
                  : "Storico"}
                ·
                ${esc(
                  booking.status || "—"
                )}
              </small>

            </span>

            <i
              class="bi bi-chevron-right">
            </i>

          </button>

        `;

      }).join("");
  }


  function renderChat(
    root,
    conversations
  ){

    const panel =
      root.querySelector(
        '[data-p360-panel="chat"]'
      );


    root.querySelector(
      '[data-p360-count="chat"]'
    ).textContent =
      conversations.length;


    if(!conversations.length){

      panel.innerHTML = `
        <div class="omnia-p360-empty">
          <i class="bi bi-chat-left"></i>
          Nessuna conversazione associata.
        </div>
      `;

      return;
    }


    panel.innerHTML =
      conversations.map(session=>{

        const messages =
          Array.isArray(
            session.messages
          )
            ? session.messages
            : [];


        const last =
          messages.length
            ? messages[
                messages.length - 1
              ]
            : null;


        return `

          <details
            class="omnia-p360-chat">

            <summary>

              <span
                class="omnia-p360-channel">

                <i class="bi ${
                  session.channel === "phone"
                    ? "bi-telephone"
                    : session.channel === "whatsapp"
                    ? "bi-whatsapp"
                    : session.channel === "telegram"
                    ? "bi-telegram"
                    : "bi-chat-dots"
                }"></i>

                ${esc(
                  session.channel ||
                  "web"
                )}

              </span>


              <span
                class="omnia-p360-chat-preview">

                <strong>
                  ${esc(
                    last?.content ||
                    "Conversazione"
                  )}
                </strong>

                <small>
                  ${esc(
                    dateTime(
                      session.updated_at ||
                      session.created_at
                    )
                  )}
                </small>

              </span>


              <i
                class="bi bi-chevron-down">
              </i>

            </summary>


            <div
              class="omnia-p360-messages">

              ${messages.length
                ? messages.map(message=>`

                    <div
                      class="omnia-p360-message ${
                        message.role === "user"
                          ? "from-patient"
                          : "from-cup"
                      }">

                      <div>
                        ${esc(
                          message.content
                        )}
                      </div>

                      <small>
                        ${esc(
                          message.role
                        )}
                        ·
                        ${esc(
                          dateTime(
                            message.created_at
                          )
                        )}
                      </small>

                    </div>

                  `).join("")
                : `
                  <div class="omnia-p360-empty">
                    Nessun messaggio.
                  </div>
                `
              }

            </div>

          </details>

        `;

      }).join("");
  }


  function renderRecord(
    root,
    patient,
    documents
  ){

    const panel =
      root.querySelector(
        '[data-p360-panel="record"]'
      );


    root.querySelector(
      '[data-p360-count="record"]'
    ).textContent =
      documents.length;


    const notes =
      String(
        patient?.notes || ""
      ).trim();


    panel.innerHTML = `

      <div class="omnia-p360-record-notes">

        <div class="omnia-p360-section-title">

          <i class="bi bi-journal-medical"></i>
          Note paziente

        </div>

        <div class="${
          notes
            ? ""
            : "text-muted"
        }">

          ${notes
            ? esc(notes)
            : "Nessuna nota presente."}

        </div>

      </div>


      <div class="omnia-p360-section-title mt-3">

        <i class="bi bi-file-earmark-medical"></i>
        Documenti e referti

      </div>


      ${documents.length
        ? `
          <div class="omnia-p360-documents">

            ${documents.map(document=>`

              <div
                class="omnia-p360-document">

                <span
                  class="omnia-p360-document-icon">
                  <i class="bi bi-file-earmark-text"></i>
                </span>

                <span
                  class="omnia-p360-document-main">

                  <strong>
                    ${esc(
                      document.title ||
                      document.filename ||
                      "Documento"
                    )}
                  </strong>

                  <small>
                    ${esc(
                      document.category ||
                      "documento"
                    )}
                    ·
                    ${esc(
                      dateTime(
                        document.created_at
                      )
                    )}
                  </small>

                </span>

                <span
                  class="badge bg-light text-dark border">

                  ${esc(
                    document.status ||
                    "available"
                  )}

                </span>

              </div>

            `).join("")}

          </div>
        `
        : `
          <div class="omnia-p360-empty">
            <i class="bi bi-folder2-open"></i>
            Nessun documento presente.
          </div>
        `
      }

    `;
  }


  async function load360(
    patientId
  ){

    const root =
      ensure360();

    if(!root)
      return;


    root.classList.add(
      "is-loading"
    );


    root.querySelectorAll(
      ".omnia-p360-panel"
    )
    .forEach(panel=>{

      panel.innerHTML = `
        <div class="omnia-p360-loading">
          <span
            class="spinner-border spinner-border-sm">
          </span>
          Caricamento...
        </div>
      `;

    });


    try{

      const data =
        await patientFetchJson(
          `/api/patients/${patientId}/overview`
        );


      const bookings =
        Array.isArray(data.bookings)
          ? data.bookings
          : [];


      const conversations =
        Array.isArray(
          data.conversations
        )
          ? data.conversations
          : [];


      const documents =
        Array.isArray(data.documents)
          ? data.documents
          : [];


      root.querySelector(
        "#omnia-p360-summary"
      ).textContent =
        `${bookings.length} prenotazioni · `
        +`${conversations.length} conversazioni · `
        +`${documents.length} documenti`;


      renderBookings(
        root,
        bookings
      );


      renderChat(
        root,
        conversations
      );


      renderRecord(
        root,
        data.patient || {},
        documents
      );


    }catch(error){

      console.error(
        "[CUP] Patient 360",
        error
      );


      root.querySelectorAll(
        ".omnia-p360-panel"
      )
      .forEach(panel=>{

        panel.innerHTML = `
          <div class="alert alert-danger py-2 small">
            ${esc(
              error?.message ||
              "Impossibile caricare la scheda completa."
            )}
          </div>
        `;

      });

    }finally{

      root.classList.remove(
        "is-loading"
      );
    }
  }



  /*
   * API pubblica per integrazione con
   * la modale paziente esistente.
   */
  window.OmniaPatient360Load = load360;


  /*
   * TAB
   */

  document.addEventListener(
    "click",
    event=>{

      const button =
        event.target.closest(
          "#omnia-patient-360 [data-p360-tab]"
        );


      if(!button)
        return;


      const root =
        button.closest(
          "#omnia-patient-360"
        );


      const tab =
        button.dataset.p360Tab;


      root.querySelectorAll(
        "[data-p360-tab]"
      )
      .forEach(x=>
        x.classList.toggle(
          "active",
          x === button
        )
      );


      root.querySelectorAll(
        "[data-p360-panel]"
      )
      .forEach(panel=>
        panel.classList.toggle(
          "d-none",
          panel.dataset.p360Panel
            !== tab
        )
      );

    }
  );


  /*
   * Apertura prenotazione.
   */

  document.addEventListener(
    "click",
    async event=>{

      const item =
        event.target.closest(
          "#omnia-patient-360 [data-booking-id]"
        );


      if(!item)
        return;


      const id =
        Number(
          item.dataset.bookingId
        );


      if(
        !id ||
        typeof openBookingEditor !==
          "function"
      )
        return;


      try{

        await openBookingEditor(
          id
        );

      }catch(error){

        console.error(
          "[CUP] apertura prenotazione Patient 360",
          error
        );
      }

    }
  );


  /*
   * Agganciamo la funzione già esistente.
   */

  const originalOpenPatientDetail =
    window.openPatientDetail;


  if(
    typeof originalOpenPatientDetail ===
    "function"
  ){

    window.openPatientDetail =
      async function(patientId){

        const result =
          await originalOpenPatientDetail(
            patientId
          );


        await load360(
          Number(patientId)
        );


        return result;
      };

  }


  console.log(
    "[CUP] Patient 360 UI V1 attiva"
  );

})();

/* /OMNIA_PATIENT_360_UI_V1 */



/* ============================================================
   OMNIA_PATIENT_OPEN_FINAL_V1
   Override definitivo pulsante Apri Phone Island
   ============================================================ */

(function(){

  if(window.__omniaPatientOpenFinalV1)
    return;

  window.__omniaPatientOpenFinalV1 = true;


  document.addEventListener(
    "click",
    async event => {

      const button =
        event.target.closest(
          '.cup-phone-island-v3 '
          +'[data-island-action="patient"]'
        );

      if(!button)
        return;


      /*
       * Blocchiamo QUALSIASI vecchio handler.
       */
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();


      const patientBox =
        button.closest(
          ".cup-phone-island-patient"
        );


      const patientId =
        Number(
          patientBox?.dataset.patientId || 0
        );


      console.log(
        "[OMNIA PHONE] APRI SCHEDA FINAL",
        patientId
      );


      if(!patientId){

        console.warn(
          "[OMNIA PHONE] patient_id assente"
        );

        if(typeof showToast === "function"){
          showToast(
            "Paziente non identificato.",
            "warning"
          );
        }

        return;
      }


      if(
        typeof window.OmniaPatientCardOpen !==
        "function"
      ){

        console.error(
          "[OMNIA PHONE] OmniaPatientCardOpen non disponibile"
        );

        if(typeof showToast === "function"){
          showToast(
            "Scheda paziente non disponibile.",
            "error"
          );
        }

        return;
      }


      try{

        await window.OmniaPatientCardOpen(
          patientId
        );

      }catch(error){

        console.error(
          "[OMNIA PHONE] apertura Patient Card",
          error
        );

        if(typeof showToast === "function"){
          showToast(
            error?.message ||
            "Impossibile aprire la scheda paziente.",
            "error"
          );
        }
      }

    },

    /*
     * Capture = vero:
     * questo handler viene eseguito PRIMA
     * dei vecchi listener della Phone Island.
     */
    true
  );


  console.log(
    "[OMNIA PHONE] Patient Open Final V1 attivo"
  );

})();

/* /OMNIA_PATIENT_OPEN_FINAL_V1 */



/* ============================================================
   OMNIA_PATIENT_CARD_MODAL_V2
   Scheda Paziente dedicata
   ============================================================ */

(function(){

  if(window.__omniaPatientCardModalV2)
    return;

  window.__omniaPatientCardModalV2 = true;


  function h(value){

    const el = document.createElement("div");

    el.textContent =
      String(value ?? "");

    return el.innerHTML;
  }


  function dt(value){

    if(!value)
      return "—";

    try{

      return new Date(value)
        .toLocaleString("it-IT", {
          dateStyle: "short",
          timeStyle: "short"
        });

    }catch(_){

      return String(value);
    }
  }


  function ensurePatientCard(){

    let modal =
      document.getElementById(
        "omnia-patient-card-modal"
      );


    if(modal)
      return modal;


    modal =
      document.createElement("div");

    modal.id =
      "omnia-patient-card-modal";

    modal.className =
      "modal fade";

    modal.tabIndex = -1;


    modal.innerHTML = `

      <div
        class="modal-dialog modal-xl modal-dialog-scrollable">

        <div class="modal-content">


          <div class="modal-header">

            <div>

              <div
                style="
                  font-size:10px;
                  font-weight:800;
                  letter-spacing:.08em;
                  color:#2563eb;
                ">
                SCHEDA PAZIENTE
              </div>

              <h5
                class="modal-title mb-0"
                data-pcard-name>
                Paziente
              </h5>

              <div
                class="small text-muted"
                data-pcard-id>
              </div>

            </div>


            <button
              type="button"
              class="btn-close"
              data-bs-dismiss="modal"
              aria-label="Chiudi">
            </button>

          </div>


          <div class="modal-body">


            <div
              data-pcard-loading
              class="text-center py-5">

              <div
                class="spinner-border spinner-border-sm me-2">
              </div>

              Caricamento scheda paziente...

            </div>


            <div
              data-pcard-error
              class="alert alert-danger d-none">
            </div>


            <div
              data-pcard-content
              class="d-none">


              <div
                class="row g-2 mb-3"
                data-pcard-anagrafica>
              </div>


              <div
                class="nav nav-pills nav-fill gap-1 mb-3"
                role="tablist">

                <button
                  type="button"
                  class="nav-link active"
                  data-pcard-tab="bookings">

                  <i class="bi bi-calendar3 me-1"></i>
                  Prenotazioni

                  <span
                    class="badge text-bg-light ms-1"
                    data-pcard-count="bookings">
                    0
                  </span>

                </button>


                <button
                  type="button"
                  class="nav-link"
                  data-pcard-tab="chat">

                  <i class="bi bi-chat-left-text me-1"></i>
                  Conversazioni

                  <span
                    class="badge text-bg-light ms-1"
                    data-pcard-count="chat">
                    0
                  </span>

                </button>


                <button
                  type="button"
                  class="nav-link"
                  data-pcard-tab="record">

                  <i class="bi bi-folder2-open me-1"></i>
                  Cartella paziente

                  <span
                    class="badge text-bg-light ms-1"
                    data-pcard-count="record">
                    0
                  </span>

                </button>

                <button
                  type="button"
                  class="nav-link"
                  data-pcard-tab="relationships">
                  <i class="bi bi-people me-1"></i>
                  Contatti e delegati
                  <span
                    class="badge text-bg-light ms-1"
                    data-pcard-count="relationships">
                    0
                  </span>
                </button>

              </div>


              <div
                data-pcard-panel="bookings">
              </div>


              <div
                data-pcard-panel="chat"
                class="d-none">
              </div>


              <div
                data-pcard-panel="record"
                class="d-none">
              </div>

              <div
                data-pcard-panel="relationships"
                class="d-none">
              </div>


            </div>

          </div>


          <div class="modal-footer">

            <button
              type="button"
              class="btn btn-outline-primary me-auto"
              data-pcard-edit>

              <i class="bi bi-pencil me-1"></i>
              Modifica anagrafica

            </button>


            <button
              type="button"
              class="btn btn-secondary"
              data-bs-dismiss="modal">

              Chiudi

            </button>

          </div>


        </div>

      </div>

    `;


    if(!document.getElementById("omnia-relationship-edit-modal")){

      const relModal = document.createElement("div");

      relModal.id = "omnia-relationship-edit-modal";
      relModal.className = "modal fade";
      relModal.tabIndex = -1;
      relModal.style.zIndex = "1070";

      relModal.addEventListener("shown.bs.modal", () => {
        const backdrops =
          document.querySelectorAll(".modal-backdrop");

        const backdrop =
          backdrops[backdrops.length - 1];

        if(backdrop)
          backdrop.style.zIndex = "1065";
      });

      relModal.innerHTML = `
        <div class="modal-dialog">
          <form class="modal-content" id="omnia-relationship-edit-form">

            <div class="modal-header">
              <h5 class="modal-title">Modifica contatto/delegato</h5>
              <button
                type="button"
                class="btn-close"
                data-bs-dismiss="modal">
              </button>
            </div>

            <div class="modal-body">

              <input type="hidden" id="omnia-rel-id">

              <div class="mb-3">
                <label class="form-label">Nome</label>
                <input
                  class="form-control"
                  id="omnia-rel-name"
                  required>
              </div>

              <div class="mb-3">
                <label class="form-label">Cellulare</label>
                <input
                  class="form-control"
                  id="omnia-rel-phone"
                  type="tel">
              </div>

              <div class="mb-3">
                <label class="form-label">Relazione</label>
                <select
                  class="form-select"
                  id="omnia-rel-type">
                  <option value="daughter">Figlia</option>
                  <option value="son">Figlio</option>
                  <option value="spouse">Coniuge</option>
                  <option value="mother">Madre</option>
                  <option value="father">Padre</option>
                  <option value="sibling">Fratello / Sorella</option>
                  <option value="caregiver">Caregiver</option>
                  <option value="guardian">Tutore</option>
                  <option value="relative">Altro familiare</option>
                  <option value="other">Altro contatto</option>
                </select>
              </div>

              <div class="form-check mb-2">
                <input class="form-check-input" type="checkbox" id="omnia-rel-docreq">
                <label class="form-check-label" for="omnia-rel-docreq">
                  Riceve richieste documenti
                </label>
              </div>

              <div class="form-check mb-2">
                <input class="form-check-input" type="checkbox" id="omnia-rel-senddocs">
                <label class="form-check-label" for="omnia-rel-senddocs">
                  Può inviare documenti
                </label>
              </div>

              <div class="form-check mb-2">
                <input class="form-check-input" type="checkbox" id="omnia-rel-book">
                <label class="form-check-label" for="omnia-rel-book">
                  Può prenotare
                </label>
              </div>

              <div class="form-check mb-2">
                <input class="form-check-input" type="checkbox" id="omnia-rel-manage">
                <label class="form-check-label" for="omnia-rel-manage">
                  Gestisce prenotazioni
                </label>
              </div>

              <div class="form-check mb-2">
                <input class="form-check-input" type="checkbox" id="omnia-rel-reminders">
                <label class="form-check-label" for="omnia-rel-reminders">
                  Riceve promemoria
                </label>
              </div>

              <div class="form-check">
                <input class="form-check-input" type="checkbox" id="omnia-rel-primary">
                <label class="form-check-label" for="omnia-rel-primary">
                  Contatto principale
                </label>
              </div>

            </div>

            <div class="modal-footer">
              <button
                type="button"
                class="btn btn-secondary"
                data-bs-dismiss="modal">
                Annulla
              </button>

              <button
                type="submit"
                class="btn btn-primary">
                Salva
              </button>
            </div>

          </form>
        </div>
      `;

      document.body.appendChild(relModal);
    }

    document.body.appendChild(modal);

    return modal;
  }


  function infoBox(label, value){

    return `

      <div class="col-md-3 col-6">

        <div
          class="h-100 p-2 border rounded-3 bg-light">

          <div
            class="text-muted"
            style="font-size:10px">
            ${h(label)}
          </div>

          <div
            class="fw-semibold text-truncate"
            style="font-size:12px">
            ${h(value || "—")}
          </div>

        </div>

      </div>

    `;
  }


  function renderBookings(
    modal,
    bookings
  ){

    modal.querySelector(
      '[data-pcard-count="bookings"]'
    ).textContent =
      bookings.length;


    const panel =
      modal.querySelector(
        '[data-pcard-panel="bookings"]'
      );


    if(!bookings.length){

      panel.innerHTML = `
        <div
          class="text-center text-muted py-4">
          Nessuna prenotazione presente.
        </div>
      `;

      return;
    }


    panel.innerHTML =
      bookings.map(row => `

        <div
          class="
            d-flex
            align-items-center
            gap-3
            border
            rounded-3
            p-2
            mb-2
          ">

          <div
            class="
              d-flex
              align-items-center
              justify-content-center
              bg-light
              rounded-3
            "
            style="
              width:38px;
              height:38px;
              flex:0 0 38px;
            ">

            <i class="bi bi-calendar-event"></i>

          </div>


          <div class="flex-grow-1 min-w-0">

            <div class="fw-semibold">

              ${h(
                row.service_name ||
                "Prestazione"
              )}

            </div>

            <div class="small text-muted">

              ${h(dt(row.scheduled_at))}

            </div>

          </div>


          <span
            class="badge text-bg-light border">

            ${h(row.status || "—")}

          </span>

        </div>

      `).join("");
  }


  function renderChat(
    modal,
    conversations
  ){

    modal.querySelector(
      '[data-pcard-count="chat"]'
    ).textContent =
      conversations.length;


    const panel =
      modal.querySelector(
        '[data-pcard-panel="chat"]'
      );


    if(!conversations.length){

      panel.innerHTML = `
        <div
          class="text-center text-muted py-4">
          Nessuna conversazione associata.
        </div>
      `;

      return;
    }


    panel.innerHTML =
      conversations.map(session => {

        const messages =
          Array.isArray(session.messages)
            ? session.messages
            : [];


        return `

          <details
            class="border rounded-3 mb-2">

            <summary
              class="
                d-flex
                align-items-center
                justify-content-between
                gap-3
                p-3
              "
              style="cursor:pointer">

              <div>

                <div class="fw-semibold">

                  <i
                    class="bi bi-chat-dots me-1">
                  </i>

                  ${h(
                    session.channel ||
                    "Web"
                  )}

                </div>

                <div class="small text-muted">

                  ${h(
                    dt(
                      session.updated_at ||
                      session.created_at
                    )
                  )}

                </div>

              </div>


              <span
                class="badge text-bg-light">

                ${messages.length}
                messaggi

              </span>

            </summary>


            <div
              class="border-top bg-light p-2">

              ${
                messages.length
                  ? messages.map(message => `

                      <div
                        class="
                          bg-white
                          border
                          rounded-3
                          p-2
                          mb-2
                        ">

                        <div>
                          ${h(
                            message.content ||
                            ""
                          )}
                        </div>

                        <div
                          class="
                            small
                            text-muted
                            mt-1
                          ">

                          ${h(
                            message.role ||
                            ""
                          )}

                          ·

                          ${h(
                            dt(
                              message.created_at
                            )
                          )}

                        </div>

                      </div>

                    `).join("")

                  : `
                      <div
                        class="
                          text-muted
                          text-center
                          py-3
                        ">
                        Nessun messaggio.
                      </div>
                    `
              }

            </div>

          </details>

        `;

      }).join("");
  }


  function renderRecord(
    modal,
    patient,
    documents
  ){

    modal.querySelector(
      '[data-pcard-count="record"]'
    ).textContent =
      documents.length;


    const panel =
      modal.querySelector(
        '[data-pcard-panel="record"]'
      );


    const notes =
      String(
        patient.notes || ""
      ).trim();


    const docs =
      documents.length
        ? documents.map(doc => `

            <div
              class="
                d-flex
                align-items-center
                gap-3
                border
                rounded-3
                p-2
                mb-2
              ">

              <div
                class="
                  d-flex
                  align-items-center
                  justify-content-center
                  bg-light
                  rounded-3
                "
                style="
                  width:38px;
                  height:38px;
                ">

                <i
                  class="
                    bi
                    bi-file-earmark-medical
                  ">
                </i>

              </div>


              <div class="flex-grow-1">

                <div class="fw-semibold">

                  ${h(
                    doc.title ||
                    doc.filename ||
                    "Documento"
                  )}

                </div>

                <div class="small text-muted">

                  ${h(
                    doc.category ||
                    "Documento"
                  )}

                  ·

                  ${h(
                    dt(doc.created_at)
                  )}

                </div>

              </div>

            </div>

          `).join("")

        : `
            <div
              class="
                text-center
                text-muted
                py-4
              ">
              Nessun documento presente.
            </div>
          `;


    panel.innerHTML = `

      <div
        class="
          border
          rounded-3
          bg-light
          p-3
          mb-3
        ">

        <div class="fw-semibold mb-1">

          <i
            class="
              bi
              bi-journal-medical
              me-1
            ">
          </i>

          Note paziente

        </div>

        <div class="small">

          ${
            notes
              ? h(notes)
              : '<span class="text-muted">Nessuna nota presente.</span>'
          }

        </div>

      </div>


      <div class="fw-semibold mb-2">

        <i
          class="
            bi
            bi-folder2-open
            me-1
          ">
        </i>

        Documenti e referti

      </div>

      ${docs}

    `;
  }


  function renderRelationships(modal, rows){

    modal._relationships = rows;

    const panel =
      modal.querySelector(
        '[data-pcard-panel="relationships"]'
      );

    const count =
      modal.querySelector(
        '[data-pcard-count="relationships"]'
      );

    if(count)
      count.textContent = rows.length;

    const labels = {
      daughter:"Figlia",
      son:"Figlio",
      spouse:"Coniuge",
      mother:"Madre",
      father:"Padre",
      sibling:"Fratello / Sorella",
      caregiver:"Caregiver",
      guardian:"Tutore",
      relative:"Familiare",
      other:"Altro contatto"
    };

    panel.innerHTML = (rows.length
      ? rows.map(r=>`
          <div class="border rounded-3 p-3 mb-2">
            <div class="d-flex justify-content-between gap-3">
              <div>
                <div class="fw-semibold">
                  ${h(r.display_name || "Contatto")}
                </div>
                <div class="small text-muted">
                  ${h(labels[r.relationship_type] || r.relationship_type || "Contatto")}
                  · ${h(r.phone || r.email || "—")}
                </div>
              </div>
              ${r.is_primary ? '<span class="badge text-bg-primary">Principale</span>' : ''}
            </div>

            <div class="small mt-2">
              ${r.can_receive_document_requests ? "✓" : "○"} Richieste documenti
              · ${r.can_send_documents ? "✓" : "○"} Invio documenti
              · ${r.can_book ? "✓" : "○"} Prenotazioni
              · ${r.can_receive_reminders ? "✓" : "○"} Promemoria
            </div>

            <div class="d-flex gap-2 mt-3">
              <button
                type="button"
                class="btn btn-sm btn-outline-primary"
                data-rel-edit="${r.id}">
                Modifica
              </button>

              <button
                type="button"
                class="btn btn-sm btn-outline-danger"
                data-rel-disable="${r.id}">
                Disattiva
              </button>
            </div>
          </div>
        `).join("")
      : `<div class="text-muted p-3">Nessun contatto o delegato configurato.</div>`)
      + `
        <div class="mt-3">
          <button
            type="button"
            class="btn btn-primary"
            data-rel-add>
            <i class="bi bi-plus-lg me-1"></i>
            Aggiungi contatto/delegato
          </button>
        </div>
      `;
  }


  async function openPatientCard(
    patientId
  ){

    patientId =
      Number(patientId);


    if(!patientId)
      throw new Error(
        "ID paziente non valido"
      );


    const modal =
      ensurePatientCard();


    modal.dataset.patientId =
      String(patientId);


    const loading =
      modal.querySelector(
        "[data-pcard-loading]"
      );


    const content =
      modal.querySelector(
        "[data-pcard-content]"
      );


    const error =
      modal.querySelector(
        "[data-pcard-error]"
      );


    loading.classList.remove(
      "d-none"
    );

    content.classList.add(
      "d-none"
    );

    error.classList.add(
      "d-none"
    );


    bootstrap.Modal
      .getOrCreateInstance(modal)
      .show();


    try{

      const data =
        await patientFetchJson(
          `/api/patients/${patientId}/overview`
        );


      const relationshipsData =
        await patientFetchJson(
          `/api/patients/${patientId}/relationships`
        );

      const relationships =
        Array.isArray(relationshipsData)
          ? relationshipsData
          : [];


      const patient =
        data.patient || {};


      const bookings =
        Array.isArray(data.bookings)
          ? data.bookings
          : [];


      const conversations =
        Array.isArray(
          data.conversations
        )
          ? data.conversations
          : [];


      const documents =
        Array.isArray(data.documents)
          ? data.documents
          : [];


      modal.querySelector(
        "[data-pcard-name]"
      ).textContent =
        patient.full_name ||
        `Paziente #${patientId}`;


      modal.querySelector(
        "[data-pcard-id]"
      ).textContent =
        `Paziente #${patientId}`;


      modal.querySelector(
        "[data-pcard-anagrafica]"
      ).innerHTML =

        infoBox(
          "Telefono",
          patient.phone
        )

        +

        infoBox(
          "Email",
          patient.email
        )

        +

        infoBox(
          "Codice fiscale",
          patient.fiscal_code
        )

        +

        infoBox(
          "Data di nascita",
          patient.date_of_birth
        );


      renderBookings(
        modal,
        bookings
      );


      renderChat(
        modal,
        conversations
      );


      renderRecord(
        modal,
        patient,
        documents
      );


      renderRelationships(
        modal,
        relationships
      );




      loading.classList.add(
        "d-none"
      );

      content.classList.remove(
        "d-none"
      );


    }catch(ex){

      console.error(
        "[CUP] Patient Card V2",
        ex
      );


      loading.classList.add(
        "d-none"
      );


      error.textContent =
        ex?.message ||
        "Errore caricamento scheda paziente";


      error.classList.remove(
        "d-none"
      );
    }
  }


  /*
   * QUESTA È LA FUNZIONE CHE FINORA MANCAVA.
   */

  window.OmniaPatientCardOpen =
    openPatientCard;


  /*
   * TAB
   */

  document.addEventListener(
    "click",
    event => {

      const button =
        event.target.closest(
          "#omnia-patient-card-modal "
          +"[data-pcard-tab]"
        );


      if(!button)
        return;


      const modal =
        button.closest(
          "#omnia-patient-card-modal"
        );


      const selected =
        button.dataset.pcardTab;


      modal.querySelectorAll(
        "[data-pcard-tab]"
      ).forEach(item => {

        item.classList.toggle(
          "active",
          item === button
        );

      });


      modal.querySelectorAll(
        "[data-pcard-panel]"
      ).forEach(panel => {

        panel.classList.toggle(
          "d-none",
          panel.dataset.pcardPanel
            !== selected
        );

      });

    }
  );


  document.addEventListener(
    "click",
    async event => {

      const button =
        event.target.closest(
          "#omnia-patient-card-modal [data-rel-disable]"
        );

      if(!button)
        return;

      const modal =
        button.closest("#omnia-patient-card-modal");

      const patientId =
        Number(modal?.dataset.patientId || 0);

      const relationshipId =
        Number(button.dataset.relDisable || 0);

      if(!patientId)
        return;

      if(!confirm("Disattivare questo contatto/delegato?"))
        return;

      try{

        await patientFetchJson(
          `/api/patients/${patientId}/relationships/${relationshipId}`,
          {
            method:"PATCH",
            body:JSON.stringify({
              is_active:false
            })
          }
        );

        await window.OmniaPatientCardOpen(patientId);

      }catch(ex){

        showToast(
          ex?.message || "Errore disattivazione contatto",
          "error"
        );
      }

    }
  );


  document.addEventListener(
    "click",
    event => {

      const button =
        event.target.closest(
          "#omnia-patient-card-modal [data-rel-add]"
        );

      if(!button)
        return;

      document.getElementById("omnia-rel-id").value = "";
      document.getElementById("omnia-rel-name").value = "";
      document.getElementById("omnia-rel-phone").value = "";
      document.getElementById("omnia-rel-type").value = "other";

      document.getElementById("omnia-rel-docreq").checked = true;
      document.getElementById("omnia-rel-senddocs").checked = true;
      document.getElementById("omnia-rel-book").checked = false;
      document.getElementById("omnia-rel-manage").checked = false;
      document.getElementById("omnia-rel-reminders").checked = false;
      document.getElementById("omnia-rel-primary").checked = false;

      const title =
        document.querySelector(
          "#omnia-relationship-edit-modal .modal-title"
        );

      if(title)
        title.textContent = "Nuovo contatto/delegato";

      bootstrap.Modal
        .getOrCreateInstance(
          document.getElementById(
            "omnia-relationship-edit-modal"
          )
        )
        .show();

    }
  );


  document.addEventListener(
    "click",
    event => {

      const button =
        event.target.closest(
          "#omnia-patient-card-modal [data-rel-edit]"
        );

      if(!button)
        return;

      const modal =
        button.closest("#omnia-patient-card-modal");

      const relationshipId =
        Number(button.dataset.relEdit || 0);

      const rows =
        modal?._relationships || [];

      const row =
        rows.find(x => Number(x.id) === relationshipId);

      if(!row)
        return;

      document.getElementById("omnia-rel-id").value =
        String(row.id);

      document.getElementById("omnia-rel-name").value =
        row.display_name || "";

      document.getElementById("omnia-rel-phone").value =
        row.phone || "";

      document.getElementById("omnia-rel-type").value =
        row.relationship_type || "other";

      document.getElementById("omnia-rel-docreq").checked =
        Boolean(row.can_receive_document_requests);

      document.getElementById("omnia-rel-senddocs").checked =
        Boolean(row.can_send_documents);

      document.getElementById("omnia-rel-book").checked =
        Boolean(row.can_book);

      document.getElementById("omnia-rel-manage").checked =
        Boolean(row.can_manage_bookings);

      document.getElementById("omnia-rel-reminders").checked =
        Boolean(row.can_receive_reminders);

      document.getElementById("omnia-rel-primary").checked =
        Boolean(row.is_primary);

      const title =
        document.querySelector(
          "#omnia-relationship-edit-modal .modal-title"
        );

      if(title)
        title.textContent = "Modifica contatto/delegato";

      bootstrap.Modal
        .getOrCreateInstance(
          document.getElementById("omnia-relationship-edit-modal")
        )
        .show();

    }
  );


  document.addEventListener(
    "submit",
    async event => {

      if(event.target?.id !== "omnia-relationship-edit-form")
        return;

      event.preventDefault();

      const patientModal =
        document.getElementById("omnia-patient-card-modal");

      const patientId =
        Number(patientModal?.dataset.patientId || 0);

      const relationshipId =
        Number(
          document.getElementById("omnia-rel-id")?.value || 0
        );

      if(!patientId)
        return;

      const payload = {
        display_name:
          document.getElementById("omnia-rel-name")?.value || "",
        phone:
          document.getElementById("omnia-rel-phone")?.value || "",
        relationship_type:
          document.getElementById("omnia-rel-type")?.value || "other",
        can_receive_document_requests:
          Boolean(document.getElementById("omnia-rel-docreq")?.checked),
        can_send_documents:
          Boolean(document.getElementById("omnia-rel-senddocs")?.checked),
        can_book:
          Boolean(document.getElementById("omnia-rel-book")?.checked),
        can_manage_bookings:
          Boolean(document.getElementById("omnia-rel-manage")?.checked),
        can_receive_reminders:
          Boolean(document.getElementById("omnia-rel-reminders")?.checked),
        is_primary:
          Boolean(document.getElementById("omnia-rel-primary")?.checked)
      };

      try{

        const url = relationshipId
          ? `/api/patients/${patientId}/relationships/${relationshipId}`
          : `/api/patients/${patientId}/relationships`;

        const method = relationshipId
          ? "PATCH"
          : "POST";

        await patientFetchJson(
          url,
          {
            method,
            body:JSON.stringify(payload)
          }
        );

        bootstrap.Modal
          .getInstance(
            document.getElementById("omnia-relationship-edit-modal")
          )
          ?.hide();

        await window.OmniaPatientCardOpen(patientId);

      }catch(ex){

        showToast(
          ex?.message || "Errore salvataggio contatto",
          "error"
        );
      }

    }
  );


  /*
   * MODIFICA ANAGRAFICA
   */

  document.addEventListener(
    "click",
    event => {

      const button =
        event.target.closest(
          "#omnia-patient-card-modal "
          +"[data-pcard-edit]"
        );


      if(!button)
        return;


      const modal =
        button.closest(
          "#omnia-patient-card-modal"
        );


      const patientId =
        Number(
          modal.dataset.patientId || 0
        );


      if(!patientId)
        return;


      bootstrap.Modal
        .getInstance(modal)
        ?.hide();


      setTimeout(
        () => {

          openPatientDetail(
            patientId
          );

        },
        180
      );

    }
  );


  console.log(
    "[CUP] Patient Card Modal V2 attiva"
  );

})();

/* /OMNIA_PATIENT_CARD_MODAL_V2 */


















/* ============================================================
   OMNIA_VOICE_COUNTERS_FINAL_V1

   UNICA sorgente:
   /api/calls/voice-registry

   Backend autorevole:
   - live
   - started_at
   - ended_at
   - asterisk_linkedid
   ============================================================ */

(function(){

  if(window.__omniaVoiceCountersFinalV1)
    return;

  window.__omniaVoiceCountersFinalV1 =
    true;


  let busy = false;


  function el(id){

    return document.getElementById(id);
  }


  function setText(
    id,
    value
  ){

    const node = el(id);

    if(node){
      node.textContent =
        String(value);
    }
  }


  function localDateKey(){

    const now =
      new Date();

    const y =
      now.getFullYear();

    const m =
      String(
        now.getMonth() + 1
      ).padStart(2,"0");

    const d =
      String(
        now.getDate()
      ).padStart(2,"0");

    return `${y}-${m}-${d}`;
  }


  function dateKey(value){

    if(!value)
      return "";

    /*
     * L'API restituisce datetime ISO:
     *
     * 2026-08-30T18:53:41...
     *
     * Prendiamo direttamente la parte
     * YYYY-MM-DD, senza conversione Date().
     *
     * Evita qualsiasi problema UTC/CEST.
     */
    return String(value)
      .trim()
      .slice(0,10);
  }


  function callKey(call){

    return String(
      call?.asterisk_linkedid
      ||
      call?.linkedid
      ||
      call?.asterisk_uniqueid
      ||
      call?.call_id
      ||
      call?.id
      ||
      ""
    );
  }


  function uniqueLogicalCalls(rows){

    const map =
      new Map();


    for(const call of rows || []){

      const key =
        callKey(call);

      if(!key)
        continue;


      /*
       * voice-registry è già ordinato
       * dal record più recente.
       */
      if(!map.has(key)){
        map.set(
          key,
          call
        );
      }
    }


    return [
      ...map.values()
    ];
  }


  function isLive(call){

    /*
     * Usiamo il valore calcolato
     * direttamente dal backend.
     */
    return call?.live === true;
  }


  function updateVoiceBadge(count){

    const badge =
      el(
        "omnia-voice-live-badge"
      );


    if(!badge)
      return;


    const value =
      badge.querySelector(
        "strong"
      );


    if(value)
      value.textContent =
        String(count);


    badge.classList.toggle(
      "d-none",
      count === 0
    );
  }


  async function refresh(){

    if(busy)
      return;


    if(
      typeof CupApi === "undefined"
      ||
      !currentUser
    ){
      return;
    }


    if(
      currentUser.role !== "admin"
      &&
      currentUser.can_phone === false
    ){
      return;
    }


    busy = true;


    try{

      const response =
        await CupApi.request(
          "/calls/voice-registry?limit=500"
        );


      const rows =
        Array.isArray(
          response?.items
        )
          ? response.items
          : [];


      const calls =
        uniqueLogicalCalls(
          rows
        );


      const todayKey =
        localDateKey();


      const today =
        calls.filter(
          call =>
            dateKey(
              call?.started_at
            ) === todayKey
        );


      const live =
        calls.filter(
          isLive
        );


      const completedToday =
        today.filter(
          call =>
            call?.live !== true
        );


      /*
       * KPI PRINCIPALI
       */
      setText(
        "stat-calls-active",
        live.length
      );


      setText(
        "stat-calls-today",
        today.length
      );


      /*
       * KPI SECONDARI
       */
      setText(
        "stat-calls-live-mini",
        live.length
      );


      setText(
        "stat-calls-ended-mini",
        completedToday.length
      );


      /*
       * BADGE SIDEBAR
       */
      updateVoiceBadge(
        live.length
      );


      console.log(
        "[OMNIA VOICE FINAL]",
        {
          raw:
            rows.length,

          logical:
            calls.length,

          date:
            todayKey,

          today:
            today.length,

          live:
            live.length,

          completedToday:
            completedToday.length
        }
      );


    }catch(error){

      console.error(
        "[OMNIA VOICE FINAL]",
        error
      );

    }finally{

      busy = false;
    }
  }


  /*
   * Prima lettura.
   */
  setTimeout(
    refresh,
    500
  );


  /*
   * Polling autorevole.
   */
  const timer =
    setInterval(
      refresh,
      2000
    );


  /*
   * Eventi realtime chiamate CUP.
   */
  window.addEventListener(
    "cup-call-event",
    ()=>{
      setTimeout(
        refresh,
        100
      );
    }
  );


  /*
   * Eventi WebPhone.
   */
  window.addEventListener(
    "message",
    event=>{

      if(
        event.origin !==
        "https://phone.ai.basidiai.it"
      ){
        return;
      }


      if(
        event.data?.type ===
        "OMNIA_PHONE_EVENT"
      ){
        setTimeout(
          refresh,
          100
        );
      }

    }
  );


  window.OmniaVoiceCounters = {

    refresh,

    destroy(){
      clearInterval(timer);
    }

  };


  console.log(
    "[OMNIA] Voice Counters FINAL V1 attivo"
  );

})();

/* /OMNIA_VOICE_COUNTERS_FINAL_V1 */


/* ============================================================
   OMNIA_OUTBOUND_RECONCILE_CLIENT_V1
   ============================================================ */

(function(){

  if(
    window.__OMNIA_OUTBOUND_RECONCILE_V1__
  )
    return;

  window.__OMNIA_OUTBOUND_RECONCILE_V1__ =
    true;


  async function reconcileOutbound(
    number,
    attempt = 0
  ){

    const destination =
      String(number || "")
      .trim()
      .replace(/[^\d+]/g, "");


    if(!destination)
      return;


    try{

      const result =
        await CupApi.request(
          "/calls/operator-outbound",
          {
            method: "POST",
            body: JSON.stringify({
              destination
            })
          }
        );


      console.log(
        "[OMNIA OUTBOUND RECONCILE]",
        attempt,
        result
      );


      /*
       * L'evento SIP outgoing precede normalmente
       * il Newchannel AMI di qualche centinaio
       * di millisecondi.
       */
      if(
        result?.pending === true
        &&
        attempt < 6
      ){

        const delays = [
          300,
          600,
          1000,
          1600,
          2500,
          4000,
          6000
        ];


        window.setTimeout(
          ()=>{
            reconcileOutbound(
              destination,
              attempt + 1
            );
          },
          delays[attempt] || 1500
        );
      }


    }catch(error){

      console.warn(
        "[OMNIA OUTBOUND RECONCILE] errore",
        error
      );


      if(attempt < 4){

        window.setTimeout(
          ()=>{
            reconcileOutbound(
              destination,
              attempt + 1
            );
          },
          1000
        );
      }
    }
  }


  window.addEventListener(
    "message",
    event => {

      if(
        event.origin !==
        "https://phone.ai.basidiai.it"
      )
        return;


      if(
        event.data?.type !==
        "OMNIA_PHONE_EVENT"
      )
        return;


      const action =
        String(
          event.data?.event || ""
        ).toLowerCase();


      if(action !== "outgoing")
        return;


      const number =
        event.data?.number;


      console.log(
        "[OMNIA OUTBOUND RECONCILE] outgoing",
        number
      );


      /*
       * Prima richiesta quasi immediata.
       * Le successive vengono gestite dal retry
       * se AMI non ha ancora creato la Call.
       */
      window.setTimeout(
        ()=>{
          reconcileOutbound(
            number,
            0
          );
        },
        150
      );
    }
  );


  console.log(
    "[OMNIA] Outbound Reconcile Client V1 attivo"
  );

})();

/* /OMNIA_OUTBOUND_RECONCILE_CLIENT_V1 */






/* ============================================================
   OMNIA_CHAT_COUNTERS_FINAL_V1
   ============================================================ */

(function(){

  if(window.__omniaChatCountersFinalV1)
    return;

  window.__omniaChatCountersFinalV1 = true;

  let busy = false;


  function setText(id,value){

    const el =
      document.getElementById(id);

    if(el)
      el.textContent =
        String(value);
  }


  function localDateKey(){

    const now =
      new Date();

    return [
      now.getFullYear(),
      String(
        now.getMonth()+1
      ).padStart(2,"0"),
      String(
        now.getDate()
      ).padStart(2,"0")
    ].join("-");
  }


  function dateKey(value){

    if(!value)
      return "";

    return String(value)
      .trim()
      .slice(0,10);
  }


  function isDigital(session){

    const channel =
      String(
        session?.channel || ""
      )
      .trim()
      .toLowerCase();

    return ![
      "phone",
      "voice",
      "voice_ai",
      "telephone"
    ].includes(channel);
  }


  function isLive(session){

    const status =
      String(
        session?.status || ""
      )
      .trim()
      .toLowerCase();


    /*
     * Nel CUP:
     *
     * bot     = conversazione gestita dall'AI
     * handoff = conversazione presa/in attesa operatore
     * closed  = conclusa
     *
     * Quindi NON basta verificare che non sia closed.
     */
    if(status !== "handoff")
      return false;


    /*
     * Una vecchia sessione handoff può rimanere
     * aperta nel DB anche se non c'è più attività.
     *
     * Per il badge LIVE consideriamo soltanto
     * attività aggiornata negli ultimi 10 minuti.
     */
    const raw =
      session?.updated_at
      ||
      session?.created_at;


    if(!raw)
      return false;


    let value =
      String(raw).trim();


    /*
     * I DateTime PostgreSQL possono arrivare senza
     * timezone. In quel caso sono UTC nel progetto.
     */
    if(
      !/(?:Z|[+-]\\d{2}:?\\d{2})$/i
        .test(value)
    ){
      value += "Z";
    }


    const updated =
      new Date(value);


    if(Number.isNaN(updated.getTime()))
      return false;


    const ageMs =
      Date.now()
      -
      updated.getTime();


    const LIVE_WINDOW_MS =
      10 * 60 * 1000;


    return (
      ageMs >= 0
      &&
      ageMs <= LIVE_WINDOW_MS
    );
  }


  function updateBadge(count){

    const badge =
      document.getElementById(
        "omnia-chat-live-badge"
      );

    if(!badge)
      return;


    const value =
      badge.querySelector(
        "strong"
      );

    if(value)
      value.textContent =
        String(count);


    badge.classList.toggle(
      "d-none",
      count === 0
    );
  }


  async function refresh(){

    if(busy)
      return;

    if(
      typeof CupApi === "undefined"
      ||
      !currentUser
    ){
      return;
    }


    if(
      currentUser.role !== "admin"
      &&
      currentUser.can_chat === false
    ){
      return;
    }


    busy = true;


    try{

      const sessions =
        await CupApi.getChatSessions();


      const rows =
        Array.isArray(sessions)
          ? sessions
          : [];


      const digital =
        rows.filter(
          isDigital
        );


      const todayKey =
        localDateKey();


      const today =
        digital.filter(
          session =>
            dateKey(
              session?.created_at
              ||
              session?.updated_at
            ) === todayKey
        );


      const live =
        digital.filter(
          isLive
        );


      setText(
        "stat-chat-today",
        today.length
      );


      setText(
        "stat-chat-active-mini",
        live.length
      );


      updateBadge(
        live.length
      );


      console.log(
        "[OMNIA CHAT FINAL]",
        {
          total:
            digital.length,

          today:
            today.length,

          live:
            live.length
        }
      );


    }catch(error){

      console.error(
        "[OMNIA CHAT FINAL]",
        error
      );

    }finally{

      busy = false;
    }
  }


  setTimeout(
    refresh,
    700
  );


  setInterval(
    refresh,
    3000
  );


  window.OmniaChatCounters = {
    refresh
  };


  console.log(
    "[OMNIA] Chat Counters FINAL V1 attivo"
  );

})();

/* /OMNIA_CHAT_COUNTERS_FINAL_V1 */








/* OMNIA_HOLD_DIRECT_BRIDGE_V1 */

(function(){

  function installHoldBridge(){

    if(
      !window.OmniaPhone ||
      typeof window.OmniaPhone !== "object"
    ){
      setTimeout(
        installHoldBridge,
        250
      );

      return;
    }


    window.OmniaPhone.hold =
      function(){

        const frame =
          document.getElementById(
            "cup-phone-frame"
          );


        if(
          !frame ||
          !frame.contentWindow
        ){

          console.error(
            "[OMNIA PHONE] HOLD iframe non disponibile"
          );

          return false;
        }


        console.log(
          "[OMNIA PHONE] UI HOLD TOGGLE"
        );


        frame.contentWindow.postMessage(
          {
            type:
              "OMNIA_PHONE_HOLD_TOGGLE_V1"
          },
          "https://phone.ai.basidiai.it"
        );


        return true;
      };


    console.log(
      "[OMNIA PHONE] HOLD direct bridge ready"
    );
  }


  installHoldBridge();

})();

/* /OMNIA_HOLD_DIRECT_BRIDGE_V1 */

/* OMNIA_HOLD_UI_STATE_V1 */

(function(){

  window.addEventListener(
    "message",
    event => {

      if(
        event.origin !==
        "https://phone.ai.basidiai.it"
      ){
        return;
      }

      if(
        event.data?.type !==
        "OMNIA_PHONE_HOLD_STATE"
      ){
        return;
      }

      const held =
        event.data.held === true;

      const buttons =
        document.querySelectorAll(
          ".cup-phone-island button"
        );

      buttons.forEach(button => {

        const text =
          String(
            button.textContent || ""
          )
          .trim()
          .toLowerCase();

        if(
          text === "hold" ||
          text === "riprendi"
        ){

          button.textContent =
            held
              ? "Riprendi"
              : "Hold";

          button.classList.toggle(
            "is-active",
            held
          );

          button.setAttribute(
            "aria-pressed",
            held
              ? "true"
              : "false"
          );

          button.title =
            held
              ? "Chiamata in attesa - premi per riprendere"
              : "Metti la chiamata in attesa";
        }
      });

      const phone =
        document.querySelector(
          ".cup-phone-island"
        );

      if(phone){

        phone.classList.toggle(
          "is-hold",
          held
        );
      }

      console.log(
        "[OMNIA PHONE] UI HOLD STATE",
        held
      );

    }
  );

})();

/* /OMNIA_HOLD_UI_STATE_V1 */


/* OMNIA_HOLD_UI_STATE_V2 */

(function(){

  function findHoldButton(){

    const buttons =
      document.querySelectorAll(
        ".cup-phone-island button"
      );

    for(const button of buttons){

      const text =
        String(
          button.textContent || ""
        )
        .trim()
        .toLowerCase();

      if(
        text === "hold" ||
        text === "riprendi"
      ){
        return button;
      }
    }

    return null;
  }


  function updateHoldUI(held){

    const button =
      findHoldButton();

    if(button){

      button.textContent =
        held
          ? "Riprendi"
          : "Hold";

      button.classList.toggle(
        "is-active",
        held
      );

      button.setAttribute(
        "aria-pressed",
        held
          ? "true"
          : "false"
      );

      button.title =
        held
          ? "Chiamata in attesa - premi per riprendere"
          : "Metti la chiamata in attesa";
    }


    const phone =
      document.querySelector(
        ".cup-phone-island"
      );

    if(phone){

      phone.classList.toggle(
        "is-hold",
        held
      );
    }


    /*
     * Cerca il testo di stato della Phone Island.
     * Supporta più versioni del layout.
     */
    const selectors = [
      ".cup-phone-island-status",
      ".cup-phone-status",
      "[data-phone-status]",
      ".phone-status"
    ];

    let status = null;

    for(const selector of selectors){

      status =
        document.querySelector(
          selector
        );

      if(status)
        break;
    }


    if(status){

      if(held){

        if(
          !status.dataset
            .omniaBeforeHold
        ){
          status.dataset
            .omniaBeforeHold =
              status.textContent || "";
        }

        status.textContent =
          "Chiamata in attesa";

        status.classList.add(
          "is-hold"
        );

      }else{

        const previous =
          status.dataset
            .omniaBeforeHold;

        if(previous){

          status.textContent =
            previous;

          delete status.dataset
            .omniaBeforeHold;
        }

        status.classList.remove(
          "is-hold"
        );
      }
    }


    console.log(
      "[OMNIA PHONE] UI HOLD STATE",
      held
    );
  }


  window.addEventListener(
    "message",
    event => {

      if(
        event.origin !==
        "https://phone.ai.basidiai.it"
      ){
        return;
      }


      if(
        event.data?.type !==
        "OMNIA_PHONE_HOLD_STATE"
      ){
        return;
      }


      updateHoldUI(
        event.data.held === true
      );
    }
  );


  /*
   * Reset visuale automatico
   * quando una chiamata termina.
   */
  window.addEventListener(
    "message",
    event => {

      if(
        event.origin !==
        "https://phone.ai.basidiai.it"
      ){
        return;
      }


      if(
        event.data?.type !==
        "OMNIA_PHONE_EVENT"
      ){
        return;
      }


      const ev =
        String(
          event.data.event || ""
        ).toLowerCase();


      if(
        ev === "hangup" ||
        ev === "ended" ||
        ev === "terminated" ||
        ev === "idle"
      ){
        updateHoldUI(false);
      }
    }
  );


  window.OmniaUpdateHoldUI =
    updateHoldUI;

})();

/* /OMNIA_HOLD_UI_STATE_V2 */





/* OMNIA_HOLD_FEEDBACK_V4 */

(function(){

  function getHoldButton(){

    if(
      window.__omniaHoldButton &&
      document.contains(
        window.__omniaHoldButton
      )
    ){
      return window.__omniaHoldButton;
    }

    return Array.from(
      document.querySelectorAll("button")
    ).find(button => {

      const text =
        String(
          button.textContent || ""
        )
        .trim()
        .toLowerCase();

      return (
        text.includes("hold") ||
        text.includes("riprendi") ||
        text.includes("attivazione") ||
        text.includes("ripresa")
      );
    }) || null;
  }


  function renderHoldState(held){

    const button =
      getHoldButton();

    if(!button){
      console.warn(
        "[OMNIA PHONE] pulsante Hold non trovato"
      );
      return;
    }

    button.disabled = false;

    button.removeAttribute(
      "aria-busy"
    );

    button.setAttribute(
      "aria-pressed",
      held ? "true" : "false"
    );

    /*
     * IMPORTANTE:
     * testo semplice per essere compatibile
     * con il controller esistente.
     */
    button.textContent =
      held
        ? "Riprendi"
        : "Hold";


    /*
     * Feedback grafico discreto.
     */
    if(held){

      button.style.fontWeight =
        "600";

      button.style.boxShadow =
        "inset 0 0 0 1px currentColor";

      button.style.opacity =
        "1";

      button.title =
        "Chiamata in attesa - premi per riprendere";

    }else{

      button.style.fontWeight = "";
      button.style.boxShadow = "";
      button.style.opacity = "";

      button.title =
        "Metti la chiamata in attesa";
    }


    /*
     * Rimuove eventuale badge invasivo
     * creato dalla V3.
     */
    const badge =
      document.getElementById(
        "omnia-hold-badge"
      );

    if(badge){
      badge.remove();
    }


    console.log(
      "[OMNIA PHONE] HOLD UI",
      held
        ? "IN ATTESA"
        : "ATTIVA"
    );
  }


  window.addEventListener(
    "message",
    event => {

      if(
        event.origin !==
        "https://phone.ai.basidiai.it"
      ){
        return;
      }


      if(
        event.data?.type ===
        "OMNIA_PHONE_HOLD_STATE"
      ){

        renderHoldState(
          event.data.held === true
        );

        return;
      }


      if(
        event.data?.type ===
        "OMNIA_PHONE_EVENT"
      ){

        const ev =
          String(
            event.data.event || ""
          ).toLowerCase();

        if(
          ev === "hangup" ||
          ev === "ended" ||
          ev === "terminated" ||
          ev === "idle"
        ){
          renderHoldState(false);
        }
      }
    }
  );


  window.OmniaRenderHoldState =
    renderHoldState;

  console.log(
    "[OMNIA PHONE] HOLD feedback V4 ready"
  );

})();

/* /OMNIA_HOLD_FEEDBACK_V4 */



/* ============================================================
   OMNIA_CONSOLE_PHONE_BRIDGE_V3
   Bridge UI -> WebPhone esistente
   ============================================================ */

window.OmniaConsolePhone = {

  available(){
    return !!window.OmniaPhone;
  },

  answer(){
    if(window.OmniaPhone?.answer)
      return window.OmniaPhone.answer();
  },

  reject(){
    if(window.OmniaPhone?.reject)
      return window.OmniaPhone.reject();
  },

  hangup(){
    if(window.OmniaPhone?.hangup)
      return window.OmniaPhone.hangup();
  },

  hold(){
    if(window.OmniaPhone?.hold)
      return window.OmniaPhone.hold();
  },

  mute(){
    if(window.OmniaPhone?.mute)
      return window.OmniaPhone.mute();
  },

  call(number){
    if(window.OmniaPhone?.call)
      return window.OmniaPhone.call(number);
  }

};

console.info(
  "[OMNIA CONSOLE] Phone bridge V3 attivo"
);

/* /OMNIA_CONSOLE_PHONE_BRIDGE_V3 */



/* ============================================================
   OMNIA_CONSOLE_INTEGRATED_V4

   Integra Omnia Console nella stessa finestra che possiede
   window.OmniaPhone.

   NON crea una seconda registrazione SIP.
   ============================================================ */

(function(){

  const MARKER_ID =
    "omnia-console-workspace-v4";


  function createWorkspace(){

    let root =
      document.getElementById(
        MARKER_ID
      );

    if(root)
      return root;


    root =
      document.createElement("div");

    root.id =
      MARKER_ID;

    root.style.cssText = `
      position:fixed;
      inset:0;
      z-index:99990;
      background:#f5f7fa;
      display:none;
      flex-direction:column;
    `;


    root.innerHTML = `
      <div
        style="
          height:52px;
          flex:0 0 52px;
          background:#ffffff;
          border-bottom:1px solid #e4e8ee;
          display:flex;
          align-items:center;
          justify-content:space-between;
          padding:0 14px 0 18px;
          font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
        "
      >

        <div
          style="
            display:flex;
            align-items:center;
            gap:10px;
          "
        >
          <div
            style="
              width:30px;
              height:30px;
              border-radius:9px;
              background:#111827;
              color:white;
              display:grid;
              place-items:center;
              font-weight:800;
            "
          >O</div>

          <div>
            <div
              style="
                font-size:14px;
                font-weight:750;
                color:#18212f;
              "
            >
              Omnia Console
            </div>

            <div
              style="
                font-size:11px;
                color:#697586;
              "
            >
              Postazione operatore
            </div>
          </div>
        </div>


        <button
          id="omnia-console-close-v4"
          type="button"
          title="Chiudi Omnia Console"
          style="
            border:1px solid #d6dce5;
            background:#fff;
            border-radius:9px;
            min-width:38px;
            height:34px;
            cursor:pointer;
            font-size:18px;
          "
        >
          ×
        </button>

      </div>


      <iframe
        id="omnia-console-frame-v4"
        src="/omnia-console.html?embedded=1"
        title="Omnia Console"
        style="
          flex:1 1 auto;
          width:100%;
          border:0;
          background:#f5f7fa;
        "
      ></iframe>
    `;


    document.body.appendChild(
      root
    );


    root
      .querySelector(
        "#omnia-console-close-v4"
      )
      ?.addEventListener(
        "click",
        ()=>{
          root.style.display =
            "none";
        }
      );


    return root;
  }


  function openConsole(){

    const root =
      createWorkspace();

    root.style.display =
      "flex";


    /*
     * Ricarichiamo i dati della console,
     * non il WebPhone.
     */
    const frame =
      document.getElementById(
        "omnia-console-frame-v4"
      );

    try{
      frame?.contentWindow
        ?.postMessage(
          {
            type:
              "OMNIA_CONSOLE_REFRESH"
          },
          window.location.origin
        );
    }catch(e){}
  }


  function closeConsole(){

    const root =
      document.getElementById(
        MARKER_ID
      );

    if(root)
      root.style.display =
        "none";
  }


  window.OmniaConsole = {
    open:openConsole,
    close:closeConsole,
  };


  function installLauncher(){

    if(
      document.getElementById(
        "omnia-console-launcher-v4"
      )
    )
      return;


    const callsTab =
      document.querySelector(
        '[data-tab="calls"]'
      );


    const button =
      document.createElement(
        "button"
      );

    button.id =
      "omnia-console-launcher-v4";

    button.type =
      "button";

    button.textContent =
      "Omnia Console";


    if(callsTab){

      /*
       * Mantiene il linguaggio grafico
       * della navigazione esistente.
       */
      button.className =
        callsTab.className || "";

      button.style.marginLeft =
        "4px";

      callsTab.insertAdjacentElement(
        "afterend",
        button
      );

    }else{

      /*
       * Fallback solamente se la nav
       * non fosse ancora disponibile.
       */
      button.style.cssText = `
        position:fixed;
        right:18px;
        bottom:18px;
        z-index:9000;
        padding:10px 14px;
        border:0;
        border-radius:10px;
        background:#111827;
        color:white;
        font-weight:700;
        cursor:pointer;
        box-shadow:0 8px 28px rgba(15,23,42,.18);
      `;

      document.body.appendChild(
        button
      );
    }


    button.addEventListener(
      "click",
      event=>{

        event.preventDefault();
        event.stopPropagation();

        openConsole();
      }
    );
  }


  /*
   * La sidebar può essere costruita dopo
   * il bootstrap dell'app.
   */
  installLauncher();

  window.setTimeout(
    installLauncher,
    1000
  );

  window.setTimeout(
    installLauncher,
    3000
  );


  document.addEventListener(
    "keydown",
    event=>{

      if(
        event.key==="Escape" &&
        document.getElementById(
          MARKER_ID
        )?.style.display==="flex"
      ){
        closeConsole();
      }
    }
  );


  console.info(
    "[OMNIA CONSOLE] Integrated Workspace V4 attivo"
  );

})();

/* /OMNIA_CONSOLE_INTEGRATED_V4 */



/* ============================================================
   OMNIA_CONSOLE_NATIVE_WORKSPACE_V5

   Console nativa nell'area centrale dell'app.
   Il WebPhone/SIP esistente resta unico.
   ============================================================ */

(function(){

  const ROOT_ID =
    "omnia-native-console-v5";

  const NAV_ID =
    "omnia-native-console-nav-v5";


  function hideOldOverlay(){

    const old =
      document.getElementById(
        "omnia-console-workspace-v4"
      );

    if(old)
      old.style.display = "none";


    const oldLauncher =
      document.getElementById(
        "omnia-console-launcher-v4"
      );

    if(oldLauncher)
      oldLauncher.style.display = "none";
  }


  function findMainArea(){

    /*
     * Cerchiamo prima i contenitori tipici.
     */
    const selectors = [
      "main",
      ".main-content",
      "#main-content",
      ".content-area",
      "#content-area",
      ".page-content",
      "#page-content",
      ".content-wrapper"
    ];


    for(const selector of selectors){

      const el =
        document.querySelector(
          selector
        );

      if(
        el &&
        el.offsetWidth > 500 &&
        el.offsetHeight > 300
      )
        return el;
    }


    /*
     * Fallback:
     * usiamo il pannello attualmente
     * associato a Conversazioni.
     */
    const chatTab =
      document.querySelector(
        '[data-tab="chatbot"]'
      );

    if(chatTab){

      const target =
        chatTab.getAttribute(
          "data-target"
        ) ||
        chatTab.getAttribute(
          "href"
        );

      if(
        target &&
        target.startsWith("#")
      ){

        const el =
          document.querySelector(
            target
          );

        if(el)
          return el.parentElement || el;
      }
    }


    return null;
  }


  function ensureWorkspace(){

    let root =
      document.getElementById(
        ROOT_ID
      );

    if(root)
      return root;


    root =
      document.createElement(
        "section"
      );

    root.id =
      ROOT_ID;

    root.style.cssText = `
      display:none;
      width:100%;
      height:calc(100vh - 92px);
      min-height:600px;
      background:#f5f7fa;
      overflow:hidden;
    `;


    root.innerHTML = `
      <iframe
        id="omnia-native-console-frame-v5"
        src="/omnia-console.html?embedded=1&native=1&v=20260902-noflicker2"
        title="Omnia Console"
        style="
          width:100%;
          height:100%;
          border:0;
          display:block;
          background:#f5f7fa;
        "
      ></iframe>
    `;


    const main =
      findMainArea();


    if(main){

      /*
       * La inseriamo come sibling delle viste
       * applicative, senza distruggere DOM
       * o listener esistenti.
       */
      main.appendChild(
        root
      );

    }else{

      /*
       * Fallback sicuro.
       */
      root.style.position =
        "fixed";

      root.style.left =
        "280px";

      root.style.right =
        "0";

      root.style.top =
        "92px";

      root.style.bottom =
        "0";

      root.style.height =
        "auto";

      root.style.zIndex =
        "8000";

      document.body.appendChild(
        root
      );
    }


    return root;
  }


  function applicationViews(){

    const root =
      document.getElementById(
        ROOT_ID
      );

    if(!root)
      return [];


    const parent =
      root.parentElement;

    if(!parent)
      return [];


    return Array.from(
      parent.children
    ).filter(
      el =>
        el !== root &&
        el.tagName !== "SCRIPT"
    );
  }


  function openNativeConsole(){

    hideOldOverlay();

    const root =
      ensureWorkspace();


    /*
     * Nascondiamo solamente le viste sorelle.
     * Le conserviamo intatte nel DOM.
     */
    applicationViews()
      .forEach(el=>{

        if(
          el.dataset
            .omniaV5Display ===
          undefined
        ){

          el.dataset
            .omniaV5Display =
            el.style.display || "";
        }

        el.style.display =
          "none";
      });


    root.style.display =
      "block";


    document
      .querySelectorAll(
        "[data-tab]"
      )
      .forEach(el=>
        el.classList.remove(
          "active"
        )
      );


    document
      .getElementById(
        NAV_ID
      )
      ?.classList.add(
        "active"
      );


    const frame =
      document.getElementById(
        "omnia-native-console-frame-v5"
      );


    try{

      frame?.contentWindow
        ?.postMessage(
          {
            type:
              "OMNIA_CONSOLE_REFRESH"
          },
          window.location.origin
        );

    }catch(e){}
  }


  function closeNativeConsole(){

    const root =
      document.getElementById(
        ROOT_ID
      );

    if(!root)
      return;


    root.style.display =
      "none";


    applicationViews()
      .forEach(el=>{

        el.style.display =
          el.dataset
            .omniaV5Display || "";

        delete el.dataset
          .omniaV5Display;
      });
  }


  function installNativeNav(){

    hideOldOverlay();


    if(
      document.getElementById(
        NAV_ID
      )
    )
      return;


    /*
     * Usiamo Conversazioni come riferimento
     * grafico e strutturale.
     */
    const reference =
      document.querySelector(
        '[data-tab="chatbot"]'
      ) ||
      document.querySelector(
        '[data-tab="calls"]'
      );


    if(!reference)
      return;


    const nav =
      reference.cloneNode(
        true
      );


    nav.id =
      NAV_ID;


    /*
     * Evitiamo che il router precedente
     * interpreti questo elemento come
     * una vecchia tab.
     */
    nav.removeAttribute(
      "data-tab"
    );

    nav.removeAttribute(
      "data-target"
    );

    nav.removeAttribute(
      "href"
    );


    /*
     * Sostituiamo solo i nodi testuali,
     * mantenendo icona/stile esistenti.
     */
    const walker =
      document.createTreeWalker(
        nav,
        NodeFilter.SHOW_TEXT
      );


    let node;

    while(
      node = walker.nextNode()
    ){

      const value =
        node.nodeValue?.trim();

      if(value){
        node.nodeValue =
          node.nodeValue.replace(
            value,
            "Omnia Console"
          );

        break;
      }
    }


    nav.classList.remove(
      "active"
    );


    nav.addEventListener(
      "click",
      event=>{

        event.preventDefault();
        event.stopImmediatePropagation();

        openNativeConsole();
      },
      true
    );


    /*
     * La nuova Console prende il posto
     * concettuale principale nella sezione
     * Comunicazioni.
     */
    reference.parentNode
      ?.insertBefore(
        nav,
        reference
      );
  }


  /*
   * Se l'utente apre una vecchia tab,
   * ripristiniamo le normali viste.
   */
  document.addEventListener(
    "click",
    event=>{

      const tab =
        event.target
          ?.closest?.(
            "[data-tab]"
          );

      if(!tab)
        return;


      const root =
        document.getElementById(
          ROOT_ID
        );


      if(
        root &&
        root.style.display !==
          "none"
      ){

        closeNativeConsole();
      }

    },
    true
  );


  window.OmniaConsoleNative = {
    open:
      openNativeConsole,

    close:
      closeNativeConsole
  };


  /*
   * La sidebar viene popolata durante
   * il bootstrap: installazione ripetuta
   * ma idempotente.
   */
  installNativeNav();

  setTimeout(
    installNativeNav,
    700
  );

  setTimeout(
    installNativeNav,
    1800
  );

  setTimeout(
    installNativeNav,
    3500
  );


  console.info(
    "[OMNIA CONSOLE] Native Workspace V5 attivo"
  );

})();

/* /OMNIA_CONSOLE_NATIVE_WORKSPACE_V5 */



/* ============================================================
   OMNIA_CONSOLE_PHONE_VISIBILITY_V6

   Nasconde SOLO graficamente il widget telefonico flottante
   mentre la Console nativa è aperta.

   SIP, audio e sessione OmniaPhone restano attivi.
   ============================================================ */

(function(){

  let consoleVisible =
    false;


  function candidatePhoneWidgets(){

    const result = [];


    document
      .querySelectorAll(
        "div,aside,section"
      )
      .forEach(el=>{

        const text =
          String(
            el.innerText || ""
          );


        if(
          !text.includes(
            "Telefono CUP"
          ) &&
          !text.includes(
            "Chiamata in arrivo"
          )
        )
          return;


        const style =
          getComputedStyle(el);


        if(
          style.position !==
            "fixed"
        )
          return;


        const rect =
          el.getBoundingClientRect();


        /*
         * Evitiamo di nascondere grandi
         * contenitori dell'app.
         */
        if(
          rect.width > 520 ||
          rect.height > 520
        )
          return;


        result.push(el);

      });


    return result;
  }


  function setFloatingPhoneHidden(
    hidden
  ){

    consoleVisible =
      !!hidden;


    candidatePhoneWidgets()
      .forEach(el=>{

        if(hidden){

          if(
            el.dataset
              .omniaConsoleDisplay ===
            undefined
          ){

            el.dataset
              .omniaConsoleDisplay =
              el.style.display || "";
          }


          el.style.display =
            "none";

        }else{

          if(
            el.dataset
              .omniaConsoleDisplay !==
            undefined
          ){

            el.style.display =
              el.dataset
                .omniaConsoleDisplay;

            delete el.dataset
              .omniaConsoleDisplay;
          }

        }

      });
  }


  window.addEventListener(
    "message",
    event=>{

      if(
        event.origin !==
        window.location.origin
      )
        return;


      if(
        event.data?.type !==
        "OMNIA_CONSOLE_VISIBILITY"
      )
        return;


      setFloatingPhoneHidden(
        !!event.data.visible
      );

    }
  );


  /*
   * Il widget può essere ricreato quando
   * arriva una chiamata. Lo nascondiamo
   * nuovamente soltanto se siamo nella Console.
   */
  const observer =
    new MutationObserver(
      ()=>{

        if(consoleVisible)
          setFloatingPhoneHidden(
            true
          );

      }
    );


  observer.observe(
    document.body,
    {
      childList:true,
      subtree:true
    }
  );


  /*
   * Integrazione diretta con la V5:
   * quando apriamo/chiudiamo la Console
   * aggiorniamo subito lo stato.
   */
  if(
    window.OmniaConsoleNative
  ){

    const oldOpen =
      window.OmniaConsoleNative.open;

    const oldClose =
      window.OmniaConsoleNative.close;


    window.OmniaConsoleNative.open =
      function(){

        const result =
          oldOpen.apply(
            this,
            arguments
          );

        setFloatingPhoneHidden(
          true
        );

        return result;
      };


    window.OmniaConsoleNative.close =
      function(){

        setFloatingPhoneHidden(
          false
        );

        return oldClose.apply(
          this,
          arguments
        );
      };
  }


  console.info(
    "[OMNIA CONSOLE] Phone Visibility V6 attiva"
  );

})();

/* /OMNIA_CONSOLE_PHONE_VISIBILITY_V6 */


