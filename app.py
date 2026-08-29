from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
import os
import requests
from bs4 import BeautifulSoup
import re
import concurrent.futures
import time
import random

app = Flask(__name__)
app.secret_key = "alnaqil_secret_key_2026"
DB_NAME = "recruitment.db"

def setup_database():
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
    
    normalized = normalize_arabic_numbers(text)
    clean = re.sub(r'[\s\-_\.\(\)\/]', '', normalized)
    
    patterns = [
        r'(?:\+?966|0)?5\d{8}',
        r'\b05\d{8}\b',
        r'\b5\d{8}\b'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, clean)
        if match:
            raw = match.group(0)
            if raw.startswith('05'):
                clean_num = '966' + raw[1:]
            elif raw.startswith('+966'):
                clean_num = raw[1:]
            elif raw.startswith('966'):
                clean_num = raw
            elif raw.startswith('5') and len(raw) == 9:
                clean_num = '966' + raw
            else:
                continue
            
            display = '0' + clean_num[3:]
            wa = f"https://wa.me/{clean_num}"
            return display, wa
    return "", ""

def scrape_source(source):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.google.com/"
    }
    
    ads_found = []
    
    try:
        resp = requests.get(source['url'], headers=headers, timeout=25)
        if resp.status_code != 200:
            print(f"❌ {source['name']} → {resp.status_code}")
            return ads_found
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        candidates = soup.select(
            'div.post, div.ad, div.listing, article, .card, .item, '
            'div[class*="post"], div[class*="ad"], div[class*="listing"], '
            'li, tr, section'
        ) or soup.find_all(['div', 'article', 'section', 'li', 'tr'])
        
        # كلمات مفتاحية قوية + تركيز على اليمني
        keywords = [
            'استقدام', 'عاملة', 'سائق', 'مطلوب', 'تأشيرة', 'تنازل', 'نقل كفالة',
            'خادمة', 'مربية', 'شغالة', 'عمالة منزلية', 'سائق خاص',
            'يمني', 'يمنية', 'من اليمن', 'يمنيين', 'يمنيات',
            'عامل يمني', 'عاملة يمنية', 'سائق يمني'
        ]
        
        seen = set()
        
        for elem in candidates:
            text = elem.get_text(separator=" ", strip=True)
            if len(text) < 35 or text in seen:
                continue
            seen.add(text)
            
            if not any(kw in text for kw in keywords):
                continue
            
            phone, wa = extract_phone_and_whatsapp(text)
            
            if not phone:
                for a in elem.find_all('a', href=True):
                    href = a['href']
                    if 'wa.me' in href or 'whatsapp' in href.lower():
                        m = re.search(r'(\d{9,15})', href)
                        if m:
                            raw = m.group(1)
                            if raw.startswith('966'):
                                phone = '0' + raw[3:]
                                wa = f"https://wa.me/{raw}"
                            elif len(raw) == 9 and raw.startswith('5'):
                                phone = '0' + raw
                                wa = f"https://wa.me/966{raw}"
                            break
            
            if not phone:
                continue
            
            # تصنيف
            category = "استقدام عام"
            if any(w in text for w in ['يمني', 'يمنية', 'من اليمن', 'يمنيين']):
                category = "عمالة يمنية"
            elif any(w in text for w in ['تنازل', 'نقل كفالة', 'نقل خدمات']):
                category = "تنازل / نقل كفالة"
            elif any(w in text for w in ['سائق']):
                category = "سائقين"
            elif any(w in text for w in ['عاملة', 'خادمة', 'مربية', 'شغالة']):
                category = "عمالة منزلية"
            
            title = text[:85].replace("\n", " ").strip()
            if len(text) > 85:
                title += "..."
            
            ads_found.append({
                "source_name": source['name'],
                "source_url": source['url'],
                "title": title,
                "content": text[:3000],
                "category": category,
                "phone": phone,
                "whatsapp_link": wa
            })
            
            if len(ads_found) >= 60:
                break
        
        print(f"✅ {source['name']}: {len(ads_found)} إعلان")
        
    except Exception as e:
        print(f"❌ {source['name']}: {str(e)[:80]}")
    
    time.sleep(random.uniform(1.5, 3.0))
    return ads_found

