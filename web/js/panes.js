/**
 * ARCHER Workspace Resizable & Movable Panes (Spec 4c).
 * Uses GridStack.js (MIT, vendored in /static/vendor/gridstack/).
 * Preserves persistent DOM elements so <video> and <iframe> never reload.
 */
(() => {
  'use strict';

  const STORAGE_KEY = 'archer.layout.v1';

  const DEFAULT_LAYOUT = [
    { id: 'pane-chat', x: 0, y: 0, w: 3, h: 5, minW: 2, minH: 3 },
    { id: 'pane-orb', x: 0, y: 5, w: 3, h: 3, minW: 2, minH: 2 },
    { id: 'pane-camera', x: 0, y: 8, w: 3, h: 3, minW: 2, minH: 2 },
    { id: 'pane-listening', x: 0, y: 11, w: 3, h: 2, minW: 2, minH: 2 },
    { id: 'pane-workspace', x: 3, y: 0, w: 9, h: 13, minW: 4, minH: 4 }
  ];

  let grid = null;

  function loadSavedLayout() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed.length > 0) {
          return parsed;
        }
      }
    } catch (e) {
      console.warn('[ArcherPanes] Failed reading saved layout:', e);
    }
    return DEFAULT_LAYOUT;
  }

  function saveCurrentLayout() {
    if (!grid) return;
    try {
      const items = grid.save(false);
      if (!Array.isArray(items)) return;
      const layoutData = items.map(item => ({
        id: item.id,
        x: item.x,
        y: item.y,
        w: item.w,
        h: item.h,
        minW: item.minW,
        minH: item.minH
      }));
      localStorage.setItem(STORAGE_KEY, JSON.stringify(layoutData));
      console.log('[ArcherPanes] Layout saved to localStorage.');
    } catch (e) {
      console.warn('[ArcherPanes] Failed saving layout:', e);
    }
  }

  function resetLayout() {
    if (!grid) return;
    try {
      localStorage.removeItem(STORAGE_KEY);
      DEFAULT_LAYOUT.forEach(item => {
        const el = document.getElementById(item.id);
        if (el) {
          grid.update(el, { x: item.x, y: item.y, w: item.w, h: item.h });
        }
      });
      window.dispatchEvent(new Event('resize'));
      console.log('[ArcherPanes] Layout reset to default.');
    } catch (e) {
      console.warn('[ArcherPanes] Failed resetting layout:', e);
    }
  }

  function initPanes() {
    const container = document.getElementById('archer-main-layout');
    if (!container || typeof GridStack === 'undefined') {
      console.warn('[ArcherPanes] GridStack not loaded or #archer-main-layout missing.');
      return;
    }

    const availableHeight = Math.max(window.innerHeight - 100, 600);
    const cellHeight = Math.max(Math.floor(availableHeight / 14), 48);

    grid = GridStack.init({
      column: 12,
      cellHeight: cellHeight,
      animate: true,
      handle: '.archer-pane-header',
      resizable: { handles: 'all' },
      margin: 6,
      disableOneColumnMode: true
    }, container);

    // Apply saved positions
    const saved = loadSavedLayout();
    if (saved && saved.length > 0) {
      saved.forEach(item => {
        const el = document.getElementById(item.id);
        if (el) {
          grid.update(el, { x: item.x, y: item.y, w: item.w, h: item.h });
        }
      });
    }

    // Save on drag/resize changes
    grid.on('change', () => {
      saveCurrentLayout();
    });

    grid.on('dragstart resizestart', () => {
      document.body.classList.add('grid-stack-dragging');
    });

    grid.on('dragstop resizestop', () => {
      document.body.classList.remove('grid-stack-dragging');
      saveCurrentLayout();
      window.dispatchEvent(new Event('resize'));
    });

    // Reset layout button listener
    const resetBtn = document.getElementById('archer-reset-layout-btn');
    if (resetBtn) {
      resetBtn.addEventListener('click', resetLayout);
    }

    // Expose API on window
    window.ArcherPanes = {
      grid,
      save: saveCurrentLayout,
      reset: resetLayout
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPanes);
  } else {
    initPanes();
  }
})();
