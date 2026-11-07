// Interfaz del chat. Sin JS inline en el HTML, para que la CSP de la versión segura
// (tarea 14) no rompa la aplicación.
"use strict";

const $ = (id) => document.getElementById(id);
let renderMode = "text";

async function api(path, body) {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });
  let data = null;
  try { data = await res.json(); } catch (_) { /* respuesta sin JSON */ }
  return { status: res.status, ok: res.ok, data };
}

function addMessage(role, content) {
  const el = document.createElement("div");
  el.className = `msg msg-${role}`;
  if (role === "assistant" && renderMode === "html") {
    // VULN-V5: la respuesta del modelo se inserta como HTML sin codificar. Un
    // <img onerror=...> en la salida del modelo se ejecuta en el navegador del cliente.
    el.innerHTML = content;
  } else {
    el.textContent = content;
  }
  $("messages").appendChild(el);
  $("messages").scrollTop = $("messages").scrollHeight;
  return el;
}

function showChat(customerId) {
  $("login-view").hidden = true;
  $("chat-view").hidden = false;
  $("user-box").hidden = false;
  $("user-name").textContent = customerId;
  $("chat-input").focus();
}

function showLogin() {
  $("login-view").hidden = false;
  $("chat-view").hidden = true;
  $("user-box").hidden = true;
  $("messages").replaceChildren();
}

$("login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  $("login-error").textContent = "";
  const r = await api("/api/login", { customer_id: $("login-user").value.trim(), password: $("login-pass").value });
  if (!r.ok) {
    $("login-error").textContent = "Usuario o contraseña incorrectos.";
    return;
  }
  $("login-pass").value = "";
  showChat(r.data.customer_id);
  addMessage("assistant", "¡Hola! Soy Lumi. ¿En qué te puedo ayudar?");
});

$("logout-btn").addEventListener("click", async () => {
  await api("/api/logout", {});
  showLogin();
});

$("chat-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const input = $("chat-input");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  addMessage("user", message);
  const pending = addMessage("system", "Lumi está escribiendo…");
  const button = ev.submitter || $("chat-form").querySelector("button");
  button.disabled = true;
  try {
    const r = await api("/api/chat", { message });
    pending.remove();
    if (r.status === 401) { showLogin(); return; }
    if (r.status === 503) { addMessage("system", "El asistente no está disponible. Probá de nuevo en un rato."); return; }
    if (!r.ok) { addMessage("system", "No se pudo enviar el mensaje."); return; }
    addMessage("assistant", r.data.reply);
  } finally {
    button.disabled = false;
    input.focus();
  }
});

$("review-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const r = await api("/api/reviews", { text: $("review-text").value });
  if (r.ok && r.data.accepted) {
    $("review-status").textContent = "¡Gracias! Tu reseña fue publicada.";
    $("review-text").value = "";
  } else if (r.ok) {
    $("review-status").textContent = "La reseña no fue aceptada.";
  } else {
    $("review-status").textContent = "No se pudo publicar la reseña.";
  }
});

(async () => {
  const r = await api("/api/config");
  if (r.ok && r.data && r.data.render_mode) renderMode = r.data.render_mode;
})();
