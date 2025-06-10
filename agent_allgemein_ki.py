import os
import json
import time
import openai
import smtplib
from email.message import EmailMessage

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

openai.api_key = OPENAI_API_KEY

PROCESSED_FILE = "processed_articles.json"

# Lade IDs bereits verarbeiteter Artikel, um Duplikate zu vermeiden
def load_processed():
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

# Speichere verarbeitete Artikel-IDs
def save_processed(processed_ids):
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(list(processed_ids), f, ensure_ascii=False, indent=2)

# Beispiel: Funktion zum Abrufen neuer Artikel (hier musst du die reale Logik ergänzen)
def fetch_new_articles():
    # Beispielstruktur: Liste von dicts mit 'id', 'title', 'abstract', 'link'
    # Hier solltest du deine echte Abfrage oder RSS-Parser verwenden
    return [
        {
            "id": "arxiv_2506.08013v1",
            "title": "StableMTL: Repurposing Latent Diffusion Models for Multi-Task Learning from Partially Annotated Synthetic Datasets",
            "abstract": "We propose a method to ...",
            "link": "http://arxiv.org/abs/2506.08013v1"
        },
        # ... mehr Artikel ...
    ]

PROMPT = """
Du bist ein hochentwickelter wissenschaftlicher Investment- & Technologieradar für Künstliche Intelligenz und dezentrale Dateninfrastruktur.
Der Nutzer hält bereits 1 000 € in Off-Chain-Storage-Token (FIL, STORJ, ASI/OCEAN, BTT, BZZ, SC) und On-Chain-Data-Availability-Token (ETH, TIA, AVAIL, AR, NEAR).
Du erhältst eine Liste neuer Studien (jeweils Titel + Abstract) aus peer-reviewten Journalen, Konferenzbeiträgen (NeurIPS, ICLR, IEEE, ACM, SOSP, SIGCOMM) und Preprints (arXiv).

Analyse-Kriterien:
- Quantitative Kennzahlen: Netzwerk-Adoption, Storage-Volumen, Transaktionszahlen, Entwickler-Aktivität, Token-Ökonomie
- Regulatorik & Compliance: z. B. MiCA, SEC-Rahmen
- Marktstudien & Roadmaps: Messari, L2BEAT, DePIN Scan, Projekt-Roadmaps
- Emergente Paradigmen: ZK-Rollups, modulare Blockchain-Architekturen, Data-DAOs, DePIN, KI-optimierte Infrastruktur

Aufgabe:
1. Vergib für jede Studie eine Gesamtbewertung von 0 (irrelevant) bis 10 (höchste Relevanz).
2. Erstelle ein prägnantes 1–2-Satz-Fazit, das die Bewertung begründet.
3. Liste 1–2 Schlüsselzahlen (z. B. Adoption-Rate, Volumen-Wachstum) als Beleg.

Antworte ausschließlich mit einem JSON-Array, ohne Fließtext drumherum.
Jedes Element muss folgende Felder enthalten:
- "kurztitel": String
- "relevant": Integer 0–10
- "kurzfazit": String
- "key_figures": Array von bis zu zwei Strings

Beispiel:
[
  {
    "kurztitel": "NeurIPS Storage Analytics",
    "relevant": 10,
    "kurzfazit": "Hohe Netzwerk-Adoption und starkes Volumenwachstum, daher top relevant.",
    "key_figures": ["Adoption-Rate: 24 %", "Volumen: 15 TB"]
  }
]
"""

def create_prompt(articles):
    studies = []
    for art in articles:
        # Titel und Abstract zusammen für die Analyse
        studies.append({
            "title": art["title"],
            "abstract": art["abstract"]
        })
    return PROMPT + "\n\n" + json.dumps(studies, ensure_ascii=False, indent=2)

def call_openai(prompt):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=2000,
    )
    return response.choices[0].message.content.strip()

def parse_response(response_text):
    try:
        return json.loads(response_text)
    except Exception:
        # Falls JSON nicht sauber: Rückgabe leerer Liste und Log
        print("❌ JSON-Fehler, versuche Fallback-Parsing...")
        print("Roh-Antwort (Auszug):", response_text[:500])
        return []

def send_email(content):
    msg = EmailMessage()
    msg["Subject"] = "KI & Dezentrale Dateninfrastruktur - Tagesreport"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_RECEIVER
    msg.set_content(content)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        smtp.send_message(msg)
    print("✅ E-Mail gesendet")

def main():
    processed_ids = load_processed()
    new_articles = fetch_new_articles()

    # Filtere nur neue Artikel (nach id)
    to_process = [a for a in new_articles if a["id"] not in processed_ids]
    if not to_process:
        print("Keine neuen Artikel zu verarbeiten.")
        return

    prompt = create_prompt(to_process)
    response_text = call_openai(prompt)
    analysis_results = parse_response(response_text)

    # Zuordnung Ergebnisse zu Artikeln
    results = []
    for art, res in zip(to_process, analysis_results):
        results.append({
            "id": art["id"],
            "title": art["title"],
            "link": art["link"],
            "relevant": res.get("relevant") if isinstance(res, dict) else None,
            "kurzfazit": res.get("kurzfazit") if isinstance(res, dict) else "",
            "key_figures": res.get("key_figures") if isinstance(res, dict) else [],
        })

    # Nur die mit Bewertung 10 als relevant herausfiltern
    top_articles = [a for a in results if a.get("relevant") == 10]

    # E-Mail-Inhalt bauen
    mail_content = "🧠 Relevanz = 10\n"
    if top_articles:
        for art in top_articles:
            mail_content += f"{art['title']} ({art['relevant']}/10)\n{art['link']}\n\n"
    else:
        mail_content += "Keine 10/10-Studien gefunden.\n"

    mail_content += "\n⚙️ Debug (alle geladenen Studien)\n"
    for art in results:
        rel = art.get("relevant")
        rel_str = f"{rel}/10" if rel is not None else "n/a/10"
        mail_content += f"{art['title']} ({rel_str})\n{art['link']}\n"

    send_email(mail_content)

    # Verarbeite IDs speichern
    for art in to_process:
        processed_ids.add(art["id"])
    save_processed(processed_ids)

if __name__ == "__main__":
    main()

