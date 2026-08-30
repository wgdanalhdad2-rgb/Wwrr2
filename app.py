import os
import time
import hashlib
import sqlite3
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template_string
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
DB_PATH = "ads.db"

SOURCES = [
    {
        "name": "Example Source 1",
        "url": "https://example.com/news",
        "item_selector": ".ad-item",
        "title_selector": ".ad-title",
        "link_selector": "a",
        "date_selector": ".ad-date",
    },
]

HTML = """
<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>متابعة الإعلانات</title>
  <style>
    body{font-family:Arial;background:#f7f8fa;margin:0;color:#111827}
    .wrap{max-width:1000px;margin:auto;padding:24px}
    .card{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:18px;margin-bottom:16px}
    h1,h2{margin-top:0}
    a{color:#0f766e;text-decoration:none}
    table{width:100%;border-collapse:collapse}
    th,td{border:1px solid #e5e7eb;padding:10px;text-align:right;vertical-align:top}
    th{background:#ecfeff}
    .badge{display:inline-block;background:#d1fae5;color:#065f46;padding:4px 10px;border-radius:999px;font-size:13px}
  </style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <span class="badge">Live Ads Tracker</span>
    <h1>الإعلانات الجديدة أولًا بأول</h1>
    <p>آخر تحديث: {{ last_run }}</p>
    <p><a href="/api/ads">API JSON</a></p>
  </div>

  <div class="card">
    <h2>آخر الإعلانات</h2>
    <table>
      <thead>
        <tr>
          <th>المصدر</th>
          <th>العنوان</th>
          <th>الرابط</th>
          <th>التاريخ</th>
          <th>وقت الإدخال</th>
        </tr>
      </thead>
      <tbody>
      {% for ad in ads %}
        <tr>
          <td>{{ ad['source'] }}</td>
          <td>{{ ad['title'] }}</td>
          <td><a href="{{ ad['link'] }}" target="_blank">فتح</a></td>
          <td>{{ ad['published_at'] }}</td>
          <td>{{ ad['created_at'] }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</div>
</body>
</html>
"""

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                link TEXT NOT NULL UNIQUE,
                published_at TEXT,
                created_at TEXT NOT NULL,
                content_hash TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                k TEXT PRIMARY KEY,
                v TEXT NOT NULL
            )
        """)
        conn.commit()

def get_meta(key, default=""):
    with db() as conn:
        row = conn.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
        return row["v"] if row else default

def set_meta(key, value):
    with db() as conn:
        conn.execute("INSERT INTO meta(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, value))
        conn.commit()

def make_hash(text):
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

def scrape_source(src):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AdsTracker/1.0; +contact@example.com)"
    }
    r = requests.get(src["url"], headers=headers, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    items = soup.select(src["item_selector"])
    results = []

    for item in items:
        title_el = item.select_one(src["title_selector"]) if src.get("title_selector") else item
        link_el = item.select_one(src["link_selector"]) if src.get("link_selector") else None
        date_el = item.select_one(src["date_selector"]) if src.get("date_selector") else None

        title = title_el.get_text(" ", strip=True) if title_el else item.get_text(" ", strip=True)
        link = link_el.get("href") if link_el and link_el.get("href") else src["url"]
        if link.startswith("/"):
            from urllib.parse import urljoin
            link = urljoin(src["url"], link)

        published_at = date_el.get_text(" ", strip=True) if date_el else ""
        content_hash = make_hash(title + "|" + link)

        results.append({
            "source": src["name"],
            "title": title,
            "link": link,
            "published_at": published_at,
            "content_hash": content_hash,
        })

    return results

def save_new_ads(items):
    inserted = 0
    with db() as conn:
        for ad in items:
            try:
                conn.execute("""
                    INSERT INTO ads(source, title, link, published_at, created_at, content_hash)
                    VALUES(?, ?, ?, ?, ?, ?)
                """, (
                    ad["source"],
                    ad["title"],
                    ad["link"],
                    ad["published_at"],
                    datetime.now(timezone.utc).isoformat(),
                    ad["content_hash"],
                ))
                inserted += 1
            except sqlite3.IntegrityError:
                pass
        conn.commit()
    return inserted

def update_feeds():
    total = 0
    for src in SOURCES:
        try:
            items = scrape_source(src)
            total += save_new_ads(items)
        except Exception as e:
            print(f"[{src['name']}] error:", e)
    set_meta("last_run", datetime.now(timezone.utc).isoformat())
    return total

@app.route("/")
def index():
    with db() as conn:
        ads = conn.execute("""
            SELECT source, title, link, published_at, created_at
            FROM ads
            ORDER BY id DESC
            LIMIT 200
        """).fetchall()
    return render_template_string(HTML, ads=ads, last_run=get_meta("last_run", "never"))

@app.route("/api/ads")
def api_ads():
    with db() as conn:
        ads = conn.execute("""
            SELECT source, title, link, published_at, created_at
            FROM ads
            ORDER BY id DESC
            LIMIT 200
        """).fetchall()
    return jsonify([dict(a) for a in ads])

@app.route("/api/update")
def api_update():
    count = update_feeds()
    return jsonify({"inserted": count, "last_run": get_meta("last_run", "")})

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    init_db()
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_feeds, "interval", minutes=5)
    scheduler.start()
    update_feeds()
    app.run(host="0.0.0.0", port=5000, debug=True)
