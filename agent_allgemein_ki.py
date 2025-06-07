import os
import json
import urllib.request
import feedparser
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

# Kategorien, die abgefragt werden sollen
ARXIV_CATEGORIES = ["cs.AI", "cs.LG", "cs.CR", "cs.DC", "cs.DB", "cs.NI", "cs.CY", "stat.ML"]

ARXIV_API_BASE = "http://export.arxiv.org/api/query?search_query=cat:{}&start=0&max_results=100"

PROCESSED_ARTICLES_FILE = "processed_articles.json"

def get_zeitfenster_utc():
    """Zeitfenster der letzten 7 Tage in UTC zurückgeben"""
    jetzt = datetime.now(timezone.utc)
    start = jetzt - timedelta(days=7)
    return start, jetzt

def load_processed_articles():
    """Lade bereits verarbeitete Artikel-IDs aus JSON-Datei"""
    if not os.path.exists(PROCESSED_ARTICLES_FILE):
        return set()
    with open(PROCESSED_ARTICLES_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            return set(data)
        except Exception as e:
            print(f"[DEBUG] Fehler beim Laden der verarbeiteten Artikel: {e}")
            return set()

def save_processed_articles(ids):
    """Speichere verarbeitete Artikel-IDs in JSON-Datei"""
    with open(PROCESSED_ARTICLES_FILE, "w", encoding="utf-8") as f:
        json.dump(list(ids), f, indent=2)

def fetch_arxiv_entries_neu():
    start, ende = get_zeitfenster_utc()
    processed_ids = load_processed_articles()
    artikel_liste = []

    headers = {'User-Agent': 'Mozilla/5.0 (compatible; KI-News-Agent/1.0; +https://github.com/Karr3r)'}

    for cat in ARXIV_CATEGORIES:
        url = ARXIV_API_BASE.format(cat)
        print(f"[DEBUG] Lade API Feed: {url}")
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request) as response:
                data = response.read()
        except Exception as e:
            print(f"[DEBUG] Fehler beim Abrufen des Feeds für {cat}: {e}")
            continue

        feed = feedparser.parse(data)
        print(f"[DEBUG] {len(feed.entries)} Einträge im API Feed für Kategorie {cat}.")

        # Debug: Zeige Datum der ersten drei Einträge
        for i, entry in enumerate(feed.entries[:3]):
            print(f"[DEBUG] Beispiel-Eintrag {i+1}")
            print(f"  ID: {entry.id}")
            print(f"  Title: {entry.title}")
            print(f"  published: {getattr(entry, 'published', 'nicht vorhanden')}")
            print(f"  published_parsed: {getattr(entry, 'published_parsed', 'nicht vorhanden')}")

        for entry in feed.entries:
            if not hasattr(entry, "published_parsed"):
                print(f"[DEBUG] Kein published_parsed bei Artikel {entry.get('title','(kein Titel)')}, übersprungen.")
                continue

            publ_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            if not (start <= publ_dt < ende):
                continue

            artikel_id = entry.id
            if artikel_id in processed_ids:
                continue

            artikel_liste.append({
                "id":       artikel_id,
                "title":    entry.title.strip(),
                "authors":  [a.name for a in entry.authors] if hasattr(entry, "authors") else [],
                "abstract": entry.summary.replace("\n", " ").strip() if hasattr(entry, "summary") else "",
                "link":     entry.link,
                "published": publ_dt.isoformat()
            })

    print(f"[DEBUG] Insgesamt {len(artikel_liste)} neue Artikel im Zeitfenster gefunden.")
    return artikel_liste

def send_email(subject, body):
    """Sende eine einfache Text-E-Mail mit den angegebenen Betreff und Inhalt"""
    email_address = os.getenv("EMAIL_ADDRESS")
    email_password = os.getenv("EMAIL_APP_PASSWORD")
    email_receiver = os.getenv("EMAIL_RECEIVER")

    if not (email_address and email_password and email_receiver):
        print("[DEBUG] E-Mail-Zugangsdaten oder Empfänger nicht gesetzt.")
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = email_address
    msg["To"] = email_receiver

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(email_address, email_password)
            smtp.send_message(msg)
        print("[DEBUG] E-Mail erfolgreich versendet.")
        return True
    except Exception as e:
        print(f"[DEBUG] Fehler beim E-Mail-Versand: {e}")
        return False

def main():
    print("[DEBUG] Starte Agent...")
    start, ende = get_zeitfenster_utc()
    print(f"[DEBUG] Zeitfenster UTC: {start.isoformat()} bis {ende.isoformat()}")

    processed_ids = load_processed_articles()
    print(f"[DEBUG] Geladene Artikel-IDs: {list(processed_ids)[:5]} ...")

    artikel = fetch_arxiv_entries_neu()

    if not artikel:
        print("[DEBUG] Keine neuen Artikel gefunden.")
        send_email("KI-News Agent: Keine neuen Artikel", "Im definierten Zeitfenster wurden keine neuen Artikel gefunden.")
        return

    text = "Neue arXiv-Artikel der letzten 7 Tage:\n\n"
    for art in artikel:
        text += f"- {art['title']} ({art['published']})\n  {art['link']}\n\n"

    neue_ids = {art['id'] for art in artikel}
    alle_ids = processed_ids.union(neue_ids)
    save_processed_articles(alle_ids)

    send_email("KI-News Agent: Neue arXiv Artikel", text)

if __name__ == "__main__":
    main()

