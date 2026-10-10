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
  img.src = `data:image/png;base64,${imageB64}`;
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

ArcherClient.on("hello", ({ mode, micMuted, ttsMuted }) => {
  if (mode) setModeButton(mode);
  setMicButton(!!micMuted);
  setTtsButton(!!ttsMuted);
});
ArcherClient.on("mode", setModeButton);
ArcherClient.on("micMute", setMicButton);
ArcherClient.on("ttsMute", setTtsButton);
ArcherClient.on("connected", () => statusDotEl.classList.remove("is-offline"));
ArcherClient.on("disconnected", () => statusDotEl.classList.add("is-offline"));

modeBtnEl.addEventListener("click", () => ArcherClient.sendModeToggle());
micBtnEl.addEventListener("click", () => ArcherClient.sendMicMuteToggle());
ttsBtnEl.addEventListener("click", () => ArcherClient.sendTtsMuteToggle());
haltBtnEl.addEventListener("click", () => ArcherClient.sendHalt());

// Offline until the first "connected" event actually fires.
statusDotEl.classList.add("is-offline");
