/**
 * ARCHER browser client — transcript + text input.
 *
 * The orb (js/orb.js, ArcherApertureOrb) owns state/amplitude/wakeWord/halt
 * rendering on its own — see its bindClient(). This file covers everything
 * else ArcherClient exposes: live partial transcription, finalized lines,
 * and the typed-text fallback. Load after app.js and orb.js.
 */

const liveEl = document.getElementById("archer-live");
const transcriptEl = document.getElementById("archer-transcript");
const textInputEl = document.getElementById("archer-text-input");
const textFormEl = document.getElementById("archer-text-form");
const statusDotEl = document.getElementById("archer-status");
const modeBtnEl = document.getElementById("archer-mode-btn");
const micBtnEl = document.getElementById("archer-mic-btn");
const ttsBtnEl = document.getElementById("archer-tts-btn");
const haltBtnEl = document.getElementById("archer-halt-btn");
const listeningIndicatorEl = document.getElementById("archer-listening-indicator");
const listeningStatusTextEl = document.getElementById("archer-listening-status-text");
const pause15mBtnEl = document.getElementById("archer-listen-pause-15m");
const pause1hBtnEl = document.getElementById("archer-listen-pause-1h");
const pauseHoldBtnEl = document.getElementById("archer-listen-pause-hold");
const resumeBtnEl = document.getElementById("archer-listen-resume");
const forgetBtnEl = document.getElementById("archer-listen-forget");

function addTranscriptLine(role, text) {
  if (!text) return;
  const line = document.createElement("p");
  line.className = `line line-${role}`;
  line.textContent = text;
  transcriptEl.appendChild(line);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

ArcherClient.on("sttPartial", (text) => {
  liveEl.textContent = text || "";
});

ArcherClient.on("sttFinal", (text) => {
  addTranscriptLine("user", text);
  liveEl.textContent = "";
});

ArcherClient.on("assistantLine", ({ text }) => {
  addTranscriptLine("assistant", text);
});

ArcherClient.on("artifactPush", ({ imageB64, title }) => {
  if (!imageB64) return;
  const wrap = document.createElement("div");
  wrap.className = "line line-assistant line-artifact";
  const label = document.createElement("p");
  label.className = "artifact-label";
  label.textContent = title ? `📸 ${title}` : "📸 Screenshot";
  const img = document.createElement("img");
  img.className = "artifact-image";
  if (imageB64.startsWith("data:")) {
    img.src = imageB64;
  } else {
    const mime = imageB64.startsWith("/9j/") ? "image/jpeg" : "image/png";
    img.src = `data:${mime};base64,${imageB64}`;
  }
  img.alt = title || "Screenshot";
  wrap.appendChild(label);
  wrap.appendChild(img);
  transcriptEl.appendChild(wrap);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
});

ArcherClient.on("halt", () => {
  liveEl.textContent = "";
  document.querySelectorAll(".approval-card").forEach((card) => {
    if (card._approvalTimer) clearInterval(card._approvalTimer);
    const actions = card.querySelector(".approval-actions");
    const timer = card.querySelector(".approval-countdown");
    const status = card.querySelector(".approval-status");
    if (actions && actions.style.display !== "none") {
      actions.style.display = "none";
      if (timer) timer.style.display = "none";
      if (status) {
        status.style.display = "block";
        status.className = "approval-status status-denied";
        status.textContent = "🛑 Cancelled (HALT)";
      }
    }
  });
});

textFormEl.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = textInputEl.value.trim();
  if (!text) return;
  ArcherClient.sendText(text);
  addTranscriptLine("user", text);
  textInputEl.value = "";
});

// --- Toolbar: connection status + mode/mic/tts toggles + HALT ---
// Mirrors the desktop GUI's own toolbar 1:1 (see gui/main_window.py
// _on_toggle_mode / _on_toggle_mic / _on_halt_clicked) rather than adding
// browser-only behavior.

function setModeButton(mode) {
  modeBtnEl.textContent = mode === "cloud" ? "☁ CLOUD" : "🖥 LOCAL";
  modeBtnEl.classList.toggle("is-cloud", mode === "cloud");
}

