from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
import os
import requests
from bs4 import BeautifulSoup
import re
import concurrent.futures

app = Flask(__name__)
app.secret_key = "alnaqil_secret_key_2026"
DB_NAME = "recruitment.db"

def setup_database():
    """إنشاء قاعدة البيانات والجداول إذا لم تكن موجودة"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT,
            source_url TEXT,
            title TEXT,
            content TEXT,
            category TEXT,
            phone TEXT,
            whatsapp_link TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(content)
        )
    ''')
    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def normalize_arabic_numbers(text: str) -> str:
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    english_digits = "0123456789"
    return text.translate(str.maketrans(arabic_digits, english_digits))

def extract_phone_and_whatsapp(text: str):
    if not text:
        return "", ""
    normalized_text = normalize_arabic_numbers(text)
    clean_text = re.sub(r'[\s\-_\.\(\)]', '', normalized_text)
    patterns = [r'(?:\+?966|0)?5\d{8}', r'\b5\d{8}\b']
    for pattern in patterns:
        match = re.search(pattern, clean_text)
        if match:
            raw = match.group(0)
            if raw.startswith('05'):
                clean = '966' + raw[1:]
            elif raw.startswith('+966'):
                clean = raw[1:]
            elif raw.startswith('966'):
                clean = raw
            elif raw.startswith('5') and len(raw) == 9:
                clean = '966' + raw
            else:
                continue
            display = '0' + clean[3:]
            whatsapp_link = f"https://wa.me/{clean}"
            return display, whatsapp_link
    return "", ""

def scrape_source(source):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ar-SA,ar;q=0.9"
    }
    ads_found = []
    try:
        response = requests.get(source['url'], headers=headers, timeout=15)
        if response.status_code != 200:
            return ads_found
        soup = BeautifulSoup(response.text, 'html.parser')
        elements = soup.find_all(['div', 'article', 'section', 'li', 'tr'])
        for elem in elements:
            text = elem.get_text(separator=" ").strip()
            if len(text) < 30:
                continue
            keywords = ['تنازل', 'استقدام', 'نقل كفالة', 'عاملة', 'خادمة', 'سائق', 'طباخ', 'شغالة', 'كفيل']
            if not any(kw in text for kw in keywords):
                continue
            phone, wa_link = extract_phone_and_whatsapp(text)
            if not phone:
                continue
            category = "تنازل ونقل كفالة" if any(k in text for k in ['تنازل', 'نقل']) else "استقدام وتأشيرات"
            title = text[:60].replace("\n", " ").strip() + "..."
            ads_found.append({
                "source_name": source['name'],
                "source_url": source['url'],
                "title": title,
                "content": text,
                "category": category,
                "phone": phone,
                "whatsapp_link": wa_link
            })
    except Exception:
        pass
    return ads_found

def run_real_scraper():
    setup_database()
    # قائمة شاملة للمصادر والمواقع السعودية المتخصصة
    target_sources = [
        {"name": "حراج (استقدام)", "url": "https://haraj.com.sa/tags/%D8%A7%D8%B3%D8%AA%D9%82%D8%AF%D8%A7%D9%85"},
        {"name": "حراج (تنازل)", "url": "https://haraj.com.sa/tags/%D8%AA%D9%86%D8%A7%D8%B2%D9%84"},
        {"name": "حراج (سائق خاص)", "url": "https://haraj.com.sa/tags/%D8%B3%D8%A7%D8%A6%D9%82%20%D8%AE%D8%A7%D8%B5"},
        {"name": "السوق المفتوح (استقدام)", "url": "https://sa.opensooq.com/ar/%D8%AE%D8%AF%D9%85%D8%A7%D8%AA/%D8%AE%D8%AF%D9%85%D8%A7%D8%AA-%D8%A7%D8%B3%D8%AA%D9%82%D8%AF%D8%A7%D9%85"}
    ]
    
    all_ads = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = executor.map(scrape_source, target_sources)
        for result in results:
            all_ads.extend(result)
            
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    added_count = 0
    for ad in all_ads:
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO ads (source_name, source_url, title, content, category, phone, whatsapp_link)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (ad['source_name'], ad['source_url'], ad['title'], ad['content'], ad['category'], ad['phone'], ad['whatsapp_link']))
            if cursor.rowcount > 0:
                added_count += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return added_count

@app.route('/')
def index():
    setup_database()
    conn = get_db_connection()
    search_query = request.args.get('q', '').strip()
    category_filter = request.args.get('cat', '').strip()
    
    query = "SELECT * FROM ads WHERE 1=1"
    params = []
    if search_query:
        query += " AND (content LIKE ? OR title LIKE ?)"
        params.extend([f"%{search_query}%", f"%{search_query}%"])
    if category_filter:
        query += " AND category = ?"
        params.append(category_filter)
        
    query += " ORDER BY id DESC LIMIT 100"
    ads = conn.execute(query, params).fetchall()
    conn.close()
    return render_template('index.html', ads=ads, search=search_query, cat=category_filter)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    setup_database()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'scrape':
            count = run_real_scraper()
            flash(f'🚀 تم تشغيل السحب بنجاح! تم العثور على وإضافة {count} إعلان حقيقي جديد.', 'success')
        elif action == 'add':
            title = request.form.get('title')
            content = request.form.get('content')
            category = request.form.get('category')
            phone = request.form.get('phone')
            clean_phone = phone.strip().replace(' ', '').replace('+', '')
            wa_num = '966' + clean_phone[1:] if clean_phone.startswith('05') else clean_phone
            wa_link = f"https://wa.me/{wa_num}"
            
            conn = get_db_connection()
            try:
                conn.execute('INSERT INTO ads (source_name, title, content, category, phone, whatsapp_link) VALUES ("إضافة يدوية", ?, ?, ?, ?, ?)', 
                             (title, content, category, phone, wa_link))
                conn.commit()
                flash('✅ تم إضافة الإعلان يدوياً بنجاح!', 'success')
            except Exception as e:
                flash(f'❌ خطأ: {e}', 'error')
            conn.close()
        elif action == 'clear':
            conn = get_db_connection()
            conn.execute('DELETE FROM ads')
            conn.commit()
            conn.close()
            flash('🗑️ تم تفريغ قاعدة البيانات.', 'warning')
        return redirect(url_for('admin'))
        
    conn = get_db_connection()
    ads = conn.execute("SELECT * FROM ads ORDER BY id DESC").fetchall()
    conn.close()
    return render_template('admin.html', ads=ads)

if __name__ == '__main__':
    setup_database()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

