import feedparser
import openai
import json
import os
import smtplib
import time
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from dotenv import load_dotenv
from itertools import islice
import re

load_dotenv()

# OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# Email
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

# Kategorien
CATEGORIES = [
    "cs.AI", "cs.LG", "cs.CR", "cs.DC",
    "cs.DB", "cs.NI", "cs.CY", "stat.ML"
]

DAYS_BACK = 3
BATCH_SIZE = 5

BASE_URL = "http://export.arxiv.org/rss/"

processed_ids_path = os.path.join(os.path.dirname(__file__), "processed_articles.json")
if os.path.exists(processed_ids_path):
    with open(processed_ids_path, "r") as f:
        processed_ids = set(json.load(f))
else:
    processed_ids = set()

def save_processed_ids():
    with open(processed_ids_path, "w") as f:
        json.dump(list(processed_ids), f)

def fetch_articles():
    articles = []
    for cat in CATEGORIES:
        d = feedparser.parse(BASE_URL + cat)
        for entry in d.entries:
            published = datetime(*entry.published_parsed[:6])
            if datetime.now() - published < timedelta(days=DAYS_BACK):
                if entry.id not in processed_ids:
                    articles.append({
                        "id": entry.id,
                        "title": entry.title,
                        "summary": entry.summary,
                        "link": entry.link
                    })
    return articles

def chunked(iterable, size):
    it = iter(iterable)
    return iter(lambda: list(islice(it, size)), [])

def clean_json_string(json_str):
    json_str = re.sub(r",\s*(\}|\])", r"\\1", json_str)
    json_str = json_str.replace("$\\ell_2$", "l2").replace("ℓ₂", "l2")
    json_str = json_str.replace("\\", "\\\\")
    return json_str

def analyse_articles_batch(batch):
    system_prompt = """
    Du bist ein wissenschaftlicher KI-Analyst. Für jeden Paper-Titel + Abstract gib eine Analyse im JSON-Format zurück:
    [
        {
            "kurztitel": "kurzer Titel oder Akronym",
            "relevant": true/false,
            "kurzfazit": "Ein prägnantes Fazit, warum das Paper relevant oder nicht relevant ist."
        },
        ...
    ]
    """

    user_input = "\n".join(
        [f"Titel: {a['title']}\nAbstract: {a['summary']}" for a in batch]
    )

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ]
        )
        content = response.choices[0].message.content.strip()
        cleaned = clean_json_string(content)
        try:
            result = json.loads(cleaned)
            return result
        except json.JSONDecodeError as je:
            print("❌ JSON-Fehler nach Cleanup:", je)
            print("Bereinigte GPT-Rohantwort:\n", cleaned)
            return []
    except Exception as e:
        print("Fehler bei GPT-Analyse:", e)
        return []

def send_email(analyses, debug_infos):
    body = "\n\n".join([
        f"{a['kurztitel']}\nRelevant: {a['relevant']}\n{a['kurzfazit']}"
        for a in analyses
    ])
    debug_text = "\n\n--- DEBUG INFOS ---\n\n" + "\n\n".join(debug_infos)

    msg = MIMEText(body + debug_text)
    msg["Subject"] = f"KI-Analyse Report – {datetime.now().strftime('%Y-%m-%d')}"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_RECEIVER

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg)
            print("✅ E-Mail gesendet")
    except Exception as e:
        print("❌ Fehler beim Senden der E-Mail:", e)

if __name__ == "__main__":
    all_articles = fetch_articles()
    print(f"Gefundene neue Artikel: {len(all_articles)}")

    relevant_analyses = []
    debug_infos = []

    for i, batch in enumerate(chunked(all_articles, BATCH_SIZE)):
        print(f"Analysiere Batch {i+1}/{(len(all_articles) // BATCH_SIZE) + 1}")
        analysis = analyse_articles_batch(batch)
        if not analysis:
            debug_infos.append(f"⚠️ Leere Analyse bei Batch {i+1}")
        else:
            for result in analysis:
                if result.get("relevant"):
                    relevant_analyses.append(result)
        time.sleep(1.5)

    processed_ids.update([a["id"] for a in all_articles])
    save_processed_ids()

    send_email(relevant_analyses, debug_infos)
