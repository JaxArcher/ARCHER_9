/**
 * ARCHER browser client — barehands merge.
 *
 * Embeds barehands (jaredrhod/barehands, a separate local server + page —
 * see CONTRACT.md) inside the GESTURE tab specifically, when it's
 * reachable — not as a whole-page background. Col's call (2026-09-16):
 * the camera/gesture workspace is its own separate pane, not blended
 * into the rest of the UI. Additive and optional: if barehands' own
 * server isn't running on its configured port, the Gesture tab just
 * shows a short explanation instead of an iframe.
 *
 * Camera ownership (Phase 2): Chrome shares the camera stream via
 * getUserMedia between the main ARCHER page and barehands' iframe. No
 * server camera release or reacquire handoff is needed or performed.
 *
 * barehands is mounted fresh each time the tab opens, never while hidden.
 * That also keeps the 2026-09-16 sizing fix: stage.html sizes its ring
 * from its own window size, read once at boot, and an iframe inside a
 * display:none tab reports ~0 — so it must only ever load while visible.
 */
(() => {
  const BAREHANDS_PORT = 8794; // barehands.json's "port" — keep in sync if changed
  // ?camhide=1 -- added directly to barehands/stage.html (Col's call,
  // 2026-09-16): hides the live camera (shrinks #cam to near-zero) while
  // MediaPipe keeps reading frames off it for tracking -- gestures still
  // work, but the video itself is never shown. Background matches
  // ARCHER's own navy.
  const stageUrl = `${location.protocol}//${location.hostname}:${BAREHANDS_PORT}/stage.html?camhide=1&bg=%2303121d`;
  const probeUrl = `${location.protocol}//${location.hostname}:${BAREHANDS_PORT}/config`;
  const gestureTab = document.getElementById("tab-files") || document.getElementById("tab-gesture");
  const client = window.ArcherClient;

  // ARCHER's own webcam, as last reported by the server (hello on connect,
  // observer_camera on every change).
  let cameraAvailable = false;
  let cameraReleased = false;
  let cameraWaiters = [];

  let gestureActive = false; // the FILES/Gesture tab is the visible tab
  let autoReleased = false;  // this file released the webcam, so it gives it back
  let entrySeq = 0;          // bumped on every enter/leave so a slow entry can't finish after you've left

  function setCameraState(released) {
    cameraReleased = !!released;
    const ready = cameraWaiters.filter((w) => w.released === cameraReleased);
    cameraWaiters = cameraWaiters.filter((w) => w.released !== cameraReleased);
    ready.forEach((w) => w.resolve(true));
  }

  function waitForCamera(released, timeoutMs) {
    if (cameraReleased === released) return Promise.resolve(true);
    return new Promise((resolve) => {
      const waiter = { released, resolve };
      cameraWaiters.push(waiter);
      setTimeout(() => {
        if (cameraWaiters.includes(waiter)) {
          cameraWaiters = cameraWaiters.filter((w) => w !== waiter);
          resolve(false);
        }
      }, timeoutMs);
    });
  }

  async function barehandsReachable() {
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 1500);
      await fetch(probeUrl, { mode: "no-cors", signal: ctrl.signal });
      clearTimeout(timer);
      return true;
    } catch {
      return false;
    }
  }

  function showMessage(text) {
    if (!gestureTab) return;
    gestureTab.innerHTML = "";
    const p = document.createElement("p");
    p.id = "archer-gesture-placeholder";
    p.textContent = text;
    gestureTab.appendChild(p);
  }

  function mountBarehands() {
    if (!gestureTab) return;
    gestureTab.innerHTML = "";
    const frame = document.createElement("iframe");
    frame.id = "archer-barehands-frame";
    frame.src = stageUrl;
    frame.title = "barehands";
    frame.allow = "camera"; // required to delegate camera access into a cross-origin iframe
    gestureTab.appendChild(frame);
    console.log("[archer] barehands mounted in the FILES tab (:" + BAREHANDS_PORT + ").");
  }

  function unmountBarehands() {
    const frame = document.getElementById("archer-barehands-frame");
    if (frame) {
      frame.src = "about:blank"; // stop barehands' camera stream before the element goes away
      frame.remove();
    }
    showMessage("barehands will connect when you open this tab.");
  }

  async function enterGesture() {
    if (gestureActive) return;
    gestureActive = true;
    const seq = ++entrySeq;
    showMessage("Connecting to barehands…");

    if (!(await barehandsReachable())) {
      if (seq === entrySeq) {
        showMessage(
          "barehands isn't reachable on :" + BAREHANDS_PORT +
          ". Start its own server.py (see CONTRACT.md), then open this tab again."
        );
      }
      return;
    }
    if (seq !== entrySeq) return; // left the tab while checking

    mountBarehands();
  }

  function leaveGesture() {
    if (!gestureActive) return;
    gestureActive = false;
    entrySeq++;
    unmountBarehands();
  }

  const filesBtn = document.querySelector('#archer-tabs .tab-btn[data-tab="files"]') || document.querySelector('#archer-tabs .tab-btn[data-tab="gesture"]');
  const otherTabBtns = document.querySelectorAll('#archer-tabs .tab-btn:not([data-tab="files"]):not([data-tab="gesture"])');
  if (filesBtn) filesBtn.addEventListener("click", enterGesture);
  otherTabBtns.forEach((b) => b.addEventListener("click", leaveGesture));

  if (client) {
    client.on("hello", ({ cameraReleased: released, cameraAvailable: available }) => {
      cameraAvailable = !!available;
      setCameraState(released);
    });
    client.on("observerCamera", setCameraState);
    client.on("switchTab", (tabName) => {
      const normalized = (tabName || "").toLowerCase();
      if (normalized === "files" || normalized === "gesture") enterGesture();
      else leaveGesture();
    });
  }
})();

