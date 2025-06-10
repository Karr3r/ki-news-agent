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
import re

# ENV-Variablen laden
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS  = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PW   = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

# OpenAI-Client
client = OpenAI(api_key=OPENAI_API_KEY)

# Einstellungen
CATEGORIES     = ["cs.AI","cs.LG","cs.CR","cs.DC","cs.DB","cs.NI","cs.CY","stat.ML"]
DAYS_BACK      = 3
BATCH_SIZE     = 5
PROCESSED_FILE = "processed_articles.json"

# processed_articles.json anlegen/laden
if not os.path.exists(PROCESSED_FILE):
    with open(PROCESSED_FILE, "w") as f:
        json.dump([], f)
with open(PROCESSED_FILE, "r") as f:
    processed_ids = set(json.load(f))

# 1) arXiv-Artikel holen
def fetch_articles():
    base   = "http://export.arxiv.org/api/query?"
    raw    = "cat:" + " OR cat:".join(CATEGORIES)
    sq     = quote_plus(raw)
    url    = f"{base}search_query={sq}&sortBy=submittedDate&sortOrder=descending&start=0&max_results=200"
    feed   = feedparser.parse(url)
    cutoff = datetime.now(UTC) - timedelta(days=DAYS_BACK)
    new    = []
    for e in feed.entries:
        dt  = datetime.strptime(e.published, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        aid = e.id.split("/")[-1]
        if dt < cutoff or aid in processed_ids:
            continue
        new.append({
            "id":      aid,
            "title":   e.title.strip(),
            "summary": e.summary.replace("\n"," ").strip(),
            "link":    e.link
        })
    return new

# 2) Prompt

def build_prompt(batch):
    p = (
        "Du bist ein wissenschaftlicher Investment-Agent für KI & dezentrale Dateninfrastruktur.\n"
        "Analysiere die übergebenen Studien (Titel + Abstract) auf langfristige (5–10 Jahre) Relevanz.\n"
        "Bewerte jedes Paper mit einer Zahl von 0 bis 10 und liefere zu jedem ein 1-Satz-Fazit.\n"
        "Antworte bitte im folgenden Format:\n\n"
        "1. Titel: <Titel>\n"
        "   Relevanz: <Bewertung 0-10>\n"
        "   Fazit: <1 Satz Fazit>\n\n"
        "Beginne mit den folgenden Papers:\n"
    )
    for i, art in enumerate(batch, 1):
        p += f"{i}. Titel: {art['title']}\n   Abstract: {art['summary']}\n"
    return p

# 3) Fallback-Parsing bei fehlgeschlagenem JSON

def parse_gpt_output(raw_text, batch):
    parsed = []
    pattern = re.compile(
        r"\d+\.\s*Titel:\s*(.*?)\n\s*Relevanz:?\s*(\d+)\n\s*Fazit:\s*(.*?)\n(?=\d+\. Titel:|\Z)",
        re.DOTALL | re.IGNORECASE
    )
    matches = pattern.findall(raw_text)

    for (title, rel, summary), art in zip(matches, batch):
        try:
            parsed.append({
                "kurztitel": title.strip(),
                "relevant": int(rel.strip()),
                "kurzfazit": summary.strip(),
                "id": art["id"],
                "link": art["link"]
            })
        except Exception as e:
            print("⚠️ Fehler beim Parsen eines Eintrags:", e)
            continue

    return parsed

# 4) GPT-Analyse in Batches

def analyze(articles):
    analyses = []
    for idx in range(0, len(articles), BATCH_SIZE):
        batch = articles[idx:idx+BATCH_SIZE]
        print(f"Analysiere Batch {idx//BATCH_SIZE+1}/{(len(articles)+BATCH_SIZE-1)//BATCH_SIZE}")
        try:
            resp = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": build_prompt(batch)}],
                temperature=0.2
            )
            content = resp.choices[0].message.content.strip()
            try:
                arr = json.loads(content)
                for rec, art in zip(arr, batch):
                    rec["id"] = art["id"]
                    rec["link"] = art["link"]
                analyses.extend(arr)
            except json.JSONDecodeError:
                print("❌ JSON-Fehler, versuche Fallback-Parsing...")
                print("Roh-Antwort (Auszug):", content[:300].replace("\n", " ") + "…")
                fallback = parse_gpt_output(content, batch)
                if fallback:
                    analyses.extend(fallback)
                else:
                    print("⚠️ Fallback-Parsing fehlgeschlagen.")
        except Exception as e:
            print("❌ GPT-/Analysefehler:", e)
    return analyses

# 5) E-Mail versenden (mit Relevanzfilter & Debug)

def send_email(analyses, articles):
    msg = MIMEMultipart("alternative")
    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = EMAIL_RECEIVER
    msg["Subject"] = f"KI-Update {datetime.now().date()}"

    html = "<html><body>"
    html += "<h2 style='border-bottom:1px solid #ccc;'>🧠 Relevanz ≥ 6</h2>"
    rel = [a for a in analyses if a.get("relevant", 0) >= 6]
    if rel:
        for a in rel:
            html += (
                f"<div style='margin-bottom:15px;'>"
                f"<h3>{a['kurztitel']} (<b>{a['relevant']}</b>/10)</h3>"
                f"<p>{a['kurzfazit']}</p>"
                f"<a href='{a['link']}'>{a['link']}</a>"
                f"</div><hr>"
            )
    else:
        html += "<p>Keine Artikel mit Relevanz ≥ 6 gefunden.</p>"

    html += "<h2 style='border-bottom:1px solid #ccc;'>⚙️ Debug (neu geladen)</h2>"
    aid_map = {a["id"]: a for a in analyses}
    for art in articles:
        analysis = aid_map.get(art["id"], {})
        score = analysis.get("relevant", "–")
        title = analysis.get("kurztitel", art["title"])
        html += (
            f"<div style='margin-bottom:10px;'>"
            f"<b>{title}</b> (<b>{score}</b>/10)<br>"
            f"<a href='{art['link']}'>{art['link']}</a>"
            f"</div>"
        )

    html += "</body></html>"
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(EMAIL_ADDRESS, EMAIL_APP_PW)
            s.send_message(msg)
            print("✅ E-Mail gesendet")
    except Exception as e:
        print("❌ Fehler beim Senden:", e)

# 6) Hauptprogramm

if __name__ == "__main__":
    articles = fetch_articles()
    print(f"Neue Artikel: {len(articles)}")
    if not articles:
        send_email([], [])
        exit(0)

    analyses = analyze(articles)
    processed_ids.update([a["id"] for a in articles])
    with open(PROCESSED_FILE, "w") as f:
        json.dump(list(processed_ids), f)

    send_email(analyses, articles)