def run_real_scraper():
    setup_database()
    
    target_sources = [
        # ===== حراج - تركيز على اليمني + الاستقدام =====
        {"name": "حراج - يمني", "url": "https://haraj.com.sa/search/%D9%8A%D9%85%D9%86%D9%8A"},
        {"name": "حراج - يمنية", "url": "https://haraj.com.sa/search/%D9%8A%D9%85%D9%86%D9%8A%D8%A9"},
        {"name": "حراج - من اليمن", "url": "https://haraj.com.sa/search/%D9%85%D9%86%20%D8%A7%D9%84%D9%8A%D9%85%D9%86"},
        {"name": "حراج - عاملة يمنية", "url": "https://haraj.com.sa/search/%D8%B9%D8%A7%D9%85%D9%84%D8%A9%20%D9%8A%D9%85%D9%86%D9%8A%D8%A9"},
        {"name": "حراج - استقدام يمني", "url": "https://haraj.com.sa/search/%D8%A7%D8%B3%D8%AA%D9%82%D8%AF%D8%A7%D9%85%20%D9%8A%D9%85%D9%86%D9%8A"},
        {"name": "حراج - استقدام", "url": "https://haraj.com.sa/search/%D8%A7%D8%B3%D8%AA%D9%82%D8%AF%D8%A7%D9%85"},
        {"name": "حراج - عاملة منزلية", "url": "https://haraj.com.sa/search/%D8%B9%D8%A7%D9%85%D9%84%D8%A9%20%D9%85%D9%86%D8%B2%D9%84%D9%8A%D8%A9"},
        {"name": "حراج - تنازل", "url": "https://haraj.com.sa/search/%D8%AA%D9%86%D8%A7%D8%B2%D9%84"},
        {"name": "حراج - نقل كفالة", "url": "https://haraj.com.sa/search/%D9%86%D9%82%D9%84%20%D9%83%D9%81%D8%A7%D9%84%D8%A9"},
        {"name": "حراج - سائق", "url": "https://haraj.com.sa/search/%D8%B3%D8%A7%D8%A6%D9%82"},
        
        # مصادر إضافية
        {"name": "دوبيزل السعودية", "url": "https://saudi.dubizzle.com/"},
        {"name": "السوق المفتوح", "url": "https://sa.opensooq.com/"},
        {"name": "الإسناد السريع", "url": "https://qsr.sa/"},
        {"name": "الدار السعودية", "url": "https://www.darsaudia.com/"},
    ]
    
    all_ads = []
    print("🚀 بدء سحب إعلانات استقدام العمالة اليمنية + العامة...\n")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(scrape_source, target_sources))
        for r in results:
            all_ads.extend(r)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    added = 0
    
    for ad in all_ads:
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO ads 
                (source_name, source_url, title, content, category, phone, whatsapp_link)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (ad['source_name'], ad['source_url'], ad['title'],
                  ad['content'], ad['category'], ad['phone'], ad['whatsapp_link']))
            if cursor.rowcount > 0:
                added += 1
        except:
            pass
    
    conn.commit()
    conn.close()
    
    print(f"\n✅ تم إضافة {added} إعلان جديد")
    return added

@app.route('/')
def index():
    setup_database()
    conn = get_db_connection()
    
    q = request.args.get('q', '').strip()
    cat = request.args.get('cat', '').strip()
    
    query = "SELECT * FROM ads WHERE 1=1"
    params = []
    
    if q:
        query += " AND (content LIKE ? OR title LIKE ? OR phone LIKE ? OR category LIKE ?)"
        params.extend([f"%{q}%"] * 4)
    if cat:
        query += " AND category = ?"
        params.append(cat)
    
    query += " ORDER BY id DESC LIMIT 250"
    ads = conn.execute(query, params).fetchall()
    conn.close()
    
    return render_template('index.html', ads=ads, search=q, cat=cat)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    setup_database()
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'scrape':
            count = run_real_scraper()
            flash(f'تم السحب بنجاح! الإعلانات الجديدة: {count}', 'success')
        elif action == 'clear':
            conn = get_db_connection()
            conn.execute('DELETE FROM ads')
            conn.commit()
            conn.close()
            flash('تم تفريغ قاعدة البيانات', 'warning')
        return redirect(url_for('admin'))
    
    conn = get_db_connection()
    ads = conn.execute("SELECT * FROM ads ORDER BY id DESC").fetchall()
    total = len(ads)
    conn.close()
    return render_template('admin.html', ads=ads, total=total)

if __name__ == '__main__':
    setup_database()
    port = int(os.environ.get("PORT", 5000))
    print(f"السيرفر شغال: http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)
