import os
import json
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from dotenv import load_dotenv
from openai import OpenAI, OpenAIError
from openai.types.chat import ChatCompletionMessageParam

# .env laden
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

client = OpenAI(api_key=OPENAI_API_KEY)

PROCESSED_FILE = "processed_articles.json"
DAYS_BACK = 3
MAX_TOKENS = 4096

ARXIV_CATEGORIES = [
    "cs.AI", "cs.LG", "cs.CR", "cs.DC", "cs.DB", "cs.NI", "cs.CY", "stat.ML"
]

# Lade bereits verarbeitete IDs
def load_processed_ids():
    if not os.path.exists(PROCESSED_FILE):
        return set()
    with open(PROCESSED_FILE, "r") as f:
        return set(json.load(f))

def save_processed_ids(processed_ids):
    with open(PROCESSED_FILE, "w") as f:
        json.dump(list(processed_ids), f)

# Artikel aus arXiv API laden
def fetch_arxiv_articles():
    import feedparser
    base_url = "http://export.arxiv.org/api/query?"
    search_query = "cat:" + " OR cat:".join(ARXIV_CATEGORIES)
    start_date = (datetime.utcnow() - timedelta(days=DAYS_BACK)).strftime("%Y%m%d%H%M%S")
    url = f"{base_url}search_query={search_query}&sortBy=submittedDate&sortOrder=descending&start=0&max_results=200"
    feed = feedparser.parse(url)
    articles = []
    for entry in feed.entries:
        published = datetime.strptime(entry.published, "%Y-%m-%dT%H:%M:%SZ")
        if published < datetime.utcnow() - timedelta(days=DAYS_BACK):
            continue
        article_id = entry.id.split("/")[-1]
        summary = entry.summary.replace("\n", " ").strip()
        articles.append({
            "id": article_id,
            "title": entry.title.strip(),
            "summary": summary,
            "link": entry.link,
            "published": published.strftime("%Y-%m-%d")
        })
    return articles

# GPT Analyse
def analyze_articles_with_gpt(batches):
    analyses = []
    debug_infos = []
    for i, batch in enumerate(batches):
        print(f"Analysiere Batch {i+1}/{len(batches)}")
        try:
            prompt = build_prompt(batch)
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "system", "content": prompt}],
                temperature=0.3
            )
            raw = response.choices[0].message.content.strip()
            try:
                result = json.loads(raw)
                if isinstance(result, list):
                    analyses.extend(result)
                    debug_infos.append(f"Batch {i+1}: OK ({len(batch)} Artikel)")
                else:
                    debug_infos.append(f"⚠️ Fehlerhafte Struktur in Batch {i+1}")
            except json.JSONDecodeError as e:
                debug_infos.append(f"❌ JSON-Fehler bei GPT-Antwort: {e}\nGPT-Rohantwort war:\n{raw}")
        except OpenAIError as e:
            debug_infos.append(f"❌ Fehler bei GPT-Analyse Batch {i+1}: {str(e)}")
    return analyses, debug_infos

def build_prompt(articles):
    joined = "\n\n".join(
        f"Titel: {a['title']}\nZusammenfassung: {a['summary']}" for a in articles
    )
    return (
        "Du bist ein Analyst für KI-Investments. Analysiere die folgenden arXiv-Paper aus den letzten Tagen "
        "und gib mir für jedes Paper ein JSON-Element mit folgendem Format zurück:\n\n"
        "[\n"
        "  {\n"
        '    "kurztitel": "Kurzer Titel",\n'
        '    "relevant": true/false,\n'
        '    "kurzfazit": "Ein kurzer, prägnanter Satz zur Relevanz bzw. warum nicht relevant."\n'
        "  },\n"
        "...]\n\n"
        "Hier sind die Paper:\n\n" + joined
    )

# Email versenden
def send_email(analyses, debug_infos):
    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_RECEIVER
    msg["Subject"] = "KI-Analyse Report"

    relevant = [a for a in analyses if a.get("relevant")]
    body = "Relevante Artikel:\n\n"
    for a in relevant:
        body += f"- {a['kurztitel']}: {a['kurzfazit']}\n"
    body += "\n\n--- DEBUG ---\n" + "\n".join(debug_infos)

    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        print(f"❌ Fehler beim Senden der E-Mail: {e}")

# Aufteilen in Batches
def chunk_articles(articles, size=5):
    return [articles[i:i + size] for i in range(0, len(articles), size)]

# Hauptlogik
if __name__ == "__main__":
    all_articles = fetch_arxiv_articles()
    processed_ids = load_processed_ids()
    new_articles = [a for a in all_articles if a["id"] not in processed_ids]

    if not new_articles:
        print("Keine neuen Artikel gefunden.")
        send_email([], ["Keine neuen Artikel in den letzten Tagen."])
    else:
        batches = chunk_articles(new_articles, size=5)
        gpt_analyses, debug_infos = analyze_articles_with_gpt(batches)
        processed_ids.update([a["id"] for a in new_articles])
        save_processed_ids(processed_ids)
        send_email(gpt_analyses, debug_infos)
