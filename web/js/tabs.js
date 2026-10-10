/**
 * ARCHER browser client — top-level tab switching.
 *
 * Plain show/hide, no framework: each `.tab-btn[data-tab]` toggles the
 * `.tab-panel` with the matching `#tab-<name>` id. The toolbar above the
 * tabs is NOT part of this — it's global/persistent across tabs (mode,
 * mic, camera, halt are app-wide state, not specific to Voice or
 * Gesture). Kept deliberately tiny so adding a Memory/Logs/Battle
 * Station tab later is just another button + panel + case in whatever
 * loads that tab's content.
 */
(() => {
  const buttons = document.querySelectorAll("#archer-tabs .tab-btn");
  const panels = document.querySelectorAll("#archer-tab-content .tab-panel");

  // Phase 1 Redesign (2026-10-06): 6 workspace tabs (FILES, ARTIFACTS, TOOLS,
  // AWAY & TASKS, SYSTEM, LOGS). Legacy names resolve to their new home:
  // gesture -> files; dashboard/voice -> artifacts; memory/tasks -> away_tasks;
  // logs -> logs; system -> system; tools -> tools.
  const ALIASES = {
    gesture: "files",
    dashboard: "artifacts",
    voice: "artifacts",
    memory: "away_tasks",
    tasks: "away_tasks",
    "away & tasks": "away_tasks",
    "away_tasks": "away_tasks",
    logs: "logs",
    system: "system",
    tools: "tools",
    files: "files",
    artifacts: "artifacts",
  };

  let activeTabName = "";

  function activate(name) {
    name = (name || "").toLowerCase().trim();
    name = ALIASES[name] || name;
    const known = Array.from(buttons).some((b) => b.dataset.tab === name);
    if (!known) {
      console.warn(`[archer] switch_tab: unknown tab "${name}" — ignoring.`);
      return;
    }
    activeTabName = name;
    buttons.forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    panels.forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));

    window.dispatchEvent(new CustomEvent("archer-tab-changed", { detail: { activeTab: name } }));
  }

  buttons.forEach((b) => b.addEventListener("click", () => activate(b.dataset.tab)));

  // Exposed so a voice/text command ("switch to the gesture tab") can drive
  // the same tab-switching logic as a manual click: the switch_tab agent
  // tool -> UI_SWITCH_TAB event -> server.py's "switch_tab" WS message ->
  // app.js's "switchTab" event -> here. See CONTRACT.md.
  window.ArcherTabs = { activate, getActiveTab: () => activeTabName };
  if (window.ArcherClient) {
    window.ArcherClient.on("switchTab", (tabName) => activate(tabName));
  }

  // Trigger initial tab activation on page load (default: artifacts per Q-07)
  const initialActive = Array.from(buttons).find((b) => b.classList.contains("active"));
  const initialTabName = initialActive ? initialActive.dataset.tab : "artifacts";
  setTimeout(() => activate(initialTabName), 50);
})();

