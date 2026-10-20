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

ArcherClient.on("hello", ({ mode, micMuted, ttsMuted, listeningState }) => {
  if (mode) setModeButton(mode);
  setMicButton(!!micMuted);
  setTtsButton(!!ttsMuted);
  if (listeningState) setListeningState(listeningState.state, listeningState.until);
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
