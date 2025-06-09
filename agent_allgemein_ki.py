import os
import json
import openai
import feedparser
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# 1) ENV-Variablen laden
load_dotenv()
openai.api_key       = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS       = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD      = os.getenv("EMAIL_PASSWORD")         # GitHub Secret: EMAIL_PASSWORD
RECIPIENT_ADDRESS   = os.getenv("EMAIL_RECEIVER")         # GitHub Secret: EMAIL_RECEIVER

# 2) RSS-Feed (cs.AI)
RSS_FEEDS = ["http://export.arxiv.org/rss/cs.AI"]

# 3) Duplikat-Tracking
PROCESSED_FILE = "processed_articles.json"
if os.path.exists(PROCESSED_FILE):
    with open(PROCESSED_FILE, "r") as f:
        processed_articles = json.load(f)
else:
    processed_articles = {}

def save_processed_articles():
    with open(PROCESSED_FILE, "w") as f:
        json.dump(processed_articles, f, indent=2)

# 4) Zeitfenster: Letzte 24 h ab 07:30 (UTC+2)
def get_cutoff_datetime():
    now_utc    = datetime.now(timezone.utc)
    utc_plus2  = timezone(timedelta(hours=2))
    now_local  = now_utc.astimezone(utc_plus2)
    cutoff_loc = now_local.replace(hour=7, minute=30, second=0, microsecond=0)
    if now_local < cutoff_loc:
        cutoff_loc -= timedelta(days=1)
    return cutoff_loc.astimezone(timezone.utc)

# 5) Artikel holen
def fetch_articles():
    cutoff = get_cutoff_datetime()
    arts   = []
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for e in feed.entries:
            aid = e.link.split("/")[-1]
            if aid in processed_articles:
                continue
            pub = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
            if pub < cutoff:
                continue
            arts.append({
                "id":        aid,
                "title":     e.title,
                "summary":   e.summary,
                "link":      e.link,
                "published": pub.isoformat()
            })
    return arts

# 6) Batch-Analyse (max 5 Artikel pro Call)
def analyse_articles_in_batches(articles, batch_size=5):
    all_analyses = []
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i+batch_size]
        prompt = (
            "Du bist ein KI-Analyst. Analysiere diese arXiv-Artikel, gib für jeden\n"
            "- kurztitel (Titel)\n"
            "- relevant (true/false für KI-Newsletter)\n"
            "- kurzfazit (max. 1 Satz)\n\nArtikel:\n"
        )
        for idx, art in enumerate(batch, start=1):
            prompt += f"{idx}. {art['title']}\n   {art['summary']}\n"
        prompt += "\nAntwort als JSON-Liste [{\"kurztitel\":...,\"relevant\":...,\"kurzfazit\":...},...]."

        try:
            resp = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role":"user","content":prompt}],
                temperature=0.2,
                max_tokens=1500
            )
            results = json.loads(resp.choices[0].message.content)
        except Exception as e:
            print("GPT-Fehler im Batch:", e)
            # Platzhalter-Fehlerobjekte
            results = [{"kurztitel":"Fehler","relevant":False,"kurzfazit":""}] * len(batch)

        all_analyses.extend(results)
    return all_analyses

# 7) E-Mail versenden
def send_email(relevant, debug):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Täglicher KI arXiv Report"
    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = RECIPIENT_ADDRESS

    html = "<html><body>"
    html += "<h2>🧠 Relevante Artikel</h2>"
    if relevant:
        for a in relevant:
            html += f"<h3>{a['kurztitel']}</h3><p>{a['kurzfazit']}</p><hr>"
    else:
        html += "<p>Keine relevanten Artikel.</p>"

    html += "<h2>🛠 Debug (alle Artikel)</h2>"
    for entry, analysis in debug:
        html += f"<h4>{entry['title']}</h4>"
        html += f"<p><a href='{entry['link']}'>{entry['link']}</a></p>"
        html += f"<pre>{json.dumps(analysis, indent=2, ensure_ascii=False)}</pre><hr>"

    html += "</body></html>"
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        s.send_message(msg)
        print("E-Mail versendet.")

# === Main ===
articles = fetch_articles()
if not articles:
    print("Keine neuen Artikel.")
    exit(0)

analyses = analyse_articles_in_batches(articles, batch_size=5)
relevant, debug = [], []
for art, an in zip(articles, analyses):
    debug.append((art, an))
    processed_articles[art["id"]] = art["published"]
    if an.get("relevant"):
        relevant.append(an)

save_processed_articles()
send_email(relevant, debug)
