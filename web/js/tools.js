/**
 * ARCHER browser client — TOOLS tab renderer.
 * Dynamically fetches and displays the list of skills discovered by skills_registry.py.
 */
(() => {
  const panel = document.getElementById("tab-tools");
  if (!panel) return;

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function renderTools(skills) {
    if (!skills || !skills.length) {
      panel.innerHTML = `
        <div class="archer-dashboard-card archer-tools-card">
          <h3>ARCHER Installed Skills & Tools</h3>
          <p class="archer-memory-empty">No skills currently discovered.</p>
        </div>
      `;
      return;
    }

    panel.innerHTML = `
      <div class="archer-dashboard-card archer-tools-card">
        <h3>ARCHER Installed Skills & Tools</h3>
        <p class="archer-memory-hint">Dynamically loaded from <code>skills_registry.py</code>. Installed tool pool additions will join this list.</p>
        <div class="archer-tools-list">
          ${skills.map(s => `
            <div class="archer-tool-item">
              <div class="archer-tool-header">
                <span class="archer-tool-name">${escapeHtml(s.name || s.file_name)}</span>
                <span class="archer-memory-tag">${escapeHtml(s.category)}</span>
              </div>
              <div class="archer-tool-file">${escapeHtml(s.file_name)} (${s.tool_count} tool${s.tool_count === 1 ? '' : 's'})</div>
              <div class="archer-tool-desc">${escapeHtml(s.description)}</div>
            </div>
          `).join("")}
        </div>
      </div>
    `;
  }

  async function loadSkills() {
    try {
      const res = await fetch("/api/skills");
      if (res.ok) {
        const data = await res.json();
        renderTools(data.skills);
      } else {
        panel.innerHTML = `<p class="archer-memory-empty">Failed to load skills list.</p>`;
      }
    } catch (e) {
      console.warn("[archer] Failed to fetch skills:", e);
    }
  }

  loadSkills();

  window.addEventListener("archer-tab-changed", (evt) => {
    if (evt.detail && evt.detail.activeTab === "tools") {
      loadSkills();
    }
  });
})();
