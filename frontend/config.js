// Configurazione sistema CUP - frontend
window.CUP_CONFIG = {
  APP_VERSION: "1.1.2",
  API_BASE_URL: "/api",

  WS_HANDOFFS_URL:
    (location.protocol === "https:" ? "wss://" : "ws://") +
    location.host +
    "/api/handoffs/ws",

  WS_CALLS_URL:
    (location.protocol === "https:" ? "wss://" : "ws://") +
    location.host +
    "/api/calls/ws",

  END_USER_CHAT_URL: "/chatbot.html",
};
