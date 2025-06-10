#!/usr/bin/env python3Add commentMore actions
# -*- coding: utf-8 -*-

import os
import json
import feedparser
from datetime import datetime, timedelta
from openai import OpenAI
from dotenv import load_dotenv
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, UTC, date
from urllib.parse import quote_plus
from openai import OpenAI
from dotenv import load_dotenv
import re

# ──────────────── Konfiguration ────────────────
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS  = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PW   = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
EMAIL_ADDRESS = os.environ["EMAIL_ADDRESS"]
EMAIL_APP_PASSWORD = os.environ["EMAIL_APP_PASSWORD"]
EMAIL_RECEIVER = os.environ["EMAIL_RECEIVER"]

CATEGORIES = [
    "cs.AI", "cs.LG", "cs.CR", "cs.DC", "cs.DB", "cs.NI", "cs.CY", "stat.ML"
]
DAYS_BACK = 7
PROCESSED_FILE = "processed_articles.json"
RELEVANCE_THRESHOLD = 8
client = OpenAI(api_key=OPENAI_API_KEY)

if os.path.exists(PROCESSED_FILE):
    with open(PROCESSED_FILE, "r") as f:
        processed_ids = set(json.load(f))
else:
    processed_ids = set()
CATEGORIES        = ["cs.AI","cs.LG","cs.CR","cs.DC","cs.DB","cs.NI","cs.CY","stat.ML"]
DAYS_BACK         = 3
BATCH_SIZE        = 5
PROCESSED_FILE    = "processed_articles.json"
RELEVANCE_CUTOFF  = 10   # Nur 10/10 sind relevant

# ─────────── processed_articles.json laden ───────────
def load_processed():
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, "r") as f:
            return json.load(f)
    return {}

def fetch_articles():
    articles = []
    cutoff = datetime.utcnow() - timedelta(days=DAYS_BACK)
    for cat in CATEGORIES:
        url = f"https://export.arxiv.org/rss/{cat}"
        feed = feedparser.parse(url)
        for entry in feed.entries:
            if entry.id in processed_ids:
                continue
            published = datetime(*entry.published_parsed[:6])
            if published < cutoff:
                continue
            articles.append({
                "id": entry.id,
                "title": entry.title,
                "summary": entry.summary,
                "link": entry.link
            })
    return articles
def save_processed(data):
    with open(PROCESSED_FILE, "w") as f:
        json.dump(data, f, indent=2)

processed = load_processed()

