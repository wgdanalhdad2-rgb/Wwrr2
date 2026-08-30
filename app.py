import os
import re
import time
import hashlib
import sqlite3
import logging
import threading
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, redirect, url_for, flash
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DB_NAME = os.getenv("DB_NAME", "recruitment.db")
SECRET_KEY = os.getenv("SECRET_KEY", os.urandom(32).hex())
REQUEST_TIMEOUT = (8, 25)
MAX_ADS_PER_SOURCE = 80
MIN_SECONDS_BETWEEN_REQUESTS = 2.5

app = Flask(__name__)
app.secret_key = SECRET_KEY

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("recruitment")

scrape_lock = threading.Lock()
last_request_at = {}

# مصادر عامة - ركز على صفحات البحث المفتوحة
SOURCES = [
    # ========== حراج (الأهم للإعلانات الحقيقية) ==========
    {
        "id": "haraj_yemeni",
        "name": "حراج - يمني / يمنية",
        "type": "html",
        "enabled": True,
        "url": "https://haraj.com.sa/search/%D9%8A%D9%85%D9%86%D9%8A",
        "selectors": {
            "card": "div.post, div.ad, article, .card, li",
            "title": "h1, h2, h3, .title, a",
            "content": ".description, .content, p, div",
            "link": "a[href]"
        }
    },
    {
        "id": "haraj_yemeni_female",
        "name": "حراج - يمنية",
        "type": "html",
        "enabled": True,
        "url": "https://haraj.com.sa/search/%D9%8A%D9%85%D9%86%D9%8A%D8%A9",
        "selectors": {
            "card": "div.post, div.ad, article, .card, li",
            "title": "h1, h2, h3, .title, a",
            "content": ".description, .content, p, div",
            "link": "a[href]"
        }
    },
    {
        "id": "haraj_istiqdam",
        "name": "حراج - استقدام",
        "type": "html",
        "enabled": True,
        "url": "https://haraj.com.sa/search/%D8%A7%D8%B3%D8%AA%D9%82%D8%AF%D8%A7%D9%85",
        "selectors": {
            "card": "div.post, div.ad, article, .card, li",
            "title": "h1, h2, h3, .title, a",
            "content": ".description, .content, p, div",
            "link": "a[href]"
        }
    },
    {
        "id": "haraj_amila",
        "name": "حراج - عاملة منزلية",
        "type": "html",
        "enabled": True,
        "url": "https://haraj.com.sa/search/%D8%B9%D8%A7%D9%85%D9%84%D8%A9%20%D9%85%D9%86%D8%B2%D9%84%D9%8A%D8%A9",
        "selectors": {
            "card": "div.post, div.ad, article, .card, li",
            "title": "h1, h2, h3, .title, a",
            "content": ".description, .content, p, div",
            "link": "a[href]"
        }
    },
    {
        "id": "haraj_transfer",
        "name": "حراج - تنازل / نقل كفالة",
        "type": "html",
        "enabled": True,
        "url": "https://haraj.com.sa/search/%D8%AA%D9%86%D8%A7%D8%B2%D9%84",
        "selectors": {
            "card": "div.post, div.ad, article, .card, li",
            "title": "h1, h2, h3, .title, a",
            "content": ".description, .content, p, div",
            "link": "a[href]"
        }
    },
    {
        "id": "haraj_driver",
        "name": "حراج - سائق",
        "type": "html",
        "enabled": True,
        "url": "https://haraj.com.sa/search/%D8%B3%D8%A7%D8%A6%D9%82",
        "selectors": {
            "card": "div.post, div.ad, article, .card, li",
            "title": "h1, h2, h3, .title, a",
            "content": ".description, .content, p, div",
            "link": "a[href]"
        }
    },

    # مصادر إضافية عامة
    {
        "id": "dubizzle",
        "name": "دوبيزل السعودية",
        "type": "html",
        "enabled": True,
        "url": "https://saudi.dubizzle.com/",
        "selectors": {
            "card": "div.ad, article, .listing, .card, li",
            "title": "h2, h3, .title, a",
            "content": ".description, p, div",
            "link": "a[href]"
        }
    },
    {
        "id": "opensooq",
        "name": "السوق المفتوح",
        "type": "html",
        "enabled": True,
        "url": "https://sa.opensooq.com/",
        "selectors": {
            "card": "div.ad, article, .listing, .card, li",
            "title": "h2, h3, .title, a",
            "content": ".description, p, div",
            "link": "a[href]"
        }
    },
]


