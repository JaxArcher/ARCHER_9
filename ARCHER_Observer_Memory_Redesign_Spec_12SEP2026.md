# ARCHER Observer & Memory Redesign — Spec

Date: 2026-09-12
Status: Final — ready for implementation

## 1. Scope and confirmed decisions

This replaces the fixed-classifier observer pipeline (DeepFace emotion, MediaPipe posture) with a two-tier VLM approach, adds person identification, and closes the gap where behavioral/visual data never makes it into long-term memory.

Confirmed with Col:
- Drop `EmotionAnalyzer` (DeepFace) and `PoseAnalyzer` (MediaPipe) entirely, on both cameras. No replacement fixed classifier for either.
- One network camera and one local webcam, as today. No multi-camera / bedroom cam work in this pass — `ObserverPipeline.switch_to_network_cam()` / `switch_to_webcam()` stay single-URL for now.
- Recorded images and per-person logs have no retention/deletion policy. People are already alerted they're on camera when they enter Col's home, and Col is using this as backup memory — keep everything indefinitely unless he asks otherwise later.
- Person identification is in scope now: recognize Col specifically, and keep a running log of unrecognized visitors (image + sightings), not just a one-off classifier swap.
- The end-of-day consolidation pass is also the fix for the CoreAgent → OpenMemory write gap: right now `orchestrator.py` writes conversational turns to OpenMemory (`_om.add_memory(...)` at lines 453 and 510), but nothing ever writes observer/behavioral data there. The nightly job becomes that missing write path.

- Drop `SedentaryTracker` entirely along with posture. It had no independent input of its own — it only ever consumed the pose landmarks `PoseAnalyzer` produced — so once posture is gone, sedentary tracking goes with it rather than being rebuilt on a new signal.

## 2. What gets removed

`src/archer/observer/analyzers.py`: delete the `EmotionAnalyzer`, `PoseAnalyzer`, and `SedentaryTracker` classes outright (`_frame_to_jpeg_b64` and `SceneAnalyzer` stay — the VLM path is now the only analyzer).

`src/archer/observer/pipeline.py`: remove `self._emotion_analyzer` / `self._pose_analyzer` / `self._sedentary_tracker` instantiation, the `emotion_results` / `pose_results` blocks and the `sedentary_result = self._sedentary_tracker.update(...)` call in `_run_analysis_cycle()`, `_process_emotion()`, and the emotion/pose entries in the GUI detection aggregation.

`src/archer/observer/overlay.py`: `_draw_face_box()`, `_EMOTION_COLORS`, and `_draw_pose_landmarks()` / `_SKELETON_CONNECTIONS` become dead code — remove them. Overlay drawing for the new person-ID boxes replaces face-box drawing (see §4).

`src/archer/observer/interventions.py`: remove `_handle_sustained_emotion()`, `_handle_hunched_posture()`, `_handle_sedentary()`, `_DISTRESS_EMOTIONS`, `_TRAINER_SEDENTARY_COOLDOWN`, and the `sustained_emotion` / `posture` / `sedentary` branches in `_on_observation()`. `EmotionConfirmationManager` (`observer/emotion_confirmation.py`) becomes unused — remove the import and its instantiation, and confirm nothing else references that module before deleting the file itself.

`src/archer/agents/core_agent.py`: remove the `posture_active` / `posture_last_staged` / `emotion_last_staged` / `emotion_last_type` / `sedentary_last_staged` / `sedentary_last_mins` entries from `_blindspot_state`, and the `sustained_emotion` / `posture` / `sedentary` branches around lines 170–200. The stance-prompt text at lines 414 and 425 that references "posture alerts, emotional detection" and "feeds posture, emotion" needs rewording to describe the new behavioral-pattern framing instead (§3) so CoreAgent doesn't claim capabilities that no longer exist.

