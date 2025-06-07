import os
import json
import feedparser
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
import urllib.request
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS      = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_RECEIVER     = os.getenv("EMAIL_RECEIVER")

client = OpenAI(api_key=OPENAI_API_KEY)

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

def get_zeitfenster_utc():
    utc_plus_2 = timezone(timedelta(hours=2))
    jetzt = datetime.now(utc_plus_2)
    heute_730 = jetzt.replace(hour=7, minute=30, second=0, microsecond=0)
    if jetzt < heute_730:
        start = heute_730 - timedelta(days=7)  # 7 Tage zurück
        ende  = heute_730
    else:
        start = heute_730 - timedelta(days=6)  # Start 6 Tage zurück (inkl. heute = 7 Tage)
        ende  = heute_730 + timedelta(days=1)
    print(f"[DEBUG] Zeitfenster UTC: {start.isoformat()} bis {ende.isoformat()}")
    return start.astimezone(timezone.utc), ende.astimezone(timezone.utc)


def load_processed_articles(filename="processed_articles.json"):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                print(f"[DEBUG] Lade {len(data)} verarbeitete Artikel aus JSON.")
                return data
            except json.JSONDecodeError:
                print("[DEBUG] JSON-Datei ist leer oder ungültig, starte mit leerer Liste.")
                return []
    else:
        print("[DEBUG] JSON-Datei nicht gefunden, starte mit leerer Liste.")
        return []

def save_processed_articles(artikel_ids, filename="processed_articles.json"):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(artikel_ids, f, indent=2, ensure_ascii=False)
    print(f"[DEBUG] {len(artikel_ids)} Artikel-IDs in JSON-Datei gespeichert.")


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
            # Debug: Alle Rohdaten der Einträge anzeigen
            print(f"[DEBUG] Gefundener Artikel: '{entry.title}', Published: {entry.published}")

            try:
            publ_dt = datetime.strptime(entry.published, "%a, %d %b %Y %H:%M:%S %z")
             publ_dt = publ_dt.astimezone(timezone.utc)
            print(f"[DEBUG] Parsed Datum mit TZ: {publ_dt.isoformat()}")
            except Exception as e:
    print(f"[DEBUG] Fehler bei Datum parsen mit TZ: {e}, versuche ohne TZ")
    # Fallback: ohne Zeitzone parsen, dann manuell UTC setzen
    publ_dt = datetime.strptime(entry.published, "%a, %d %b %Y %H:%M:%S %Z")
    publ_dt = publ_dt.replace(tzinfo=timezone.utc)
    print(f"[DEBUG] Parsed Datum ohne TZ, manuell UTC gesetzt: {publ_dt.isoformat()}")



            # Filter Zeitfenster
            if not (start <= publ_dt < ende):
                print(f"[DEBUG] Artikel '{entry.title}' außerhalb Zeitfenster, ignoriert.")
                continue

            # ID für Duplikatcheck, z.B. Link (kann man anpassen)
            artikel_id = entry.link
            if artikel_id in processed_ids:
                print(f"[DEBUG] Artikel '{entry.title}' bereits verarbeitet, übersprungen.")
                continue

            artikel_liste.append({
                "id":       artikel_id,
                "title":    entry.title.strip(),
                "authors":  [a.name.strip() for a in entry.authors] if hasattr(entry, "authors") else [],
                "abstract": entry.summary.replace("\n", " ").strip() if hasattr(entry, "summary") else "",
                "link":     entry.link,
                "published": publ_dt.isoformat()
            })

    print(f"[DEBUG] Insgesamt {len(artikel_liste)} neue Artikel im Zeitfenster gefunden.")
    return artikel_liste


PROMPT_TEMPLATE = """Du bist ein hochentwickelter und wissenschaftlicher Agent, der eigenstaendig das Internet und wissenschaftliche Datenbanken nach den neuesten empirischen Erkenntnissen durchsucht, um ein langfristiges (5 bis 10 Jahre) Investment- und Technologie-Monitoring im Bereich 'Kuenstliche Intelligenz' und 'Dezentrale Dateninfrastruktur' durchzufuehren. Dein Nutzer hat bereits 1000 Euro in eine Auswahl von Krypto-Token investiert, sowohl im Off-Chain Storage (FIL, STORJ, ASI/OCEAN, BTT, BZZ, SC) als auch im On-Chain Data Availability Layer (ETH, TIA, AVAIL, AR, NEAR), und moechte diese Positionen bei Bedarf evidenzbasiert anpassen.
Du beginnst jede Analyse, indem du systematisch nach aktuellen und belastbaren Quellen suchst: peer-reviewte Studien, Konferenzbeitraege (NeurIPS, ICLR, IEEE, ACM, SOSP, SIGCOMM) und Preprints (z.B.arXiv). Besonders relevant sind quantitative Messdaten zu Netzwerk-Adoption, Storage-Volumen, Transaktionszahlen, Entwickler-Aktivitaet, Token-OEkonomie und regulatorischen Rahmenbedingungen.
Ergaenzend wertest du Marktanalysen (z.B. Messari, L2BEAT, DePIN Scan), technische Roadmaps und wissenschaftlich relevante Whitepapers aus. Du integrierst auch neue Paradigmen der Forschung wie ZK-Rollups, modulare Blockchain-Architekturen, KI-optimierte Infrastruktur, Data-DAOs oder DePIN, sofern sie empirisch begruendet und potenziell disruptiv sind.
Ziel deiner Arbeit ist eine kritische, evidenzbasierte Bewertung der technologischen und oekonomischen Relevanz dieser Projekte. Jede Einschaetzung wird ausschliesslich auf wissenschaftlicher Grundlage getroffen. Du bewertest Chancen und Risiken mit maximaler Sorgfalt. Spekulative Aussagen oder Marketingbehauptungen haben keinen Platz.
Beruecksichtige auch neue wissenschaftliche Konzepte, Paradigmenwechsel und Langzeitentwicklungen in der Forschung. Dein Output soll dem Nutzer helfen, zukuenftige Investitionsentscheidungen mit maximaler faktischer Praezision zu treffen.\n"""


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


def sende_email(text, betreff="Dein tägliches KI-Update"):
    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = betreff
    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = EMAIL_RECEIVER
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            server.send_message(msg)
        print("[DEBUG] E-Mail erfolgreich versendet.")
    except Exception as e:
        print(f"[DEBUG] Fehler beim Versenden der E-Mail: {e}")


def main():
    artikel = fetch_arxiv_entries_neu()
    if artikel:
        # IDs speichern, um Duplikate in Zukunft zu vermeiden
        processed_ids = load_processed_articles()
        neue_ids = [art["id"] for art in artikel]
        combined_ids = list(set(processed_ids) | set(neue_ids))
        save_processed_articles(combined_ids)
    uebersicht = generiere_ki_uebersicht(artikel)
    sende_email(uebersicht)


if __name__ == "__main__":
    main()
