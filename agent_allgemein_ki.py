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

# 2) Prompt bauen mit neuem Prompttext
def build_prompt(batch):
    prompt = (
        "Du bist ein wissenschaftlicher Investment- und Technologieradar für Künstliche Intelligenz und dezentrale Dateninfrastruktur. "
        "Dein Nutzer hat 1.000 € in Off-Chain-Storage-Token (z. B. FIL, STORJ, ASI/OCEAN, BTT, BZZ, SC) und On-Chain-Data-Availability-Token "
        "(z. B. ETH, TIA, AVAIL, AR, NEAR) investiert.\n\n"
        "Du erhältst eine Liste neuer Studien (Titel und Abstract). Bewerte jedes Paper auf einer Skala von 0 (irrelevant) bis 10 (höchstrelevant) "
        "für eine langfristige (5–10 Jahre) Investitionsentscheidung.\n\n"
        "Berücksichtige dabei ausschließlich objektive und wissenschaftliche Kriterien:\n"
        "• Quantitative Daten wie Netzwerkadoption, Storage-Volumen, Transaktionszahlen, Entwickleraktivität und Token-Ökonomie\n"
        "• Relevante regulatorische Rahmenbedingungen und deren Auswirkungen auf das Projektumfeld\n"
        "• Marktanalysen, z. B. von Messari, L2BEAT, DePIN Scan, sowie Roadmaps und technologische Entwicklungsperspektiven\n\n"
        "Gib zu jedem Paper außerdem ein prägnantes 1–2-Satz-Fazit, das deine Bewertung begründet. Vermeide Spekulationen und Marketing-Sprache – bleibe strikt empirisch und wissenschaftlich.\n\n"
        "Die Liste der Paper:\n"
    )
    for i, art in enumerate(batch, start=1):
        prompt += f"\n{i}. Titel: {art['title']}\nAbstract: {art['summary']}\n"
    prompt += "\nBitte gib das Ergebnis als JSON-Liste aus, mit Feldern: kurztitel (Titel), relevant (Bewertung 0-10 als Zahl), kurzfazit (1–2 Sätze)."
    return prompt

# 3) Versuche JSON zu parsen, falls Fehler: Fallback (regex) - robust gegen nicht-json-formatierten Text
def try_parse_json(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fallback: Versuch eine strukturierte Liste per Regex rauszuziehen (sehr einfach)
        results = []
        pattern = re.compile(
            r"(\d+)\.\s*Titel:\s*(.+?)\s+Relevanz[:\s]*([0-9]+)[^\d]*(?:Fazit|Summary|Begründung)[:\s]*(.+?)(?=\d+\.|$)",
            re.DOTALL | re.IGNORECASE)
        matches = pattern.findall(text)
        if matches:
            for _, title, score, summary in matches:
                try:
                    score_num = int(score)
                except:
                    score_num = 0
                results.append({
                    "kurztitel": title.strip(),
                    "relevant": score_num,
                    "kurzfazit": summary.strip().replace("\n"," "),
                })
            return results
        else:
            raise

# 4) GPT-Analyse in Batches
def analyze(articles):
    analyses = []
    for idx in range(0, len(articles), BATCH_SIZE):
        batch = articles[idx:idx+BATCH_SIZE]
        print(f"Analysiere Batch {idx//BATCH_SIZE+1}/{(len(articles)-1)//BATCH_SIZE+1}")
        try:
            resp = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role":"user", "content": build_prompt(batch)}],
                temperature=0.2
            )
            content = resp.choices[0].message.content.strip()
            try:
                arr = try_parse_json(content)
            except Exception as e:
                print("❌ JSON-Fehler, versuche Fallback-Parsing...")
                print("Roh-Antwort (Auszug):", content[:500])
                arr = []
            # ID & Link ergänzen, evtl. default Werte
            for rec, art in zip(arr, batch):
                rec["id"]   = art["id"]
                rec["link"] = art["link"]
                if "kurztitel" not in rec:
                    rec["kurztitel"] = art["title"]
                if "relevant" not in rec:
                    rec["relevant"] = 0
                if "kurzfazit" not in rec:
                    rec["kurzfazit"] = ""
            analyses.extend(arr)
        except Exception as e:
            print("❌ GPT-/JSON-Fehler:", e)
    return analyses

# 5) E-Mail versenden (Relevanz ab 8, Debug alle Artikel mit Bewertung)
def send_email(analyses, articles):
    msg = MIMEMultipart("alternative")
    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = EMAIL_RECEIVER
    msg["Subject"] = f"KI-Update {datetime.now().date()}"

    # Relevante Artikel (Score >= 8)
    html = "<html><body>"
    html += "<h2 style='border-bottom:1px solid #ccc;'>🧠 Relevanz ≥ 8</h2>"
    rel = [a for a in analyses if a.get("relevant", 0) >= 8]
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
        html += "<p>Keine Artikel mit Relevanz ≥ 8 gefunden.</p>"

    # Debug-Abschnitt: alle neu geladenen Artikel mit Bewertung (wenn vorhanden)
    html += "<h2 style='border-bottom:1px solid #ccc;'>⚙️ Debug (neu geladen mit Bewertung)</h2>"
    # Map Artikel-ID auf Bewertung + Fazit, falls vorhanden
    analysis_map = {a["id"]: a for a in analyses}
    for art in articles:
        a = analysis_map.get(art["id"], {})
        score = a.get("relevant", "n/a")
        fazit = a.get("kurzfazit", "")
        html += (
            f"<div style='margin-bottom:10px;'>"
            f"<b>{art['title']}</b> (<i>Bewertung: {score}/10</i>)<br>"
            f"<a href='{art['link']}'>{art['link']}</a><br>"
            f"<i>{fazit}</i>"
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
        send_email([], [])  # gibt Debug leer aus
        exit(0)

    analyses =

