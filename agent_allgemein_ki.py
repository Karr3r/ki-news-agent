
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import feedparser
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from openai import OpenAI


# 1. ENV-Variablen aus .env laden

load_dotenv()
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS      = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_RECEIVER     = os.getenv("EMAIL_RECEIVER")

# 2. OpenAI-Client initialisieren
client = OpenAI(api_key=OPENAI_API_KEY)

# 3. arXiv-RSS-Feeds (8 KI-relevante Kategorien)
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


# 4. Zeitfenster: jeweils 24 h von 7:30 MESZ (UTC+2)

def get_zeitfenster_utc():
    utc_plus_2 = timezone(timedelta(hours=2))
    jetzt = datetime.now(utc_plus_2)
    heute_730 = jetzt.replace(hour=7, minute=30, second=0, microsecond=0)
    if jetzt < heute_730:
        start = heute_730 - timedelta(days=1)
        ende  = heute_730
    else:
        start = heute_730
        ende  = heute_730 + timedelta(days=1)
    return start.astimezone(timezone.utc), ende.astimezone(timezone.utc)


# 5. Artikel abrufen und nach Zeitfenster filtern (ohne Obergrenze)

def fetch_arxiv_entries_since_last_run():
    start, ende = get_zeitfenster_utc()
    artikel_liste = []
    for feed_url in ARXIV_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            publ_dt = datetime.strptime(entry.published, "%Y-%m-%dT%H:%M:%SZ")
            publ_dt = publ_dt.replace(tzinfo=timezone.utc)
            if start <= publ_dt < ende:
                artikel_liste.append({
                    "title":    entry.title.strip(),
                    "authors":  [a.name.strip() for a in entry.authors],
                    "abstract": entry.summary.replace("\n", " ").strip(),
                    "link":     entry.link,
                    "published": publ_dt.isoformat()
                })
    return artikel_liste


# 6. Wissenschaftlich-investmentbasierter Prompt

PROMPT_TEMPLATE = """Du bist ein hochentwickelter und wissenschaftlicher Agent, der eigenstaendig das Internet und wissenschaftliche Datenbanken nach den neuesten empirischen Erkenntnissen durchsucht, um ein langfristiges (5 bis 10 Jahre) Investment- und Technologie-Monitoring im Bereich 'Kuenstliche Intelligenz' und 'Dezentrale Dateninfrastruktur' durchzufuehren. Dein Nutzer hat bereits 1000 Euro in eine Auswahl von Krypto-Token investiert, sowohl im Off-Chain Storage (FIL, STORJ, ASI/OCEAN, BTT, BZZ, SC) als auch im On-Chain Data Availability Layer (ETH, TIA, AVAIL, AR, NEAR), und moechte diese Positionen bei Bedarf evidenzbasiert anpassen.
        Du beginnst jede Analyse, indem du systematisch nach aktuellen und belastbaren Quellen suchst: peer-reviewte Studien, Konferenzbeitraege (NeurIPS, ICLR, IEEE, ACM, SOSP, SIGCOMM) und Preprints (z.B.arXiv). Besonders relevant sind quantitative Messdaten zu Netzwerk-Adoption, Storage-Volumen, Transaktionszahlen, Entwickler-Aktivitaet, Token-OEkonomie und regulatorischen Rahmenbedingungen.
        Ergaenzend wertest du Marktanalysen (z.B. Messari, L2BEAT, DePIN Scan), technische Roadmaps und wissenschaftlich relevante Whitepapers aus. Du integrierst auch neue Paradigmen der Forschung wie ZK-Rollups, modulare Blockchain-Architekturen, KI-optimierte Infrastruktur, Data-DAOs oder DePIN, sofern sie empirisch begruendet und potenziell disruptiv sind.
        Ziel deiner Arbeit ist eine kritische, evidenzbasierte Bewertung der technologischen und oekonomischen Relevanz dieser Projekte. Jede Einschaetzung wird ausschliesslich auf wissenschaftlicher Grundlage getroffen. Du bewertest Chancen und Risiken mit maximaler Sorgfalt. Spekulative Aussagen oder Marketingbehauptungen haben keinen Platz.
        Beruecksichtige auch neue wissenschaftliche Konzepte, Paradigmenwechsel und Langzeitentwicklungen in der Forschung. Dein Output soll dem Nutzer helfen, zukuenftige Investitionsentscheidungen mit maximaler faktischer Praezision zu treffen.\n"""
        "nenne dabei Trends, Highlights und besonders erwaehnenswerte Ansaetze:\n\n"

# 7. Artikel-Analyse in einem Gesamt-Prompt

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
    prompt = PROMPT_TEMPLATE.format(artikel=inhalt)
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


# 8. E-Mail-Versand
def sende_email(text, betreff="Dein tägliches KI-Update"):
    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = betreff
    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = EMAIL_RECEIVER
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            server.send_message(msg)
        print("E-Mail erfolgreich versendet.")
    except Exception as e:
        print(f"Fehler beim Versenden der E-Mail: {e}")


# 9. Hauptprogramm

def main():
    artikel = fetch_arxiv_entries_since_last_run()
    uebersicht = generiere_ki_uebersicht(artikel)
    sende_email(uebersicht)

if __name__ == "__main__":
    main()

