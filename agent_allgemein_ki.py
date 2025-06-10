import os
import json
import feedparser
from datetime import datetime, timedelta
from openai import OpenAI
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText

load_dotenv()

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

if os.path.exists(PROCESSED_FILE):
    with open(PROCESSED_FILE, "r") as f:
        processed_ids = set(json.load(f))
else:
    processed_ids = set()


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
    else:
        for a in relevant:
            body += f"{a['score']}/10 – {a['title']}\n{a['summary']}\n{a['link']}\n\n"

    body += "\n⚙️ Debug (alle geladenen Artikel)\n"
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


