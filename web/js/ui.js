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
const voiceEngineBtnEl = document.getElementById("archer-voice-engine-btn");
const cameraBtnEl = document.getElementById("archer-camera-btn");
const enrollBtnEl = document.getElementById("archer-enroll-btn");
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

// Separate from SPEAKER above (which just mutes/unmutes): this picks WHICH
// voice engine speaks. Independent of the MODE button too — conversation
// can run on the local model while voice output still defaults to
// ElevenLabs (cloud). See ToggleService.tts_mode / CONTRACT.md.
function setVoiceEngineButton(ttsMode) {
  voiceEngineBtnEl.textContent = ttsMode === "cloud" ? "☁ VOICE: ELEVENLABS" : "🖥 VOICE: KOKORO";
  voiceEngineBtnEl.classList.toggle("is-cloud", ttsMode === "cloud");
}

// Releasing frees the physical webcam device so another app (barehands,
// specifically — see CONTRACT.md) can open it; only one process can hold
// a webcam at a time on Windows. Analysis just goes stale while released,
// nothing crashes; toggle it back to resume ARCHER's own observer.
function setCameraButton(released) {
  cameraBtnEl.textContent = released ? "📷 CAMERA RELEASED" : "📷 CAMERA (ARCHER)";
  cameraBtnEl.classList.toggle("is-muted", released);
}

ArcherClient.on("hello", ({ mode, ttsMode, micMuted, ttsMuted, cameraReleased, cameraAvailable }) => {
  if (mode) setModeButton(mode);
  if (ttsMode) setVoiceEngineButton(ttsMode);
  setMicButton(!!micMuted);
  setTtsButton(!!ttsMuted);
  cameraBtnEl.style.display = cameraAvailable ? "" : "none";
  setCameraButton(!!cameraReleased);
});
ArcherClient.on("mode", setModeButton);
ArcherClient.on("ttsMode", setVoiceEngineButton);
ArcherClient.on("micMute", setMicButton);
ArcherClient.on("ttsMute", setTtsButton);
ArcherClient.on("observerCamera", setCameraButton);
ArcherClient.on("connected", () => statusDotEl.classList.remove("is-offline"));
ArcherClient.on("disconnected", () => statusDotEl.classList.add("is-offline"));

// Face enrollment — see server.py's "enroll_face" handler and
// ObserverPipeline.enroll_current_person. Reuses the transcript log for
// status messages rather than adding new UI chrome.
ArcherClient.on("enrollProgress", ({ name }) => {
  enrollBtnEl.disabled = true;
  enrollBtnEl.textContent = "LOOK AT CAMERA…";
  addTranscriptLine("assistant", `Enrolling "${name}" — look at the camera for a few seconds...`);
});
ArcherClient.on("enrollResult", ({ success, name, error }) => {
  enrollBtnEl.disabled = false;
  enrollBtnEl.textContent = "ENROLL FACE";
  addTranscriptLine(
    "assistant",
    success
      ? `Enrolled "${name}" — ARCHER should recognize you now.`
      : `Enrollment failed${error ? ": " + error : ""} — make sure you're in frame and well lit, and try again.`
  );
});

modeBtnEl.addEventListener("click", () => ArcherClient.sendModeToggle());
micBtnEl.addEventListener("click", () => ArcherClient.sendMicMuteToggle());
ttsBtnEl.addEventListener("click", () => ArcherClient.sendTtsMuteToggle());
voiceEngineBtnEl.addEventListener("click", () => ArcherClient.sendTtsModeToggle());
cameraBtnEl.addEventListener("click", () => ArcherClient.sendCameraReleaseToggle());
enrollBtnEl.addEventListener("click", () => ArcherClient.sendEnrollFace("Col"));
haltBtnEl.addEventListener("click", () => ArcherClient.sendHalt());

// Offline until the first "connected" event actually fires.
statusDotEl.classList.add("is-offline");
