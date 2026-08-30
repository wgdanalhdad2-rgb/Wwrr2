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
            whatsapp TEXT,
            source TEXT,
            url TEXT,
            UNIQUE(content)
        )
    ''')
    conn.commit()
    conn.close()

def extract_phone(text):
    if not text:
        return "", ""
    text = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    clean = re.sub(r'[\s\-\.\(\)/]', '', text)
    
    match = re.search(r'(?:\+?966|0)?5\d{8}', clean)
    if match:
        raw = match.group(0)
        if raw.startswith('05'):
            num = '0' + raw[1:]
            wa = f"https://wa.me/966{raw[1:]}"
            return num, wa
        if raw.startswith('5') and len(raw) == 9:
            num = '0' + raw
            wa = f"https://wa.me/966{raw}"
            return num, wa
        if raw.startswith('966') and len(raw) >= 12:
            num = '0' + raw[3:]
            wa = f"https://wa.me/{raw}"
            return num, wa
    return "", ""

def scrape_sources():
    setup_db()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    # ========== كل المصادر ==========
    sources = [
        # حراج
        {"name": "حراج - يمني", "url": "https://haraj.com.sa/search/%D9%8A%D9%85%D9%86%D9%8A"},
        {"name": "حراج - يمنية", "url": "https://haraj.com.sa/search/%D9%8A%D9%85%D9%86%D9%8A%D8%A9"},
        {"name": "حراج - استقدام", "url": "https://haraj.com.sa/search/%D8%A7%D8%B3%D8%AA%D9%82%D8%AF%D8%A7%D9%85"},
        {"name": "حراج - عاملة منزلية", "url": "https://haraj.com.sa/search/%D8%B9%D8%A7%D9%85%D9%84%D8%A9%20%D9%85%D9%86%D8%B2%D9%84%D9%8A%D8%A9"},
        {"name": "حراج - تنازل", "url": "https://haraj.com.sa/search/%D8%AA%D9%86%D8%A7%D8%B2%D9%84"},
        {"name": "حراج - سائق يمني", "url": "https://haraj.com.sa/search/%D8%B3%D8%A7%D8%A6%D9%82%20%D9%8A%D9%85%D9%86%D9%8A"},
        {"name": "حراج - نقل كفالة", "url": "https://haraj.com.sa/search/%D9%86%D9%82%D9%84%20%D9%83%D9%81%D8%A7%D9%84%D8%A9"},
        
        # دوبيزل
        {"name": "دوبيزل السعودية", "url": "https://saudi.dubizzle.com/"},
        {"name": "دوبيزل - وظائف", "url": "https://saudi.dubizzle.com/jobs/"},
        
        # السوق المفتوح
        {"name": "السوق المفتوح", "url": "https://sa.opensooq.com/"},
        {"name": "السوق المفتوح - عمالة", "url": "https://sa.opensooq.com/ar/jobs-recruitment"},
        
        # مصادر أخرى عامة
        {"name": "وظيفة.كوم", "url": "https://www.wadheefa.com/"},
        {"name": "الإسناد السريع", "url": "https://qsr.sa/"},
        {"name": "الدار السعودية", "url": "https://www.darsaudia.com/"},
    ]

    keywords = [
        "يمني", "يمنية", "من اليمن", "استقدام", "عاملة", "سائق",
        "تنازل", "نقل كفالة", "خادمة", "مربية", "شغالة",
        "عمالة منزلية", "سائق خاص", "مطلوب", "تأشيرة"
    ]

    added = 0

    for src in sources:
        try:
            print(f"→ جاري السحب من: {src['name']}")
            r = requests.get(src['url'], headers=headers, timeout=18)
            
            if r.status_code != 200:
                print(f"  ✗ فشل ({r.status_code})")
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            elements = soup.find_all(["div", "article", "li", "section", "p", "a", "tr"])

            seen = set()
            count_this = 0

            for el in elements:
                text = el.get_text(" ", strip=True)
                
                if len(text) < 45:
                    continue
                    
                key = text[:120]
                if key in seen:
                    continue
                seen.add(key)

                if not any(k in text for k in keywords):
                    continue

                phone, wa = extract_phone(text)
                title = text[:85] + ("..." if len(text) > 85 else "")

                conn = sqlite3.connect(DB)
                try:
                    conn.execute('''
                        INSERT OR IGNORE INTO ads (title, content, phone, whatsapp, source, url)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (title, text[:2500], phone, wa, src['name'], src['url']))
                    
                    if conn.total_changes > 0:
                        added += 1
                        count_this += 1
                    conn.commit()
                except:
                    pass
                finally:
                    conn.close()

                if count_this >= 40:  # حد لكل مصدر
                    break

            print(f"  ✓ أضيف {count_this} إعلان")
            time.sleep(random.uniform(2.0, 4.0))

        except Exception as e:
            print(f"  ✗ خطأ: {str(e)[:80]}")

    print(f"\n✅ إجمالي الإعلانات الجديدة: {added}")
    return added


