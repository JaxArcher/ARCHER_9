/**
 * ARCHER browser client — Camera Ownership & WS Frame Provider.
 *
 * Phase 2 Redesign: The browser client opens the webcam itself via getUserMedia
 * on page load. The left column #archer-system-camera-feed video element binds
 * to this stream. When the server needs a frame for ENROLL FACE or visual Q&A,
 * it sends a "camera_frame_request" message and this module replies with
 * "camera_frame_response" containing the current video frame as a base64 JPEG.
 */
(() => {
  let mediaStream = null;
  let videoEl = document.getElementById("archer-system-camera-feed");
  const fallbackEl = document.getElementById("archer-camera-unavailable");
  let canvasEl = document.getElementById("archer-camera-canvas");

  if (!canvasEl) {
    canvasEl = document.createElement("canvas");
    canvasEl.id = "archer-camera-canvas";
    canvasEl.style.display = "none";
    document.body.appendChild(canvasEl);
  }

  if (videoEl && videoEl.tagName !== "VIDEO") {
    const newVideo = document.createElement("video");
    newVideo.id = "archer-system-camera-feed";
    newVideo.autoplay = true;
    newVideo.playsInline = true;
    newVideo.muted = true;
    videoEl.parentNode.replaceChild(newVideo, videoEl);
    videoEl = newVideo;
  }

  async function initCamera() {
    if (!videoEl) return;
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false
      });
      videoEl.srcObject = mediaStream;
      videoEl.style.display = "block";
      if (fallbackEl) fallbackEl.style.display = "none";
      console.log("[ArcherCamera] Browser webcam stream active.");
    } catch (err) {
      console.warn("[ArcherCamera] Could not open webcam via getUserMedia:", err);
      if (videoEl) videoEl.style.display = "none";
      if (fallbackEl) fallbackEl.style.display = "flex";
    }
  }

  function captureFrameB64(quality = 0.85) {
    if (!videoEl || !mediaStream || videoEl.readyState < 2) return null;
    canvasEl.width = videoEl.videoWidth || 640;
    canvasEl.height = videoEl.videoHeight || 480;
    const ctx = canvasEl.getContext("2d");
    ctx.drawImage(videoEl, 0, 0, canvasEl.width, canvasEl.height);
    const dataUrl = canvasEl.toDataURL("image/jpeg", quality);
    return dataUrl.split(",")[1] || dataUrl;
  }

  if (window.ArcherClient) {
    window.ArcherClient.on("cameraFrameRequest", (data) => {
      const reqId = data && data.requestId;
      const b64 = captureFrameB64(0.85);
      window.ArcherClient.sendCameraFrameResponse(reqId, b64);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initCamera);
  } else {
    initCamera();
  }

  window.ArcherCamera = {
    getStream: () => mediaStream,
    getVideoElement: () => videoEl,
    captureFrameB64,
  };
})();
