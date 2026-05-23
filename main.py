import os
import anthropic
from dotenv import load_dotenv
import speech_recognition as sr


load_dotenv()
ANTHROPIC_API_KEY= os.environ.get("ANTHROPIC_API_KEY")
recognizer=sr.Recognizer()
client=anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

with sr.Microphone() as source:
    print("Adjusting for ambient noise... Please wait.")
    recognizer.adjust_for_ambient_noise(source, duration=1)
    print("Listening... Speak now!")
    audio_data=recognizer.listen(source)
    print("Audio captured, size:", len(audio_data.get_raw_data()))
    print("Processing you voice...")

try:
    text = recognizer.recognize_google(audio_data)
    message=client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=100,
        messages=[{"role":"user","content":text}]
    )
    print(message.content[0].text)
except sr.UnknownValueError:
    print ("Couldn't understand what u said")
except sr.RequestError as e:
    print(f"Could not request results from the service; {e}")
except Exception as e:
    print(f"Error: {e}")