import os
import json
import openai
import feedparser
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
RECIPIENT_ADDRESS = os.getenv("RECIPIENT_ADDRESS")

# RSS feeds
RSS_FEEDS = [
    "http://export.arxiv.org/rss/cs.AI",
    "http://export.arxiv.org/rss/cs.LG",
    "http://export.arxiv.org/rss/cs.CR",
    "http://export.arxiv.org/rss/cs.DC",
    "http://export.arxiv.org/rss/cs.DB",
    "http://export.arxiv.org/rss/cs.NI",
    "http://export.arxiv.org/rss/cs.CY",
    "http://export.arxiv.org/rss/stat.ML",
]

# Load processed articles
PROCESSED_FILE = "processed_articles.json"
if os.path.exists(PROCESSED_FILE):
    with open(PROCESSED_FILE, "r") as f:
        processed_articles = json.load(f)
else:
    processed_articles = {}

def save_processed_articles():
    with open(PROCESSED_FILE, "w") as f:
        json.dump(processed_articles, f, indent=2)

def fetch_articles():
    articles = []
    cutoff_date = datetime.utcnow() - timedelta(days=3)
    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            arxiv_id = entry.link.split("/")[-1]
            if arxiv_id in processed_articles:
                continue
            published = datetime(*entry.published_parsed[:6])
            if published < cutoff_date:
                continue
            article = {
                "id": arxiv_id,
                "title": entry.title,
                "summary": entry.summary,
                "link": entry.link,
                "published": published.strftime("%Y-%m-%d"),
            }
            articles.append(article)
    return articles

def analyse_article_with_gpt(article):
    prompt = f"""
    Du bist ein KI- und Technologie-Analyst.

    Analysiere den folgenden arXiv-Artikel im Hinblick auf langfristig relevante wissenschaftlich-technologische Trends.

    Artikel:
    Titel: {article['title']}
    Zusammenfassung: {article['summary']}

    Gib die Ausgabe bitte im folgenden JSON-Format zurück:
    {{
        "kurztitel": "...",
        "innovation": "...",
        "relevanz": "...",
        "anwendungspotenzial": "...",
        "langfristiges_investmentpotenzial": "...",
        "fazit": "...",
        "relevant_fuer_newsletter": true/false
    }}
    """

    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        content = response.choices[0].message.content
        analysis = json.loads(content)
        return analysis
    except Exception as e:
        return {"error": str(e), "raw": content if 'content' in locals() else "", "relevant_fuer_newsletter": False}

def send_email(relevant_analyses, debug_infos):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Täglicher KI arXiv Report"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = RECIPIENT_ADDRESS

    html = """
    <html><body>
    <h2>🧠 Relevante Artikel (laut GPT)</h2>
    """
    if relevant_analyses:
        for analysis in relevant_analyses:
            html += f"""
            <h3>{analysis.get('kurztitel', 'Unbenannt')}</h3>
            <p><strong>Innovation:</strong> {analysis.get('innovation', '')}</p>
            <p><strong>Relevanz:</strong> {analysis.get('relevanz', '')}</p>
            <p><strong>Anwendungspotenzial:</strong> {analysis.get('anwendungspotenzial', '')}</p>
            <p><strong>Langfristiges Investmentpotenzial:</strong> {analysis.get('langfristiges_investmentpotenzial', '')}</p>
            <p><strong>Fazit:</strong> {analysis.get('fazit', '')}</p>
            <hr>
            """
    else:
        html += "<p>Keine relevanten Artikel laut GPT.</p>"

    html += "<h2>🛠 Debug-Ansicht (alle Artikel der letzten 3 Tage)</h2>"
    for debug in debug_infos:
        html += f"""
        <h4>{debug['article']['title']}</h4>
        <p><a href='{debug['article']['link']}'>{debug['article']['link']}</a></p>
        <pre>{json.dumps(debug['analysis'], indent=2, ensure_ascii=False)}</pre>
        <hr>
        """

    html += "</body></html>"
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)

# ==== Hauptlogik ====
articles = fetch_articles()
relevant_analyses = []
debug_infos = []

for article in articles:
    analysis = analyse_article_with_gpt(article)
    debug_infos.append({"article": article, "analysis": analysis})
    if analysis.get("relevant_fuer_newsletter"):
        relevant_analyses.append(analysis)
    processed_articles[article["id"]] = article["published"]

save_processed_articles()
send_email(relevant_analyses, debug_infos)
