/**
 * ARCHER browser client — TASKS card.
 *
 * Cut down to a plain read-only list (2026-09-16, Col's call): "There
 * should only be tasks that I need to do" -- no add-task input table on
 * the dashboard, and Habits dropped from here entirely. Task/habit
 * CREATION and management now happens either by voice/text (tasks_SKILL.md
 * -- add_task, complete_habit, etc., unchanged) or as a file through the
 * barehands Notes pane (see notes_sync.py, which mirrors the same SQLite
 * tables this card reads out to barehands/sample-notes/ARCHER/Tasks.md and
 * Habits.md on every change). This card is just "what's actually open
 * right now, at a glance" -- you can still mark one done from here (that's
 * a checkbox tap, not an input form), but nothing here is typed into.
 *
 * Loads once the WebSocket connects; re-renders on every tasks_snapshot
 * broadcast (which fires from any surface that changes a task/habit).
 */
(() => {
  const panel = document.getElementById("tab-tasks");
  if (!panel) return;

  panel.innerHTML = `
    <div id="archer-tasks-root">
      <section class="archer-memory-pane" id="archer-tasks-tasks">
        <h3>Tasks</h3>
        <p class="archer-memory-hint">What's open right now. Add/edit by voice ("add a task to...") or as a file in barehands' Notes pane.</p>
        <div id="archer-tasks-list"></div>
      </section>
    </div>
  `;

  const tasksList = document.getElementById("archer-tasks-list");

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function renderTasks(tasks) {
    const open = (tasks || []).filter((t) => t.status !== "completed");
    if (!open.length) {
      tasksList.innerHTML = '<p class="archer-memory-empty">Nothing on your list.</p>';
      return;
    }
    tasksList.innerHTML = open.map((t) => `
      <div class="archer-memory-row">
        <div class="archer-memory-row-main">
          <label class="archer-tasks-check">
            <input type="checkbox" data-complete="${t.id}" />
            <strong>${escapeHtml(t.title)}</strong>
          </label>
        </div>
        ${t.due_date ? `<div class="archer-memory-row-sub">Due ${escapeHtml(t.due_date)}</div>` : ""}
      </div>
    `).join("");

    tasksList.querySelectorAll("[data-complete]").forEach((box) => {
      box.addEventListener("change", () => window.ArcherClient.sendTasksComplete(parseInt(box.dataset.complete, 10)));
    });
  }

  if (window.ArcherClient) {
    window.ArcherClient.on("tasksSnapshot", (data) => renderTasks(data.tasks));
  }

  // Consolidated 2026-09-16: TASKS is now a card on the always-visible
  // Dashboard tab, not its own lazily-opened tab -- so there's no "first
  // time you open it" click to gate on anymore. Load once the WebSocket
  // is actually open rather than at script-parse time (this file runs
  // before DOMContentLoaded fires ArcherClient.connect(), so the socket
  // isn't open yet here -- sendTasksGetAll() would silently no-op).
  let loaded = false;
  function ensureLoaded() {
    if (loaded) return;
    loaded = true;
    if (window.ArcherClient) window.ArcherClient.sendTasksGetAll();
  }
  if (window.ArcherClient) window.ArcherClient.on("connected", ensureLoaded);
})();
