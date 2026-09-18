/**
 * ARCHER browser client — barehands merge.
 *
 * Embeds barehands (jaredrhod/barehands, a separate local server + page —
 * see CONTRACT.md) inside the GESTURE tab specifically, when it's
 * reachable — NOT as a whole-page background anymore. Earlier this
 * merged in as a full-bleed layer behind everything (Voice included),
 * which put ARCHER's own live webcam feed in the same frame as
 * everything else; Col's call (2026-09-16) was that the camera/gesture
 * workspace should be its own separate pane, not blended into the rest
 * of the UI. The Voice tab's own standalone orb (orb.js) is untouched
 * either way now — the two are just separate tabs, not competing for
 * the same screen space, so there's no more need to destroy/hide it
 * when barehands is present.
 *
 * Additive and optional either way: if barehands' own server isn't
 * running on its configured port, the Gesture tab just shows a short
 * explanation instead of an iframe.
 */
(() => {
  const BAREHANDS_PORT = 8794; // barehands.json's "port" — keep in sync if changed
  // ?camhide=1 -- added directly to barehands/stage.html (Col's call,
  // 2026-09-16): hides the live camera (shrinks #cam to near-zero) while
  // MediaPipe keeps reading frames off it for tracking exactly as
  // before -- gestures still work, but the video itself is never shown.
  // Cards stay translucent glass (unlike barehands' own built-in
  // ?mode=key, which is for real OBS chroma-keying and flattens cards to
  // an opaque fill as a side effect -- not what "float over a dark
  // background" means here). Background matches ARCHER's own navy.
  const stageUrl = `${location.protocol}//${location.hostname}:${BAREHANDS_PORT}/stage.html?camhide=1&bg=%2303121d`;
  const probeUrl = `${location.protocol}//${location.hostname}:${BAREHANDS_PORT}/config`;
  const gestureTab = document.getElementById("tab-gesture");

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

  function mountBarehands() {
    gestureTab.innerHTML = "";
    const frame = document.createElement("iframe");
    frame.id = "archer-barehands-frame";
    frame.src = stageUrl;
    frame.title = "barehands";
    frame.allow = "camera"; // required to delegate camera access into a cross-origin iframe
    gestureTab.appendChild(frame);
    console.log("[archer] barehands detected on :" + BAREHANDS_PORT + " — mounted in the Gesture tab.");
  }

  function showUnavailable() {
    gestureTab.innerHTML =
      '<p id="archer-gesture-placeholder">barehands isn\'t reachable on :' + BAREHANDS_PORT +
      '. Start its own server.py (see CONTRACT.md), then reload this tab.</p>';
    console.log("[archer] barehands not reachable on :" + BAREHANDS_PORT + ".");
  }

  // Mount lazily -- the first time the Gesture tab actually becomes
  // visible -- rather than eagerly on page load. Fix for 2026-09-16
  // (Col): stage.html's boot() sizes the ring's initial position from
  // its OWN window's innerWidth/innerHeight, read once at boot. Voice is
  // the default active tab, so #tab-gesture is display:none at page
  // load; an iframe inside a display:none ancestor reports ~0 for its
  // own innerWidth/innerHeight, so the ring span nearly off-screen and
  // had to be dragged into view by hand. barehands is a cross-origin
  // iframe (different port = different origin), so there's no reaching
  // in afterward to re-run spawnStage() with correct numbers once
  // mounted -- waiting until the tab is genuinely on screen before the
  // iframe's src is ever set sidesteps needing to.
  let mounted = false;
  async function ensureMounted() {
    if (mounted) return;
    mounted = true;
    if (await barehandsReachable()) mountBarehands();
    else showUnavailable();
  }

  const gestureBtn = document.querySelector('#archer-tabs .tab-btn[data-tab="gesture"]');
  if (gestureBtn) gestureBtn.addEventListener("click", ensureMounted);
  // Also covers switching there by voice/text command ("switch to the
  // gesture tab" -> the switch_tab tool -> this same event -- see
  // CONTRACT.md) without a manual click ever happening.
  if (window.ArcherClient) {
    window.ArcherClient.on("switchTab", (tabName) => {
      if (tabName === "gesture") ensureMounted();
    });
  }
})();
