#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import sys
import feedparser
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone, date
from urllib.parse import quote_plus
from openai import OpenAI
from dotenv import load_dotenv
import re

# ========================
# Lade Pfade aus Kommandozeile
# ========================
input_path  = sys.argv[1] if len(sys.argv) > 1 else "Data/processed_articles.json"
output_path = sys.argv[2] if len(sys.argv) > 2 else "Data/processed_articles.json"

# Falls Datei noch nicht existiert, initialisiere mit leerem Dict
if not os.path.exists(input_path):
    os.makedirs(os.path.dirname(input_path), exist_ok=True)
    with open(input_path, "w") as f:
        json.dump({}, f)

# Lade bereits verarbeitete Artikel (als Dict mit Titel als Key)
with open(input_path, "r") as f:
    try:
        processed_articles = json.load(f)
        if not isinstance(processed_articles, dict):
            processed_articles = {}
    except json.JSONDecodeError:
        processed_articles = {}

# ──────────────── Konfiguration ────────────────
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS  = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PW   = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

client = OpenAI(api_key=OPENAI_API_KEY)

CATEGORIES       = ["cs.AI","cs.LG","cs.CR","cs.DC","cs.DB","cs.NI","cs.CY","stat.ML"]
DAYS_BACK        = 3
BATCH_SIZE       = 2
RELEVANCE_CUTOFF = 10

# ─────────── Utility: speichere processed_articles ───────────
def save_processed(data):
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

# ─────────────── 1) arXiv-Artikel holen ───────────────
def fetch_articles():
    base = "http://export.arxiv.org/api/query?"
    raw  = "cat:" + " OR cat:".join(CATEGORIES)
    sq   = quote_plus(raw)
    url  = f"{base}search_query={sq}&sortBy=submittedDate&sortOrder=descending&start=0&max_results=200"
    feed = feedparser.parse(url)

    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    new     = []
    seen_titles = set(processed_articles.keys())

    for e in feed.entries:
        title = e.title.strip()
        if title in seen_titles:
            continue
        dt = datetime.strptime(e.published, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if dt < cutoff:
            continue
        new.append({
            "id":      e.id.split("/")[-1],
            "title":   title,
            "summary": e.summary.replace("\n"," ").strip(),
            "link":    e.link
        })
    return new

# ─────────────── 2) Prompt Block (unverändert) ───────────────
PROMPT = """
You are a highly advanced scientific investment & technology radar for artificial intelligence and decentralized data infrastructure. The user already holds €1,000 in off-chain storage tokens (FIL, STORJ, ASI/OCEAN, BTT, BZZ, SC) and on-chain data availability tokens (ETH, TIA, AVAIL, AR, NEAR). You are given a list of new studies (title + abstract) from peer-reviewed journals, conference papers (e.g. NeurIPS, ICLR, IEEE, ACM, SOSP, SIGCOMM), and preprints.

### 1. Goal of analysis
Identify only studies with a **concrete connection to AI infrastructure** and **decentralized data processing**. General AI, model architecture, or cybersecurity studies without an infrastructure reference are **not relevant**.

Your task:
- Strictly evaluate each study based on its relevance to *decentralized AI infrastructure*, *data availability*, *storage networks*, *Data-DAOs*, *modular blockchains*, *AI-scalable architectures*, or *regulation of data infrastructure*.

### 2. Evaluation criteria
Assign a score from **0 to 10** based on these categories:
- **Technology & Infrastructure**: network adoption, storage volume, transaction metrics, developer activity, token economics
- **Emerging paradigms**: ZK-Rollups, modular blockchain architectures, Data-DAOs, DePIN, Filecoin/FVM, AI-optimized infra
- **Regulation & Compliance**: e.g. GDPR, SEC, MiCA, data governance
- **Market data & roadmaps**: e.g. Messari, L2BEAT, DePIN Scan, developer ecosystems

A study is only rated **9–10/10** if it is **directly technically relevant**. Pure LLM, NLP, defense/offense methods, or bioinformatics papers without infra relevance should receive **0–3**.

### 3. Keyword-based relevance signals
Use especially the following **30 key terms** to recognize and weigh papers automatically:

Decentralized storage & infrastructure:
- Decentralized storage
- Peer-to-peer networks (P2P protocols)
- Content-addressing
- Distributed Hash Tables (DHT)
- Merkle Trees / Namespaced Merkle Trees
- Blockweave architecture
- Data Availability Sampling
- Erasure Coding
- Proof-of-Replication / Proof-of-Spacetime
- Proto-Danksharding (EIP-4844)
- Filecoin Virtual Machine (FVM)
- Modular blockchain design
- Layer-2 Rollups
- Zero-Knowledge-Proofs (ZKP)
- Restaking models (e.g. EigenLayer)
- Cross-chain bridges
- Oracle mechanisms (on-chain vs. off-chain)
- Decentralized Identifiers (DID)
- Data-DAOs
- Incentive and token economies
- Content-delivery via P2P (e.g. BTFS)
- Verifiable Data Provenance
- Secure Multiparty Computation
- Persistent archiving (Permanent Storage)
- Developer ecosystems (GitHub activity, SDKs, APIs)

AI & data processing:
- AI data pipelines (Data ingestion)
- Hybrid AI-human workflows
- Data governance and compliance (e.g. GDPR conformity)

Relevance signals:
- **positive**: Studies focusing on these technologies or introducing new technical concepts get higher scores.
- **caution**: Mere mentions of a keyword are not enough – evaluate substance.

### 4. Output format
Respond **exclusively** with a **JSON array**, no extra text.
Each object must have:
- "title": string
- "relevance": integer 0–10
- "summary": string
- "key_figures": array with up to two strings

```markdown
#### Example JSON output for 2 studies:
[
  {
    "title": "Paper A Title",
    "relevance": 8,
    "summary": "Summary for paper A.",
    "key_figures": ["Adoption: 20%", "Volume: 5 TB"]
  },
  {
    "title": "Paper B Title",
    "relevance": 3,
    "summary": "Summary for paper B.",
    "key_figures": []
  }
]

"""

def build_prompt(batch):
    text = []
    for i, art in enumerate(batch, start=1):
        text.append(f"{i}. Title: {art['title']}\n   Abstract: {art['summary']}")
    return PROMPT + "\n\n" + "\n\n".join(text)

# ─────────── 3) JSON-Fallback-Parsing ───────────
def try_parse_json(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        out    = []
        pattern = re.compile(
            r"(\d+)\.\s*Title:\s*(.*?)\n\s*(?:Relevance|Score|Rating|Bewertung)[^\d]*([0-9]+)\b.*?Fazit[:\s]*(.*?)(?=\n\d+\.|$)",
            re.DOTALL|re.IGNORECASE
        )
        for _, title, score, summary in pattern.findall(text):
            out.append({
                "title":   title.strip(),
                "relevance":    int(score),
                "summary":   summary.strip(),
                "key_figures": []
            })
        return out

# ───────── 4) Analyse in Batches ─────────
def analyze(articles):
    analyses = []
    for i in range(0, len(articles), BATCH_SIZE):
        batch = articles[i:i+BATCH_SIZE]
        print(f"Analysiere Batch {i//BATCH_SIZE+1}/{(len(articles)+BATCH_SIZE-1)//BATCH_SIZE+1}")
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role":"system","content": PROMPT},
                {"role":"user",  "content": build_prompt(batch)}
            ],
            temperature=0.2
        )
        content = resp.choices[0].message.content.strip()
        print("🔍 GPT-Antwort:\n", content)  # <-- GPT-Ausgabe anzeigen
        parsed  = try_parse_json(content)
        for rec, art in zip(parsed, batch):
            rec["id"]       = art["id"]
            rec["link"]     = art["link"]
            rec.setdefault("title", art["title"])
            rec.setdefault("relevance", 0)
            rec.setdefault("summary", "")
            rec.setdefault("key_figures", [])
        analyses.extend(parsed)
    return analyses

