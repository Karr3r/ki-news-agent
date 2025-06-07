#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import feedparser
import smtplib
import json
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
import urllib.request
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

# 4. Veröffentlichungsfenster: letzte 7 Tage
ZEITFENSTER_TAGE = 7

# 5. Gelesene Artikel merken
PROCESSED_FILE = "processed_articles.json"

def lade_bekannte_links():
    try:
        with open(PROCESSED_FILE, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()

def speichere_bekannte_links(links):
    try:
        with open(PROCESSED_FILE, "w") as f:
            json.dump(sorted(list(links)), f, indent=2)
    except Exception as e:
        print(f"Fehler beim Speichern von processed_articles.json: {e}")

# 6. Neue Artikel aus dem Zeitraum holen

def fetch_arxiv_entries_neu():
    start = datetime.now(timezone.utc) - timedelta(days=ZEITFENSTER_TAGE)
    bekannte_links = lade_bekannte_links()
    neue_links = set()
    artikel_liste = []

    headers = {'User-Agent': 'Mozilla/5.0 (compatible; KI-News-Agent/1.0; +https://github.com/Karr3r)'}
    for feed_url in ARXIV_FEEDS:
        request = urllib.request.Request(feed_url, headers=headers)
        with urllib.request.urlopen(request) as response:
            data = response.read()
        feed = feedparser.parse(data)
        for entry in feed.entries:
            publ_dt = datetime.strptime(entry.published, "%a, %d %b %Y %H:%M:%S %z")
            publ_dt = publ_dt.astimezone(timezone.utc)
            if publ_dt >= start and entry.link not in bekannte_links:
                artikel_liste.append({
                    "title":    entry.title.strip(),
                    "authors":  [a.name.strip() for a in entry.authors],
                    "abstract": entry.summary.replace("", " ").strip(),
                    "link":     entry.link,
                    "published": publ_dt.isoformat()
                })
                neue_links.add(entry.link)

    if neue_links:
        bekannte_links.update(neue_links)
        speichere_bekannte_links(bekannte_links)

    return artikel_liste

# 7. Wissenschaftlich-investmentbasierter Prompt

PROMPT_TEMPLATE = """Du bist ein hochentwickelter und wissenschaftlicher Agent, der eigenstaendig das Internet und wissenschaftliche Datenbanken nach den neuesten empirischen Erkenntnissen durchsucht, um ein langfristiges (5 bis 10 Jahre) Investment- und Technologie-Monitoring im Bereich 'Kuenstliche Intelligenz' und 'Dezentrale Dateninfrastruktur' durchzufuehren. Dein Nutzer hat bereits 1000 Euro in eine Auswahl von Krypto-Token investiert, sowohl im Off-Chain Storage (FIL, STORJ, ASI/OCEAN, BTT, BZZ, SC) als auch im On-Chain Data Availability Layer (ETH, TIA, AVAIL, AR, NEAR), und moechte diese Positionen bei Bedarf evidenzbasiert anpassen.
        Du beginnst jede Analyse, indem du systematisch nach aktuellen und belastbaren Quellen suchst: peer-reviewte Studien, Konferenzbeitraege (NeurIPS, ICLR, IEEE, ACM, SOSP, SIGCOMM) und Preprints (z.B.arXiv). Besonders relevant sind quantitative Messdaten zu Netzwerk-Adoption, Storage-Volumen, Transaktionszahlen, Entwickler-Aktivitaet, Token-OEkonomie und regulatorischen Rahmenbedingungen.
        Ergaenzend wertest du Marktanalysen (z.B. Messari, L2BEAT, DePIN Scan), technische Roadmaps und wissenschaftlich relevante Whitepapers aus. Du integrierst auch neue Paradigmen der Forschung wie ZK-Rollups, modulare Blockchain-Architekturen, KI-optimierte Infrastruktur, Data-DAOs oder DePIN, sofern sie empirisch begruendet und potenziell disruptiv sind.
        Ziel deiner Arbeit ist eine kritische, evidenzbasierte Bewertung der technologischen und oekonomischen Relevanz dieser Projekte. Jede Einschaetzung wird ausschliesslich auf wissenschaftlicher Grundlage getroffen. Du bewertest Chancen und Risiken mit maximaler Sorgfalt. Spekulative Aussagen oder Marketingbehauptungen haben keinen Platz.
        Beruecksichtige auch neue wissenschaftliche Konzepte, Paradigmenwechsel und Langzeitentwicklungen in der Forschung. Dein Output soll dem Nutzer helfen, zukuenftige Investitionsentscheidungen mit maximaler faktischer Praezision zu treffen.\n"""

# 8. Artikel-Analyse in einem Gesamt-Prompt

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

# 9. E-Mail-Versand

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

# 10. Hauptprogramm

def main():
    artikel = fetch_arxiv_entries_neu()
    uebersicht = generiere_ki_uebersicht(artikel)
    sende_email(uebersicht)

if __name__ == "__main__":
    main()
