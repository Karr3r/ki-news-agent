import os
import json
import feedparser
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
import urllib.request
from dotenv import load_dotenv
from openai import OpenAI

# === Konfiguration ===

# arXiv RSS-Feeds für KI-relevante Kategorien
ARXIV_FEEDS = [
    "http://export.arxiv.org/rss/cs.AI",
    "http://export.arxiv.org/rss/cs.LG",
    "http://export.arxiv.org/rss/cs.CR",
    "http://export.arxiv.org/rss/cs.DC",
    "http://export.arxiv.org/rss/cs.DB",
    "http://export.arxiv.org/rss/cs.NI",
    "http://export.arxiv.org/rss/cs.CY",
    "http://export.arxiv.org/rss/stat.ML",
]

PROCESSED_JSON = "processed_articles.json"

# Lade Umgebungsvariablen aus .env (API-Keys, E-Mail-Daten)
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

client = OpenAI(api_key=OPENAI_API_KEY)

# === Funktionen ===

def get_zeitfenster_utc():
    # Berechnet das 7-Tage-Zeitfenster für Artikel (UTC)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=7)
    print(f"[DEBUG] Zeitfenster UTC: {start.isoformat()} bis {now.isoformat()}")
    return start, now

def load_processed_articles():
    if not os.path.exists(PROCESSED_JSON):
        print("[DEBUG] Keine JSON-Datei mit verarbeiteten Artikeln gefunden.")
        return set()
    with open(PROCESSED_JSON, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            print(f"[DEBUG] Lade {len(data)} verarbeitete Artikel aus JSON.")
            return set(data)
        except json.JSONDecodeError:
            print("[DEBUG] JSON-Datei ist leer oder fehlerhaft.")
            return set()

def save_processed_articles(processed_ids):
    with open(PROCESSED_JSON, "w", encoding="utf-8") as f:
        json.dump(list(processed_ids), f, indent=2)

def fetch_arxiv_entries_neu():
    start, ende = get_zeitfenster_utc()
    processed_ids = load_processed_articles()
    artikel_liste = []
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; KI-News-Agent/1.0; +https://github.com/Karr3r)'}
    for feed_url in ARXIV_FEEDS:
        print(f"[DEBUG] Lade Feed: {feed_url}")
        request = urllib.request.Request(feed_url, headers=headers)
        with urllib.request.urlopen(request) as response:
            data = response.read()
        feed = feedparser.parse(data)
        for entry in feed.entries:
            print(f"[DEBUG] Gefundener Artikel: '{entry.title}', Published: {entry.published}")
            try:
                publ_dt = datetime.strptime(entry.published, "%a, %d %b %Y %H:%M:%S %z")
            except Exception as e:
                print(f"[DEBUG] Fehler bei Datum parsen: {e}, setze als UTC-naiv")
                publ_dt = datetime.strptime(entry.published, "%a, %d %b %Y %H:%M:%S %Z")
                publ_dt = publ_dt.replace(tzinfo=timezone.utc)

            if not (start <= publ_dt < ende):
                print(f"[DEBUG] Artikel '{entry.title}' außerhalb Zeitfenster, ignoriert.")
                continue

            artikel_id = entry.link
            if artikel_id in processed_ids:
                print(f"[DEBUG] Artikel '{entry.title}' bereits verarbeitet, übersprungen.")
                continue

            artikel_liste.append({
                "id": artikel_id,
                "title": entry.title.strip(),
                "authors": [a.name.strip() for a in entry.authors] if hasattr(entry, "authors") else [],
                "abstract": entry.summary.replace("\n", " ").strip() if hasattr(entry, "summary") else "",
                "link": entry.link,
                "published": publ_dt.isoformat()
            })

    print(f"[DEBUG] Insgesamt {len(artikel_liste)} neue Artikel im Zeitfenster gefunden.")
    return artikel_liste

PROMPT_TEMPLATE = """Bitte analysiere und fasse die folgenden wissenschaftlichen Artikel aus dem Bereich Künstliche Intelligenz zusammen.
Die Zusammenfassung soll evidenzbasiert, informativ und relevant für langfristige Technologie-Investitionen sein.
"""

def generiere_ki_uebersicht(artikel_liste):
    if not artikel_liste:
        return "Heute wurden keine neuen relevanten KI-Publikationen gefunden."
    inhalt = ""
    for idx, art in enumerate(artikel_liste, start=1):
        inhalt += (
            f"{idx}. Titel: {art['title']}\n"
            f"   Autoren: {', '.join(art['authors'])}\n"
            f"   Abstract: {art['abstract']}\n"
            f"   Link: {art['link']}\n\n"
        )
    prompt = PROMPT_TEMPLATE + inhalt
    try:
        resp = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.7
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"Fehler bei der Generierung der Übersicht: {e}"

def send_mail(text):
    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = "Tägliche KI-News aus arXiv (letzte 7 Tage)"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_RECEIVER

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            server.send_message(msg)
        print("[DEBUG] E-Mail erfolgreich versendet.")
    except Exception as e:
        print(f"[DEBUG] Fehler beim E-Mail Versand: {e}")

def main():
    artikel = fetch_arxiv_entries_neu()
    if artikel:
        # Verarbeitete Artikel-IDs laden & erweitern
        processed_ids = load_processed_articles()
        new_ids = {art["id"] for art in artikel}
        processed_ids.update(new_ids)
        save_processed_articles(processed_ids)
    else:
        print("[DEBUG] Keine neuen Artikel gefunden.")

    mail_text = generiere_ki_uebersicht(artikel)
    send_mail(mail_text)

if __name__ == "__main__":
    main()

