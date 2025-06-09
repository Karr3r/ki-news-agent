#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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

# ENV-Variablen laden (lokal über .env, in Actions über Secrets)
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS  = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PW   = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

# OpenAI-Client initialisieren
client = OpenAI(api_key=OPENAI_API_KEY)

# Einstellungen
CATEGORIES     = ["cs.AI","cs.LG","cs.CR","cs.DC","cs.DB","cs.NI","cs.CY","stat.ML"]
DAYS_BACK      = 3
BATCH_SIZE     = 5
PROCESSED_FILE = "processed_articles.json"

# processed_articles.json anlegen, falls nicht vorhanden
if not os.path.exists(PROCESSED_FILE):
    with open(PROCESSED_FILE, "w") as f:
        json.dump([], f)
with open(PROCESSED_FILE, "r") as f:
    processed_ids = set(json.load(f))

# arXiv-Artikel holen
def fetch_articles():
    base = "http://export.arxiv.org/api/query?"
    raw  = "cat:" + " OR cat:".join(CATEGORIES)
    sq   = quote_plus(raw)
    url  = f"{base}search_query={sq}&sortBy=submittedDate&sortOrder=descending&start=0&max_results=200"
    feed = feedparser.parse(url)
    cutoff = datetime.now(UTC) - timedelta(days=DAYS_BACK)
    new = []
    for e in feed.entries:
        dt  = datetime.strptime(e.published, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        aid = e.id.split("/")[-1]
        if dt < cutoff or aid in processed_ids:
            continue
        new.append({"id":aid, "title":e.title.strip(), "summary":e.summary.replace("\n"," ").strip(), "link":e.link})
    return new

# Ultrakurzer Prompt
def build_prompt(batch):
    prompt = (
        "Ultrakurz: Bewerte folgende Paper (Titel+Abstract) auf Relevanz 0–10 "
        "und gib ein 1-Satz-Fazit:" 
    )
    for art in batch:
        prompt += f"\n\nTitel: {art['title']}\nAbstract: {art['summary']}"
    return prompt

# GPT-Analyse in Batches
def analyze(articles):
    result = []
    for idx in range(0, len(articles), BATCH_SIZE):
        batch = articles[idx:idx+BATCH_SIZE]
        print(f"Analysiere Batch {idx//BATCH_SIZE+1}/{(len(articles)-1)//BATCH_SIZE+1}")
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role":"user","content":build_prompt(batch)}],
            temperature=0.2
        )
        content = resp.choices[0].message.content.strip()
        try:
            arr = json.loads(content)
            for rec, art in zip(arr, batch):
                rec['id']   = art['id']
                rec['link'] = art['link']
            result.extend(arr)
        except Exception as e:
            print("❌ JSON-Parse-Fehler:", e)
            print("Roh Antwort:", content)
    return result

# E-Mail-Versand (HTML)
def send_email(analyses):
    msg = MIMEMultipart("alternative")
    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = EMAIL_RECEIVER
    msg["Subject"] = f"KI-Update {datetime.now().date()}"

    # HTML Body zusammenbauen
    html = "<html><body>"
    html += "<h2>🧠 Relevanz >=6</h2>"
    rel = [a for a in analyses if a.get('relevant',0)>=6]
    if rel:
        for a in rel:
            html += (
                f"<div style='margin-bottom:15px'>"
                f"<h3>{a['kurztitel']} (<b>{a['relevant']}</b>/10)</h3>"
                f"<p>{a['kurzfazit']}</p>"
                f"<a href='{a['link']}'>{a['link']}</a>"
                f"</div><hr>"
            )
    else:
        html += "<p>Keine Artikel mit Relevanz >=6.</p>"

    html += "<h2>⚙️ Debug (alle)</h2>"
    for a in analyses:
        html += f"<p><b>{a['kurztitel']}</b>: {a['kurzfazit']} ({a['relevant']}/10)</p>"
    html += "</body></html>"

    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
            s.login(EMAIL_ADDRESS, EMAIL_APP_PW)
            s.send_message(msg)
            print("✅ E-Mail gesendet")
    except Exception as e:
        print("❌ E-Mail-Fehler:", e)

# Haupt
if __name__ == '__main__':
    articles = fetch_articles()
    print(f"Neue Artikel: {len(articles)}")
    if not articles:
        send_email([])
        exit(0)

    analyses = analyze(articles)

    # Speichern
    processed_ids.update([a['id'] for a in articles])
    with open(PROCESSED_FILE, 'w') as f:
        json.dump(list(processed_ids), f)

    send_email(analyses)
