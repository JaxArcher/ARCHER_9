import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseSettings
from TTS.api import TTS
import torch
import tempfile
from fastapi.responses import FileResponse
import time

app = FastAPI(title="ARCHER Coqui TTS Service")

# Agree to Coqui TOS (required for XTTS)
os.environ["COQUI_TOS_AGREED"] = "1"

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Loading Coqui XTTS-v2 on {device}...")

# Initialize TTS
# Using XTTS-v2 for high quality cloning and expressivity
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)

@app.get("/health")
def health():
    return {"status": "ok", "device": device, "model": "xtts_v2"}

@app.post("/synthesize")
async def synthesize(data: dict):
    text = data.get("text")
    if not text:
        raise HTTPException(status_code=400, detail="No text provided")
    
    # Optional voice cloning - currently using a default neutral speaker
    # In the future, we can provide speaker_wav for cloning
    speaker = data.get("speaker", "Claribel Dervla") # Default high-quality speaker
    language = data.get("language", "en")
    
    try:
        temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        temp_path = temp_file.name
        
        # XTTS v2 synthesis
        tts.tts_to_file(
            text=text,
            speaker=speaker,
            language=language,
            file_path=temp_path
        )
        
        return FileResponse(
            temp_path, 
            media_type="audio/wav", 
            headers={"X-Sample-Rate": "24000"}
        )
    except Exception as e:
        print(f"Synthesis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