function setMicButton(muted) {
  micBtnEl.textContent = muted ? "🔇 MIC MUTED" : "🎤 MIC ON";
  micBtnEl.classList.toggle("is-muted", muted);
}

function setTtsButton(muted) {
  ttsBtnEl.textContent = muted ? "🔇 SPEAKER MUTED" : "🔊 SPEAKER ON";
  ttsBtnEl.classList.toggle("is-muted", muted);
}

// Session Approval Badge Elements (Phase 3)
const sessionBadgeEl = document.getElementById("archer-session-approval-badge");
const endSessionBtnEl = document.getElementById("archer-end-session-approval-btn");

function setSessionApproval(active) {
  if (sessionBadgeEl) {
    sessionBadgeEl.style.display = active ? "inline-flex" : "none";
  }
}

function escapeHtml(s) {
  if (!s) return "";
  const d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML;
}

function addApprovalCard({ requestId, toolName, actionType, description, details, timeoutSeconds }) {
  if (!transcriptEl) return;
  const card = document.createElement("div");
  card.className = "line line-assistant approval-card";
  card.id = `approval-card-${requestId}`;

  let timeLeft = timeoutSeconds || 30;

  card.innerHTML = `
    <div class="approval-header">
      <span class="approval-icon">⚠️</span>
      <span class="approval-title">Approval Required</span>
      <span class="approval-countdown" id="appr-timer-${requestId}">${timeLeft}s</span>
    </div>
    <div class="approval-desc">${escapeHtml(description)}</div>
    ${details ? `<div class="approval-details">${escapeHtml(details)}</div>` : ""}
    <div class="approval-actions" id="appr-actions-${requestId}">
      <button type="button" class="approval-btn approve-btn" data-act="approve">Approve</button>
      <button type="button" class="approval-btn deny-btn" data-act="deny">Deny</button>
      <button type="button" class="approval-btn session-btn" data-act="approve_session">Approve Session</button>
    </div>
    <div class="approval-status" id="appr-status-${requestId}" style="display:none;"></div>
  `;

  // Countdown timer
  const timerEl = card.querySelector(`#appr-timer-${requestId}`);
  const timer = setInterval(() => {
    timeLeft--;
    if (timerEl) timerEl.textContent = `${timeLeft}s`;
    if (timeLeft <= 0) {
      clearInterval(timer);
    }
  }, 1000);
  card._approvalTimer = timer;

  // Actions
  const actionsEl = card.querySelector(`#appr-actions-${requestId}`);
  const statusEl = card.querySelector(`#appr-status-${requestId}`);

  actionsEl.addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    const act = btn.getAttribute("data-act");
    if (!act) return;

    if (card._approvalTimer) clearInterval(card._approvalTimer);
    ArcherClient.sendApprovalResponse(requestId, act);

    actionsEl.style.display = "none";
    if (timerEl) timerEl.style.display = "none";
    statusEl.style.display = "block";
    if (act === "approve") {
      statusEl.className = "approval-status status-approved";
      statusEl.textContent = "✓ Approved";
    } else if (act === "approve_session") {
      statusEl.className = "approval-status status-session";
      statusEl.textContent = "⚡ Approved for entire session";
    } else {
      statusEl.className = "approval-status status-denied";
      statusEl.textContent = "✗ Denied";
    }
  });

  transcriptEl.appendChild(card);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

ArcherClient.on("approvalRequest", (payload) => {
  addApprovalCard(payload);
});

ArcherClient.on("approvalTimeout", ({ requestId }) => {
  const card = document.getElementById(`approval-card-${requestId}`);
  if (card) {
    if (card._approvalTimer) clearInterval(card._approvalTimer);
    const actionsEl = card.querySelector(`#appr-actions-${requestId}`);
    const timerEl = card.querySelector(`#appr-timer-${requestId}`);
    const statusEl = card.querySelector(`#appr-status-${requestId}`);
    if (actionsEl) actionsEl.style.display = "none";
    if (timerEl) timerEl.style.display = "none";
    if (statusEl) {
      statusEl.style.display = "block";
      statusEl.className = "approval-status status-denied";
      statusEl.textContent = "⏱ Denied (timed out)";
    }
  }
});

ArcherClient.on("sessionApprovalState", ({ active }) => {
  setSessionApproval(active);
});

