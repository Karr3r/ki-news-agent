#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import urllib.request
import feedparser
import smtplib
from email.mime.text import MIMEText
import openai
from dotenv import load_dotenv

# 1. ENV-Variablen aus .env laden
load_dotenv()  # Liest .env im aktuellen Verzeichnis ein

OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS      = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_RECEIVER     = os.getenv("EMAIL_RECEIVER")

# 2. OpenAI initialisieren (für GPT-Zusammenfassung)
openai.api_key = OPENAI_API_KEY

# 3. arXiv-RSS-Feed nur für cs.AI (KI)
ARXIV_FEEDS = [
    "http://export.arxiv.org/rss/cs.AI",
]

def fetch_arxiv_entries(max_per_feed=1):
    artikel_liste = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; KI-News-Agent/1.0; +https://github.com/Karr3r)'
    }
    for feed_url in ARXIV_FEEDS:
        req = urllib.request.Request(feed_url, headers=headers)
        with urllib.request.urlopen(req) as response:
            feed_data = response.read()
        feed = feedparser.parse(feed_data)
        for entry in feed.entries[:max_per_feed]:
            titel   = entry.title.strip()
            autore  = [a.name.strip() for a in entry.authors]
            abk     = entry.summary.replace("\n", " ").strip()
            link    = entry.link
            artikel_liste.append({
                "title": titel,
                "authors": autore,
                "abstract": abk,
                "link": link
            })
    return artikel_liste

def generiere_ki_uebersicht(artikel_liste):
    if not artikel_liste:
        return "Heute wurden keine neuen KI-Publikationen gefunden."

    prompt = (
        "Du bist ein Experte für Künstliche Intelligenz. "
        "Fasse bitte in 200–300 Wörtern kurz die folgenden neuen Publikationen zusammen, "
        "nenne dabei Trends, Highlights und besonders erwähnenswerte Ansätze:\n\n"
    )
    for idx, art in enumerate(artikel_liste, start=1):
        prompt += (
            f"{idx}. Titel: {art['title']}\n"
            f"   Autoren: {', '.join(art['authors'])}\n"
            f"   Abstract: {art['abstract']}\n"
            f"   Link: {art['link']}\n\n"
        )
    prompt += "Bitte formuliere in gut lesbarem Deutsch."

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Fehler bei der Generierung der Übersicht: {e}"

def sende_email(text, betreff="Dein tägliches KI-Update"):
    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = betreff
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_RECEIVER

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            server.send_message(msg)
        print("E-Mail erfolgreich versendet.")
    except Exception as e:
        print(f"Fehler beim Versenden der E-Mail: {e}")

def main():
    artikel = fetch_arxiv_entries(max_per_feed=1)
    uebersicht = generiere_ki_uebersicht(artikel)
    sende_email(uebersicht)

if __name__ == "__main__":
    main()
