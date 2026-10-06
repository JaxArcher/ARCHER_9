/* Dependency-free HUD pointer. Keep barehands/assets/cursor.js in sync. */
(() => {
  'use strict';
  if (document.getElementById('archer-cursor')) return;
  const key = 'archer.cursor.enabled';
  const fine = matchMedia('(any-hover: hover) and (any-pointer: fine)');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let enabled = true;
  try { enabled = localStorage.getItem(key) !== 'false'; } catch (_) {}
  const root = document.documentElement;
  const cursor = document.createElement('div');
  cursor.id = 'archer-cursor';
  cursor.setAttribute('aria-hidden', 'true');
  cursor.innerHTML = '<i class="ac-ring ac-one"></i><i class="ac-ring ac-two"></i><i class="ac-ring ac-three"></i><i class="ac-core"></i>';
  document.body.append(cursor);
  const trails = Array.from({length: 8}, () => {
    const dot = document.createElement('i');
    dot.className = 'archer-cursor-trail';
    dot.setAttribute('aria-hidden', 'true');
    document.body.append(dot);
    return dot;
  });
  const button = document.getElementById('archer-cursor-toggle');
  let trailIndex = 0, lastTrail = 0, clickTimer;
  let parentOrigin = null;
  if (window.parent !== window && document.referrer) {
    const ref = new URL(document.referrer);
    if (ref.hostname === location.hostname && /^https?:$/.test(ref.protocol)) parentOrigin = ref.origin;
  }
  function hide() {
    root.classList.remove('archer-cursor-active');
    cursor.classList.remove('ac-visible', 'ac-click');
    trails.forEach(dot => dot.getAnimations().forEach(animation => animation.cancel()));
  }
  function syncFrame() {
    const frame = document.getElementById('archer-barehands-frame');
    if (frame && frame.contentWindow) {
      frame.contentWindow.postMessage({type: 'archer-cursor-setting', enabled}, new URL(frame.src).origin);
    }
  }
  function refresh() {
    hide();
    if (button) {
      button.setAttribute('aria-pressed', String(enabled));
      button.textContent = `CURSOR FX: ${enabled ? 'ON' : 'OFF'}`;
      button.title = reduced.matches ? 'Cursor effects paused by your reduced-motion preference' : 'Toggle animated cursor effects';
    }
    syncFrame();
  }
  function save(value) {
    enabled = value;
    try { localStorage.setItem(key, String(value)); } catch (_) {}
    refresh();
  }
  button?.addEventListener('click', () => save(!enabled));
  fine.addEventListener('change', refresh);
  reduced.addEventListener('change', refresh);
  window.addEventListener('storage', event => { if (event.key === key) { enabled = event.newValue !== 'false'; refresh(); } });
  window.addEventListener('message', event => {
    if (parentOrigin && event.source === window.parent && event.origin === parentOrigin && event.data?.type === 'archer-cursor-setting' && typeof event.data.enabled === 'boolean') {
      save(event.data.enabled);
    }
    const frame = document.getElementById('archer-barehands-frame');
    if (frame && event.source === frame.contentWindow && event.origin === new URL(frame.src).origin && event.data?.type === 'archer-cursor-ready') syncFrame();
  });
  document.addEventListener('pointermove', event => {
    const target = event.target instanceof Element ? event.target : null;
    if (!enabled || !fine.matches || reduced.matches || event.pointerType !== 'mouse' ||
        target?.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"]), iframe, [data-native-cursor]')) {
      hide(); return;
    }
    root.classList.add('archer-cursor-active');
    cursor.classList.add('ac-visible');
    cursor.classList.toggle('ac-hover', !!target?.closest('button, a, [role="button"]'));
    cursor.style.left = `${event.clientX}px`;
    cursor.style.top = `${event.clientY}px`;
    if (performance.now() - lastTrail > 35) {
      lastTrail = performance.now();
      const dot = trails[trailIndex++ % trails.length];
      dot.getAnimations().forEach(animation => animation.cancel());
      dot.style.left = `${event.clientX}px`; dot.style.top = `${event.clientY}px`;
      dot.animate([{opacity: .45, transform: 'translate(-50%,-50%) scale(1)'}, {opacity: 0, transform: 'translate(-50%,-50%) scale(.2)'}], {duration: 280});
    }
  }, {passive: true});
  document.addEventListener('pointerdown', event => {
    if (event.pointerType !== 'mouse') { hide(); return; }
    cursor.classList.add('ac-click');
    clearTimeout(clickTimer);
    clickTimer = setTimeout(() => cursor.classList.remove('ac-click'), 180);
  }, {passive: true});
  document.documentElement.addEventListener('pointerleave', hide);
  window.addEventListener('blur', hide);
  document.addEventListener('visibilitychange', hide);
  document.addEventListener('keydown', hide);
  refresh();
  if (parentOrigin) window.parent.postMessage({type: 'archer-cursor-ready'}, parentOrigin);
})();
