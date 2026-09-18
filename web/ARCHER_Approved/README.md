# ARCHER — approved artwork edition

Visual source: the exact still approved immediately before this build, included as web/assets/approved.png and embedded in the renderer for offline use. No font installation is needed: its lettering and glow are preserved in the artwork. This is a 2.5D artwork renderer, not a rigged 3D model. Ring regions and the aperture make restrained, smoothly blended angular oscillations around a fixed center. The central lettering area remains fixed. It does not open and close individual blades or continuously rotate the turbine through 360 degrees. These limits preserve the approved flattened artwork without hard cutout seams.

## Preview first
Extract the ZIP fully, then open preview.html in Chrome or Edge. The Approved still button displays the unmodified source. State buttons demonstrate idle, listening, processing, and simulated speaking. Pause freezes motion; Halt stops it and clears voice energy. Reduced-motion settings suppress motion.

## Install without disturbing the voice pipeline
Back up your current web folder. Copy assets/approved.png, css/orb.css and js/orb.js from this package's web folder into the corresponding project folders. Do not replace app.js. Your entry page must contain a DIV with data-archer-orb (or id orb-container / orb) and load /static/css/orb.css, then your existing app.js, then /static/js/orb.js. Refresh http://127.0.0.1:8200/app.

The current project index.html, app.js and original renderer were not supplied, so an exact drop-in signature and live server integration could not be verified. If your mount is a canvas, change it to a DIV or manually create new ArcherApertureOrb(divElement). To attach a client created later, call ArcherOrb.bindClient(ArcherClient).

## Public API
ArcherOrb.setState('idle'|'listening'|'processing'|'speaking'|'error'|'halted'); setAmplitude(0..1); setReference(boolean); setPaused(boolean); destroy().
Consumes ArcherClient state/amplitude/halt/wakeWord events. Amplitude accepts a number or {value}; state accepts a string or {state}. Stale speaking amplitude decays after 400 ms. Error and halt stop motion. A subsequent state event resumes the requested state. No network connection, microphone access, typed-message handling or HALT transmission is added by this visual component; those remain in the existing client.

## Verification and limitations
JavaScript syntax and state dispatch, amplitude clamping, Halt, pause and reduced-motion behavior passed local automated tests. The actual Canvas renderer was run in a local Canvas implementation and its output visually inspected. Browser testing could not be completed: Chromium was unavailable and its download failed. Browser performance and live ARCHER integration therefore remain unverified. This package is an integration candidate, not a claim of verified production deployment. Motion uses an 824px-wide intermediate canvas; reference mode uses the full-resolution source.
