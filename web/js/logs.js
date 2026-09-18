/**
 * ARCHER browser client — LOGS tab.
 *
 * Port of gui/console_widget.py's behavior, not new design: the desktop
 * Console tab tails ARCHER's own rotating log file in-process; this tab
 * shows the exact same stream, pushed here by server.py's background
 * tailer thread over the WS bridge as {"type": "log_line", "text": ...}
 * (see CONTRACT.md). Read-only, newest at the bottom, auto-scrolls unless
 * the user has scrolled up to read something (matches normal log-viewer
 * behavior) — with the same Pause/Clear controls the desktop widget has.
 */
(() => {
  const panel = document.getElementById("tab-logs");
  if (!panel) return;

  panel.innerHTML = `
    <div id="archer-logs-toolbar">
      <span id="archer-logs-label">Tailing ARCHER's log...</span>
      <button id="archer-logs-pause" type="button">Pause</button>
      <button id="archer-logs-clear" type="button">Clear</button>
    </div>
    <pre id="archer-logs-view"></pre>
  `;

  const view = document.getElementById("archer-logs-view");
  const pauseBtn = document.getElementById("archer-logs-pause");
  const clearBtn = document.getElementById("archer-logs-clear");
  const label = document.getElementById("archer-logs-label");

  let paused = false;
  // Only auto-scroll if the user hasn't deliberately scrolled up to read
  // back through history — otherwise new lines would keep yanking them
  // back to the bottom.
  const NEAR_BOTTOM_PX = 40;
  function isNearBottom() {
    return view.scrollHeight - view.scrollTop - view.clientHeight < NEAR_BOTTOM_PX;
  }

  const MAX_CHARS = 400000; // cap so a long session doesn't grow the DOM forever

  pauseBtn.addEventListener("click", () => {
    paused = !paused;
    pauseBtn.textContent = paused ? "Resume" : "Pause";
    label.textContent = paused ? "Paused." : "Tailing ARCHER's log...";
  });

  clearBtn.addEventListener("click", () => {
    view.textContent = "";
  });

  if (window.ArcherClient) {
    window.ArcherClient.on("logLine", (text) => {
      if (paused || !text) return;
      const stickToBottom = isNearBottom();
      view.textContent += text;
      if (view.textContent.length > MAX_CHARS) {
        view.textContent = view.textContent.slice(-MAX_CHARS);
      }
      if (stickToBottom) {
        view.scrollTop = view.scrollHeight;
      }
    });
  }
})();
