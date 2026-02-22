import os
from groq import Groq

# ── Config ────────────────────────────────────────────────────────────────────
GROQ_API_KEY = "your_key"   # or set as env var: GROQ_API_KEY=xxx
AUDIO_FILE   = "english_command.m4a"      # swap with your audio file path
# ─────────────────────────────────────────────────────────────────────────────

client = Groq(api_key=GROQ_API_KEY or os.environ.get("GROQ_API_KEY"))

# def transcribe(audio_path: str) -> str:
#     with open(audio_path, "rb") as f:
#         response = client.audio.transcriptions.create(
#             model    = "whisper-large-v3-turbo",
#             file     = f,
#             language = "en",                 # English only, skip auto-detect overhead
#             response_format = "text",        # returns plain string, no JSON parsing needed
#         )
#     return response # type: ignore (as groq returns the complete transcript)


response = client.audio.speech.create(
    model="canopylabs/orpheus-v1-english",
    voice="autumn",                  # or leah, jessica, zoe, zac, hannah, troy, austin
    input="""
[sad] I still remember the day we lost everything... [tearful] it felt like the whole world had collapsed around us. 
[pause] But then, [hopeful] slowly, things started to change. [warm] Friends showed up at our door with food and laughter. 
[cheerful] And before we knew it, we were smiling again! [excited] Oh and then — you won't BELIEVE this — 
[breathless] we actually got the call! We got it! [laughing] I literally fell off my chair, I'm not even joking! 
[whisper] But between us... I had cried the entire night before. [vulnerable] I didn't think I was good enough, honestly. 
[firm] But I refused to give up. [passionate] Because some things in life are worth fighting for with every single piece of you! 
[angry] And anyone who told us we couldn't do it — [pause] [calm] well, I forgive them now. 
[reflective] Because pain has a strange way of becoming your greatest teacher. [gentle] And today, 
[grateful] I am just... so deeply thankful for every single moment — the broken ones, the beautiful ones, all of it.
""",
    response_format="wav",
)

response.write_to_file("output.wav")

# if __name__ == "__main__":
#     # import time

#     # print(f"Transcribing: {AUDIO_FILE}")
#     # start = time.time()

#     # transcript = transcribe(AUDIO_FILE)

#     # elapsed = time.time() - start
#     # print(f"\n── Transcript ──────────────────────────────")
#     # print(transcript)
#     # print(f"\n── Done in {elapsed:.2f}s ──────────────────")

#     # Ready to pass to your LLM:
#     # response = your_llm(transcript)
    