def setup_database():
    with sqlite3.connect(DB_NAME) as conn:
        conn.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_url TEXT NOT NULL,
            ad_url TEXT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            category TEXT NOT NULL,
            phone TEXT,
            whatsapp_link TEXT,
            fingerprint TEXT NOT NULL UNIQUE,
            published_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_ads_created_at ON ads(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_ads_category ON ads(category);
        CREATE INDEX IF NOT EXISTS idx_ads_source_id ON ads(source_id);

        CREATE TABLE IF NOT EXISTS source_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            source_name TEXT NOT NULL,
            status TEXT NOT NULL,
            found_count INTEGER NOT NULL DEFAULT 0,
            inserted_count INTEGER NOT NULL DEFAULT 0,
            message TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT
        );
        """)


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def make_session():
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False
    )
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.google.com/"
    })
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


def wait_for_rate_limit(url):
    domain = urlparse(url).netloc.lower()
    elapsed = time.monotonic() - last_request_at.get(domain, 0)
    if elapsed < MIN_SECONDS_BETWEEN_REQUESTS:
        time.sleep(MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
    last_request_at[domain] = time.monotonic()


def can_fetch(url, user_agent="RecruitmentAggregator"):
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True  # نسمح بالمحاولة إذا فشل قراءة robots


def normalize_arabic_numbers(text):
    return (text or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))


def extract_phone_and_whatsapp(text, links=None):
    text = normalize_arabic_numbers(text or "")
    compact = re.sub(r"[^\d+]", "", text)

    patterns = [
        r"(?:\+966|00966|966|0)?5\d{8}",
        r"\b5\d{8}\b"
    ]

    candidates = [compact]
    if links:
        candidates.extend(links)

    for value in candidates:
        value = normalize_arabic_numbers(str(value))
        match = None
        for pattern in patterns:
            match = re.search(pattern, value)
            if match:
                break
        if not match:
            continue

        raw = match.group(0).replace("+", "").replace(" ", "")
        if raw.startswith("00966"):
            raw = raw[2:]
        elif raw.startswith("0") and len(raw) == 10:
            raw = "966" + raw[1:]
        elif raw.startswith("5") and len(raw) == 9:
            raw = "966" + raw

        if raw.startswith("9665") and len(raw) == 12:
            return "0" + raw[3:], f"https://wa.me/{raw}"

    return "", ""


def detect_category(text):
    text = text or ""
    if any(x in text for x in ["يمني", "يمنية", "من اليمن", "يمنيين", "يمنيات"]):
        return "عمالة يمنية"
    if any(x in text for x in ["تنازل", "نقل كفالة", "نقل خدمات"]):
        return "تنازل / نقل كفالة"
    if any(x in text for x in ["سائق", "سواق"]):
        return "سائقين"
    if any(x in text for x in ["عاملة", "خادمة", "مربية", "شغالة", "عمالة منزلية"]):
        return "عمالة منزلية"
    return "استقدام عام"


def is_relevant(text):
    keywords = [
        "استقدام", "عاملة", "سائق", "مطلوب", "تأشيرة",
        "تنازل", "نقل كفالة", "خادمة", "مربية",
        "شغالة", "عمالة منزلية", "سائق خاص",
        "يمني", "يمنية", "من اليمن", "يمنيين"
    ]
    return any(word in (text or "") for word in keywords)


def fingerprint(ad):
    raw = "|".join([
        ad["source_id"],
        re.sub(r"\s+", " ", ad["title"]).strip().lower(),
        re.sub(r"\s+", " ", ad["content"]).strip().lower()[:1200],
        ad.get("phone", "")
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def clean_ad(source, title, content, ad_url="", phone="", published_at=""):
    title = re.sub(r"\s+", " ", title or "").strip()[:250]
    content = re.sub(r"\s+", " ", content or "").strip()[:5000]

    if len(content) < 35 or not is_relevant(f"{title} {content}"):
        return None

    found_phone, whatsapp = extract_phone_and_whatsapp(f"{title} {content} {phone}")
    if phone and not found_phone:
        found_phone, whatsapp = extract_phone_and_whatsapp(phone)

    ad = {
        "source_id": source["id"],
        "source_name": source["name"],
        "source_url": source["url"],
        "ad_url": ad_url or source["url"],
        "title": title or content[:100],
        "content": content,
        "category": detect_category(f"{title} {content}"),
        "phone": found_phone,
        "whatsapp_link": whatsapp,
        "published_at": published_at or ""
    }
    ad["fingerprint"] = fingerprint(ad)
    return ad


def scrape_html(source, session):
    if not can_fetch(source["url"]):
        raise PermissionError("robots.txt لا يسمح بجمع هذه الصفحة")

    wait_for_rate_limit(source["url"])
    response = session.get(source["url"], timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    selectors = source.get("selectors", {})
    cards = soup.select(selectors.get("card", "div, article, li, section"))
    ads = []
    seen = set()

    for card in cards[:MAX_ADS_PER_SOURCE]:
        title_el = card.select_one(selectors.get("title", "h1, h2, h3, a"))
        content_el = card.select_one(selectors.get("content", "p, div"))
        link_el = card.select_one(selectors.get("link", "a[href]"))

        title = title_el.get_text(" ", strip=True) if title_el else ""
        content = content_el.get_text(" ", strip=True) if content_el else card.get_text(" ", strip=True)

        if content in seen or len(content) < 35:
            continue
        seen.add(content)

        href = source["url"]
        if link_el and link_el.get("href"):
            href = urljoin(source["url"], link_el["href"])

        links = [a.get("href", "") for a in card.select("a[href]")]
        phone, _ = extract_phone_and_whatsapp(content, links)

        ad = clean_ad(source, title, content, href, phone)
        if ad:
            ads.append(ad)

    return ads


def save_ads(ads):
    inserted = 0
    with get_db() as conn:
        for ad in ads:
            cursor = conn.execute("""
                INSERT OR IGNORE INTO ads (
                    source_id, source_name, source_url, ad_url, title,
                    content, category, phone, whatsapp_link, fingerprint, published_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ad["source_id"], ad["source_name"], ad["source_url"], ad["ad_url"],
                ad["title"], ad["content"], ad["category"], ad["phone"],
                ad["whatsapp_link"], ad["fingerprint"], ad["published_at"]
            ))
            inserted += cursor.rowcount
    return inserted


