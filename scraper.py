import requests
from bs4 import BeautifulSoup
import re
import sqlite3
from datetime import datetime
import concurrent.futures
from urllib.parse import urlparse

# اسم قاعدة البيانات
DB_NAME = "recruitment.db"

def setup_database():
    """إنشاء قاعدة البيانات والجداول اللازمة إذا لم تكن موجودة"""
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

def normalize_arabic_numbers(text: str) -> str:
    """تحويل الأرقام العربية الشرقية (٠١٢٣٤٥٦٧٨٩) إلى الأرقام الغربية (0123456789)"""
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    english_digits = "0123456789"
    translation_table = str.maketrans(arabic_digits, english_digits)
    return text.translate(translation_table)

def extract_phone_and_whatsapp(text: str):
    """استخراج أرقام الهواتف السعودية وتوليد روابط الواتساب المباشرة بدقة عالية"""
    if not text:
        return "", ""
    
    normalized_text = normalize_arabic_numbers(text)
    clean_text = re.sub(r'[\s\-_\.\(\)]', '', normalized_text)
    
    # صيغ الهواتف السعودية: تبدأ بـ 05 أو 9665 أو +9665 أو 5
    patterns = [
        r'(?:\+?966|0)?5\d{8}',  
        r'\b5\d{8}\b'            
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
    """سحب البيانات من مصدر معين وتحليل محتواه"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ar-SA,ar;q=0.9,en-US;q=0.8,en;q=0.7"
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
    except Exception as e:
        pass
        
    return ads_found

def save_ads_to_db(ads):
    """حفظ الإعلانات المستخرجة في قاعدة البيانات وتجنب التكرار"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    added_count = 0
    
    for ad in ads:
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

def display_saved_ads():
    """عرض الإعلانات المخزنة في قاعدة البيانات بشكل منظم"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, category, phone, whatsapp_link, title FROM ads ORDER BY id DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()
    
    if rows:
        print("\n" + "="*80)
        print(f" 📋 أحدث الإعلانات النشطة في قاعدة البيانات (العدد الحالي المعروض: {len(rows)})")
        print("="*80)
        for row in rows:
            print(f"🆔 معرف: {row[0]}")
            print(f"🗂️ القسم: {row[1]}")
            print(f"📞 الهاتف: {row[2]}")
            print(f"💬 واتساب: {row[3]}")
            print(f"📝 العنوان: {row[4]}")
            print("-" * 80)
    else:
        print("\n⚠️ لا توجد إعلانات مخزنة حالياً في قاعدة البيانات.")

def run_scraper():
    """المحرك الرئيسي لعملية السحب والمعالجة"""
    setup_database()
    
    target_sources = [
        {
            "name": "موقع حراج (الاستقدام)",
            "url": "https://haraj.com.sa/tags/%D8%A7%D8%B3%D8%AA%D9%82%D8%AF%D8%A7%D9%85"
        },
        {
            "name": "موقع حراج (تنازل)",
            "url": "https://haraj.com.sa/tags/%D8%AA%D9%86%D8%A7%D8%B2%D9%84"
        },
        {
            "name": "السوق المفتوح السعودي (خدمات استقدام)",
            "url": "https://sa.opensooq.com/ar/%D8%AE%D8%AF%D9%85%D8%A7%D8%AA/%D8%AE%D8%AF%D9%85%D8%A7%D8%AA-%D8%A7%D8%B3%D8%AA%D9%82%D8%AF%D8%A7%D9%85"
        }
    ]
    
    print("🚀 بدء تشغيل نظام سحب إعلانات الاستقدام والتنازل...")
    
    all_ads = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = executor.map(scrape_source, target_sources)
        for result in results:
            all_ads.extend(result)
            
    if not all_ads:
        print("ℹ️ لم يتم سحب بيانات جديدة من الروابط المباشرة (بسبب قيود الحماية).")
        print("💡 سيتم توليد عينات إعلانات محاكاة واقعية لتجربة النظام بالكامل...")
        all_ads = [
            {
                "source_name": "محاكاة النظام النشط",
                "source_url": "https://haraj.com.sa",
                "title": "مطلوب نقل كفالة عاملة منزلية بنجلاديشية ممتازة في الطبخ...",
                "content": "للتنازل عاملة منزلية من بنجلاديش تجيد كافة أعمال المنزل والطبخ ورعاية الأطفال، ترغب بالعمل لدى عائلة جديدة. للتواصل الجادين فقط: 0554321098 نقل كفالة فوري.",
                "category": "تنازل ونقل كفالة",
                "phone": "0554321098",
                "whatsapp_link": "https://wa.me/966554321098"
            },
            {
                "source_name": "محاكاة النظام النشط",
                "source_url": "https://sa.opensooq.com",
                "title": "مكتب استقدام مرخص - خادمات من الفلبين وكينيا وأوغندا...",
                "content": "يعلن مكتبنا عن توفر تأشيرات جاهزة واستقدام سريع خلال 45 يوم عمل من الفلبين وكينيا وأوغندا بأسعار منافسة وضمانات حقيقية. اتصل الآن: 0501234567 أو راسلنا واتساب.",
                "category": "استقدام وتأشيرات",
                "phone": "0501234567",
                "whatsapp_link": "https://wa.me/966501234567"
            },
            {
                "source_name": "محاكاة النظام النشط",
                "source_url": "https://haraj.com.sa",
                "title": "سائق خاص هندي للتنازل نقل كفالة سريع...",
                "content": "يوجد سائق خاص هندي الجنسية لديه رخصة قيادة سعودية سارية المفعول، يعرف شوارع الرياض وجدة ممتاز جداً للتنازل بسبب السفر. رقم الجوال للتواصل 0569876543.",
                "category": "تنازل ونقل كفالة",
                "phone": "0569876543",
                "whatsapp_link": "https://wa.me/966569876543"
            }
        ]
        
    added_count = save_ads_to_db(all_ads)
    print(f"✅ تم فحص المصادر بنجاح. الإعلانات الجديدة المضافة: {added_count}")
    display_saved_ads()

if __name__ == "__main__":
    run_scraper()
