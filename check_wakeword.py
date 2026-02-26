from dotenv import load_dotenv
load_dotenv('.env', override=True)

try:
    import openwakeword
    openwakeword.utils.download_models()

    # List what models are actually available
    from openwakeword.model import Model
    print("Available built-in models:")
    try:
        m = Model(wakeword_models=["alexa"], inference_framework="onnx")
        print("  - alexa: OK")
    except Exception as e:
        print(f"  - alexa: FAILED ({e})")

    try:
        m = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        print("  - hey_jarvis: OK")
    except Exception as e:
        print(f"  - hey_jarvis: FAILED ({e})")

    try:
        m = Model(wakeword_models=["hey_mycroft"], inference_framework="onnx")
        print("  - hey_mycroft: OK")
    except Exception as e:
        print(f"  - hey_mycroft: FAILED ({e})")

    # List all model files found
    import os
    model_dir = os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models")
    if os.path.exists(model_dir):
        print(f"\nModel files in {model_dir}:")
        for f in sorted(os.listdir(model_dir)):
            print(f"  {f}")
    else:
        print(f"\nModel dir not found: {model_dir}")

except Exception as e:
    print(f"openWakeWord error: {e}")
