from openai import OpenAI
from dotenv import load_dotenv
import os

# .env laden (achte darauf, dass die .env im selben Ordner liegt, oder Pfad angeben)
load_dotenv()

# API-Key aus Umgebungsvariable lesen
api_key = os.getenv("OPENAI_API_KEY")
print("OpenAI API Key:", api_key)  # Zum Testen, ob der Key geladen wurde

# OpenAI-Client initialisieren mit deinem Key
client = OpenAI(api_key=api_key)

# Beispiel-Chat-Anfrage an GPT-4o-mini (oder dein gewünschtes Modell)
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": "Du bist ein hilfsbereiter Assistent."},
        {"role": "user", "content": "Erzähl mir was über Künstliche Intelligenz."}
    ]
)

# Antwort ausgeben
print(response.choices[0].message.content)

