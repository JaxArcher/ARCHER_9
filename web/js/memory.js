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
 * 2. Unrecognized People: recurring faces waiting on a name.
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

      <section class="archer-memory-pane" id="archer-memory-pending-people">
        <h3>Unrecognized People</h3>
        <p class="archer-memory-hint">Faces the camera keeps seeing but can't put a name to. Type a name to enroll them (no separate enrollment step needed), or dismiss a one-off visitor you don't want remembered. Saying "this is &lt;name&gt;" out loud while they're in frame does this automatically -- this list is only for whoever nobody's introduced yet.</p>
        <div id="archer-memory-pending-people-list"></div>
      </section>
    </div>
  `;

  const interventionsList = document.getElementById("archer-memory-interventions-list");
  const pendingPeopleList = document.getElementById("archer-memory-pending-people-list");

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

  function renderPendingPeople(people) {
    if (!people || !people.length) {
      pendingPeopleList.innerHTML = '<p class="archer-memory-empty">Nobody unrecognized right now.</p>';
      return;
    }
    pendingPeopleList.innerHTML = people.map((p) => `
      <div class="archer-memory-row" data-id="${p.id}">
        <div class="archer-memory-row-main">
          ${p.snapshot_data_uri
            ? `<img class="archer-memory-person-thumb" src="${p.snapshot_data_uri}" alt="Unrecognized person" />`
            : ""}
          <strong>${escapeHtml(p.person_id)}</strong>
          <span class="archer-memory-count">seen ${p.sighting_count}x</span>
        </div>
        <div class="archer-memory-row-sub">Last seen: ${escapeHtml(p.last_seen_at)}</div>
        <form class="archer-memory-form archer-memory-confirm-person-form" data-id="${p.id}">
          <input type="text" class="archer-memory-person-name-input" placeholder="Who is this?" required />
          <button type="submit">Enroll</button>
          <button type="button" class="archer-memory-dismiss-person-btn" data-id="${p.id}">Dismiss</button>
        </form>
      </div>
    `).join("");

    pendingPeopleList.querySelectorAll(".archer-memory-confirm-person-form").forEach((form) => {
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        const input = form.querySelector(".archer-memory-person-name-input");
        const name = input.value.trim();
        if (!name) return;
        window.ArcherClient.sendMemoryConfirmPerson(parseInt(form.dataset.id, 10), name);
      });
    });
    pendingPeopleList.querySelectorAll(".archer-memory-dismiss-person-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        window.ArcherClient.sendMemoryDismissPerson(parseInt(btn.dataset.id, 10));
      });
    });
  }

  if (window.ArcherClient) {
    window.ArcherClient.on("memorySnapshot", (data) => {
      renderInterventions(data.interventions);
      renderPendingPeople(data.pendingPeople);
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