PROMPT = (
    "3. Du bist ein wissenschaftlicher Investment- und Technologieradar für Künstliche Intelligenz & dezentrale Dateninfrastruktur.\n"
    "Dein Nutzer hat 1 000 € in Off-Chain-Storage-Token (FIL, STORJ, ASI/OCEAN, BTT, BZZ, SC) und On-Chain-Data-Availability-Token (ETH, TIA, AVAIL, AR, NEAR) investiert.\n"
    "Du bekommst vom Agenten eine Liste neuer Studien (Titel + Abstract).\n"
    "Untersuche jede Studie anhand dieser Kriterien:\n"
    "  • Quantitative Daten (Netzwerk-Adoption, Storage-Volumen, Transaktionszahlen, Entwickler-Aktivität, Token-Ökonomie)\n"
    "  • Regulatorische Rahmenbedingungen\n"
    "  • Marktanalysen (Messari, L2BEAT, DePIN Scan) und Roadmaps\n"
    "Bewerte jedes Paper auf einer Skala von 0 (irrelevant) bis 10 (höchstrelevant).\n"
    "Gib zudem ein kurzes 1–2-Satz-Fazit, das deine Entscheidung erläutert.\n"
    "Spekulation und Marketing-Sprache unterlasse – bleibe strikt empirisch und wissenschaftlich.\n"
)
# ─────────────── 1) arXiv-Artikel holen ───────────────
def fetch_articles():
    base   = "http://export.arxiv.org/api/query?"
    raw    = "cat:" + " OR cat:".join(CATEGORIES)
    sq     = quote_plus(raw)
    url    = f"{base}search_query={sq}&sortBy=submittedDate&sortOrder=descending&start=0&max_results=200"
    feed   = feedparser.parse(url)

    cutoff = datetime.now(UTC) - timedelta(days=DAYS_BACK)
    new    = []
    for e in feed.entries:
        aid = e.id.split("/")[-1]
        if aid in processed:
            continue
        dt  = datetime.strptime(e.published, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        if dt < cutoff:
            continue
        new.append({
            "id":      aid,
            "title":   e.title.strip(),
            "summary": e.summary.replace("\n"," ").strip(),
            "link":    e.link
        })
    return new

# ─────────────── 2) Langweiliger Prompt ───────────────
def build_prompt(studies):
    studies_text = "\n\n".join(f"Title: {s['title']}\nAbstract: {s['abstract']}" for s in studies)
    prompt = f"""
Du bist ein hochentwickelter wissenschaftlicher Investment- & Technologieradar für Künstliche Intelligenz und dezentrale Dateninfrastruktur.
Der Nutzer hält bereits 1 000 € in Off-Chain-Storage-Token (FIL, STORJ, ASI/OCEAN, BTT, BZZ, SC) und On-Chain-Data-Availability-Token (ETH, TIA, AVAIL, AR, NEAR).
Du erhältst eine Liste neuer Studien (jeweils Titel + Abstract) aus peer-reviewten Journalen, Konferenzbeiträgen (NeurIPS, ICLR, IEEE, ACM, SOSP, SIGCOMM) und Preprints (arXiv).

**Analyse-Kriterien:**
- Quantitative Kennzahlen: Netzwerk-Adoption, Storage-Volumen, Transaktionszahlen, Entwickler-Aktivität, Token-Ökonomie
- Regulatorik & Compliance: z. B. MiCA, SEC-Rahmen
- Marktstudien & Roadmaps: Messari, L2BEAT, DePIN Scan, Projekt-Roadmaps
- Emergente Paradigmen: ZK-Rollups, modulare Blockchain-Architekturen, Data-DAOs, DePIN, KI-optimierte Infrastruktur

**Aufgabe:**
1. Vergib für jede Studie eine Gesamtbewertung von 0 (irrelevant) bis 10 (höchste Relevanz).
2. Erstelle ein prägnantes 1–2-Satz-Fazit, das die Bewertung begründet.
3. Liste 1–2 Schlüsselzahlen (z. B. Adoption-Rate, Volumen-Wachstum) als Beleg.

Antworte ausschließlich mit einem JSON-Array, ohne Fließtext drumherum.
Jedes Element muss folgende Felder enthalten:
- "kurztitel": String
- "relevant": Integer 0–10
- "kurzfazit": String
- "key_figures": Array von bis zu zwei Strings

Hier sind die Studien:
{studies_text}
"""
    return prompt


# ─────────── 3) JSON-Fallback-Parsing ───────────
def try_parse_json(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fallback: Nummerierte Liste per Regex extrahieren
        out = []
        pattern = re.compile(
            r"(\d+)\.\s*Titel:\s*(.*?)\n\s*Relevanz[:\s]*([0-9]+)\b.*?Fazit[:\s]*(.*?)(?=\n\d+\.|$)",
            re.DOTALL | re.IGNORECASE
        )
        for idx, title, score, summary in pattern.findall(text):
            out.append({
                "kurztitel": title.strip(),
                "relevant": int(score),
                "kurzfazit": summary.replace("\n"," ").strip()
            })
        return out

# ───────── 4) Analyse in 5er-Batches ─────────
def analyze(articles):
    analyses = []
    batch_size = 5
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        text = "\n\n".join(f"Titel: {a['title']}\nAbstract: {a['summary']}" for a in batch)
        try:
            print(f"Analysiere Batch {i // batch_size + 1}/{(len(articles) - 1) // batch_size + 1}")
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": text}
                ],
                temperature=0.2
            )
            raw = response.choices[0].message.content.strip()
            try:
                parsed = parse_response(raw, batch)
                analyses.extend(parsed)
            except Exception as e:
                print(f"❌ JSON-Fehler, versuche Fallback-Parsing...\nRoh-Antwort (Auszug): {raw[:300]}")
                fallback = fallback_parse(raw, batch)
                analyses.extend(fallback)
        except Exception as e:
            print(f"❌ GPT-/JSON-Fehler: {e}\nRoh-Antwort: {raw if 'raw' in locals() else '?'}")
    return analyses


def parse_response(raw, batch):
    lines = [line for line in raw.splitlines() if line.strip()]
    analyses = []
    i = 0
    for line in lines:
        if i >= len(batch):
            break
        a = batch[i]
        if any(str(n) in line for n in range(11)) and "/10" in line:
            score = int([s for s in line.split() if s.isdigit()][0])
            text = line.split("-", 1)[-1].strip()
            analyses.append({"id": a["id"], "score": score, "summary": text, "title": a["title"], "link": a["link"]})
            i += 1
    for i in range(0, len(articles), BATCH_SIZE):
        batch = articles[i:i+BATCH_SIZE]
        print(f"Analysiere Batch {i//BATCH_SIZE+1}/{(len(articles)+BATCH_SIZE-1)//BATCH_SIZE+1}")
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role":"system",  "content": PROMPT},
                {"role":"user",    "content": build_prompt(batch)}
            ],
            temperature=0.2
        )
        content = resp.choices[0].message.content.strip()
        parsed  = try_parse_json(content)
        # IDs & Links ergänzen, defaults setzen
        for rec, art in zip(parsed, batch):
            rec["id"]       = art["id"]
            rec["link"]     = art["link"]
            rec.setdefault("kurztitel", art["title"])
            rec.setdefault("relevant", 0)
            rec.setdefault("kurzfazit", "")
        analyses.extend(parsed)
    return analyses


