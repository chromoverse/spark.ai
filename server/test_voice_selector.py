from app.services.tts.voice_selector import VoiceSelector

def test_voice_selector():
    print("🧪 Testing Voice Selector...")
    
    test_cases = [
        ("Hello, how are you?", "en"),
        ("नमस्ते, आप कैसे हैं?", "hi"),
        ("こんにちは", "ja"),
        ("Bonjour", "fr"),
        ("Hola", "es"),
    ]
    
    for text, expected_lang in test_cases:
        detected_lang = VoiceSelector.detect_language(text)
        voice = VoiceSelector.get_voice(detected_lang)
        print(f"📝 Text: '{text}' -> Lang: {detected_lang} (Expected: {expected_lang}) -> Voice: {voice}")
        
    print("\n🧪 Testing Gender Selection...")
    print(f"English Male: {VoiceSelector.get_voice('en', 'male')}")
    print(f"English Female: {VoiceSelector.get_voice('en', 'female')}")
    print(f"Hindi Male: {VoiceSelector.get_voice('hi', 'male')}")

if __name__ == "__main__":
    test_voice_selector()
