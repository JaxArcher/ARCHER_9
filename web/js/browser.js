/**
 * ARCHER browser client — Browser (mirror) card.
 *
 * Added 2026-09-16 per Col's ask: "a built-in browser could be a pane
 * that would be useful that archer can see and control along with me."
 * Read-only mirror for this first pass (Col's explicit call, weighed
 * against building click/keystroke forwarding right away): shows a live
 * view of the SAME real, visible Chromium window ARCHER's existing
 * browser-control tools already drive (tools/pc_control.py, Playwright)
 * -- you watch what ARCHER is doing here, but still click/type in the
 * actual popped-up Chrome window itself, not this pane. Joint control
 * (forwarding clicks/keys from this pane into that same session) is a
 * deliberate fast-follow, not built yet.
 *
 * Reflow on activity (2026-09-16, second pass, Col's ask: "the cam feed
 * and chat box and anything else in the way would shift to the side when
 * the browser mirror is active... large enough for me to see it"): a
 * comment-node placeholder marks this card's normal spot in the
 * secondary grid. When a real session goes active, the card physically
 * moves into #archer-root (the primary row, beside orb/chat/system) and
 * grows via .archer-browser-primary; when the session ends, it moves
 * back to its placeholder. See ui.css for the size rules both states use.
 *
 * Screenshots only get pulled while the Dashboard tab is actually
 * visible (same gating as system.js's camera feed/polling), and only if
 * a browser session is actually open -- otherwise this card just shows
 * a quiet "no active browser session" message instead of polling
 * pointlessly.
 */
(() => {
  const panel = document.getElementById("tab-browser");
  if (!panel) return;

  const placeholder = document.createComment("browser-mirror-slot");
  panel.parentNode.insertBefore(placeholder, panel);
  const archerRoot = document.getElementById("archer-root");

  panel.innerHTML = `
    <h3>Browser (mirror)</h3>
    <p class="archer-memory-hint">Live view of the browser ARCHER's own tools are driving. Read-only for now -- click/type in the actual Chrome window, not here.</p>
    <div id="archer-browser-mirror-wrap">
      <img id="archer-browser-mirror-img" alt="Browser mirror" />
      <p id="archer-browser-mirror-empty" class="archer-memory-empty">No active browser session yet -- opens automatically the next time ARCHER uses a browser-control tool.</p>
    </div>
  `;

  const img = document.getElementById("archer-browser-mirror-img");
  const emptyMsg = document.getElementById("archer-browser-mirror-empty");

  let isPrimary = false;
  function render({ imageB64, active }) {
    if (active && imageB64) {
      img.src = "data:image/png;base64," + imageB64;
      img.style.display = "block";
      emptyMsg.style.display = "none";
    } else {
      img.style.display = "none";
      emptyMsg.style.display = "block";
    }

    if (active && !isPrimary) {
      isPrimary = true;
      panel.classList.add("archer-browser-primary");
      if (archerRoot) {
        archerRoot.appendChild(panel);
        archerRoot.classList.add("archer-browser-active");
      }
    } else if (!active && isPrimary) {
      isPrimary = false;
      panel.classList.remove("archer-browser-primary");
      if (archerRoot) archerRoot.classList.remove("archer-browser-active");
      placeholder.parentNode.insertBefore(panel, placeholder);
    }
  }

  if (window.ArcherClient) {
    window.ArcherClient.on("browserScreenshot", render);
  }

  // Same Dashboard-vs-Gesture visibility gating as system.js's camera
  // feed -- Playwright screenshots are heavier than a webcam frame grab,
  // so this polls every 2s rather than streaming continuously.
  const LIVE_TAB_NAMES = new Set(["dashboard", "voice", "logs", "memory", "tasks", "system"]);
  let pollTimer = null;
  function startPolling() {
    if (window.ArcherClient) window.ArcherClient.sendBrowserGetScreenshot();
    if (!pollTimer) {
      pollTimer = setInterval(() => {
        if (window.ArcherClient) window.ArcherClient.sendBrowserGetScreenshot();
      }, 2000);
    }
  }
  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  const dashboardBtn = document.querySelector('#archer-tabs .tab-btn[data-tab="dashboard"]');
  const gestureBtn = document.querySelector('#archer-tabs .tab-btn[data-tab="gesture"]');
  if (dashboardBtn) dashboardBtn.addEventListener("click", startPolling);
  if (gestureBtn) gestureBtn.addEventListener("click", stopPolling);
  if (window.ArcherClient) {
    window.ArcherClient.on("switchTab", (tabName) => {
      if (LIVE_TAB_NAMES.has(tabName)) startPolling();
      else stopPolling();
    });
    window.ArcherClient.on("connected", startPolling);
  }
})();