# ─────────── 5) E-Mail versenden ───────────
def send_email(analyses):
    msg = MIMEMultipart("alternative")
    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = EMAIL_RECEIVER
    msg["Subject"] = f"🧠 KI-Update {date.today()}"

    # Relevanz ≥ cutoff
    html = "<html><body>"
    html += f"<h2>🧠 Relevanz ≥ {RELEVANCE_CUTOFF}</h2>"
    top = sorted([a for a in analyses if a["relevance"]>=RELEVANCE_CUTOFF],
                 key=lambda x: x["relevance"], reverse=True)
    if top:
        for a in top:
            html += (
                f"<div><h3>{a['title']} (<b>{a['relevance']}</b>/10)</h3>"
                f"<p>{a['summary']}</p>"
                f"<a href='{a['link']}'>{a['link']}</a></div><hr>"
            )
    else:
        html += "<p>Keine Artikel mit ausreichender Relevanz gefunden.</p>"

    html += "<h2>⚙️ Debug (alle geladenen Studien nach Score)</h2>"
    for a in sorted(analyses, key=lambda x: x["relevance"], reverse=True):
        html += (
            f"<div><b>{a['title']}</b> (<i>{a['relevance']}/10</i>)<br>"
            f"<a href='{a['link']}'>{a['link']}</a><br>"
            f"<i>{a['summary']}</i></div>"
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
        send_email([])
        sys.exit(0)

    analyses = analyze(articles)

    # 6) Verarbeitet speichern: Titel als Key
    for a in analyses:
        processed_articles[a["title"]] = {
            "id":       a["id"],
            "title":    a["title"],
            "relevance": a["relevance"],
            "summary":  a["summary"]
        }
    save_processed(processed_articles)

    send_email(analyses)
    print(f"✅ Fertig. {len(analyses)} Artikel analysiert.")




