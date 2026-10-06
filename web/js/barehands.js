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
 * Camera handoff (2026-10-06, Col: "Clicking the tab should automatically
 * switch camera utility so the error doesn't appear"). Windows only lets
 * one process hold a webcam at a time, and ARCHER's own server keeps it
 * open for the Dashboard's live camera pane — so barehands' getUserMedia
 * failed with "device in use" unless the CAMERA button was clicked first.
 * Now:
 *   - entering Gesture releases ARCHER's webcam (camera_release), waits
 *     for the server to confirm, then mounts barehands;
 *   - leaving Gesture unmounts barehands (unloading the iframe is what
 *     makes the browser let go of the device) and hands the webcam back
 *     (camera_reacquire — the server retries briefly while the browser
 *     finishes closing it).
 * If you released the camera yourself with the CAMERA button, leaving
 * Gesture leaves it released: only an automatic release is automatically
 * undone.
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
  const gestureTab = document.getElementById("tab-gesture");
  const client = window.ArcherClient;

  // ARCHER's own webcam, as last reported by the server (hello on connect,
  // observer_camera on every change).
  let cameraAvailable = false;
  let cameraReleased = false;
  let cameraWaiters = [];

  let gestureActive = false; // the Gesture tab is the visible tab
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
      // no-cors: barehands' own server sets no CORS headers, and we only
      // need to know a connection + response happened at all, never the
      // body -- an opaque response still resolves the fetch promise.
      await fetch(probeUrl, { mode: "no-cors", signal: ctrl.signal });
      clearTimeout(timer);
      return true;
    } catch {
      return false;
    }
  }

  function showMessage(text) {
    gestureTab.innerHTML = "";
    const p = document.createElement("p");
    p.id = "archer-gesture-placeholder";
    p.textContent = text;
    gestureTab.appendChild(p);
  }

  function mountBarehands() {
    gestureTab.innerHTML = "";
    const frame = document.createElement("iframe");
    frame.id = "archer-barehands-frame";
    frame.src = stageUrl;
    frame.title = "barehands";
    frame.allow = "camera"; // required to delegate camera access into a cross-origin iframe
    gestureTab.appendChild(frame);
    console.log("[archer] barehands mounted in the Gesture tab (:" + BAREHANDS_PORT + ").");
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

    if (client && cameraAvailable && !cameraReleased) {
      showMessage("Handing the webcam over to barehands…");
      autoReleased = true;
      client.sendCameraRelease();
      const confirmed = await waitForCamera(true, 8000);
      if (seq !== entrySeq) return; // left the tab while waiting
      if (!confirmed) {
        console.warn("[archer] ARCHER didn't confirm releasing the webcam in time -- mounting barehands anyway.");
      }
    }
    mountBarehands();
  }

  function leaveGesture() {
    if (!gestureActive) return;
    gestureActive = false;
    entrySeq++;
    unmountBarehands();
    if (client && autoReleased) {
      autoReleased = false;
      // A short head start for the browser to close the device after the
      // iframe unloads; the server also retries if it's still busy.
      setTimeout(() => client.sendCameraReacquire(), 600);
    }
  }

  const gestureBtn = document.querySelector('#archer-tabs .tab-btn[data-tab="gesture"]');
  const otherTabBtns = document.querySelectorAll('#archer-tabs .tab-btn:not([data-tab="gesture"])');
  if (gestureBtn) gestureBtn.addEventListener("click", enterGesture);
  otherTabBtns.forEach((b) => b.addEventListener("click", leaveGesture));

  if (client) {
    client.on("hello", ({ cameraReleased: released, cameraAvailable: available }) => {
      cameraAvailable = !!available;
      setCameraState(released);
    });
    client.on("observerCamera", setCameraState);
    // Switching by voice/text command ("switch to the gesture tab" -> the
    // switch_tab tool -> this event -- see CONTRACT.md) gets the same
    // handoff as a click. Legacy tab names all alias to the Dashboard.
    client.on("switchTab", (tabName) => {
      if (tabName === "gesture") enterGesture();
      else leaveGesture();
    });
  }
})();
