"""
Download the base daemon models and remind the installer about the custom Spark
wake-word assets that must be copied into voice_daemon/models.
"""

from __future__ import annotations

from pathlib import Path


def main() -> None:
    import openwakeword
    import torch

    models_dir = Path(__file__).resolve().parents[1] / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    print("Downloading openWakeWord base assets...")
    openwakeword.utils.download_models()
    print("Downloading Silero VAD model...")
    torch.hub.load("snakers4/silero-vad", "silero_vad", force_reload=False)

    print("Base daemon models are ready.")
    print("Custom Spark wake-word models still need to be added manually:")
    print(f"  - {models_dir / 'hey_spark.onnx'}")
    print(f"  - {models_dir / 'spark.onnx'}")


if __name__ == "__main__":
    main()
