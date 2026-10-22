/**
 * ARCHER browser client — Global MediaPipe Hand Tracker & Cursor Effects.
 *
 * Phase 2 Redesign + 2026-10-21 Review Queue Item 4:
 * - The ring follows the mouse whenever the mouse moves.
 * - Mouse wins: any mouse movement locks out hand tracking for 2 seconds.
 * - Hand tracking takes over only when mouse is idle > 2s and hand moves > 40px or pinches.
 * - There is always a cursor: native cursor restored over inputs/iframes/window exit,
 *   and ring is always visible when moving over the page.
 * - MediaPipe tasks-vision v0.10.14 vendored locally from /static/vendor/tasks-vision/.
 * - Gestures: hover moves cursor; quick pinch (<350ms) = click; pinch-and-drag = scroll area under cursor.
 * - Pauses global tracking while the FILES tab is active (barehands iframe takes over).
 * - Toggle button (#archer-cursor-toggle) saved per browser in localStorage.
 */
import { HandLandmarker, FilesetResolver } from "/static/vendor/tasks-vision/vision_bundle.mjs";

(() => {
  'use strict';

  const key = 'archer.cursor.enabled';
  const fine = matchMedia('(any-hover: hover) and (any-pointer: fine)');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');

  let enabled = true;
  try { enabled = localStorage.getItem(key) !== 'false'; } catch (_) {}

  const root = document.documentElement;

  // Ensure cursor DOM element exists
  let cursor = document.getElementById('archer-cursor');
  if (!cursor) {
    cursor = document.createElement('div');
    cursor.id = 'archer-cursor';
    cursor.setAttribute('aria-hidden', 'true');
    cursor.innerHTML = '<i class="ac-ring ac-one"></i><i class="ac-ring ac-two"></i><i class="ac-ring ac-three"></i><i class="ac-core"></i>';
    document.body.append(cursor);
  }

  // 8-dot trail elements
  const trails = Array.from({ length: 8 }, () => {
    const dot = document.createElement('i');
    dot.className = 'archer-cursor-trail';
    dot.setAttribute('aria-hidden', 'true');
    document.body.append(dot);
    return dot;
  });

  let trailIndex = 0;
  let lastTrail = 0;
  let clickTimer = null;

  const button = document.getElementById('archer-cursor-toggle');

  function syncFrame() {
    const frame = document.getElementById('archer-barehands-frame');
    if (frame && frame.contentWindow) {
      try {
        frame.contentWindow.postMessage({ type: 'archer-cursor-setting', enabled }, new URL(frame.src).origin);
      } catch (_) {}
    }
  }

  function refreshButtonUI() {
    if (button) {
      button.setAttribute('aria-pressed', String(enabled));
      button.textContent = `CURSOR FX: ${enabled ? 'ON' : 'OFF'}`;
      button.title = reduced.matches ? 'Cursor effects paused by your reduced-motion preference' : 'Toggle animated cursor effects';
    }
    syncFrame();
  }

  function saveEnabled(val) {
    enabled = val;
    try { localStorage.setItem(key, String(val)); } catch (_) {}
    refreshButtonUI();
    if (!enabled) hideCursor();
  }

  button?.addEventListener('click', () => saveEnabled(!enabled));
  fine.addEventListener('change', refreshButtonUI);
  reduced.addEventListener('change', refreshButtonUI);
  refreshButtonUI();

  window.addEventListener('storage', (event) => {
    if (event.key === key) {
      enabled = event.newValue !== 'false';
      refreshButtonUI();
    }
  });

  window.addEventListener('message', (event) => {
    const frame = document.getElementById('archer-barehands-frame');
    if (frame && event.source === frame.contentWindow && event.data?.type === 'archer-cursor-ready') {
      syncFrame();
    }
  });

  function hideCursor() {
    root.classList.remove('archer-cursor-active');
    cursor.classList.remove('ac-visible', 'ac-click', 'ac-hover');
    trails.forEach(dot => {
      try {
        dot.getAnimations().forEach(anim => anim.cancel());
      } catch (_) {}
    });
  }

  function showCursor(x, y, isHover, isClick) {
    if (!enabled || isFilesTabActive || reduced.matches) {
      hideCursor();
      return;
    }
    root.classList.add('archer-cursor-active');
    cursor.classList.add('ac-visible');
    cursor.classList.toggle('ac-hover', !!isHover);
    cursor.classList.toggle('ac-click', !!isClick);
    cursor.style.left = `${x}px`;
    cursor.style.top = `${y}px`;
  }

  function spawnTrailDot(x, y) {
    if (!enabled || isFilesTabActive || reduced.matches) return;
    const now = performance.now();
    if (now - lastTrail > 35) {
      lastTrail = now;
      const dot = trails[trailIndex++ % trails.length];
      try {
        dot.getAnimations().forEach(anim => anim.cancel());
      } catch (_) {}
      dot.style.left = `${x}px`;
      dot.style.top = `${y}px`;
      dot.animate([
        { opacity: 0.45, transform: 'translate(-50%, -50%) scale(1)' },
        { opacity: 0, transform: 'translate(-50%, -50%) scale(0.2)' }
      ], { duration: 280 });
    }
  }

  let isFilesTabActive = false;
  window.addEventListener('archer-tab-changed', (evt) => {
    const activeTab = evt.detail && evt.detail.activeTab;
    isFilesTabActive = (activeTab === 'files' || activeTab === 'gesture');
    if (isFilesTabActive) {
      hideCursor();
    }
  });

  // Mouse Arbitration & State
  let lastMouseTime = 0;
  let lastMouseX = window.innerWidth / 2;
  let lastMouseY = window.innerHeight / 2;
  const MOUSE_OVERRIDE_TIMEOUT_MS = 2000;

  // Hand Tracking State
  let handLandmarker = null;
  let videoEl = document.getElementById('archer-system-camera-feed');
  let lastVideoTime = -1;
  let handTrackingActive = false;
  let lastHandX = window.innerWidth / 2;
  let lastHandY = window.innerHeight / 2;

  // Gesture State
  const PINCH_THRESHOLD = 0.28;
  let isPinched = false;
  let pinchStartTime = 0;
  let pinchStartX = 0;
  let pinchStartY = 0;
  let isDragging = false;

  // --- Mouse Listeners ---
  document.addEventListener('pointermove', (event) => {
    if (event.pointerType && event.pointerType !== 'mouse') return;

    lastMouseTime = performance.now();
    lastMouseX = event.clientX;
    lastMouseY = event.clientY;
    handTrackingActive = false; // Mouse wins immediately

    const target = event.target instanceof Element ? event.target : null;
    if (!enabled || !fine.matches || reduced.matches ||
        target?.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"]), iframe, [data-native-cursor]')) {
      hideCursor();
      return;
    }

    const isHover = !!target?.closest('button, a, select, input, .tab-btn, [role="button"]');
    showCursor(event.clientX, event.clientY, isHover, false);
    spawnTrailDot(event.clientX, event.clientY);
  }, { passive: true });

  document.addEventListener('pointerdown', (event) => {
    if (event.pointerType && event.pointerType !== 'mouse') return;
    lastMouseTime = performance.now();
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"]), iframe, [data-native-cursor]')) {
      hideCursor();
      return;
    }
    cursor.classList.add('ac-click');
    clearTimeout(clickTimer);
    clickTimer = setTimeout(() => cursor.classList.remove('ac-click'), 180);
  }, { passive: true });

  document.documentElement.addEventListener('pointerleave', hideCursor);
  window.addEventListener('blur', hideCursor);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) hideCursor();
  });
  document.addEventListener('keydown', (event) => {
    if (['Escape', 'Tab'].includes(event.key)) hideCursor();
  });

  // --- MediaPipe Hand Tracker ---
  async function initHandLandmarker() {
    try {
      console.log('[ArcherTracker] Initializing local MediaPipe tasks-vision...');
      const vision = await FilesetResolver.forVisionTasks('/static/vendor/tasks-vision/wasm');
      handLandmarker = await HandLandmarker.createFromOptions(vision, {
        baseOptions: {
          modelAssetPath: '/static/vendor/tasks-vision/hand_landmarker.task',
          delegate: 'GPU'
        },
        runningMode: 'VIDEO',
        numHands: 1
      });
      console.log('[ArcherTracker] MediaPipe HandLandmarker ready.');
      requestAnimationFrame(predictLoop);
    } catch (err) {
      console.warn('[ArcherTracker] Could not initialize MediaPipe HandLandmarker:', err);
    }
  }

  function distance(p1, p2) {
    const dx = p1.x - p2.x;
    const dy = p1.y - p2.y;
    const dz = (p1.z || 0) - (p2.z || 0);
    return Math.sqrt(dx * dx + dy * dy + dz * dz);
  }

  function getScrollableParent(el) {
    let current = el;
    while (current && current !== document.body && current !== document.documentElement) {
      const style = window.getComputedStyle(current);
      const overflowY = style.overflowY;
      const isScrollable = (overflowY === 'auto' || overflowY === 'scroll') && current.scrollHeight > current.clientHeight;
      if (isScrollable) return current;
      current = current.parentElement;
    }
    return window;
  }

  function dispatchClick(x, y) {
    const target = document.elementFromPoint(x, y);
    if (!target) return;
    console.log('[ArcherTracker] Gesture click dispatched to:', target);

    const opts = { clientX: x, clientY: y, bubbles: true, cancelable: true, view: window };
    target.dispatchEvent(new PointerEvent('pointerdown', opts));
    target.dispatchEvent(new MouseEvent('mousedown', opts));
    target.dispatchEvent(new PointerEvent('pointerup', opts));
    target.dispatchEvent(new MouseEvent('mouseup', opts));
    target.click();
  }

  function predictLoop() {
    if (!videoEl) videoEl = document.getElementById('archer-system-camera-feed');

    const now = performance.now();
    const isMouseActive = (now - lastMouseTime) < MOUSE_OVERRIDE_TIMEOUT_MS;

    if (handLandmarker && videoEl && videoEl.readyState >= 2 && !isFilesTabActive && enabled && !reduced.matches) {
      if (videoEl.currentTime !== lastVideoTime) {
        lastVideoTime = videoEl.currentTime;
        const results = handLandmarker.detectForVideo(videoEl, now);

        if (results && results.landmarks && results.landmarks.length > 0) {
          const landmarks = results.landmarks[0];

          // Index tip (landmark 8)
          const rawX = landmarks[8].x;
          const rawY = landmarks[8].y;

          // Video is mirrored horizontally
          const targetX = (1.0 - rawX) * window.innerWidth;
          const targetY = rawY * window.innerHeight;

          // Pinch distance ratio (Index tip #8 to Thumb tip #4 vs Wrist #0 to Middle MCP #9)
          const pThumb = landmarks[4];
          const pIndex = landmarks[8];
          const pWrist = landmarks[0];
          const pMiddleMcp = landmarks[9];

          const pinchDist = distance(pThumb, pIndex);
          const handSpan = distance(pWrist, pMiddleMcp);
          const ratio = handSpan > 0 ? (pinchDist / handSpan) : 1.0;
          const currentlyPinched = ratio < PINCH_THRESHOLD;

          // Mouse wins: if mouse was moved within last 2s, completely ignore hand landmarks
          if (!isMouseActive) {
            // Hand takeover check: must move > 40px or pinch to take over from last position
            const distFromLast = Math.hypot(targetX - lastHandX, targetY - lastHandY);
            if (!handTrackingActive) {
              if (distFromLast > 40 || currentlyPinched) {
                handTrackingActive = true;
                lastHandX = targetX;
                lastHandY = targetY;
              }
            }

            if (handTrackingActive) {
              // Smooth cursor interpolation
              const cursorX = lastHandX + (targetX - lastHandX) * 0.45;
              const cursorY = lastHandY + (targetY - lastHandY) * 0.45;

              const targetEl = document.elementFromPoint(cursorX, cursorY);
              const isHover = !!targetEl?.closest('button, a, select, input, .tab-btn, [role="button"]');

              if (currentlyPinched && !isPinched) {
                // Pinch Start
                isPinched = true;
                pinchStartTime = now;
                pinchStartX = cursorX;
                pinchStartY = cursorY;
                isDragging = false;
              } else if (currentlyPinched && isPinched) {
                // Pinch Hold / Drag / Scroll
                const deltaY = cursorY - lastHandY;
                const moveDist = Math.hypot(cursorX - pinchStartX, cursorY - pinchStartY);

                if (moveDist > 12) {
                  isDragging = true;
                  const scrollTarget = getScrollableParent(targetEl);
                  if (scrollTarget === window) {
                    window.scrollBy(0, -deltaY * 2.5);
                  } else if (scrollTarget && scrollTarget.scrollBy) {
                    scrollTarget.scrollBy({ top: -deltaY * 2.5, behavior: 'instant' });
                  }
                }
              } else if (!currentlyPinched && isPinched) {
                // Pinch End
                const pinchDuration = now - pinchStartTime;
                if (pinchDuration < 350 && !isDragging) {
                  dispatchClick(cursorX, cursorY);
                }
                isPinched = false;
                isDragging = false;
              }

              showCursor(cursorX, cursorY, isHover, isPinched);
              spawnTrailDot(cursorX, cursorY);
              lastHandX = cursorX;
              lastHandY = cursorY;
            }
          }
        } else {
          // No hand landmarks detected
          handTrackingActive = false;
          isPinched = false;
          isDragging = false;
          if (!isMouseActive) {
            hideCursor();
          }
        }
      }
    } else if (isFilesTabActive || !enabled || reduced.matches) {
      hideCursor();
    }

    requestAnimationFrame(predictLoop);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHandLandmarker);
  } else {
    initHandLandmarker();
  }
})();
