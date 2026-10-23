/**
 * ARCHER browser client — TOOLS tab renderer (Spec Section 11a Tool Chest).
 * Displays ARCHER's Tool Chest registry with where each tool runs and availability status.
 */
(() => {
  const panel = document.getElementById("tab-tools");
  if (!panel) return;

  let allTools = [];
  let summary = {};
  let currentFilter = "all";

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function renderView() {
    const filtered = currentFilter === "all" ? allTools : allTools.filter(t => t.target.toLowerCase() === currentFilter.toLowerCase());

    panel.innerHTML = `
      <div class="archer-dashboard-card archer-tools-card">
        <div class="tools-chest-header">
          <div class="tools-title-group">
            <h3>ARCHER's Tool Chest</h3>
            <p class="archer-memory-hint">
              ARCHER's default move on tasks is to reach for its tool chest.
              <strong>LENNY is the default bench</strong> for programs, Office, browsing, and mouse/keyboard.
            </p>
          </div>
          <div class="tools-bench-pills">
            <button class="bench-pill ${currentFilter === 'all' ? 'active' : ''}" data-filter="all">
              All (${allTools.length})
            </button>
            <button class="bench-pill ${currentFilter === 'lenny' ? 'active' : ''}" data-filter="lenny">
              LENNY (${summary.lenny || 0}) ${summary.lenny_online ? '🟢' : '⚪'}
            </button>
            <button class="bench-pill ${currentFilter === 'beast' ? 'active' : ''}" data-filter="beast">
              Beast (${summary.beast || 0})
            </button>
            <button class="bench-pill ${currentFilter === 'antigravity' ? 'active' : ''}" data-filter="antigravity">
              Antigravity (${summary.antigravity || 0})
            </button>
            <button class="bench-pill ${currentFilter === 'telegram' ? 'active' : ''}" data-filter="telegram">
              Telegram (${summary.telegram || 0})
            </button>
          </div>
        </div>

        <div class="tools-search-bar">
          <input type="text" id="tool-chest-search" placeholder="Type a task to test Tool Chest matching (e.g. 'make a spreadsheet of my bills')..." />
          <div id="tool-chest-routed-notice" class="routed-notice" style="display:none;"></div>
        </div>

        <div class="archer-tools-list">
          ${filtered.length ? filtered.map(t => {
            const availDot = t.is_available ? 'dot-available' : 'dot-unavailable';
            const targetClass = `target-${t.target.toLowerCase()}`;
            const apprClass = t.needs_approval ? 'appr-needed' : 'appr-exempt';
            const apprLabel = t.needs_approval ? 'Approval Required' : 'Pre-Approved';

            return `
              <div class="archer-tool-item">
                <div class="archer-tool-header">
                  <div class="tool-name-wrap">
                    <span class="tool-avail-dot ${availDot}" title="${t.is_available ? 'Available' : 'Unavailable'}"></span>
                    <span class="archer-tool-name">${escapeHtml(t.name)}</span>
                    <span class="tool-bench-badge ${targetClass}">Bench: ${escapeHtml(t.target)}</span>
                  </div>
                  <span class="tool-appr-badge ${apprClass}">${apprLabel}</span>
                </div>
                <div class="archer-tool-desc">${escapeHtml(t.description)}</div>
                <div class="tool-call-sig"><code>${escapeHtml(t.how_to_call)}</code></div>
              </div>
            `;
          }).join("") : `<p class="archer-memory-empty">No tools found matching filter '${escapeHtml(currentFilter)}'.</p>`}
        </div>
      </div>
    `;

    bindActions();
  }

  function bindActions() {
    panel.querySelectorAll(".bench-pill").forEach(btn => {
      btn.addEventListener("click", () => {
        currentFilter = btn.dataset.filter;
        renderView();
      });
    });

    const searchInput = document.getElementById("tool-chest-search");
    const routedNotice = document.getElementById("tool-chest-routed-notice");
    if (searchInput) {
      searchInput.addEventListener("input", async (e) => {
        const val = e.target.value.trim();
        if (!val) {
          if (routedNotice) routedNotice.style.display = "none";
          return;
        }
        try {
          const res = await fetch("/api/tool_chest/find", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ task: val }),
          });
          if (res.ok) {
            const data = await res.json();
            if (routedNotice) {
              if (data.routed) {
                routedNotice.style.display = "block";
                routedNotice.innerHTML = `<strong>Auto-Routed:</strong> ${escapeHtml(data.routed.tool)} on <strong>${escapeHtml(data.routed.target)}</strong> — <em>${escapeHtml(data.routed.reason)}</em>`;
              } else if (data.matches && data.matches.length) {
                routedNotice.style.display = "block";
                routedNotice.innerHTML = `<strong>Best Match:</strong> ${escapeHtml(data.matches[0].name)} on <strong>${escapeHtml(data.matches[0].target)}</strong> (${escapeHtml(data.matches[0].description)})`;
              } else {
                routedNotice.style.display = "block";
                routedNotice.innerHTML = `<em>"I don't have a tool for that yet. Would you like me to research and propose a new tool in the R&D tab?"</em>`;
              }
            }
          }
        } catch (err) {
          console.warn("[archer] Tool chest find error:", err);
        }
      });
    }
  }

  async function loadToolChest() {
    try {
      const res = await fetch("/api/tool_chest");
      if (res.ok) {
        const data = await res.json();
        allTools = data.tools || [];
        summary = data.summary || {};
        renderView();
      } else {
        panel.innerHTML = `<p class="archer-memory-empty">Failed to load Tool Chest.</p>`;
      }
    } catch (e) {
      console.warn("[archer] Failed to fetch Tool Chest:", e);
    }
  }

  loadToolChest();

  window.addEventListener("archer-tab-changed", (evt) => {
    if (evt.detail && evt.detail.activeTab === "tools") {
      loadToolChest();
    }
  });
})();
