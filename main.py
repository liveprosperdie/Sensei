import speech_recognition as sr
import anthropic

recognizer=sr.Recognizer()

with sr.Microphone() as source:
    print("Adjusting for ambient noise... Please wait.")
    recognizer.adjust_for_ambient_noise(source, duration=1)
    print("Listening... Speak now!")
    audio_data=recognizer.listen(source)
    print("Processing you voice...")

try:
    text = recognizer.recognize_google(audio_data)
    print(f"You said: {text}")

except sr.UnknownValueError:
    print ("Couldn't understand what u said")
except sr.RequestError as e:
    print(f"Could not request results from the service; {e}")