def record_run(source, status, found=0, inserted=0, message=""):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO source_runs (
                source_id, source_name, status, found_count,
                inserted_count, message, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            source["id"], source["name"], status, found, inserted,
            message[:1000], utc_now(), utc_now()
        ))


def scrape_one_source(source):
    session = make_session()
    try:
        if source["type"] == "html":
            ads = scrape_html(source, session)
        else:
            raise ValueError(f"نوع غير مدعوم حالياً: {source['type']}")

        inserted = save_ads(ads)
        record_run(source, "success", len(ads), inserted)
        logger.info("%s → found=%s inserted=%s", source["name"], len(ads), inserted)
        return inserted
    except Exception as exc:
        record_run(source, "failed", message=str(exc))
        logger.warning("%s failed: %s", source["name"], exc)
        return 0


def run_scraper():
    if not scrape_lock.acquire(blocking=False):
        logger.warning("Scraper already running")
        return

    try:
        total = 0
        for source in SOURCES:
            if source.get("enabled"):
                total += scrape_one_source(source)
        logger.info("Scraper finished → %s new ads", total)
    finally:
        scrape_lock.release()


@app.route("/")
def index():
    setup_database()
    q = request.args.get("q", "").strip()
    category = request.args.get("cat", "").strip()

    sql = "SELECT * FROM ads WHERE 1=1"
    params = []

    if q:
        sql += " AND (title LIKE ? OR content LIKE ? OR category LIKE ? OR phone LIKE ?)"
        params.extend([f"%{q}%"] * 4)
    if category:
        sql += " AND category = ?"
        params.append(category)

    sql += " ORDER BY id DESC LIMIT 250"

    with get_db() as conn:
        ads = conn.execute(sql, params).fetchall()

    return render_template("index.html", ads=ads, search=q, cat=category)


@app.route("/admin", methods=["GET", "POST"])
def admin():
    setup_database()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "scrape":
            if scrape_lock.locked():
                flash("السحب يعمل حالياً، انتظر حتى ينتهي.", "warning")
            else:
                threading.Thread(target=run_scraper, daemon=True).start()
                flash("بدأ السحب في الخلفية. حدّث الصفحة بعد قليل.", "success")

        elif action == "clear":
            with get_db() as conn:
                conn.execute("DELETE FROM ads")
            flash("تم تفريغ قاعدة البيانات.", "warning")

        return redirect(url_for("admin"))

    with get_db() as conn:
        ads = conn.execute("SELECT * FROM ads ORDER BY id DESC LIMIT 500").fetchall()
        runs = conn.execute("SELECT * FROM source_runs ORDER BY id DESC LIMIT 50").fetchall()
        total = conn.execute("SELECT COUNT(*) FROM ads").fetchone()[0]

    return render_template(
        "admin.html",
        ads=ads,
        runs=runs,
        total=total,
        is_running=scrape_lock.locked()
    )


if __name__ == "__main__":
    setup_database()
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
