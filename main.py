import os
import json
import anthropic
import subprocess
import webbrowser
from dotenv import load_dotenv
import speech_recognition as sr

APP_MAP={
    "clock":"ms-clock",
    "web browser":"https:",
    "edge":"microsoft-edge:",
    "messages":"ms-chat:",
    "photos":"ms-photos:",
    "settings":"ms-settings:",
    "app store":"ms-windows-store:",
    "weather":"msnweather:",
    "calendar":"ms-calendar",
    "calculator":"calculator:",
    "paint":"ms-paint:",
    "notepad":"notepad"
}

load_dotenv()
ANTHROPIC_API_KEY= os.environ.get("ANTHROPIC_API_KEY")
recognizer=sr.Recognizer()
client=anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
try:
    while(True):
        with sr.Microphone() as source:
            print("Adjusting for ambient noise... Please wait.")
            recognizer.adjust_for_ambient_noise(source, duration=1)
            print("Listening... Speak now!")
            audio_data=recognizer.listen(source)
            print("Processing you voice...")

        try:
            text = recognizer.recognize_google(audio_data)
            message=client.messages.create(
                # TODO: switch back to claude-sonnet-4-5 for production
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                messages=[{"role":"user","content":text}],
                system="You are Sensei, a PC assistant. You must ALWAYS respond with valid JSON only. No other text, explanation, or formatting — ever. Your response must contain exactly two keys:- \"action\": one of \"open\", \"play\", \"search\", or \"answer\"- \"parameter\": the relevant value for that action    Action definitions:    - \"open\"   → open an application or file (parameter: app or file name)    - \"play\"   → play media such as music or video (parameter: title or query)    - \"search\" → search the web or system (parameter: search query)    - \"answer\" → respond to a question or statement (parameter: the answer text)    Example responses:    {\"action\": \"open\", \"parameter\": \"calculator\"}    {\"action\": \"play\", \"parameter\": \"Bohemian Rhapsody\"}    {\"action\": \"search\", \"parameter\": \"weather in London\"}    {\"action\": \"answer\", \"parameter\": \"The capital of France is Paris.\"}    Never output anything outside of this JSON structure. No preamble, no explanation, no markdown.")
            r=(message.content[0].text).replace("```json","").replace("```","").strip()
            response=json.loads(r)
            if response["action"]=="open":
                if response["parameter"].lower() in APP_MAP:
                    os.startfile(APP_MAP[response["parameter"].lower()])
                else:
                    subprocess.Popen(f"start {response['parameter']}", shell=True)
                
            elif response["action"]=="answer":
                print(response["parameter"])
            elif response["action"]=="play":
                url=f"https://www.youtube.com/results?search_query={response['parameter'].strip().replace(' ','+')}"
                webbrowser.open(url)
            elif response["action"]=="search":
                url=f"https://www.google.com/search?q={response['parameter'].strip().replace(' ','+')}"
                webbrowser.open(url)
        except sr.UnknownValueError:
            print ("Couldn't understand what u said")
        except sr.RequestError as e:
            print(f"Could not request results from the service; {e}")
        except json.JSONDecodeError as e:
            print("Failed to parse JSON!")
except KeyboardInterrupt:
    print("Sensei stopped.")
    
    