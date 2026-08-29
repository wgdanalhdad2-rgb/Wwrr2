import requests
from bs4 import BeautifulSoup
import re
import sqlite3
from datetime import datetime

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

def extract_phone_and_whatsapp(text: str):
    if not text:
        return "", ""
    clean_text = re.sub(r'[\s\-_\.]', '', text)
    # تتبع الأرقام السعودية بدقة (+966 أو 05)
    patterns = [r'(?:\+?966|0)?5\d{8}', r'05\d{8}', r'\+9665\d{8}', r'9665\d{8}']
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
            else:
                clean = '966' + raw[-9:]
            display = '0' + clean[3:] if clean.startswith('966') else raw
            return display, f"https://wa.me/{clean}"
    return "", ""

def run_scraper():
    setup_database()
    
    # الروابط والمصادر المخصصة لإعلانات الاستقدام والتنازل في السعودية
    target_sources = [
        {
            "name": "منصات الإعلانات السعودية",
            "url": "https://example.com/saudi-recruitment" # استبدل برابط المصدر المستهدف
        }
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ar-SA,ar;q=0.9"
    }
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    for source in target_sources:
        try:
            print(f"🌐 جاري سحب الإعلانات من: {source['name']}")
            response = requests.get(source['url'], headers=headers, timeout=20)
            if response.status_code != 200:
                continue
                
            soup = BeautifulSoup(response.text, 'html.parser')
            posts = soup.find_all(['div', 'article', 'li'], class_=re.compile('ad|post|item|listing', re.I))
            
            if not posts:
                posts = soup.find_all(['p', 'div'])
                
            added = 0
            for post in posts:
                text = post.get_text(separator=" ").strip()
                if len(text) < 25:
                    continue
                
                # الكلمات المفتاحية الحصرية لسوق الاستقدام والتنازل السعودي
                saudi_keywords = ['تنازل', 'استقدام', 'نقل كفالة', 'تأشيرة', 'عاملة منزلية', 'خادمة', 'سائق خاص', 'مقيم', 'الكتاف', 'المملكة']
                if not any(kw in text for kw in saudi_keywords):
                    continue
                    
                phone, wa_link = extract_phone_and_whatsapp(text)
                if not phone:
                    continue
                    
                category = "تنازل ونقل كفالة" if "تنازل" in text or "نقل" in text else "استقدام وتأشيرات"
                title = text[:70].replace("\n", " ") + "..."
                
                try:
                    cursor.execute('''
                        INSERT OR IGNORE INTO ads (source_name, source_url, title, content, category, phone, whatsapp_link)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (source['name'], source['url'], title, text, category, phone, wa_link))
                    if cursor.rowcount > 0:
                        added += 1
                except Exception:
                    pass
                    
            conn.commit()
            print(f"✅ تمت إضافة {added} إعلان جديد بنجاح.")
        except Exception as e:
            print(f"❌ خطأ: {e}")
            
    conn.close()

if __name__ == "__main__":
    run_scraper()

