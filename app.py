from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
import os
import requests
from bs4 import BeautifulSoup
import re
import concurrent.futures
import time
import random
from urllib.parse import quote

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
    
    normalized_text = normalize_arabic_numbers(text)
    clean_text = re.sub(r'[\s\-_\.\(\)\/]', '', normalized_text)
    
    patterns = [
        r'(?:\+?966|0)?5\d{8}',
        r'\b05\d{8}\b',
        r'\b5\d{8}\b',
        r'(?:\+966)?5\d{8}'
    ]
    
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive"
    }
    
    ads_found = []
    
    try:
        response = requests.get(source['url'], headers=headers, timeout=25)
        if response.status_code != 200:
            print(f"❌ {source['name']} → Status {response.status_code}")
            return ads_found
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # selectors محسنة لحراج + عامة
        candidates = soup.select(
            'div.post, div.ad, div.listing, article, .card, .item, '
            'div[class*="post"], div[class*="ad"], div[class*="listing"], '
            'div[class*="offer"], .product, li, tr, section, a[href*="haraj"]'
        )
        
        if len(candidates) < 5:
            candidates = soup.find_all(['div', 'article', 'section', 'li', 'tr'])
        
        # كلمات مفتاحية قوية جدًا
        keywords = [
            'استقدام', 'عاملة', 'سائق', 'مطلوب', 'تأشيرة', 'تأشيرات',
            'طباخ', 'نقل كفالة', 'تنازل', 'كفالة', 'خادمة', 'مربية',
            'عمالة منزلية', 'سائق خاص', 'شغالة', 'خادمة منزلية',
            'نقل خدمات', 'تنازل عن', 'ابغى استقدم', 'اريد استقدام',
            'عاملات', 'سائقين', 'مربية أطفال', 'طباخة'
        ]
        
        seen = set()
        
        for elem in candidates:
            text = elem.get_text(separator=" ", strip=True)
            
            if len(text) < 35 or text in seen:
                continue
            seen.add(text)
            
            if not any(kw in text for kw in keywords):
                continue
            
            phone, wa_link = extract_phone_and_whatsapp(text)
            
            # استخراج من الروابط إذا لم نجد رقم
            if not phone:
                for a in elem.find_all('a', href=True):
                    href = a.get('href', '')
                    if any(x in href.lower() for x in ['wa.me', 'whatsapp', 'api.whatsapp']):
                        match = re.search(r'(\d{9,15})', href)
                        if match:
                            raw = match.group(1)
                            if raw.startswith('966') and len(raw) >= 12:
                                phone = '0' + raw[3:]
                                wa_link = f"https://wa.me/{raw}"
                            elif len(raw) == 9 and raw.startswith('5'):
                                phone = '0' + raw
                                wa_link = f"https://wa.me/966{raw}"
                            break
            
            if not phone:
                continue
            
            # تصنيف دقيق
            category = "استقدام / مطلوب"
            if any(w in text for w in ['تنازل', 'نقل كفالة', 'نقل خدمات', 'للتنازل', 'كفالته']):
                category = "تنازل / نقل كفالة"
            elif any(w in text for w in ['سائق', 'سائق خاص', 'سائق منزلي']):
                category = "سائقين"
            elif any(w in text for w in ['عاملة', 'خادمة', 'مربية', 'طباخ', 'شغالة']):
                category = "عمالة منزلية"
            
            title = text[:80].replace("\n", " ").strip()
            if len(text) > 80:
                title += "..."
            
            ads_found.append({
                "source_name": source['name'],
                "source_url": source['url'],
                "title": title,
                "content": text[:3000],
                "category": category,
                "phone": phone,
                "whatsapp_link": wa_link
            })
            
            if len(ads_found) >= 50:
                break
        
        print(f"✅ {source['name']}: {len(ads_found)} إعلان")
        
    except Exception as e:
        print(f"❌ Error in {source['name']}: {str(e)[:100]}")
    
    time.sleep(random.uniform(1.2, 2.8))
    return ads_found

