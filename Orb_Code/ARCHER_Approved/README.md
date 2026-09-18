# ARCHER aperture — rotating layers

Extract the archive and open preview.html in Chrome or Edge. Five layers rotate continuously in opposing directions, including the metallic aperture. One stationary wordmark stays upright. Idle, listening, processing and speaking have different speeds and signal activity. Speaking uses simulated amplitude in the preview and ArcherClient amplitude events when integrated. Pause, Halt and reduced-motion preference stop movement.

The exterior and gaps between rings are transparent. The dark center and ring surfaces are part of the orb. Check against the preview's white, black, slate and checkerboard backgrounds.

This is layered 2D animation based on the approved artwork. A text-free aperture texture was reconstructed; the isolated lettering has a mint/lavender gradient. Individual blades do not mechanically open or close.

## Install

Back up existing files. Replace web/js/orb.js and web/css/orb.css and copy web/assets. Keep app.js. Mount on a DIV with data-archer-orb or id orb-container. Load orb.css, your app.js, then orb.js. Remove old orb scripts. If the client initializes later, call ArcherOrb.bindClient(ArcherClient).

Important: display the canvas component, not approved.png in an IMG tag. The source PNG is static and still contains its background; the renderer removes that background. Remove background and box-shadow styling from the dashboard's orb container as well.

API: setState('idle'|'listening'|'processing'|'speaking'|'error'|'halted'), setAmplitude(0..1), setPaused(boolean), setReference(boolean), destroy(). Reference mode freezes the initial layered pose. Events: state, amplitude, halt, wakeWord. No microphone or network access is added.

Canvas rendering and state behavior were verified locally. Live ARCHER integration and browser performance on your computer remain unverified.
