import os
import json
import openai
import feedparser
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
RECIPIENT_ADDRESS = os.getenv("RECIPIENT_ADDRESS")

RSS_FEEDS = ["http://export.arxiv.org/rss/cs.AI"]
PROCESSED_FILE = "processed_articles.json"

if os.path.exists(PROCESSED_FILE):
    with open(PROCESSED_FILE, "r") as f:
        processed_articles = json.load(f)
else:
    processed_articles = {}

def save_processed_articles():
    with open(PROCESSED_FILE, "w") as f:
        json.dump(processed_articles, f, indent=2)

def get_cutoff_datetime():
    now_utc = datetime.now(timezone.utc)
    utc_plus_2 = timezone(timedelta(hours=2))
    now_local = now_utc.astimezone(utc_plus_2)
    cutoff_local = now_local.replace(hour=7, minute=30, second=0, microsecond=0)
    if now_local < cutoff_local:
        cutoff_local -= timedelta(days=1)
    # erweitere auf 3 Tage rückwirkend ab Cutoff
    return (cutoff_local - timedelta(days=2)).astimezone(timezone.utc)

def fetch_articles():
    articles = []
    cutoff_date = get_cutoff_datetime()
    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            arxiv_id = entry.link.split("/")[-1]
            if arxiv_id in processed_articles:
                continue
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            if published < cutoff_date:
                continue
            articles.append({
                "id": arxiv_id,
                "title": entry.title,
                "summary": entry.summary,
                "link": entry.link,
                "published": published.isoformat()
            })
    return articles

def analyse_articles_batch(articles):
    prompt_intro = (
        "Du bist ein KI-Analyst. Analysiere die folgenden arXiv-Artikel und gib für jeden "
        "Artikel eine kurze Einschätzung in JSON zurück, mit diesen Feldern:\n"
        "- kurztitel (kurzer Titel)\n"
        "- relevant (true/false, ob relevant für KI-Newsletter)\n"
        "- kurzfazit (max 1 Satz)\n\nArtikel:\n"
    )
    for i, art in enumerate(articles, start=1):
        prompt_intro += f"{i}. Titel: {art['title']}\n   Zusammenfassung: {art['summary']}\n"
    prompt_intro += "\nGib die Antwort als JSON-Liste zurück."

    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt_intro}],
            temperature=0.2,
            max_tokens=1500
        )
        content = response.choices[0].message.content
        try:
            analyses = json.loads(content)
            return analyses
        except json.JSONDecodeError as je:
            print("❌ JSON-Fehler bei GPT-Antwort:", je)
            print("GPT-Rohantwort war:\n", content)
            return []
    except Exception as e:
        print("Fehler bei GPT-Analyse:", e)
        return []

def analyse_all_in_batches(all_articles, batch_size=5):
    all_analyses = []
    for i in range(0, len(all_articles), batch_size):
        batch = all_articles[i:i+batch_size]
        result = analyse_articles_batch(batch)
        if not result:
            print(f"⚠️ Leere Analyse bei Batch {i//batch_size + 1}")
        all_analyses.extend(result)
    return all_analyses

def send_email(relevant_analyses, debug_infos):
    if not debug_infos:
        print("⚠️ Kein Inhalt für Debug-Infos vorhanden → Mail wird nicht gesendet.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Täglicher KI arXiv Report"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = RECIPIENT_ADDRESS

    html = "<html><body>"
    html += "<h2>🧠 Relevante Artikel (laut GPT)</h2>"

    if relevant_analyses:
        for analysis in relevant_analyses:
            html += f"<h3>{analysis.get('kurztitel', 'Kein Titel')}</h3>"
            html += f"<p><b>Fazit:</b> {analysis.get('kurzfazit', '')}</p><hr>"
    else:
        html += "<p>Keine relevanten Artikel.</p>"

    html += "<h2>🛠 Debug-Ansicht (alle Artikel der letzten 3 Tage ab 7:30)</h2>"
    for debug in debug_infos:
        art = debug['article']
        html += f"<h4>{art['title']}</h4>"
        html += f"<p><a href='{art['link']}'>{art['link']}</a></p>"
        html += f"<pre>{json.dumps(debug['analysis'], indent=2, ensure_ascii=False)}</pre><hr>"

    html += "</body></html>"
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg)
            print("✅ E-Mail erfolgreich gesendet.")
    except smtplib.SMTPAuthenticationError as e:
        print("❌ SMTP-Authentifizierungsfehler:", e)
    except Exception as e:
        print("❌ Fehler beim Senden der E-Mail:", e)

# === Hauptlogik ===
articles = fetch_articles()

if not articles:
    print("ℹ️ Keine neuen Artikel gefunden.")
    exit(0)

analyses = analyse_all_in_batches(articles)

relevant_analyses = []
debug_infos = []

if not analyses:
    print("⚠️ GPT konnte keine Analysen liefern. Kein Versand.")
    exit(1)

for article, analysis in zip(articles, analyses):
    debug_infos.append({"article": article, "analysis": analysis})
    processed_articles[article["id"]] = article["published"]
    if analysis.get("relevant", False):
        relevant_analyses.append(analysis)

save_processed_articles()
send_email(relevant_analyses, debug_infos)
