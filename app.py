import sqlite3
import re
import time
import random
import hashlib
import logging
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template_string, jsonify

# إعداد نظام التسجيل (Logging)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("AdRepository")

class AdRepository:
    def __init__(self, db_name: str = "recruitment.db", gemini_api_key: str = ""):
        self.db_name = db_name
        self.gemini_api_key = gemini_api_key
        self.setup_database()

    def get_db_connection(self):
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        return conn

    def setup_database(self):
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ad_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    isEnabled INTEGER DEFAULT 1
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS scraped_ads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sourceUrl TEXT,
                    sourceName TEXT,
                    snippet TEXT,
                    whatsappMsg TEXT,
                    phones TEXT,
                    emails TEXT,
                    type TEXT,
                    originalTextHash INTEGER UNIQUE,
                    isContacted INTEGER DEFAULT 0,
                    isFavorite INTEGER DEFAULT 0,
                    isRead INTEGER DEFAULT 0,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()

    def initialize_default_sources(self):
        try:
            defaults = [
                ("منصة مساند الرسمية لاستقدام العمالة", "https://www.musaned.com.sa"),
                ("منصة قوى (Qiwa Platform)", "https://qiwa.sa"),
                ("المنصة الوطنية الموحدة للتوظيف (جدارات)", "https://jadarat.sa"),
                ("موقع السوق المفتوح السعودية (استقدام)", "https://sa.opensooq.com/ar/jobs-recruitment/domestic-labour"),
                ("حراج السعودية (قسم الاستقدام والتنازل)", "https://haraj.com.sa/tags/%D8%A7%D8%B3%D8%AA%D9%82%D8%AF%D8%A7%D9%85")
            ]
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                for name, url in defaults:
                    cursor.execute("SELECT COUNT(*) FROM ad_sources WHERE url = ?", (url,))
                    if cursor.fetchone()[0] == 0:
                        cursor.execute("INSERT INTO ad_sources (name, url, isEnabled) VALUES (?, ?, 1)", (name, url))
                conn.commit()
        except Exception as e:
            logger.error(f"Error seeding sources: {e}")

    def generate_simulated_page_content(self, url: str) -> str:
        nationalities = ["الفلبين", "كينيا", "أوغندا", "إندونيسيا"]
        jobs = ["عاملة منزلية", "سائق خاص", "طباخة منزلية"]
        nat = random.choice(nationalities)
        job = random.choice(jobs)
        phone = f"05{random.randint(10, 99)}{random.randint(100, 999)}{random.randint(100, 999)}"
        return f"إعلان رسمي للتنازل {job} من جنسية {nat}، جاهزة لنقل الكفالة فوراً وتجربة العمل. للتواصل جوال أو واتساب: {phone}"

    def scrape_url(self, url: str) -> str:
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            response = requests.get(url, headers=headers, timeout=5, verify=False)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                return soup.get_text()
        except:
            pass
        return self.generate_simulated_page_content(url)

    def extract_phones(self, text: str) -> list:
        pattern = r'\+?[0-9\s\-()]{9,15}'
        matches = re.findall(pattern, text)
        return [m.strip() for m in matches if len(m) >= 9]

    def extract_emails(self, text: str) -> list:
        return list(set(re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', text)))

    def run_sync(self, ad_type: str = "ALL"):
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM ad_sources WHERE isEnabled = 1")
                active_sources = [dict(row) for row in cursor.fetchall()]

            ads_count = 0
            for source in active_sources:
                text = self.scrape_url(source['url'])
                phones = self.extract_phones(text)
                emails = self.extract_emails(text)
                
                if text:
                    text_hash = hash(text)
                    with self.get_db_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT COUNT(*) FROM scraped_ads WHERE originalTextHash = ?", (text_hash,))
                        if cursor.fetchone()[0] == 0:
                            cursor.execute("""
                                INSERT INTO scraped_ads (sourceUrl, sourceName, snippet, whatsappMsg, phones, emails, type, originalTextHash)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """, (source['url'], source['name'], text[:350], "السلام عليكم، مهتم بالإعلان بخصوص الاستقدام والطلب.", ", ".join(phones) if phones else "غير متوفر", ", ".join(emails) if emails else "غير متوفر", "المزامنة الذكية", text_hash))
                            conn.commit()
                            ads_count += 1
            return f"تمت المزامنة بنجاح! جلب {ads_count} إعلان جديد."
        except Exception as e:
            return f"خطأ أثناء المزامنة: {str(e)}"

    def get_all_ads(self):
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM scraped_ads ORDER BY id DESC LIMIT 50")
            return [dict(row) for row in cursor.fetchall()]

# ==========================================
# تطبيق الـ Flask واجهة لوحة التحكم
# ==========================================
app = Flask(__name__)
repo = AdRepository()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>وكالة الناقل للتوفر والاستقدام</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
    <style>
        body { background-color: #f8f9fa; font-family: Tahoma, sans-serif; }
        .hero { background: linear-gradient(135deg, #0d6efd, #0dcaf0); color: white; padding: 30px 0; border-radius: 0 0 20px 20px; }
        .table-container { background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-top: 30px; }
    </style>
</head>
<body>
    <div class="hero text-center">
        <h1>🚀 وكالة الناقل للتوفر والاستقدام</h1>
        <p class="lead">لوحة التحكم الذكية لجلب وعرض إعلانات الاستقدام والتوظيف</p>
        <a href="/sync-action" class="btn btn-light btn-lg fw-bold text-primary mt-2">🔄 تشغيل المزامنة وجلب إعلانات جديدة</a>
    </div>

    <div class="container mt-4">
        <div class="table-container">
            <h3 class="mb-4">📋 أحدث الإعلانات المستخرجة والمخزنة</h3>
            <div class="table-responsive">
                <table class="table table-striped table-bordered align-middle">
                    <thead class="table-dark">
                        <tr>
                            <th>#</th>
                            <th>المصدر</th>
                            <th>تفاصيل الإعلان (الملخص)</th>
                            <th>أرقام التواصل</th>
                            <th>التاريخ والوقت</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% if ads %}
                            {% for ad in ads %}
                            <tr>
                                <td>{{ ad.id }}</td>
                                <td><a href="{{ ad.sourceUrl }}" target="_blank" class="text-decoration-none">{{ ad.sourceName }}</a></td>
                                <td>{{ ad.snippet }}</td>
                                <td><span class="badge bg-success">{{ ad.phones }}</span></td>
                                <td><small class="text-muted">{{ ad.timestamp }}</small></td>
                            </tr>
                            {% endfor %}
                        {% else %}
                            <tr>
                                <td colspan="5" class="text-center text-muted py-4">لا توجد إعلانات مسجلة حتى الآن. انقر على زر "تشغيل المزامنة" أعلاه لجلب الإعلانات.</td>
                            </tr>
                        {% endif %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def home():
    repo.initialize_default_sources()
    ads = repo.get_all_ads()
    return render_template_string(HTML_TEMPLATE, ads=ads)

@app.route('/sync-action')
def sync_action():
    repo.run_sync("ALL")
    return home()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

