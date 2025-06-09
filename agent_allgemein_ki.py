import os
import json
import feedparser
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, UTC
from urllib.parse import quote_plus
from openai import OpenAI
from dotenv import load_dotenv

# Umgebungsvariablen laden
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

client = OpenAI(api_key=OPENAI_API_KEY)

ARXIV_CATEGORIES = ["cs.AI", "cs.LG", "cs.CR", "cs.DC", "cs.DB", "cs.NI", "cs.CY", "stat.ML"]
DAYS_BACK = 7
MAX_TOKENS = 4096
MODEL = "gpt-4"

PROCESSED_FILE = "processed_articles.json"

# Bereits verarbeitete Artikel laden
if os.path.exists(PROCESSED_FILE):
    with open(PROCESSED_FILE, "r") as f:
        processed_ids = set(json.load(f))
else:
    processed_ids = set()

def fetch_arxiv_articles():
    base_url = "http://export.arxiv.org/api/query?"
    search_query_raw = "cat:" + " OR cat:".join(ARXIV_CATEGORIES)
    search_query = quote_plus(search_query_raw)
    start_date = (datetime.now(UTC) - timedelta(days=DAYS_BACK)).strftime("%Y%m%d%H%M%S")
    url = f"{base_url}search_query={search_query}&sortBy=submittedDate&sortOrder=descending&start=0&max_results=200"
    feed = feedparser.parse(url)
    articles = []
    for entry in feed.entries:
        article_id = entry.id.split("/")[-1]
        if article_id in processed_ids:
            continue
        articles.append({
            "id": article_id,
            "title": entry.title,
            "summary": entry.summary,
            "link": entry.link
        })
    return articles

def analyze_articles_gpt(articles):
    analyses = []
    batch_size = 5
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i+batch_size]
        print(f"Analysiere Batch {i+1}/{len(articles)}")
        prompt = """
Du bist ein Investment- und Technologieradar-Agent mit Fokus auf KI, Privacy, Security und Dateninfrastruktur. Analysiere die folgenden wissenschaftlichen Paper auf folgende Weise:

- Für jedes Paper: Gib einen Kurztitel (max. 6 Wörter), eine Aussage ob es relevant ist (true/false) und ein prägnantes Kurzfazit mit Fokus auf langfristiges technologisches Potenzial, disruptive Ansätze oder Investitionsimplikationen.
- Format: JSON-Array von Objekten mit Feldern: kurztitel, relevant, kurzfazit
- Verwende nur gültiges JSON. Kein Text davor oder danach.
"""
        for art in batch:
            prompt += f"\nTitel: {art['title']}\nZusammenfassung: {art['summary']}\n"
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": "Du bist ein wissenschaftlicher Analyseagent."},
                    {"role": "user", "content": prompt.strip()}
                ],
                temperature=0.3
            )
            content = response.choices[0].message.content.strip()
            try:
                result = json.loads(content)
                for a, original in zip(result, batch):
                    a["id"] = original["id"]
                    a["link"] = original["link"]
                analyses.extend(result)
            except json.JSONDecodeError as je:
                print(f"❌ JSON-Fehler bei GPT-Antwort: {je}\nGPT-Rohantwort war:\n{content}")
        except Exception as e:
            print(f"Fehler bei GPT-Analyse: {e}")
    return analyses

def send_email(subject, body):
    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_RECEIVER
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg)
        print("✅ E-Mail gesendet.")
    except Exception as e:
        print(f"❌ Fehler beim Senden der E-Mail: {e}")

if __name__ == "__main__":
    all_articles = fetch_arxiv_articles()
    print(f"Gefundene Artikel: {len(all_articles)}")
    analyses = analyze_articles_gpt(all_articles)

    if analyses:
        relevant = [a for a in analyses if a.get("relevant")]
        debug_text = "\n\n[DEBUG-VOLLANSICHT ALLER ANALYSEN]\n\n" + json.dumps(analyses, indent=2, ensure_ascii=False)
        text = "Neue relevante Paper aus der letzten Woche:\n\n"
        for a in relevant:
            text += f"- {a['kurztitel']}\n  {a['kurzfazit']}\n  {a['link']}\n\n"
        text += debug_text
        send_email("KI-Analyse Report", text)
    else:
        send_email("KI-Analyse Report", "Keine relevanten Artikel gefunden.")

    # Speichern der verarbeiteten IDs
    processed_ids.update([a["id"] for a in all_articles])
    with open(PROCESSED_FILE, "w") as f:
        json.dump(list(processed_ids), f)