@app.route("/")
def home():
    setup_db()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    ads = conn.execute("SELECT * FROM ads ORDER BY id DESC LIMIT 150").fetchall()
    total = conn.execute("SELECT COUNT(*) FROM ads").fetchone()[0]
    conn.close()

    html = """
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>إعلانات الاستقدام الحقيقية</title>
        <style>
            * { box-sizing: border-box; }
            body { font-family: Tahoma, Arial; background: #f0f2f5; margin: 0; padding: 20px; }
            .header { background: linear-gradient(135deg, #0f766e, #0d9488); color: white; padding: 25px; border-radius: 12px; text-align: center; margin-bottom: 20px; }
            .btn { background: #fff; color: #0f766e; border: none; padding: 14px 30px; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer; }
            .btn:hover { background: #e0f2f1; }
            .stats { text-align: center; margin: 15px 0; color: #555; }
            .ad { background: white; padding: 18px; margin-bottom: 14px; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
            .ad h3 { margin: 0 0 10px 0; font-size: 1.1rem; color: #1e293b; }
            .ad p { color: #475569; line-height: 1.5; margin: 8px 0; }
            .phone { color: #059669; font-weight: bold; direction: ltr; display: inline-block; }
            .wa { background: #25d366; color: white; padding: 6px 14px; border-radius: 6px; text-decoration: none; font-size: 14px; margin-right: 8px; }
            .source { color: #64748b; font-size: 13px; }
            .empty { text-align: center; padding: 40px; color: #888; background: white; border-radius: 10px; }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>إعلانات الاستقدام الحقيقية</h1>
            <p>حراج + دوبيزل + السوق المفتوح + مصادر أخرى</p>
            <form action="/scrape" method="get" style="margin-top:15px">
                <button class="btn" type="submit">🚀 سحب إعلانات من جميع المواقع</button>
            </form>
        </div>

        <div class="stats">إجمالي الإعلانات المحفوظة: <strong>{{ total }}</strong></div>

        {% if ads %}
            {% for ad in ads %}
            <div class="ad">
                <h3>{{ ad['title'] }}</h3>
                <p>{{ ad['content'][:450] }}{% if ad['content']|length > 450 %}...{% endif %}</p>
                
                {% if ad['phone'] %}
                    <p>الهاتف: <span class="phone">{{ ad['phone'] }}</span></p>
                {% endif %}
                
                {% if ad['whatsapp'] %}
                    <a href="{{ ad['whatsapp'] }}" target="_blank" class="wa">واتساب</a>
                {% endif %}
                
                <div class="source">المصدر: {{ ad['source'] }}</div>
            </div>
            {% endfor %}
        {% else %}
            <div class="empty">
                <p>لا توجد إعلانات بعد.</p>
                <p>اضغط زر السحب أعلاه.</p>
            </div>
        {% endif %}
    </body>
    </html>
    """
    return render_template_string(html, ads=ads, total=total)


@app.route("/scrape")
def do_scrape():
    count = scrape_sources()
    return f"""
    <div style="font-family:Tahoma; text-align:center; padding:50px">
        <h2>تم الانتهاء</h2>
        <p>أُضيف <strong>{count}</strong> إعلان جديد</p>
        <br>
        <a href="/" style="background:#0f766e; color:white; padding:12px 25px; border-radius:8px; text-decoration:none">
            رجوع للصفحة الرئيسية
        </a>
    </div>
    """


if __name__ == "__main__":
    setup_db()
    print("السيرفر شغال على: http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
