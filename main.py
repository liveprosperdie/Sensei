import os
import json
import pyaudio
import winsound
import anthropic
import subprocess
import webbrowser
import numpy as np
import openwakeword
from dotenv import load_dotenv
import speech_recognition as sr
from openwakeword.model import Model as WakeModel

APP_MAP={
    "clock":"ms-clock:",
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

openwakeword.utils.download_models()
oww_model=WakeModel(wakeword_models=["sensei.onnx"],inference_framework="onnx")
load_dotenv()
ANTHROPIC_API_KEY= os.environ.get("ANTHROPIC_API_KEY")
recognizer=sr.Recognizer()
client=anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
mic=pyaudio.PyAudio()
stream= mic.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True,frames_per_buffer=1280)
print("Waiting for 'Sensei'...")
try:
    while(True):
        audio_chunk=stream.read(1280,exception_on_overflow=False)
        audio_np=np.frombuffer(audio_chunk,dtype=np.int16)
        prediction=oww_model.predict(audio_np)

        score=list(prediction.values())[0]
        if score > 0.8:
            print("Wake word detected!")
            winsound.Beep(1000,200)
            with sr.Microphone() as source:
                    recognizer.adjust_for_ambient_noise(source, duration=0.5)
                    audio_data = recognizer.listen(source, timeout=10, phrase_time_limit=8)

            try:
                text = recognizer.recognize_google(audio_data)
                print("Heard:", text)
                message=client.messages.create(
                    # TODO: switch back to claude-sonnet-4-5 for production
                    model="claude-haiku-4-5-20251001",
                    max_tokens=100,
                    messages=[{"role":"user","content":text}],
                    system="You are Sensei, a PC assistant. You must ALWAYS respond with valid JSON only. No other text, explanation, or formatting — ever. Your response must contain exactly two keys:- \"action\": one of \"open\", \"play\", \"search\", or \"answer\"- \"parameter\": the relevant value for that action    Action definitions:    - \"open\"   → open an application or file (parameter: app or file name)    - \"play\"   → play media such as music or video (parameter: title or query)    - \"search\" → search the web or system (parameter: search query)    - \"answer\" → respond to a question or statement (parameter: the answer text)    Example responses:    {\"action\": \"open\", \"parameter\": \"calculator\"}    {\"action\": \"play\", \"parameter\": \"Bohemian Rhapsody\"}    {\"action\": \"search\", \"parameter\": \"weather in London\"}    {\"action\": \"answer\", \"parameter\": \"The capital of France is Paris.\"}    Never output anything outside of this JSON structure. No preamble, no explanation, no markdown.If the request cannot be mapped to open, play, or search, always use the \"answer\" action and provide a brief answer as the parameter.For requests asking to write code, explain code, or anything technical, use the \"answer\" action with a brief one-sentence response only.For ANY request you cannot fulfill with open/play/search, including code requests, writing requests, or anything complex — always use {\"action\": \"answer\", \"parameter\": \"brief one-line response only\"}. Never return anything except valid JSON.")
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
except sr.WaitTimeoutError:
    print("No command heard, going back to listening...")
except KeyboardInterrupt:
    stream.stop_stream()
    stream.close()
    mic.terminate()
    print("Sensei stopped.")
    
    