if (endSessionBtnEl) {
  endSessionBtnEl.addEventListener("click", () => {
    ArcherClient.sendEndSessionApproval();
  });
}

ArcherClient.on("hello", ({ mode, micMuted, ttsMuted, listeningState, sessionApprovalActive }) => {
  if (mode) setModeButton(mode);
  setMicButton(!!micMuted);
  setTtsButton(!!ttsMuted);
  if (listeningState) setListeningState(listeningState.state, listeningState.until);
  if (sessionApprovalActive !== undefined) setSessionApproval(sessionApprovalActive);
});
ArcherClient.on("mode", setModeButton);
ArcherClient.on("micMute", setMicButton);
ArcherClient.on("ttsMute", setTtsButton);
ArcherClient.on("connected", () => statusDotEl.classList.remove("is-offline"));
ArcherClient.on("disconnected", () => statusDotEl.classList.add("is-offline"));

// Room listening state (Phase 2c). state: "listening" | "paused" | "empty" | "off".
// until: for "paused", the epoch seconds it ends, or -1 for "until resumed".
const LISTENING_LOOK = {
  listening: { badge: "badge-listening", label: "LISTENING", text: "Transcribing speech in the room" },
  paused: { badge: "badge-paused", label: "PAUSED", text: "Room listening paused" },
  empty: { badge: "badge-empty", label: "EMPTY", text: "Room is empty — not transcribing" },
  off: { badge: "badge-off", label: "OFF", text: "The observer isn't running — not transcribing" },
};

function setListeningState(state, until) {
  if (!listeningIndicatorEl) return;
  const look = LISTENING_LOOK[state] || LISTENING_LOOK.off;
  listeningIndicatorEl.classList.remove("badge-listening", "badge-paused", "badge-empty", "badge-off");
  listeningIndicatorEl.classList.add(look.badge);
  listeningIndicatorEl.textContent = look.label;

  const paused = state === "paused";
  for (const btn of [pause15mBtnEl, pause1hBtnEl, pauseHoldBtnEl]) {
    if (btn) btn.style.display = paused ? "none" : "inline-block";
  }
  if (resumeBtnEl) resumeBtnEl.style.display = paused ? "inline-block" : "none";

  let text = look.text;
  if (paused) {
    if (until === -1) {
      text += " until you resume it";
    } else if (until && until > 0) {
      const mins = Math.max(1, Math.round((until - Date.now() / 1000) / 60));
      text += ` (about ${mins} min left)`;
    }
  }
  if (listeningStatusTextEl) listeningStatusTextEl.textContent = text;
}

ArcherClient.on("listeningState", ({ state, until }) => {
  setListeningState(state, until);
});

modeBtnEl.addEventListener("click", () => ArcherClient.sendModeToggle());
micBtnEl.addEventListener("click", () => ArcherClient.sendMicMuteToggle());
ttsBtnEl.addEventListener("click", () => ArcherClient.sendTtsMuteToggle());
haltBtnEl.addEventListener("click", () => ArcherClient.sendHalt());

if (pause15mBtnEl) pause15mBtnEl.addEventListener("click", () => ArcherClient.sendSetListeningPause(900));
if (pause1hBtnEl) pause1hBtnEl.addEventListener("click", () => ArcherClient.sendSetListeningPause(3600));
if (pauseHoldBtnEl) pauseHoldBtnEl.addEventListener("click", () => ArcherClient.sendSetListeningPause(-1));
if (resumeBtnEl) resumeBtnEl.addEventListener("click", () => ArcherClient.sendSetListeningPause(0));
if (forgetBtnEl) forgetBtnEl.addEventListener("click", () => {
  ArcherClient.sendForgetRecentRoom(120);
  if (listeningStatusTextEl) {
    const prev = listeningStatusTextEl.textContent;
    listeningStatusTextEl.textContent = "Last 2 minutes erased.";
    setTimeout(() => {
      if (listeningStatusTextEl.textContent === "Last 2 minutes erased.") {
        listeningStatusTextEl.textContent = prev;
      }
    }, 3000);
  }
});

// Offline until the first "connected" event actually fires.
statusDotEl.classList.add("is-offline");
