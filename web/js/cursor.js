/**
 * ARCHER browser client — Global MediaPipe Hand Tracker & Gestures.
 *
 * Phase 2 Redesign: Vendors Google MediaPipe tasks-vision v0.10.14 locally from /static/vendor/tasks-vision/.
 * - Runs on shared webcam video element (#archer-system-camera-feed).
 * - Draws animated cursor over the page via #archer-cursor.
 * - Gestures: hover moves cursor; quick pinch (<300ms) = click; pinch-and-drag = scroll area under cursor.
 * - Pauses global tracking while the FILES tab is active (barehands iframe takes over).
 * - Toggle button (#archer-cursor-toggle) saved per browser in localStorage.
 */
import { HandLandmarker, FilesetResolver } from "/static/vendor/tasks-vision/vision_bundle.mjs";

(() => {
  'use strict';
  
  const key = 'archer.cursor.enabled';
  let enabled = true;
  try { enabled = localStorage.getItem(key) !== 'false'; } catch (_) {}

  const root = document.documentElement;
  let cursor = document.getElementById('archer-cursor');
  if (!cursor) {
    cursor = document.createElement('div');
    cursor.id = 'archer-cursor';
    cursor.setAttribute('aria-hidden', 'true');
    cursor.innerHTML = '<i class="ac-ring ac-one"></i><i class="ac-ring ac-two"></i><i class="ac-ring ac-three"></i><i class="ac-core"></i>';
    document.body.append(cursor);
  }

  const button = document.getElementById('archer-cursor-toggle');
  
  function refreshButtonUI() {
    if (button) {
      button.setAttribute('aria-pressed', String(enabled));
      button.textContent = `CURSOR FX: ${enabled ? 'ON' : 'OFF'}`;
    }
  }

  function saveEnabled(val) {
    enabled = val;
    try { localStorage.setItem(key, String(val)); } catch (_) {}
    refreshButtonUI();
    if (!enabled) hideCursor();
  }

  button?.addEventListener('click', () => saveEnabled(!enabled));
  refreshButtonUI();

  function hideCursor() {
    root.classList.remove('archer-cursor-active');
    cursor.classList.remove('ac-visible', 'ac-click', 'ac-hover');
  }

  function showCursor(x, y, isHover, isClick) {
    if (!enabled || isFilesTabActive) {
      hideCursor();
      return;
    }
    root.classList.add('archer-cursor-active');
    cursor.classList.add('ac-visible');
    cursor.classList.toggle('ac-hover', isHover);
    cursor.classList.toggle('ac-click', isClick);
    cursor.style.left = `${x}px`;
    cursor.style.top = `${y}px`;
  }

  let isFilesTabActive = false;
  window.addEventListener('archer-tab-changed', (evt) => {
    const activeTab = evt.detail && evt.detail.activeTab;
    isFilesTabActive = (activeTab === 'files' || activeTab === 'gesture');
    if (isFilesTabActive) {
      hideCursor();
      console.log('[ArcherTracker] Global hand tracker paused for FILES tab.');
    } else {
      console.log('[ArcherTracker] Global hand tracker active.');
    }
  });

  // MediaPipe HandLandmarker Initialization & Loop
  let handLandmarker = null;
  let videoEl = document.getElementById('archer-system-camera-feed');
  let lastVideoTime = -1;

  // Gesture State
  const PINCH_THRESHOLD = 0.28;
  let isPinched = false;
  let pinchStartTime = 0;
  let pinchStartX = 0;
  let pinchStartY = 0;
  let lastCursorX = window.innerWidth / 2;
  let lastCursorY = window.innerHeight / 2;
  let isDragging = false;

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
    
    if (handLandmarker && videoEl && videoEl.readyState >= 2 && !isFilesTabActive && enabled) {
      if (videoEl.currentTime !== lastVideoTime) {
        lastVideoTime = videoEl.currentTime;
        const results = handLandmarker.detectForVideo(videoEl, performance.now());

        if (results && results.landmarks && results.landmarks.length > 0) {
          const landmarks = results.landmarks[0];
          
          // Index tip (landmark 8)
          const rawX = landmarks[8].x;
          const rawY = landmarks[8].y;
          
          // Video is mirrored horizontally
          const targetX = (1.0 - rawX) * window.innerWidth;
          const targetY = rawY * window.innerHeight;
          
          // Smooth cursor interpolation
          const cursorX = lastCursorX + (targetX - lastCursorX) * 0.45;
          const cursorY = lastCursorY + (targetY - lastCursorY) * 0.45;

          // Pinch distance ratio (Index tip #8 to Thumb tip #4 vs Wrist #0 to Middle MCP #9)
          const pThumb = landmarks[4];
          const pIndex = landmarks[8];
          const pWrist = landmarks[0];
          const pMiddleMcp = landmarks[9];

          const pinchDist = distance(pThumb, pIndex);
          const handSpan = distance(pWrist, pMiddleMcp);
          const ratio = handSpan > 0 ? (pinchDist / handSpan) : 1.0;

          const currentlyPinched = ratio < PINCH_THRESHOLD;
          const now = performance.now();

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
            const deltaX = cursorX - lastCursorX;
            const deltaY = cursorY - lastCursorY;
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
          lastCursorX = cursorX;
          lastCursorY = cursorY;
        } else {
          hideCursor();
        }
      }
    } else if (isFilesTabActive || !enabled) {
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