Config (`config.py`): `mediapipe_url` and `deepface_url` (and the underlying Docker containers, if they're dedicated to those two services only — worth checking `docker-compose.yml` before tearing anything down) can be retired once nothing references them.

## 3. Continuous observation: two-tier VLM approach

Tier 1 (already built, keep as-is): `SceneAnalyzer` in `observer/analyzers.py` already runs `qwen2.5vl:7b` against a dedicated CPU Ollama instance (`observer_ollama_url`, default `http://127.0.0.1:11435`) on a 30-second cooldown, and logs a plain-language description + object list to `observation_events` via `_publish_observation()`. This is the "periodically describe raw scenes in plain language" piece — no new work needed here beyond making sure it runs on both the webcam and network-cam sources (it already takes a `camera_source` param).

Change: since emotion/posture are gone, `SceneAnalyzer`'s prompt should be widened to explicitly ask for behavior, not just objects — e.g. what the person is doing (sitting at desk, cooking, on the phone, pacing), not a fixed taxonomy. This is a one-line prompt edit in `SceneAnalyzer.analyze()`.

Sedentary tracking is dropped, not rebuilt: it only ever consumed `PoseAnalyzer`'s pose landmarks, so it goes when posture goes rather than getting a new presence-based proxy (§1).

Tier 2 (new): end-of-day consolidation, confirmed cloud-model. A new script, e.g. `src/archer/memory/consolidation.py`, run once daily via `run_maintenance()` in `memory/maintenance.py`. The job:

1. Pull the day's `observation_events` rows via `SQLiteStore.get_observations()` (already exists), filtered to `event_type == "scene"` plus the new person-sighting events (§4).
2. Send the day's log to the Claude API using the Anthropic key ARCHER already has configured (`config.anthropic_api_key`, `claude_model` currently set to `claude-sonnet-5`) — this is the same credential/model CoreAgent's cloud reasoning path already uses, so there's no new integration to build, just a new caller.
3. Synthesize a behavioral summary — patterns, habits, notable events — and write it via `OpenMemoryStore.add_memory(content, sector="episodic", metadata={"role": "observer", "date": ...})` (the store already exists; it just has no caller for this data today).
4. Log the run via the existing `markdown_logger` audit pattern already used in `maintenance.py`.

**On "connect it to my Claude account with our chat history":** worth being precise about what's possible here, since there are two different things that could mean. The Claude API call in step 2 above authenticates with your Anthropic API key — it does not have access to any claude.ai or Cowork conversation history (this conversation included). There's no API surface for one application to read another account's claude.ai chat history; that data lives in a completely separate system with no cross-app access. What the consolidation job *can* do, and what gets you the closest equivalent of "context from prior conversations," is pull from ARCHER's own memory before making the call: recent `OpenMemoryStore.search()` results and/or recent rows from `conversation_logs` (SQLite) already capture what you and ARCHER have actually discussed. Feeding a few days of that alongside the day's observation log gives the consolidation model real continuity — just continuity from ARCHER's own memory, not from anything in your Claude.ai account.

Needs adding since nothing calls `run_maintenance()` today: a Windows Task Scheduler entry running the venv's `python -m archer.memory.maintenance` nightly (e.g. 3 AM) — a `schtasks /create` one-liner Antigravity can set up as part of this work.

## 4. Person identification

New, separate from the VLM scene pipeline. Confirmed: InsightFace for the local face-embedding model, over `face_recognition`/dlib, given this runs continuously and accuracy on repeat unknown-visitor matching matters.

Flow per analysis cycle (or its own faster/slower cadence, doesn't need to match the 30s VLM cooldown): detect faces in the frame, compute an embedding for each, compare against a stored enrollment set.

- Col enrolls once (a short one-time capture flow, a handful of frames from different angles) → stored as `known_persons` with `name = "Col"`.
- A face that matches Col's embedding within a similarity threshold → tagged `person: Col` on the observation event, no separate log needed since it's already "his" data.
- A face that doesn't match any known embedding → check against previously-seen *unknown* embeddings first (so the same repeat visitor becomes "Person_2" consistently instead of a new ID every visit), else assign the next `Person_N` label, save a snapshot image (path goes in `observation_events.evidence_pointer`, which already exists in the schema), and log the sighting.

New SQLite tables needed (add to `sqlite_store.py`'s schema block, same pattern as `observation_events`): `known_persons(id, name, embedding BLOB, enrolled_at)` and `person_sightings(id, person_id, is_known, confidence, snapshot_path, timestamp, camera_source)`. `person_sightings` rows are what the Tier 2 consolidation job reads to include "who was present" in the daily summary.

GUI overlay: replace the removed face/emotion box in `overlay.py` with a simpler box + label (`"Col"` or `"Person_2"`), reusing the existing `_draw_label()` helper.

## 5. Camera-native detection (Reolink smart detection) — new, worth folding in

Col's network camera is a Reolink; Reolink's own firmware/app ("Smart Detection") already does onboard AI person/vehicle/pet detection with configurable zones and sensitivity, separate from anything ARCHER runs. Rather than ARCHER's pipeline pulling a frame every 0.5s and running the VLM on a flat 30s timer regardless of whether anyone's there, it can subscribe to the camera's own detection events and only trigger Tier 1 VLM analysis (and person-ID, §4) when the camera itself says a person is in frame. This is a genuine efficiency and reliability win, not just a nice-to-have.

The mechanism: `reolink-aio` (PyPI `reolink-aio`, GitHub `starkillerOG/reolink_aio`) is a Reolink-authorized async Python library — the same one Home Assistant's official Reolink integration uses — that subscribes to the camera's ONVIF push/polling events and can pull snapshots on demand. It would sit in front of the existing `WebcamCapture`/network-cam path in `pipeline.py` as a new "Tier 0": camera fires a person-detected event → ARCHER grabs a frame → runs Tier 1 VLM + person-ID on it, instead of the current always-on polling.

**Confirmed by checking Col's actual camera** (Reolink desktop app, Device → Smart Detection / Network → Advanced → Server Settings):

Camera model is a Reolink RLC-520A (PoE turret, 5MP), named "RLC-520ARCHER" in the app. Smart Detection is on with Person detection active (sensitivity 60/100); Vehicle and Animal detection sliders exist on the same hardware but are currently toggled off (greyed, not actively detecting) — worth turning on Animal at minimum if pets are ever in frame. Alarm Delay, Object Size filtering, and a Non-Detection Zone mask are all available for tuning false positives once Tier 0 is wired up.

RTSP is already enabled (port 554) — this is what ARCHER's current `network_camera_url` polling already uses. ONVIF (port 8000), which `reolink-aio` needs for push-event subscription, has now been enabled (confirmed with Col; camera warns data transfer over ONVIF is unencrypted and recommends home/work networks only, not public ones — fine for this setup). `reolink-aio` can subscribe to detection events now.

Animal/Pet smart detection: left off per Col's call — Person detection stays the only active smart-detection type on this camera for now.

Recording is on with motion-triggered pre/post capture (15s post-motion), but set to "Overwrite Oldest Files" — the camera's own local storage rolls over, so it is not a substitute for ARCHER's own persistent logging. This confirms Tier 1/Tier 2 (§3) still need to own the durable "backup memory" record; the camera's native storage is short-term and event-scoped only.

## 6. Rollout order

1. Strip emotion, posture, and sedentary tracking (§2) — bounded, mechanical, low-risk, and immediately fixes the "can't trust the emotion readings" and "posture pings are noise" complaints without needing any new dependency.
2. Widen the Tier 1 VLM prompt for behavior instead of objects (§3).
3. Build the Tier 2 consolidation job (cloud, Claude API) and wire `run_maintenance()` to a nightly Windows Task Scheduler entry — this is the OpenMemory write-path fix and is independently valuable even before person ID exists.
4. Add person identification with InsightFace (§4) — can ship after 1–3 are stable since it's additive.
5. Layer in Reolink native detection (§5) as a Tier 0 optimization once 1–4 are working — it changes *when* the pipeline runs, not what it does, so it's safe to bolt on last.

## 7. Status

All open items are resolved. Sedentary tracking is dropped entirely along with posture (§1–§3), not rebuilt on a new signal. Cloud consolidation model confirmed (Claude API, §3); InsightFace confirmed for person ID (§4); ONVIF enabled and Animal detection left off on the RLC-520A (§5). One implementation task remains for Antigravity: nothing currently calls `run_maintenance()` — the Windows Task Scheduler entry described in §3 still needs to be added.

This spec is ready to hand off.
