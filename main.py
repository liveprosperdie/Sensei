import os
import json
import anthropic
import subprocess
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
    print("Processing you voice...")

try:
    text = recognizer.recognize_google(audio_data)
    message=client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=100,
        messages=[{"role":"user","content":text}],
        system="You are Sensei, a PC assistant. You must ALWAYS respond with valid JSON only. No other text, explanation, or formatting — ever. Your response must contain exactly two keys:- \"action\": one of \"open\", \"play\", \"search\", or \"answer\"- \"parameter\": the relevant value for that action    Action definitions:    - \"open\"   → open an application or file (parameter: app or file name)    - \"play\"   → play media such as music or video (parameter: title or query)    - \"search\" → search the web or system (parameter: search query)    - \"answer\" → respond to a question or statement (parameter: the answer text)    Example responses:    {\"action\": \"open\", \"parameter\": \"calculator\"}    {\"action\": \"play\", \"parameter\": \"Bohemian Rhapsody\"}    {\"action\": \"search\", \"parameter\": \"weather in London\"}    {\"action\": \"answer\", \"parameter\": \"The capital of France is Paris.\"}    Never output anything outside of this JSON structure. No preamble, no explanation, no markdown.")
    r=(message.content[0].text).replace("```json","").replace("```","").strip()
    response=json.loads(r)
    if response["action"]=="open":
        subprocess.Popen(f"start {response['parameter']}", shell=True)
    elif response["action"]=="answer":
        print(response["parameter"])
except sr.UnknownValueError:
    print ("Couldn't understand what u said")
except sr.RequestError as e:
    print(f"Could not request results from the service; {e}")
except json.JSONDecodeError as e:
    print("Failed to parse JSON!")
except Exception as e:
    print(f"Error: {e}")