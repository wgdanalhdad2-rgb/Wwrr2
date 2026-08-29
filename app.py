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
    normalized_text = normalize_arabic_numbers(text)
    clean_text = re.sub(r'[\s\-_\.\(\)]', '', normalized_text)
    
    patterns = [
        r'(?:\+?966|0)?5\d{8}',
        r'\b5\d{8}\b',
        r'(?:\+?966)?5\d{8}'
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.google.com/"
    }
    ads_found = []
    
    try:
        response = requests.get(source['url'], headers=headers, timeout=20)
        if response.status_code != 200:
            print(f"❌ Failed {source['name']}: Status {response.status_code}")
            return ads_found
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # محاولة selectors أكثر تحديدًا + fallback عام
        candidates = soup.select(
            'div.ad, div.listing, article, .job-card, .offer, .card, '
            'div[class*="ad"], div[class*="listing"], div[class*="job"], '
            'div[class*="offer"], .product, .item, li, tr, section'
        )
        
        if not candidates:
            candidates = soup.find_all(['div', 'article', 'section', 'li', 'tr', 'a'])
        
        keywords = [
            'استقدام', 'عاملة', 'سائق', 'مطلوب', 'تأشيرة', 'تأشيرات',
            'طباخ', 'نقل كفالة', 'تنازل', 'كفالة', 'خادمة', 'مربية',
            'عمالة منزلية', 'سائق خاص', 'عاملة منزلية', 'شغالة', 'خادمة منزلية'
        ]
        
        seen_contents = set()
        
        for elem in candidates:
            text = elem.get_text(separator=" ", strip=True)
            if len(text) < 40 or text in seen_contents:
                continue
            seen_contents.add(text)
            
            if not any(kw in text for kw in keywords):
                continue
            
            phone, wa_link = extract_phone_and_whatsapp(text)
            
            # محاولة استخراج واتساب من الروابط إذا لم نجد رقم
            if not phone:
                for a in elem.find_all('a', href=True):
                    href = a.get('href', '')
                    if 'wa.me' in href or 'whatsapp' in href.lower() or 'api.whatsapp' in href.lower():
                        match = re.search(r'(\d{9,15})', href)
                        if match:
                            raw = match.group(1)
                            if raw.startswith('966'):
                                phone = '0' + raw[3:]
                                wa_link = f"https://wa.me/{raw}"
                            elif len(raw) == 9 and raw.startswith('5'):
                                phone = '0' + raw
                                wa_link = f"https://wa.me/966{raw}"
                            break
            
            if not phone:
                continue
            
            # تصنيف تلقائي
            category = "استقدام وتأشيرات"
            text_lower = text.lower()
            if any(w in text for w in ['سائق', 'سائق خاص', 'سائق منزلي']):
                category = "سائقين"
            elif any(w in text for w in ['تنازل', 'نقل كفالة', 'نقل خدمات', 'كفالة']):
                category = "نقل كفالة / تنازل"
            elif any(w in text for w in ['عاملة', 'خادمة', 'مربية', 'طباخ', 'شغالة', 'عمالة منزلية']):
                category = "عمالة منزلية"
            
            title = (text[:70].replace("\n", " ").strip() + "...") if len(text) > 70 else text
            
            ads_found.append({
                "source_name": source['name'],
                "source_url": source['url'],
                "title": title,
                "content": text[:2500],
                "category": category,
                "phone": phone,
                "whatsapp_link": wa_link
            })
            
            if len(ads_found) >= 40:  # حد أقصى لكل مصدر
                break
                
        print(f"✅ {source['name']}: وجد {len(ads_found)} إعلان")
        
    except Exception as e:
        print(f"❌ Error scraping {source['name']}: {e}")
    
    # تأخير عشوائي بسيط لتقليل فرصة الحظر
    time.sleep(random.uniform(0.8, 2.0))
    return ads_found

def run_real_scraper():
    setup_database()
    
    # قائمة مصادر سعودية حقيقية متعلقة بالاستقدام والإعلانات
    target_sources = [
        {"name": "دوبيزل السعودية", "url": "https://saudi.dubizzle.com/"},
        {"name": "دوبيزل - وظائف", "url": "https://saudi.dubizzle.com/jobs/"},
        {"name": "موقع وظيفة.كوم", "url": "https://www.wadheefa.com/"},
        {"name": "الإسناد السريع للاستقدام", "url": "https://qsr.sa/"},
        {"name": "الدار السعودية للاستقدام", "url": "https://www.darsaudia.com/"},
        {"name": "ساعد للاستقدام", "url": "https://www.saaid.online/"},
        {"name": "جدوى للاستقدام", "url": "https://jadwa-ksa.com/"},
        {"name": "منصة أيادي", "url": "https://ayady.sa/"},
        {"name": "حراج", "url": "https://haraj.com.sa/"},
        # يمكنك إضافة المزيد من صفحات العروض أو البحث المحدد
    ]
    
    all_ads = []
    
    print("🚀 بدء عملية السحب من المصادر...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        results = executor.map(scrape_source, target_sources)
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
                ad['source_name'],
                ad['source_url'],
                ad['title'],
                ad['content'],
                ad['category'],
                ad['phone'],
                ad['whatsapp_link']
            ))
            if cursor.rowcount > 0:
                added_count += 1
        except Exception as e:
            print(f"DB Error: {e}")
    
    conn.commit()
    conn.close()
    
    print(f"✅ تم إضافة {added_count} إعلان جديد")
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
        query += " AND (content LIKE ? OR title LIKE ? OR phone LIKE ?)"
        params.extend([f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"])
    
    if category_filter:
        query += " AND category = ?"
        params.append(category_filter)
        
    query += " ORDER BY id DESC LIMIT 150"
    
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
            flash(f'🚀 تم مزامنة وسحب الإعلانات بنجاح! الإعلانات الجديدة المضافة: {count}', 'success')
        
        elif action == 'clear':
            conn = get_db_connection()
            conn.execute('DELETE FROM ads')
            conn.commit()
            conn.close()
            flash('🗑️ تم تفريغ قاعدة البيانات بالكامل.', 'warning')
        
        return redirect(url_for('admin'))
        
    conn = get_db_connection()
    ads = conn.execute("SELECT * FROM ads ORDER BY id DESC").fetchall()
    total = len(ads)
    conn.close()
    
    return render_template('admin.html', ads=ads, total=total)

if __name__ == '__main__':
    setup_database()
    port = int(os.environ.get("PORT", 5000))
    print(f"🌐 السيرفر يعمل على المنفذ: {port}")
    app.run(host='0.0.0.0', port=port, debug=True)