def fallback_parse(raw, batch):
    analyses = []
    for i, a in enumerate(batch):
        block = raw.split("\n\n")[i] if i < len(raw.split("\n\n")) else ""
        score = None
        for s in range(10, -1, -1):
            if f"{s}/10" in block or f"Relevanz: {s}" in block:
                score = s
                break
        summary = block.strip().split("Fazit:")[-1].strip() if "Fazit:" in block else block.strip()
        analyses.append({"id": a["id"], "score": score or 0, "summary": summary, "title": a["title"], "link": a["link"]})
    return analyses


def send_email(analyses, all_articles):
    relevant = [a for a in analyses if a["score"] >= RELEVANCE_THRESHOLD]

    body = f"""🧠 Relevanz ≥ {RELEVANCE_THRESHOLD}
"""
    if not relevant:
        body += "Keine Artikel mit Relevanz ≥ {RELEVANCE_THRESHOLD} gefunden.\n"
# ─────────── 5) E-Mail versenden ───────────
def send_email(analyses, articles):
    msg = MIMEMultipart("alternative")
    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = EMAIL_RECEIVER
    msg["Subject"] = f"🧠 KI-Update {date.today()}"

    # Nur 10/10 als relevant
    html = "<html><body>"
    html += "<h2>🧠 Relevanz = 10</h2>"
    top = [a for a in analyses if a.get("relevant")==RELEVANCE_CUTOFF]
    if top:
        for a in top:
            html += (
                f"<div style='margin-bottom:15px;'>"
                f"<h3>{a['kurztitel']} (<b>10</b>/10)</h3>"
                f"<p>{a['kurzfazit']}</p>"
                f"<a href='{a['link']}'>{a['link']}</a>"
                f"</div><hr>"
            )
    else:
        for a in relevant:
            body += f"{a['score']}/10 – {a['title']}\n{a['summary']}\n{a['link']}\n\n"

    body += "\n⚙️ Debug (alle geladenen Artikel)\n"
        html += "<p>Keine 10/10-Studien gefunden.</p>"

    # Debug: alle Artikel mit Bewertung & Fazit
    html += "<h2>⚙️ Debug (alle geladenen Studien)</h2>"
    mp = {a["id"]:a for a in analyses}
    for art in articles:
        a = mp.get(art["id"], {})
        score = a.get("relevant", "n/a")
        fazit = a.get("kurzfazit","")
        html += (
            f"<div style='margin-bottom:10px;'>"
            f"<b>{art['title']}</b> (<i>{score}/10</i>)<br>"
            f"<a href='{art['link']}'>{art['link']}</a><br>"
            f"<i>{fazit}</i>"
            f"</div>"
        )
    html += "</body></html>"
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(EMAIL_ADDRESS, EMAIL_APP_PW)
        s.send_message(msg)
        print("✅ E-Mail gesendet")

# ───────── Hauptprogramm ─────────
if __name__ == "__main__":
    articles = fetch_articles()
    print(f"Neue Artikel: {len(articles)}")
    if not articles:
        send_email([], [])
        exit(0)

    analyses = analyze(articles)

    # E-Mail senden
    send_email(analyses, articles)

    # Als verarbeitet markieren & speichern
    for a in analyses:
        body += f"{a['score']}/10 – {a['title']}\n{a['link']}\n\n"

    msg = MIMEText(body)
    msg["Subject"] = "🧠 Tägliches KI-Update"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_RECEIVER

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        smtp.send_message(msg)


articles = fetch_articles()
print(f"Neue Artikel: {len(articles)}")

analyses = analyze(articles)
send_email(analyses, articles)

# Artikel als verarbeitet markieren
processed_ids.update(a["id"] for a in articles)
with open(PROCESSED_FILE, "w") as f:
    json.dump(list(processed_ids), f)
        processed[a["id"]] = {
            "title":          a["kurztitel"],
            "processed_date": str(date.today()),
            "rating":         a["relevant"],
            "summary":        a["kurzfazit"]
        }
    save_processed(processed)
