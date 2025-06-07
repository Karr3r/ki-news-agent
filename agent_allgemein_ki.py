import os
import time
import json
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import smtplib
from dotenv import load_dotenv
import openai
import feedparser

# Umgebung laden
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))

CATEGORIES = ["cs.AI", "cs.LG", "cs.CR", "cs.DC", "cs.DB", "cs.NI", "cs.CY", "stat.ML"]
ARXIV_API_URL = "http://export.arxiv.org/api/query?search_query=cat:{}&start=0&max_results=100"

PROCESSED_FILE = os.path.join(os.path.dirname(__file__), "processed_articles.json")

def debug(msg):
    print(f"[DEBUG] {msg}")

def load_processed_ids():
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_processed_ids(ids):
    with open(PROCESSED_FILE, "w") as f:
        json.dump(list(ids), f)

def fetch_articles():
    articles = []
    for cat in CATEGORIES:
        url = ARXIV_API_URL.format(cat)
        debug(f"Lade API Feed: {url}")
        feed = feedparser.parse(url)
        debug(f"{len(feed.entries)} Einträge im API Feed für Kategorie {cat}.")
        for i, entry in enumerate(feed.entries[:3]):
            debug(f"Beispiel-Eintrag {i+1}")
            debug(f"  ID: {entry.id}")
            debug(f"  Title: {entry.title}")
            debug(f"  published: {entry.published}")
            debug(f"  published_parsed: {entry.published_parsed}")
        articles.extend(feed.entries)
    return articles

def is_recent(published_parsed, days=7):
    now = datetime.now(timezone.utc)
    published = datetime(*published_parsed[:6], tzinfo=timezone.utc)
    return now - timedelta(days=days) <= published <= now

def analyze_article(entry):
    content = f"""
arXiv-Titel: {entry.title}
Zusammenfassung: {entry.summary}
Publikationsdatum: {entry.published}

Bitte analysiere diesen Artikel im Hinblick auf:
1. Relevanz für langfristige Entwicklungen in Künstlicher Intelligenz (KI) und maschinellem Lernen (ML),
2. mögliche Auswirkungen auf dezentrale Dateninfrastrukturen oder sicherheitsrelevante Systeme,
3. ob dieser Artikel potenziell ein Signal für ein strategisches Technologie- oder Investmentthema ist.
Gib eine evidenzbasierte Einschätzung ab. Antworte in maximal 8 Sätzen.
"""
    response = openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Du bist ein Analyst für KI und Tech-Investments."},
            {"role": "user", "content": content.strip()}
        ],
        temperature=0.4
    )
    return response.choices[0].message.content.strip()

def send_email(subject, body):
    msg = EmailMessage()
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        debug("E-Mail erfolgreich versendet.")

def main():
    debug("Starte Agent...")
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(days=7)
    debug(f"Zeitfenster UTC: {start_time.isoformat()} bis {now.isoformat()}")

    processed_ids = load_processed_ids()
    debug(f"Geladene Artikel-IDs: {list(processed_ids)[:5]} ...")

    articles = fetch_articles()

    new_articles = []
    for entry in articles:
        if entry.id in processed_ids:
            continue
        if not hasattr(entry, "published_parsed"):
            continue
        if is_recent(entry.published_parsed):
            new_articles.append(entry)

    debug(f"Insgesamt {len(new_articles)} neue Artikel im Zeitfenster gefunden.")

    relevant_articles = []
    debug_view = []
    for entry in new_articles:
        try:
            summary = analyze_article(entry)
            relevant_articles.append((entry, summary))
        except Exception as e:
            debug(f"Fehler bei Analyse: {e}")
        debug_view.append(f"{entry.published[:10]} — {entry.title.strip()}")

    if not relevant_articles:
        debug("Keine neuen Artikel gefunden.")
        email_body = (
            "Täglicher arXiv-Agentenbericht (DEBUG-MODUS)\n\n"
            "Keine relevanten neuen Artikel erkannt.\n\n"
            "Letzte 7 Tage (Debug-Ansicht):\n"
            + "\n".join(debug_view)
        )
        send_email("arXiv-Agent: Keine neuen Artikel", email_body)
        return

    # Nur wenn relevante Artikel erkannt wurden
    email_body = "Täglicher arXiv-Agentenbericht\n\n"
    for entry, summary in relevant_articles:
        email_body += f"🧠 {entry.title.strip()}\n"
        email_body += f"📅 {entry.published[:10]}\n"
        email_body += f"🔗 {entry.id}\n"
        email_body += f"📄 Analyse:\n{summary}\n\n"

    email_body += "\nLetzte 7 Tage (Debug-Ansicht):\n"
    email_body += "\n".join(debug_view)

    send_email("arXiv-Agent: Neue relevante Artikel", email_body)

    # IDs merken
    processed_ids.update(entry.id for entry in new_articles)
    save_processed_ids(processed_ids)

if __name__ == "__main__":
    main()

