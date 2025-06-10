#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import feedparser
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

client = OpenAI(api_key=OPENAI_API_KEY)

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

def save_processed(data):
    with open(PROCESSED_FILE, "w") as f:
        json.dump(data, f, indent=2)

processed = load_processed()

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

# ─────────────── 2) Prompt ───────────────
PROMPT = """
Du bist ein hochentwickelter wissenschaftlicher Investment- & Technologieradar für Künstliche Intelligenz und dezentrale Dateninfrastruktur.

Der Nutzer hält bereits 1.000 € in Off-Chain-Storage-Token (FIL, STORJ, ASI/OCEAN, BTT, BZZ, SC) sowie On-Chain-Data-Availability-Token (ETH, TIA, AVAIL, AR, NEAR). Du erhältst täglich neue wissenschaftliche Publikationen (Titel + Abstract) aus peer-reviewten Journalen, Konferenzbeiträgen (z. B. NeurIPS, ICLR, SIGCOMM, SOSP) und Preprints.

### Analyse-Kriterien:
1. **Quantitative Infrastrukturmetriken:**
   - Netzwerk-Adoption
   - Storage-Volumen
   - Transaktionszahlen
   - Entwickleraktivität
   - Token-Ökonomie
2. **Regulatorik & Compliance:**
   - Regulatorische Rahmen wie MiCA, SEC-Klassifizierungen
3. **Roadmaps & Marktdaten:**
   - z. B. Messari, L2BEAT, DePIN Scan, Projekt-Roadmaps
4. **Emergente Architekturen & Systeme:**
   - ZK-Rollups, modulare Blockchain-Architekturen, Data-DAOs, DePIN, KI-optimierte Infrastruktur

### Aufgabe:
1. **Bewerte jede Studie auf einer Skala von 0 (irrelevant) bis 10 (höchste Relevanz)** auf Basis der obigen Kriterien.
   - Studien erhalten nur **9–10 Punkte**, wenn sie **direkt** mit **KI-Infrastruktur oder dezentraler Datenverarbeitung** in Verbindung stehen (z. B. neue DA-Layer, Off-Chain-Storage, DePIN-Konzepte, KI-spezifische Layer-2-Infrastruktur, regulatorische Analysen für Storage-Protokolle etc.).
   - **Allgemeine AI-, Reinforcement-Learning- oder Sicherheitsstudien ohne konkreten Infrastrukturbezug** erhalten **maximal 5–6 Punkte**, selbst bei hoher technischer Qualität.
2. Gib ein prägnantes, faktenbasiertes Fazit (1–2 Sätze), das die Bewertung begründet.
3. Liste ein bis zwei relevante Schlüsselzahlen oder empirische Befunde (z. B. Entwickler-Wachstum, Token-Verteilung, Storage-Volumen, Netzwerkkapazität).
4. Formuliere **ohne Spekulation oder Marketing-Sprache**.

### Format:
- Verwende für die Bewertung **immer ein maschinenlesbares Format**, z. B.:  
  `Relevanz: 8/10`  
- Mögliche Begriffe für die Bewertung (zur besseren Extraktion):  
  **"Relevanz", "Relevance", "Score", "Bewertung", "Rating"**, gefolgt von Zahl/10

Beispielausgabe:
> Titel der Studie  
> Relevanz: 9/10  
> Diese Studie zeigt einen neuen Ansatz zur Off-Chain-Datenverifikation im Filecoin-Netzwerk mit 3× höherer Storage-Effizienz.  
> Beleg: 42 % Wachstum aktiver Nodes in den letzten 6 Monaten.

Bewerte streng und fokussiert auf Substanz im Bereich **Infrastruktur für KI & dezentrale Datenverarbeitung**.


Diese Zeile sollte direkt nach dem Titel oder der Zusammenfassung erscheinen.

Antworte ausschließlich mit einem JSON-Array, ohne Fließtext drumherum.
Jedes Element muss folgende Felder enthalten:
- "kurztitel": String
- "relevant": Integer 0–10
- "kurzfazit": String
- "key_figures": Array von bis zu zwei Strings
"""


def build_prompt(batch):
    text = []
    for i, art in enumerate(batch, start=1):
        text.append(f"{i}. Titel: {art['title']}\n   Abstract: {art['summary']}")
    return PROMPT + "\n\n" + "\n\n".join(text)

# ─────────── 3) JSON-Fallback-Parsing ───────────
def try_parse_json(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fallback: Nummerierte Liste per Regex extrahieren
        out = []
        pattern = re.compile(
            r"(\d+)\.\s*Titel:\s*(.*?)\n\s*(?:Relevanz|Score|Bewertung)[^\d]*([0-9]+)\b.*?Fazit[:\s]*(.*?)(?=\n\d+\.|$)",
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
        processed[a["id"]] = {
            "title":          a["kurztitel"],
            "processed_date": str(date.today()),
            "rating":         a["relevant"],
            "summary":        a["kurzfazit"]
        }
    save_processed(processed)