def run_real_scraper():
    setup_database()
    
    # أهم المصادر - روابط بحث مباشرة من حراج (الأقوى)
    target_sources = [
        # ========== حراج (الأهم) ==========
        {"name": "حراج - استقدام عمالة منزلية", "url": "https://haraj.com.sa/search/%D8%A7%D8%B3%D8%AA%D9%82%D8%AF%D8%A7%D9%85%20%D8%B9%D9%85%D8%A7%D9%84%D8%A9%20%D9%85%D9%86%D8%B2%D9%84%D9%8A%D8%A9"},
        {"name": "حراج - عاملة منزلية", "url": "https://haraj.com.sa/search/%D8%B9%D8%A7%D9%85%D9%84%D8%A9%20%D9%85%D9%86%D8%B2%D9%84%D9%8A%D8%A9"},
        {"name": "حراج - تنازل عاملة", "url": "https://haraj.com.sa/search/%D8%AA%D9%86%D8%A7%D8%B2%D9%84%20%D8%B9%D8%A7%D9%85%D9%84%D8%A9"},
        {"name": "حراج - نقل كفالة", "url": "https://haraj.com.sa/search/%D9%86%D9%82%D9%84%20%D9%83%D9%81%D8%A7%D9%84%D8%A9"},
        {"name": "حراج - سائق خاص", "url": "https://haraj.com.sa/search/%D8%B3%D8%A7%D8%A6%D9%82%20%D8%AE%D8%A7%D8%B5"},
        {"name": "حراج - مطلوب عاملة", "url": "https://haraj.com.sa/search/%D9%85%D8%B7%D9%84%D9%88%D8%A8%20%D8%B9%D8%A7%D9%85%D9%84%D8%A9"},
        {"name": "حراج - استقدام", "url": "https://haraj.com.sa/search/%D8%A7%D8%B3%D8%AA%D9%82%D8%AF%D8%A7%D9%85"},
        
        # ========== دوبيزل ==========
        {"name": "دوبيزل السعودية", "url": "https://saudi.dubizzle.com/"},
        {"name": "دوبيزل - خدمات", "url": "https://saudi.dubizzle.com/services/"},
        
        # ========== OpenSooq ==========
        {"name": "السوق المفتوح - السعودية", "url": "https://sa.opensooq.com/"},
        
        # ========== مكاتب (عروض + أرقام) ==========
        {"name": "الإسناد السريع", "url": "https://qsr.sa/"},
        {"name": "الدار السعودية", "url": "https://www.darsaudia.com/"},
        {"name": "ساعد للاستقدام", "url": "https://www.saaid.online/"},
        {"name": "أيادي", "url": "https://ayady.sa/"},
    ]
    
    all_ads = []
    print("🚀 بدء السحب من أهم المنصات السعودية...\n")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(scrape_source, target_sources))
        for result in results:
            all_ads.extend(result)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    added_count = 0
    
    for ad in all_ads:
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO ads 
                (source_name, source_url, title, content, category, phone, whatsapp_link)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                ad['source_name'], ad['source_url'], ad['title'],
                ad['content'], ad['category'], ad['phone'], ad['whatsapp_link']
            ))
            if cursor.rowcount > 0:
                added_count += 1
        except:
            pass
    
    conn.commit()
    conn.close()
    
    print(f"\n✅ تم إضافة {added_count} إعلان جديد من أصل {len(all_ads)} تم العثور عليها")
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
        query += " AND (content LIKE ? OR title LIKE ? OR phone LIKE ? OR category LIKE ?)"
        params.extend([f"%{search_query}%"] * 4)
    
    if category_filter:
        query += " AND category = ?"
        params.append(category_filter)
        
    query += " ORDER BY id DESC LIMIT 200"
    
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
            flash(f'🚀 تم السحب بنجاح! الإعلانات الجديدة: {count}', 'success')
        
        elif action == 'clear':
            conn = get_db_connection()
            conn.execute('DELETE FROM ads')
            conn.commit()
            conn.close()
            flash('🗑️ تم تفريغ قاعدة البيانات.', 'warning')
        
        return redirect(url_for('admin'))
        
    conn = get_db_connection()
    ads = conn.execute("SELECT * FROM ads ORDER BY id DESC").fetchall()
    total = len(ads)
    conn.close()
    
    return render_template('admin.html', ads=ads, total=total)

if __name__ == '__main__':
    setup_database()
    port = int(os.environ.get("PORT", 5000))
    print(f"🌐 السيرفر شغال على: http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)
