from app.config import settings
from elevenlabs.client import ElevenLabs
from elevenlabs.play import play

elevenlabs = ElevenLabs(
  api_key="sk_5d5dfa100126e708731b5a00d17f122176d8420275e44f22",
)
text = """
(धीमे स्वर में) तो सुनो...
[थोड़ी देर चुप्पी]

हाहा... यह तो मज़ेदार है।
(हल्की हँसी)

लेकिन...
(फुसफुसाते हुए)
ये बात किसी को मत बताना।
"""
audio = elevenlabs.text_to_speech.convert(
    text=text,
    voice_id="JBFqnCBsd6RMkjVDRZzb",
    model_id="eleven_multilingual_v2",
    output_format="mp3_44100_128",
)

play(audio)