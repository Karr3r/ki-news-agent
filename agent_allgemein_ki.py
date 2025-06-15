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
BATCH_SIZE       = 5
RELEVANCE_CUTOFF = 10

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
You are a highly advanced scientific investment and technology radar specialized in Artificial Intelligence and decentralized data infrastructure.

The user currently holds €1,000 in off-chain storage tokens (FIL, STORJ, ASI/OCEAN, BTT, BZZ, SC) and on-chain data availability tokens (ETH, TIA, AVAIL, AR, NEAR).

You receive a list of new studies (each with title and abstract) from peer-reviewed journals, conference proceedings (e.g., NeurIPS, ICLR, IEEE, ACM, SOSP, SIGCOMM), and preprints.

Analysis criteria:
- Quantitative metrics: network adoption, storage volume, transaction counts, developer activity, token economics
- Regulatory & compliance: e.g., MiCA, SEC frameworks
- Market research & roadmaps: Messari, L2BEAT, DePIN Scan, project roadmaps
- Emerging paradigms: zk-rollups, modular blockchain architectures, data DAOs, DePIN, AI-optimized infrastructure

Your task:
1. Assign each study a relevance score from 0 (irrelevant) to 10 (highest relevance) based on the above criteria, with a strict focus on real AI infrastructure and decentralized data processing. Studies only covering general AI, language models, or cybersecurity without clear infrastructure relevance should score low (0–3).
2. Provide a concise 1–2 sentence summary explaining the relevance score.
3. List up to two key figures (e.g., adoption rate, volume growth) as evidence supporting your rating.

Focus on the presence and substantive discussion of the following core keywords and concepts:
- Decentralized storage, Peer-to-peer networks (P2P protocols), Content addressing, Distributed hash tables (DHT), Merkle trees, Namespaced Merkle trees,
  Blockweave architecture, Data availability sampling, Erasure coding, Proof-of-replication, Proof-of-spacetime, Proto-danksharding (EIP-4844),
  Filecoin Virtual Machine (FVM), Modular blockchain design, Layer-2 rollups, Zero-knowledge proofs (ZKP), Restaking models (e.g., EigenLayer),
  Cross-chain bridges, Oracle mechanisms (on-chain vs. off-chain), Decentralized identifiers (DID), Data DAOs, Incentive and token economics,
  Content delivery via P2P (e.g., BTFS), Verifiable data provenance, Secure multiparty computation, Persistent archival storage,
  AI data pipelines (data ingestion), Hybrid AI-human workflows, Data governance and compliance (e.g., GDPR), Developer ecosystem.

Important:
- Only assign high scores (9–10) if the study contains direct and substantive technical relevance to AI infrastructure and decentralized data processing.
- Do not assign "n/a" ratings; use 0 for no relevance.
- Respond exclusively with a JSON array without any additional prose.
- Each element must contain:
  "kurztitel": "Short title of the study",
  "relevant": 0–10,
  "kurzfazit": "Concise summary explaining the score",
  "key_figures": ["Optional key figure 1", "Optional key figure 2"]
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
        print("⚠️ JSON konnte nicht direkt geparst werden – Regex-Fallback wird verwendet.")
        out = []
        pattern = re.compile(
            r"(\d+)\.\s*Title:\s*(.*?)\n\s*(?:Relevance|Score|Rating|Bewertung)[^\d]*([0-9]+)\b.*?Fazit[:\s]*(.*?)(?=\n\d+\.|$)",
            re.DOTALL | re.IGNORECASE
        )
        for idx, title, score, summary in pattern.findall(text):
            out.append({
                "kurztitel":   title.strip(),
                "relevant":    int(score),
                "kurzfazit":   summary.strip(),
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
        parsed  = try_parse_json(content)
        for rec, art in zip(parsed, batch):
            rec["id"]   = art["id"]
            rec["link"] = art["link"]
            rec.setdefault("kurztitel", art["title"])
            rec.setdefault("relevant", 0)
            rec.setdefault("kurzfazit", "")
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
    top = sorted([a for a in analyses if a["relevant"]>=RELEVANCE_CUTOFF],
                 key=lambda x: x["relevant"], reverse=True)
    if top:
        for a in top:
            html += (
                f"<div><h3>{a['kurztitel']} (<b>{a['relevant']}</b>/10)</h3>"
                f"<p>{a['kurzfazit']}</p>"
                f"<a href='{a['link']}'>{a['link']}</a></div><hr>"
            )
    else:
        html += "<p>Keine Artikel mit ausreichender Relevanz gefunden.</p>"

    html += "<h2>⚙️ Debug (alle geladenen Studien nach Score)</h2>"
    for a in sorted(analyses, key=lambda x: x["relevant"], reverse=True):
        html += (
            f"<div><b>{a['kurztitel']}</b> (<i>{a['relevant']}/10</i>)<br>"
            f"<a href='{a['link']}'>{a['link']}</a><br>"
            f"<i>{a['kurzfazit']}</i></div>"
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

    # Verarbeitet speichern: Titel als Key
    for a in analyses:
        processed_articles[a["kurztitel"]] = {
            "id":       a["id"],
            "title":    a["kurztitel"],
            "relevant": a["relevant"],
            "summary":  a["kurzfazit"]
        }
    save_processed(processed_articles)

    send_email(analyses)
    print(f"✅ Fertig. {len(analyses)} Artikel analysiert.")




