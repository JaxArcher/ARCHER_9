import time
import threading
from archer.voice.audio import AudioManager
from archer.voice.pipeline import VoicePipeline
from loguru import logger

def test_aec_pipeline():
    logger.info("Testing AEC Pipeline initialization...")
    try:
        pipeline = VoicePipeline()
        pipeline.initialize()
        pipeline.start()
        
        # Let it run for a few seconds
        time.sleep(3)
        
        logger.info(f"Pipeline state: {pipeline.state}")
        
        # Test playback while capture is active
        from archer.voice.tts import TTSService
        tts = TTSService()
        logger.info("Synthesizing test phrase...")
        result = tts.synthesize("Acoustic Echo Cancellation is now active.")
        if result:
            audio_bytes, sr = result
            logger.info("Playing test phrase (AEC should be working)...")
            # This will use the new duplex stream in AudioManager
            pipeline._audio.play_audio_bytes(audio_bytes, sr)
            logger.info("Playback finished.")
            
        time.sleep(2)
        pipeline.stop()
        logger.info("Test completed successfully.")
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_aec_pipeline()
