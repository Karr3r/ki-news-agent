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

# 1) ENV-Variablen
load_dotenv()
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS    = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PW     = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_RECEIVER   = os.getenv("EMAIL_RECEIVER")

# 2) OpenAI-Client
client = OpenAI(api_key=OPENAI_API_KEY)

# 3) Einstellungen
CATEGORIES    = ["cs.AI","cs.LG","cs.CR","cs.DC","cs.DB","cs.NI","cs.CY","stat.ML"]
DAYS_BACK     = 3
BATCH_SIZE    = 5
PROCESSED_FILE= "processed_articles.json"

# 4) processed_articles.json anlegen, falls nicht vorhanden
if not os.path.exists(PROCESSED_FILE):
    with open(PROCESSED_FILE, "w") as f:
        json.dump([], f)
with open(PROCESSED_FILE, "r") as f:
    processed_ids = set(json.load(f))

# 5) arXiv-Artikel holen
def fetch_articles():
    base = "http://export.arxiv.org/api/query?"
    raw = "cat:" + " OR cat:".join(CATEGORIES)
    sq = quote_plus(raw)
    url = f"{base}search_query={sq}&sortBy=submittedDate&sortOrder=descending&start=0&max_results=200"
    feed = feedparser.parse(url)
    cutoff = datetime.now(UTC) - timedelta(days=DAYS_BACK)
    new = []
    for e in feed.entries:
        dt = datetime.strptime(e.published, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        aid= e.id.split("/")[-1]
        if dt < cutoff or aid in processed_ids:
            continue
        new.append({
            "id":      aid,
            "title":   e.title.strip(),
            "summary": e.summary.replace("\n"," ").strip(),
            "link":    e.link
        })
    return new

# 6) Ultrakurzer Prompt
def build_prompt(batch):
    prompt = (
        "Ultrakurz: Bewerte folgende Paper (Titel+Abstract) auf Relevanz 0–10 "
        "und gib ein 1-Satz-Fazit:"
    )
    for art in batch:
        prompt += f"\n\nTitel: {art['title']}\nAbstract: {art['summary']}"
    return prompt

# 7) GPT-Analyse in Batches
def analyze(batches):
    analyses = []
    for idx, batch in enumerate(batches, start=1):
        print(f"[{idx}/{len(batches)}] GPT-Analyse …")
        content = ""
        try:
            resp = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role":"user","content": build_prompt(batch)}],
                temperature=0.2
            )
            content = resp.choices[0].message.content.strip()
            data = json.loads(content)
            # ID+Link ergänzen
            for rec, art in zip(data, batch):
                rec["id"]   = art["id"]
                rec["link"] = art["link"]
            analyses.extend(data)
        except Exception as e:
            print("❌ GPT-Fehler oder JSON:", e, "\nRoh:", content)
    return analyses

# 8) E-Mail verschönern und versenden
def send_email(analyses):
    msg = MIMEMultipart("alternative")
    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = EMAIL_RECEIVER
    msg["Subject"] = f"KI-Update {datetime.now().date()}"

    # HTML-Body
    html = """<html><body>
      <h2 style="border-bottom:1px solid #ccc;">🧠 Relevante Artikel</h2>"""
    rel = [a for a in analyses if a.get("relevant",0)>=6]
    if rel:
        for a in rel:
            html += f"""
            <div style="margin-bottom:15px;">
              <h3 style="margin:0;">{a['kurztitel']} (<b>{a['relevant']}</b>/10)</h3>
              <p style="margin:5px 0;">{a['kurzfazit']}</p>
              <a href="{a['link']}">{a['link']}</a>
            </div>
            <hr>"""
    else:
        html += "<p>Keine stark relevanten Artikel (>=6) gefunden.</p>"

    html += """
      <h2 style="border-bottom:1px solid #ccc;">⚙️ Debug (alle analysierten)</h2>"""
    for a in analyses:
        html += f"""
        <div style="margin-bottom:10px;">
          <b>{a['kurztitel']}</b>: {a['kurzfazit']} ({a['relevant']}/10)
        </div>"""
    html += "</body></html>"

    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
            s.login(EMAIL_ADDRESS, EMAIL_APP_PW)
            s.send_message(msg)
            print("✅ E-Mail gesendet")
    except Exception as e:
        print("❌ E-Mail-Fehler:", e)

# 9) Hauptlauf
if __name__=="__main__":
    arts = fetch_articles()
    print(f"Neue Artikel: {len(arts)}")
    if not arts:
        send_email([])
        exit(0)

    # Batches bilden
    batches = [arts[i:i+BATCH_SIZE] for i in range(0,len(arts),BATCH_SIZE)]
    result = analyze(batches)

    # processed_ids aktualisieren
    processed_ids.update([a["id"] for a in arts])
    with open(PROCESSED_FILE,"w") as f:
        json.dump(list(processed_ids), f)

    send_email(result)
