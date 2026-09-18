# Starts the second Ollama instance ARCHER uses for the observer/vision
# pipeline (moondream), on port 11435.
#
# Deliberately GPU, not CPU: moondream is a 1.4B model that only needs
# ~1.2GB of VRAM (model + context + compute buffer). Forcing it onto CPU
# via CUDA_VISIBLE_DEVICES="" caused 20-60s cold-start waits per query and
# pinned the CPU hard enough to starve STT/audio scheduling during active
# conversation. There's comfortably enough free VRAM left after qwen3:8b
# loads on a 16GB card, so this instance shares the GPU with the main
# instance instead.
#
# Run this in its own window each session (it does not exit). If you ever
# swap the observer model for something genuinely large (not moondream),
# reconsider CPU isolation for that model specifically.

$env:OLLAMA_HOST = "127.0.0.1:11435"
Remove-Item Env:\CUDA_VISIBLE_DEVICES -ErrorAction SilentlyContinue

Write-Host "Starting observer Ollama instance on 127.0.0.1:11435 (GPU)..."
ollama serve
