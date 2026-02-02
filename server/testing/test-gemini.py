"""
Test script for Google Gemini API using native SDK
"""
# type: ignore reportPrivateImportUsage
import google.generativeai as genai
from app.config import settings

from app.prompts.app_prompt import build_prompt_hi, build_prompt_en, build_prompt_ne

def test_prompt_hi():
    prompt_hi  = build_prompt_hi("neutral", "mark zuckerberg have launched somethin called ray ban sunglasses what is it and when it proposed", [], [])
    print(prompt_hi)
    return prompt_hi

# Configure the API key
genai.configure(api_key=settings.gemini_api_key) # type: ignore

# List available models first to verify
# print("📋 Available Gemini models:")
# for model in genai.list_models(): # type: ignore
#     if 'generateContent' in model.supported_generation_methods:
#         print(f"  ✓ {model.name}")

# print("\n" + "="*50 + "\n")

# Test with different model names
test_models = [
    "gemini-2.5-flash",
    "gemini-1.5-pro",
    "gemini-2.0-flash-exp",  # Experimental 2.0 model
]

for model_name in test_models:
    print(f"🧪 Testing model: {model_name}")
    try:
        model = genai.GenerativeModel(model_name) # type: ignore
        prommpt = test_prompt_hi()
        
        response = model.generate_content(
            prommpt,
            generation_config={ # type: ignore
                "temperature": 0.7,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 1024,
            }
        )
        
        print(f"✅ SUCCESS with {model_name}")
        print(f"Response: {response.text}...")
        print("\n" + "="*50 + "\n")
        break  # Stop after first success
        
    except Exception as e:
        print(f"❌ FAILED with {model_name}")
        print(f"Error: {str(e)}")
        print("\n" + "="*50 + "\n")
        continue

print("\n🎯 Test complete!")