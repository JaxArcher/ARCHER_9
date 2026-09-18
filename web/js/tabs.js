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

  // Consolidated 2026-09-16: voice/logs/memory/tasks/system all merged
  // into one Dashboard tab (see index.html's comment). Old names still
  // resolve here rather than failing silently -- covers a stale
  // switch_tab tool call, a saved voice-command habit ("switch to the
  // memory tab"), or anything else still using a pre-merge name.
  const ALIASES = {
    voice: "dashboard",
    logs: "dashboard",
    memory: "dashboard",
    tasks: "dashboard",
    system: "dashboard",
  };

  function activate(name) {
    name = ALIASES[name] || name;
    const known = Array.from(buttons).some((b) => b.dataset.tab === name);
    if (!known) {
      console.warn(`[archer] switch_tab: unknown tab "${name}" — ignoring.`);
      return;
    }
    buttons.forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    panels.forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
  }

  buttons.forEach((b) => b.addEventListener("click", () => activate(b.dataset.tab)));

  // Exposed so a voice/text command ("switch to the gesture tab") can drive
  // the same tab-switching logic as a manual click: the switch_tab agent
  // tool -> UI_SWITCH_TAB event -> server.py's "switch_tab" WS message ->
  // app.js's "switchTab" event -> here. See CONTRACT.md.
  window.ArcherTabs = { activate };
  if (window.ArcherClient) {
    window.ArcherClient.on("switchTab", (tabName) => activate(tabName));
  }
})();
