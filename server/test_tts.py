from fishaudio import TTS

# Initialize TTS with your HF token
tts = TTS(model_id="fishaudio/openaudio-s1-mini", token="hf_your_token_here")

# Convert text to speech
audio = tts.speak("Hello! This is OpenAudio S1-mini running locally.")

# Save to file
with open("output.wav", "wb") as f:
    f.write(audio)
