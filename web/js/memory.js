/**
 * ARCHER browser client — MEMORY card.
 *
 * Relationships (contacts/commitments, with add-contact/add-commitment
 * forms) removed 2026-09-16 per Col's explicit call -- he doesn't want a
 * dedicated input UI for that, and would rather manage that kind of
 * information as files through the barehands Notes pane instead (see
 * CONTRACT.md's barehands section). The backing SQLite tables/WS
 * messages (memory_add_contact etc.) are untouched in case a future
 * file-backed approach wants to read from them, just no longer surfaced
 * here.
 *
 * Learned Patterns (Known Entities + Recurring Themes) ALSO moved out of
 * this dashboard card on the same 2026-09-16 pass -- same reasoning, same
 * destination: it's now a file barehands' Notes pane can browse/edit
 * (barehands/sample-notes/ARCHER/Learned_Patterns.md), kept in sync by
 * notes_sync.py every time the underlying data changes. Nothing left in
 * this card is something you type into by hand:
 *
 * 1. While You Were Away: Blindspot interventions decided while you
 *    weren't in a conversation.
 *
 * (Unrecognized People -- recurring faces waiting on a name -- was here
 * too, removed 2026-09-19 per Col's call. Backend queueing in
 * person_id.py/pending_person_confirmations is untouched in case a future
 * UI wants to read from it; just nothing renders it here anymore.)
 *
 * Loads once the WebSocket connects, and re-renders automatically
 * whenever the server broadcasts a fresh memory_snapshot -- which
 * happens after every write, including ones made from a different open
 * tab/session.
 */
(() => {
  const panel = document.getElementById("tab-memory");
  if (!panel) return;

  panel.innerHTML = `
    <div id="archer-memory-root">
      <section class="archer-memory-pane" id="archer-memory-interventions">
        <h3>While You Were Away</h3>
        <p class="archer-memory-hint">Everything Blindspot has flagged as worth mentioning -- decided by the always-on observer service whether or not the desktop app or browser was open at the time. Delivered items have already been folded into a conversation; pending ones are queued for the next one.</p>
        <div id="archer-memory-interventions-list"></div>
      </section>
    </div>
  `;

  const interventionsList = document.getElementById("archer-memory-interventions-list");

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function renderInterventions(interventions) {
    if (!interventions || !interventions.length) {
      interventionsList.innerHTML = '<p class="archer-memory-empty">Nothing flagged yet.</p>';
      return;
    }
    interventionsList.innerHTML = interventions.map((iv) => `
      <div class="archer-memory-row">
        <div class="archer-memory-row-main">
          <strong>${escapeHtml(iv.category)}</strong>
          <span class="archer-memory-tag">${escapeHtml(iv.metric)}</span>
          <span class="archer-memory-tag archer-memory-status-${iv.delivered_at ? "delivered" : "pending"}">${iv.delivered_at ? "delivered" : "pending"}</span>
        </div>
        <div class="archer-memory-row-sub">${escapeHtml(iv.content)}</div>
        <div class="archer-memory-row-sub">${escapeHtml(iv.created_at)}</div>
      </div>
    `).join("");
  }

  if (window.ArcherClient) {
    window.ArcherClient.on("memorySnapshot", (data) => {
      renderInterventions(data.interventions);
    });
  }

  // Consolidated 2026-09-16: MEMORY is now a card on the always-visible
  // Dashboard tab, not its own lazily-opened tab. Load once the
  // WebSocket is actually open (this file runs before DOMContentLoaded
  // fires ArcherClient.connect(), so calling this at parse time would
  // silently no-op against a socket that isn't OPEN yet).
  let loaded = false;
  function ensureLoaded() {
    if (loaded) return;
    loaded = true;
    if (window.ArcherClient) window.ArcherClient.sendMemoryGetAll();
  }
  if (window.ArcherClient) window.ArcherClient.on("connected", ensureLoaded);
})();
