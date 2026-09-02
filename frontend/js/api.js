// Wrapper leggero per le chiamate all'API FastAPI
const CupApi = {
  base: window.CUP_CONFIG.API_BASE_URL,

  token() {
    return localStorage.getItem("cup_token") || "";
  },

  setToken(token) {
    if (token) localStorage.setItem("cup_token", token);
    else localStorage.removeItem("cup_token");
  },

  devRole() {
    const role = (localStorage.getItem("cup_dev_role") || "").toLowerCase();
    return ["admin", "operator"].includes(role) ? role : "";
  },

  setDevRole(role) {
    role = (role || "").toLowerCase();
    if (["admin", "operator"].includes(role)) localStorage.setItem("cup_dev_role", role);
    else localStorage.removeItem("cup_dev_role");
  },

  authHeaders() {
    return this.token()
      ? { Authorization: `Bearer ${this.token()}` }
      : {};
  },

  async request(path, options = {}) {
    const headers = Object.assign(
      { "Content-Type": "application/json" },
      this.authHeaders(),
      options.headers || {}
    );
    const res = await fetch(this.base + path, { ...options, headers });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      let message = "Errore API";
      if (typeof err.detail === "string") message = err.detail;
      else if (Array.isArray(err.detail)) message = err.detail.map((x) => x.msg || JSON.stringify(x)).join(" · ");
      else if (err.detail) message = JSON.stringify(err.detail);
      const e = new Error(message);
      e.status = res.status;
      throw e;
    }
    if (res.status === 204) return null;
    return res.json();
  },

  health() {
    return this.request("/health");
  },

  login(email, password) {
    return this.request("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },
  devLogin(role) {
    return this.request("/auth/dev-login", {
      method: "POST",
      body: JSON.stringify({ role }),
    });
  },
  me() {
    return this.request("/auth/me");
  },
  getMyVoip() {
    return this.request("/operators/me/voip");
  },

  getMyVoipStatus() {
    return this.request(
      "/operators/me/voip/status"
    );
  },
  getBookings(params = "") {
    return this.request("/bookings/" + params);
  },
  getDoctors(params = "") { return this.request("/calendar/doctors" + params); },
  saveDoctor(data, id = null) { return this.request(id ? `/calendar/doctors/${id}` : "/calendar/doctors", { method: id ? "PUT" : "POST", body: JSON.stringify(data) }); },
  getVisitTypes(params = "") { return this.request("/calendar/visit-types" + params); },
  saveVisitType(data, id = null) { return this.request(id ? `/calendar/visit-types/${id}` : "/calendar/visit-types", { method: id ? "PUT" : "POST", body: JSON.stringify(data) }); },
  getAgendas(params = "") { return this.request("/calendar/agendas" + params); },
  saveAgenda(data, id = null) { return this.request(id ? `/calendar/agendas/${id}` : "/calendar/agendas", { method: id ? "PUT" : "POST", body: JSON.stringify(data) }); },
  getCalendarEvents(start, end, filters = {}) {
    const q = new URLSearchParams({ start, end }); Object.entries(filters).forEach(([k,v]) => { if (v) q.set(k,v); });
    return this.request("/calendar/events?" + q.toString());
  },
  getCalendarExceptions(start, end, agendaId = null) {
    const q = new URLSearchParams({ start, end });

    if (agendaId)
      q.set("agenda_id", agendaId);

    return this.request("/calendar/exceptions?" + q.toString());
  },

  getAvailableSlots(day, agendaId, visitTypeId = null) {
    const q = new URLSearchParams({ day, agenda_id: agendaId }); if (visitTypeId) q.set("visit_type_id", visitTypeId);
    return this.request("/calendar/slots?" + q.toString());
  },

  getAvailability(agendaId, visitTypeId, fromDay = "", days = 30, maxDates = 7) {
    const q = new URLSearchParams({
      agenda_id: agendaId,
      visit_type_id: visitTypeId,
      days,
      max_dates: maxDates
    });

    if (fromDay)
      q.set("from_day", fromDay);

    return this.request("/calendar/availability?" + q.toString());
  },
  createCalendarBooking(data) { return this.request("/calendar/bookings", { method: "POST", body: JSON.stringify(data) }); },

  getReallocationIncidents() {
    return this.request("/reallocation/incidents");
  },

  getReallocatedBookings() {
    return this.request("/reallocation/reallocated-bookings");
  },

  getReallocationIncident(id) {
    return this.request(`/reallocation/incidents/${id}`);
  },

  deleteReallocationIncident(id) {
    return this.request(`/reallocation/incidents/${id}`, {
      method: "DELETE"
    });
  },

  createReallocationIncident(data) {
    return this.request("/reallocation/incidents", {
      method: "POST",
      body: JSON.stringify(data)
    });
  },

  notifyReallocationCase(id) {
    return this.request(`/reallocation/cases/${id}/notify`, {
      method: "POST"
    });
  },

  simulateReallocationNotification(id) {
    return this.request(`/reallocation/cases/${id}/simulate-notify`, {
      method: "POST"
    });
  },

  previewReallocationMessage(id) {
    return this.request(`/reallocation/cases/${id}/preview-message`);
  },

  respondReallocationAsPatient(token, action) {
    return this.request(
      `/reallocation/public/${encodeURIComponent(token)}/${action}`,
      {
        method: "POST"
      }
    );
  },

  confirmReallocationByPhone(id, note = "") {
    return this.request(`/reallocation/cases/${id}/operator-phone-confirm`, {
      method: "POST",
      body: JSON.stringify({ note })
    });
  },

  cancelReallocationCase(id) {
    return this.request(`/reallocation/cases/${id}/cancel-request`, {
      method: "POST"
    });
  },

  acceptReallocationCase(id) {
    return this.request(`/reallocation/cases/${id}/operator-accept`, {
      method: "POST"
    });
  },
  updateCalendarBooking(id, data) { return this.request(`/calendar/bookings/${id}`, { method: "PATCH", body: JSON.stringify(data) }); },
  syncCalendarBooking(id) { return this.request(`/calendar/bookings/${id}/sync`, { method: "POST" }); },
  testCalendarProvider(provider) { return this.request(`/calendar/test/${provider}`, { method: "POST" }); },
  createBooking(data) {
    return this.request("/bookings/", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },
  updateBooking(id, data) {
    return this.request(`/bookings/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },
  cancelBooking(id) {
    return this.request(`/bookings/${id}`, { method: "DELETE" });
  },
  getReminders(status = "") { return this.request("/reminders" + (status ? `?status=${encodeURIComponent(status)}` : "")); },
  getBookingReminders(id) { return this.request(`/reminders/booking/${id}`); },
  scheduleBookingReminders(id) { return this.request(`/reminders/booking/${id}/schedule`, { method: "POST" }); },
  sendBookingReminderNow(id, channels = null) { return this.request(`/reminders/booking/${id}/send-now`, { method: "POST", body: JSON.stringify({ channels }) }); },
  retryReminder(id) { return this.request(`/reminders/${id}/retry`, { method: "POST" }); },

  getReminderProviderStatus() {
    return this.request("/reminders/providers/status");
  },

  reactivateReminderProvider(channel) {
    return this.request(
      `/reminders/providers/${encodeURIComponent(channel)}/reactivate`,
      { method: "POST" }
    );
  },
  getPatients() {
    return this.request("/patients/");
  },

  getPatientsCount() {
    return this.request("/patients/count");
  },
  getPrevisitSubmissions(status = "") { return this.request("/previsit/submissions" + (status ? `?status=${encodeURIComponent(status)}` : "")); },

  getPrevisitSubmission(id) {
    return this.request(
      `/previsit/submissions/${id}`
    );
  },
  getCheckins(day = "") { return this.request("/previsit/checkins" + (day ? `?day=${encodeURIComponent(day)}` : "")); },
  setCheckinStatus(id, status, notes = null) { return this.request(`/previsit/checkins/${id}`, { method: "PATCH", body: JSON.stringify({ status, notes }) }); },
  preparePrevisit(bookingId) { return this.request(`/previsit/booking/${bookingId}/prepare`, { method: "POST" }); },
  getPrevisitTemplates() { return this.request("/previsit/templates"); },
  getWaitlist() { return this.request("/waitlist"); },
  createWaitlistEntry(data) { return this.request("/waitlist", { method: "POST", body: JSON.stringify(data) }); },
  setWaitlistStatus(id, status) { return this.request(`/waitlist/${id}/status?status=${encodeURIComponent(status)}`, { method: "PATCH" }); },
  getWaitlistOffers() { return this.request("/waitlist/offers"); },
  getFollowups() { return this.request("/care/followups"); },
  getRecalls() { return this.request("/care/recalls"); },
  getAnalyticsOverview(days=30) { return this.request(`/analytics/overview?days=${days}`); },
  getAdminAnalytics(days=30) { return this.request(`/analytics/admin?days=${days}`); },
  sendFollowup(id) { return this.request(`/care/followups/${id}/send`, { method: "POST" }); },
  resolveFollowup(id) { return this.request(`/care/followups/${id}/resolve`, { method: "PATCH" }); },
  sendRecall(id) { return this.request(`/care/recalls/${id}/send`, { method: "POST" }); },
  snoozeRecall(id, days=30) { return this.request(`/care/recalls/${id}/snooze?days=${days}`, { method: "PATCH" }); },

  updatePatientReminders(id, data) { return this.request(`/patients/${id}/reminders`, { method: "PATCH", body: JSON.stringify(data) }); },
  getCalls() {
    return this.request("/calls/");
  },

  clearCallHistory() {
    return this.request("/calls/history", {
      method: "DELETE"
    });
  },
  getChatbotStatus() {
    return this.request("/chatbot/status");
  },
  getChatSessions() {
    return this.request("/chatbot/sessions");
  },
  getChatMessages(id) {
    return this.request(`/chatbot/sessions/${id}/messages`);
  },
  async downloadChatAttachment(sessionId, attachmentId, filename) {
    const res = await fetch(
      this.base + `/chatbot/sessions/${sessionId}/attachments/${attachmentId}`,
      { headers: this.authHeaders() }
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      const e = new Error(err.detail || "Errore download allegato");
      e.status = res.status;
      throw e;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || "allegato";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
  replyChat(id, text) {
    return this.request(`/chatbot/sessions/${id}/reply`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
  },
  closeChat(id) {
    return this.request(`/chatbot/sessions/${id}/close`, { method: "POST" });
  },
  deleteChat(id) {
    return this.request(`/chatbot/sessions/${id}`, { method: "DELETE" });
  },
  clearChatHistory() {
    return this.request("/chatbot/sessions", { method: "DELETE" });
  },

  getConversationDetail(id) {
    return this.request(`/omnichannel/sessions/${id}`);
  },
  getActiveJourneys() {
    return this.request("/omnichannel/journeys/active");
  },
  getSettings() {
    return this.request("/settings");
  },
  getRuntimeSettings() { return this.request("/settings/runtime"); },
  saveSettings(values) {
    return this.request("/settings", { method: "PUT", body: JSON.stringify({ values }) });
  },

  getPublicBranding() {
    return this.request("/settings/public/branding");
  },

  async uploadClinicLogo(file) {
    const form = new FormData();
    form.append("file", file);

    const res = await fetch(
      this.base + "/settings/branding/logo",
      {
        method: "POST",
        headers: this.authHeaders(),
        body: form
      }
    );

    const body = await res.json().catch(
      () => ({detail: res.statusText})
    );

    if(!res.ok)
      throw new Error(
        body.detail || "Upload logo fallito"
      );

    return body;
  },

  deleteClinicLogo() {
    return this.request(
      "/settings/branding/logo",
      {method:"DELETE"}
    );
  },
  testSettings(section) {
    return this.request(`/settings/test/${section}`, { method: "POST" });
  },
  testChannelMessage(channel, destination, message) {
    return this.request(`/settings/test-message/${channel}`, { method: "POST", body: JSON.stringify({ destination, message }) });
  },
  requestHandoff(id, reason = "Richiesta operatore", callOperator = true) {
    return this.request(`/omnichannel/sessions/${id}/handoff`, {
      method: "POST",
      body: JSON.stringify({ reason, call_operator: callOperator }),
    });
  },
  setConversationOwner(id, owner) {
    return this.request(`/omnichannel/sessions/${id}/owner`, {
      method: "POST",
      body: JSON.stringify({ owner }),
    });
  },


  getHandoffQueue() { return this.request("/handoffs/queue"); },
  getHandoffRecent() { return this.request("/handoffs/recent"); },
  acceptHandoff(id) { return this.request(`/handoffs/${id}/accept`, { method: "POST" }); },
  rejectHandoff(id) { return this.request(`/handoffs/${id}/reject`, { method: "POST" }); },
  returnHandoffToAi(id) { return this.request(`/handoffs/${id}/return-ai`, { method: "POST" }); },
  callbackHandoff(id) { return this.request(`/handoffs/${id}/callback`, { method: "POST" }); },
  getOperatorPresence() { return this.request("/handoffs/presence"); },
  setOperatorPresence(status, extension = null) { return this.request("/handoffs/presence/me", { method: "PUT", body: JSON.stringify({ status, extension }) }); },
  getChatwootStatus() {
    return this.request("/chatwoot/status");
  },
  syncChatwoot(id) {
    return this.request(`/chatwoot/sessions/${id}/sync`, { method: "POST" });
  },
  setupChatwootWebhook() {
    return this.request("/chatwoot/setup-webhook", { method: "POST" });
  },
  sendSmsLink(id, phone = null) {
    return this.request(`/omnichannel/sessions/${id}/sms-link`, {
      method: "POST",
      body: JSON.stringify({ phone: phone || null }),
    });
  },
  seedDemo(force = false) { return this.request(`/demo/seed?force=${force ? "true" : "false"}`, { method: "POST" }); },

  getOperators() { return this.request("/operators"); },
  createOperator(data) { return this.request("/operators", { method: "POST", body: JSON.stringify(data) }); },
  updateOperator(id, data) { return this.request(`/operators/${id}`, { method: "PATCH", body: JSON.stringify(data) }); },
  getTrainingSamples(status = "") { return this.request("/training/samples" + (status ? `?status=${encodeURIComponent(status)}` : "")); },
  reviewTrainingSample(id, status, notes = null) { return this.request(`/training/samples/${id}`, { method: "PATCH", body: JSON.stringify({ status, notes }) }); },
  getLivekitTrainingContext(q = "") { return this.request(`/training/livekit-context?q=${encodeURIComponent(q)}`); },
  getPayments() { return this.request("/payments"); },
  createPayment(data) { return this.request("/payments", { method: "POST", body: JSON.stringify(data) }); },
  sendPayment(id) { return this.request(`/payments/${id}/send`, { method: "POST" }); },
  updatePaymentStatus(id, status) { return this.request(`/payments/${id}/status`, { method: "PATCH", body: JSON.stringify({ status }) }); },
  getSignatures() { return this.request("/signatures"); },
  async createSignatureRequest(formData) {
    const res = await fetch(this.base + "/signatures", { method: "POST", headers: this.authHeaders(), body: formData });
    if (!res.ok) { const err = await res.json().catch(() => ({ detail: res.statusText })); throw new Error(typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail)); }
    return res.json();
  },
  sendSignature(id) { return this.request(`/signatures/${id}/send`, { method: "POST" }); },
  getSignatureAudit(id) { return this.request(`/signatures/${id}/audit`); },
  health() {
    return this.request("/health");
  },
};
