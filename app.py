import requests
from bs4 import BeautifulSoup
import re
import sqlite3
import time
import random
from flask import Flask, render_template_string

app = Flask(__name__)
DB = "real_ads.db"

def setup_db():
    conn = sqlite3.connect(DB)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            content TEXT,
            phone TEXT,
            source TEXT,
            url TEXT,
            UNIQUE(content)
        )
    ''')
    conn.commit()
    conn.close()

def extract_phone(text):
    text = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    clean = re.sub(r'[\s\-\.\(\)]', '', text)
    match = re.search(r'(?:\+?966|0)?5\d{8}', clean)
    if match:
        raw = match.group(0)
        if raw.startswith('05'):
            return '0' + raw[1:], f"https://wa.me/966{raw[1:]}"
        if raw.startswith('5') and len(raw) == 9:
            return '0' + raw, f"https://wa.me/966{raw}"
        if raw.startswith('966'):
            return '0' + raw[3:], f"https://wa.me/{raw}"
    return "", ""

def scrape_haraj():
    setup_db()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ar,en;q=0.9"
    }

    # روابط بحث حقيقية من حراج
    urls = [
        "https://haraj.com.sa/search/%D9%8A%D9%85%D9%86%D9%8A",
        "https://haraj.com.sa/search/%D9%8A%D9%85%D9%86%D9%8A%D8%A9",
        "https://haraj.com.sa/search/%D8%A7%D8%B3%D8%AA%D9%82%D8%AF%D8%A7%D9%85",
        "https://haraj.com.sa/search/%D8%B9%D8%A7%D9%85%D9%84%D8%A9%20%D9%85%D9%86%D8%B2%D9%84%D9%8A%D8%A9",
        "https://haraj.com.sa/search/%D8%AA%D9%86%D8%A7%D8%B2%D9%84",
        "https://haraj.com.sa/search/%D8%B3%D8%A7%D8%A6%D9%82%20%D9%8A%D9%85%D9%86%D9%8A",
    ]

    keywords = ["يمني", "يمنية", "استقدام", "عاملة", "سائق", "تنازل", "نقل كفالة", "خادمة", "مربية"]
    added = 0

    for url in urls:
        try:
            print(f"جاري السحب من: {url}")
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code != 200:
                print(f"  فشل: {r.status_code}")
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            # استخراج أوسع
            elements = soup.find_all(["div", "article", "li", "section", "a", "p"])

            seen = set()
            for el in elements:
                text = el.get_text(" ", strip=True)
                if len(text) < 40 or text in seen:
                    continue
                seen.add(text)

                if not any(k in text for k in keywords):
                    continue

                phone, wa = extract_phone(text)
                title = text[:80] + ("..." if len(text) > 80 else "")

                conn = sqlite3.connect(DB)
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO ads (title, content, phone, source, url) VALUES (?,?,?,?,?)",
                        (title, text[:2000], phone, "حراج", url)
                    )
                    if conn.total_changes > 0:
                        added += 1
                    conn.commit()
                except:
                    pass
                finally:
                    conn.close()

            time.sleep(random.uniform(2, 4))  # تأخير بسيط

        except Exception as e:
            print(f"  خطأ: {e}")

    return added

@app.route("/")
def home():
    setup_db()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    ads = conn.execute("SELECT * FROM ads ORDER BY id DESC LIMIT 100").fetchall()
    conn.close()

    html = """
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>إعلانات حقيقية - استقدام</title>
        <style>
            body { font-family: Tahoma; background: #f5f5f5; padding: 20px; }
            .ad { background: white; padding: 15px; margin-bottom: 12px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
            .btn { background: #0d6efd; color: white; padding: 12px 25px; border: none; border-radius: 6px; font-size: 16px; cursor: pointer; }
            .phone { color: green; font-weight: bold; }
        </style>
    </head>
    <body>
        <h1>إعلانات الاستقدام (حقيقية قدر الإمكان)</h1>
        <form action="/scrape" method="get">
            <button class="btn" type="submit">🚀 سحب إعلانات جديدة من حراج</button>
        </form>
        <br><br>
        {% if ads %}
            {% for ad in ads %}
            <div class="ad">
                <h3>{{ ad['title'] }}</h3>
                <p>{{ ad['content'][:400] }}...</p>
                {% if ad['phone'] %}
                    <p class="phone">الهاتف: {{ ad['phone'] }}</p>
                {% else %}
                    <p>لا يوجد رقم ظاهر في القائمة</p>
                {% endif %}
                <small>المصدر: {{ ad['source'] }}</small>
            </div>
            {% endfor %}
        {% else %}
            <p>لا توجد إعلانات بعد. اضغط زر السحب.</p>
        {% endif %}
    </body>
    </html>
    """
    return render_template_string(html, ads=ads)

@app.route("/scrape")
def do_scrape():
    count = scrape_haraj()
    return f"<h2>تم إضافة {count} إعلان جديد</h2><a href='/'>رجوع</a>"

if __name__ == "__main__":
    setup_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
