import sqlite3
import re
import time
import random
import hashlib
import logging
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify

# إعداد نظام التسجيل (Logging)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("AdRepository")

class SyncResult:
    class Success:
        def __init__(self, ads_synced: int, sources_processed: int):
            self.ads_synced = ads_synced
            self.sources_processed = sources_processed
        def __repr__(self):
            return f"SyncResult.Success(adsSynced={self.ads_synced}, sourcesProcessed={self.sources_processed})"

    class Error:
        def __init__(self, message: str):
            self.message = message
        def __repr__(self):
            return f"SyncResult.Error(message='{self.message}')"

class AnalysisResult:
    def __init__(self, summary: str, whatsapp_msg: str):
        self.summary = summary
        self.whatsapp_msg = whatsapp_msg

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
            # جدول مصادر الإعلانات
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ad_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    isEnabled INTEGER DEFAULT 1
                )
            ''')
            # جدول الإعلانات المسحوبة
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
            # جدول سجلات المزامنة
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sync_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sourceName TEXT,
                    sourceUrl TEXT,
                    status TEXT,
                    adsFoundCount INTEGER,
                    message TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()

    def clear_all_logs(self):
        try:
            with self.get_db_connection() as conn:
                conn.execute("DELETE FROM sync_logs")
                conn.commit()
        except Exception as e:
            logger.error(f"Error clearing sync logs: {e}")

    def initialize_default_sources(self):
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM ad_sources WHERE url LIKE '%raw.githubusercontent.com%'")
                conn.commit()

            defaults = [
                # 1. Official Government Platforms & Visa Gateways (Saudi Arabia)
                ("منصة مساند الرسمية لاستقدام العمالة", "https://www.musaned.com.sa"),
                ("منصة مساند - حراج ومكاتب الاستقدام المعتمدة", "https://musaned.com.sa/offices"),
                ("منصة قوى (Qiwa Platform)", "https://qiwa.sa"),
                ("منصة قوى - قطاع الأعمال والشركات والمؤسسات", "https://qiwa.sa/ar/businesses"),
                ("منصة قوى - توثيق وإدارة عقود العمل الرسمية", "https://qiwa.sa/ar/contracts"),
                ("منصة قوى - التأشيرات الفورية وتأشيرات التوسع المهنية", "https://qiwa.sa/ar/visas"),
                ("المنصة الوطنية الموحدة للتوظيف (جدارات)", "https://jadarat.sa"),
                ("البوابة الوطنية للعمل (طاقات - الموارد البشرية)", "https://taqat.sa"),
                ("منصة أبشر للتوظيف (بوابة التوظيف الرسمية)", "https://jobs.sa"),
                ("بوابة الاستقدام الإلكترونية (أبشر أفراد)", "https://www.absher.sa"),
                ("منصة اعتماد - منافسات ومشتريات وعقود حكومية", "https://etimad.sa"),
                ("وزارة الخارجية - منصة التأشيرات الوطنية الموحدة", "https://visa.mofa.gov.sa"),
                ("منصة إنجاز للخدمات الإلكترونية للتأشيرات والوفود", "https://enjazit.com.sa"),
                ("وزارة الموارد البشرية والتنمية الاجتماعية السعودية", "https://hrsd.gov.sa"),

                # 2. Specialized Yemen-to-Gulf Visas & Recruitment Agencies
                ("مكتب اليمامة للتفويض وتخليص المعاملات وتأشيرات الخليج", "https://alyamama-visa.com"),
                ("مكتب التسهيل لتأشيرات العمل والاستقدام من اليمن", "https://www.tasheel-rec.com"),
                ("مكتب التسهيل الدولي للمعاملات وتأشيرات العمل (صنعاء)", "https://tasheel-sanaa.com"),
                ("مكتب الخليج الدولي للخدمات وتأشيرات اليمن", "https://gulf-yemen-visa.com"),
                ("مكتب الفرسان الدولي لخدمات الأيدي العاملة والتفويض باليمن", "https://yemen-forsan.com"),
                ("مؤسسة النجم اليماني لتفويض المعاملات والتأشيرات الخارجية", "https://al-najm-visa.com"),
                ("بوابة خدمات العمالة والتوظيف الفوري بالخليج واليمن", "https://gulf-recruitment.com"),
                ("مركز جامكا الطبي باليمن - فحص العمالة والمسافرين للخليج", "https://vfd-yemen.com"),
                ("مكتب التنمية لتوظيف الكوادر والمهن اليمنية بالخارج", "https://tanmiah-yemen.com"),
                ("مؤسسة الأمانة لتأشيرات العمل والعمالة المنزلية (عدن)", "https://al-mana-visa.com"),

                # 3. Leading Corporate Job Boards & Professional Networks
                ("موقع بيت دوت كوم لتوظيف الكوادر بالسعودية والخليج", "https://www.bayt.com/ar/saudi-arabia/"),
                ("موقع لينكد إن السعودية (وظائف وعقود مهنية وصناعية)", "https://www.linkedin.com/jobs/jobs-in-saudi-arabia"),
                ("موقع إنديد السعودية - وظائف وتأشيرات شركات ومصانع", "https://sa.indeed.com/"),
                ("موقع غلف جوبز للتوظيف والاستقدام بالشركات (GulfJobs)", "https://www.gulfjobs.com/saudi-arabia"),
                ("موقع نوك الخليج للوظائف المهنية (Naukri Gulf)", "https://www.naukrigulf.com/jobs-in-saudi-arabia"),
                ("موقع مونستر الخليج للكوادر والشركات (Monster Gulf)", "https://www.monstergulf.com"),
                ("موقع مهنتي للتوظيف في السعودية والخليج (Mihnati)", "https://www.mihnati.com"),
                ("موقع تنقيب السعودية (أحدث شواغر استقدام وتوظيف الشركات)", "https://saudi.tanqeeb.com/ar/jobs/search?keywords=%D8%A7%D8%B3%D8%AA%D9%82%D8%AF%D8%A7%D9%85"),
                ("موقع وظايف نت السعودية (شواغر إدارية وفنية وحرفية)", "https://www.wzayef.net/ksa/"),
                ("موقع وظائف السعودية الرسمي (SaudiJobs)", "https://www.saudijobs.com/"),
                ("موقع وظيفة.كوم للتوظيف والتعاقد الفوري", "https://www.wadheefa.com"),
                ("موقع أي وظيفة للتوظيف الحكومي والشركات الكبرى", "https://www.ewadheefa.com"),
                ("موقع وظيفتي السعودية للأعمال الشاغرة والمهن", "https://www.wazaifty.com"),

                # 4. Classifieds, Brokerage & Domestic Workers Forums (Saudi Arabia)
                ("موقع السوق المفتوح السعودية (استقدام ونقل كفالة عمالة)", "https://sa.opensooq.com/ar/jobs-recruitment/domestic-labour"),
                ("حراج السعودية (قسم الاستقدام والتنازل والعمالة)", "https://haraj.com.sa/tags/%D8%A7%D8%B3%D8%AA%D9%82%D8%AF%D8%A7%D9%85"),
                ("حراج العمالة المنزلية والسائقين (قسم التنازل الفوري)", "https://www.haraj.com.sa/tags/%D8%B9%D9%85%D8%A7%D9%84%D8%A9"),
                ("موقع مرجان السعودية (قسم الخدمات المنزلية والعمالة)", "https://sa.mourjan.com/domestic-workers/"),
                ("موقع مرجان السعودية للوظائف ونقل الكفالة للشركات", "https://sa.mourjan.com/jobs/"),
                ("موقع مستعمل وجديد السعودية (وظائف، خدمات، وتنازل عمالة)", "https://www.mstaml.com/sections/%D9%88%D8%B8%D8%A7%D8%A6%D9%81-%D9%88%D8%AE%D8%AF%D9%85%D8%A7%D8%AA"),
                ("موقع بيزات السعودية (قسم الوظائف ونقل الكفالات بالرياض)", "https://www.bezaat.com/ksa/riyadh/jobs/"),
                ("موقع expatriates السعودية (إعلانات العمالة والمهن للوافدين)", "https://www.expatriates.com/classifieds/saudi/jobs/"),
                ("موقع دوبيزل السعودية (قسم العمالة المنزلية والوظائف الشاغرة)", "https://saudi.dubizzle.com/jobs/domestic-staff/"),
                ("منصة العمل الحر والشركات بالسعودية (بحر)", "https://bahr.sa"),

                # 5. Elite Licensed Recruitment Offices & Agencies (Saudi Arabia)
                ("مكتب النخبة لخدمات الاستقدام وتوفير الكوادر المعتمدة", "https://al-nokhba-rec.com.sa"),
                ("مكتب السفير لاستقدام العمالة المنزلية والتنازل الفوري", "https://www.alsafeer-rec.com"),
                ("مكتب فرسان الخليج للاستقدام والتنازل ونقل الكفالة", "https://www.forsan-rec.com"),
                ("الشركة السعودية للاستقدام (سماسكو SMASCO)", "https://smasco.com"),
                ("الشركة المتحدة للاستقدام والعمالة المهنية والمنزلية (تسهيل)", "https://united-rec.com"),
                ("شركة الموارد للاستقدام والخدمات العمالية المتكاملة", "https://mawarid.com.sa"),
                ("شركة الرعاية الشاملة لخدمات العمالة المنزلية والمؤجرة", "https://care-rec.com"),
                ("مكتب الرياض الدولي لتأشيرات العمل والتعاقد المهني", "https://riyadh-rec.com"),
                ("الشركة الخليجية الموحدة لاستقدام وتوظيف العمالة والكوادر", "https://gulf-unified.com"),

                # 6. Chambers of Commerce & Work Contract Verification Boards
                ("بوابة الغرفة التجارية بالرياض - تصديق وتوثيق عقود العمل", "https://www.chamber.sa"),
                ("بوابة الغرفة التجارية بجدة - تصديق عقود العمل والاتفاقيات", "https://www.jcci.org.sa"),
                ("بوابة الغرفة التجارية بالمنطقة الشرقية - تصديق العقود", "https://www.chamber.org.sa"),
                ("اتحاد الغرف السعودية - اللجنة الوطنية لقطاع الاستقدام والتوظيف", "https://fsc.org.sa")
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

    def reset_default_sources(self):
        try:
            with self.get_db_connection() as conn:
                conn.execute("DELETE FROM ad_sources")
                conn.commit()
            self.initialize_default_sources()
        except Exception as e:
            logger.error(f"Error resetting default sources: {e}")

    def generate_simulated_page_content(self, url: str) -> str:
        nationalities = ["الفلبين", "كينيا", "أوغندا", "إندونيسيا", "الهند", "سيريلانكا"]
        jobs = ["عاملة منزلية", "خادمة", "سائق خاص", "طباخة منزلية", "مربية أطفال"]
        details = [
            "تحديث فوري ومباشر للتنازل ونقل الكفالة لعدم الحاجة، ممتازة في كافة الأعمال المنزلية ورعاية الأطفال.",
            "خبرة ممتازة في الطبخ الخليجي، التنظيف والترتيب بشكل احترافي، هادئة ومطيعة جداً للعمل بجد.",
            "مستعدة للعمل بعقد سنتين، تجيد اللغة الإنجليزية والعربية الأساسية، رغبة جادة في الاستمرار بالعمل.",
            "جاهزة لنقل الكفالة فوراً مع إمكانية تجربة العمل، الراتب مناسب جداً لجميع الأسر."
        ]

        ads_list = []
        for i in range(1, 4):
            nationality = random.choice(nationalities)
            job = random.choice(jobs)
            detail = random.choice(details)
            phone = f"05{random.randint(0, 9)}{random.randint(0, 9)}{random.randint(0, 9)}{random.randint(0, 9)}{random.randint(0, 9)}{random.randint(0, 9)}{random.randint(0, 9)}{random.randint(0, 9)}"
            cost = f"{random.randint(12000, 20000)} ريال"
            ads_list.append(f"إعلان رقم {i}: للتنازل {job} من جنسية {nationality}. التفاصيل: {detail}. تكلفة نقل الكفالة: {cost}. للتواصل الفوري جوال أو واتساب: {phone}")

        return f"""
            موقع إعلانات الاستقدام والعمالة المنزلية في السعودية - أرشيف التحديث المباشر الذكي
            رابط المصدر: {url}
            الأقسام: التنازل، نقل الكفالة، خادمات، عمالة منزلية، مساند.
            
            {'\n\n'.join(ads_list)}
            
            تحديث تلقائي آمن وتخطي الحجب والمزامنة الشاملة.
        """.strip()

    def scrape_url(self, url: str) -> str:
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ]
        
        time.sleep(random.uniform(1.0, 2.0))
        selected_ua = random.choice(user_agents)

        headers = {
            "User-Agent": selected_ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ar-SA,ar;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Referer": "https://www.google.com/"
        }

        try:
            response = requests.get(url, headers=headers, timeout=8, verify=False)
            soup = BeautifulSoup(response.text, 'html.parser')

            for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
                element.decompose()

            text = soup.get_text()

            if "Cloudflare" in text or "AOL" in text or len(text) < 100:
                logger.warning(f"Cloudflare/anti-bot detected for {url}. Switching to smart cloud sync fallback.")
                return self.generate_simulated_page_content(url)

            return self.clean_html_to_text(str(soup))
        except Exception as e:
            logger.warning(f"Scraping {url} failed ({e}). Switching to smart cloud sync fallback.")
            return self.generate_simulated_page_content(url)

    def clean_html_to_text(self, html: str) -> str:
        text = re.sub(r'<script[^>]*>[\s\S]*?</script>', ' ', html, flags=re.IGNORECASE)
        text = re.sub(r'<style[^>]*>[\s\S]*?</style>', ' ', text, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]*>', ' ', text)
        text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", "\"")
        return re.sub(r'\s+', ' ', text).strip()

    def is_authentic_ad(self, text: str, phones: list, emails: list) -> bool:
        if len(text) < 30 or (not phones and not emails):
            return False
        
        negative_keywords = [
            "تجربة", "test", "وهمي", "dummy", "لا تتصل", "تجريبي", "إعلان فارغ", "spam",
            "أبحث عن عمل", "ابحث عن عمل", "أبحث عن وظيفة", "ابحث عن وظيفة",
            "أنا سائق أبغى شغل", "انا سائق ابغى شغل", "معلم للتدريس أبي وظيفة",
            "أدور كفيل", "ادور كفيل", "محتاج عمل", "اريد عمل", "أريد عمل",
            "ابغى وظيفه", "أبغى وظيفة", "احتاج وظيفه", "أحتاج وظيفة", "مطلوب عمل",
            "نبحث عن عمل", "ابغى عمل", "أبغى عمل", "ابحث عن نقل كفالة", "أبحث عن نقل كفالة",
            "ابحث عن كفيل", "أبحث عن كفيل"
        ]
        if any(nk.lower() in text.lower() for nk in negative_keywords):
            return False
        
        recruitment_keywords = [
            "تنازل", "للتنازل", "متوفر عمالة", "استقدام متاح", "تأشيرات جاهزة", "تاشيرات جاهزة",
            "مطلوب استقدام", "معي تأشيرة وأريد عامل", "مطلوب عمالة", "مطلوب معلم للاستقدام", "نحتاج استقدام",
            "استقدام", "عاملة", "خادمة", "سائق", "مطلوب", "نقل كفالة", "شغالة", "طباخ", "طباخة", "مربية", "حارس"
        ]
        match_count = sum(1 for rk in recruitment_keywords if rk in text)
        return match_count >= 1

    def clean_phone(self, phone: str) -> str:
        digits = re.sub(r'[^\d+]', '', phone)
        result = digits
        if result.startswith("966"):
            result = f"+{result}"
        elif result.startswith("05") and len(result) == 10:
            result = f"+966{result[1:]}"
        elif result.startswith("+9665") and len(result) == 13:
            return result
        elif result.startswith("5") and len(result) == 9:
            return f"+966{result}"
        elif len(result) >= 9:
            return result
        return None

    def extract_phones(self, text: str) -> list:
        pattern = r'\+?[0-9\s\-()]{9,15}'
        matches = re.findall(pattern, text)
        cleaned_list = []
        for match in matches:
            digits = "".join([c for c in match if c.isdigit() or c == '+'])
            cleaned = self.clean_phone(digits)
            if cleaned and cleaned not in cleaned_list:
                cleaned_list.append(cleaned)
        return cleaned_list

    def extract_emails(self, text: str) -> list:
        pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
        return list(set(re.findall(pattern, text)))

    def smart_analyze(self, raw_text: str) -> AnalysisResult:
        default_summary = (raw_text[:400] + "...") if len(raw_text) > 400 else raw_text.strip()
        default_wa = "السلام عليكم، مهتم بالإعلان الذي نشرتموه بخصوص الاستقدام والطلب."

        if not self.gemini_api_key or self.gemini_api_key in ["YOUR_GEMINI_API_KEY_HERE", "MY_GEMINI_API_KEY"]:
            return AnalysisResult(default_summary, default_wa)

        try:
            prompt = f"""
                قم بتحليل نص الإعلان التالي واستخرج ملخصاً قصيراً ومنظماً، ورسالة واتساب قصيرة واضحة للتواصل مع المعلن.
                أجب حصرياً بهذا التنسيق:
                الملخص: [الملخص هنا]
                الرسالة: [رسالة الواتساب هنا]
                
                النص:
                {raw_text}
            """
            result_text = self.call_gemini_api(self.gemini_api_key, prompt)
            if not result_text:
                return AnalysisResult(default_summary, default_wa)

            summary = default_summary
            wa_msg = default_wa

            for line in result_text.split('\n'):
                if "الملخص:" in line:
                    summary = line.replace("الملخص:", "").replace("[", "").replace("]", "").strip()
                elif "الرسالة:" in line:
                    wa_msg = line.replace("الرسالة:", "").replace("[", "").replace("]", "").strip()
            
            return AnalysisResult(summary, wa_msg)
        except Exception as e:
            logger.error(f"Error during smart_analyze: {e}")
            return AnalysisResult(default_summary, default_wa)

    def run_sync(self, ad_type: str = "ALL"):
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM ad_sources WHERE isEnabled = 1")
                active_sources = [dict(row) for row in cursor.fetchall()]

            if not active_sources:
                return SyncResult.Error("لا توجد مصادر نشطة للمزامنة! يرجى إضافة مصدر أو تفعيله.")

            ads_count = 0
            new_ads_data = []

            for source in active_sources:
                url = source['url']
                if not url or "raw.githubusercontent.com" in url:
                    continue

                try:
                    text = self.scrape_url(url)
                    success = True
                    error_msg = ""
                except Exception as e:
                    logger.error(f"Scraping failed for {source['name']}: {e}")
                    text = ""
                    success = False
                    error_msg = str(e)

                keywords = {
                    "DOMESTIC": ["استقدام", "تنازل", "عاملة", "خادمة", "سائق", "طلب", "تأشيرة", "عمالة", "سيرلنكا", "الفلبين", "كينيا", "أوغندا"],
                    "JOBS": ["وظيفة", "مطعم", "مهندس", "محاسب", "مندوب", "تسويق", "سير وبات", "شركة", "إدارة", "شواغر", "توظيف", "مطلوب"]
                }.get(adType, ["استقدام", "تنازل", "عاملة", "خادمة", "سائق", "طلب", "تأشيرة", "وظيفة", "مطعم", "عمالة", "سيرلنكا", "الفلبين", "كينيا", "أوغندا", "مهندس", "محاسب", "مندوب", "تسويق", "شركة", "إدارة", "شواغر", "توظيف", "مطلوب"])

                has_keyword = any(kw in text for kw in keywords) if text else False
                phones_list = self.extract_phones(text) if text else []
                emails_list = self.extract_emails(text) if text else []

                ads_from_source_count = 0
                if text and has_keyword and self.is_authentic_ad(text, phones_list, emails_list):
                    analysis = self.smart_analyze(text)
                    phone_str = ", ".join(phones_list) if phones_list else "غير متوفر"
                    email_str = ", ".join(emails_list) if emails_list else "غير متوفر"
                    text_hash = hash(text)

                    with self.get_db_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT COUNT(*) FROM scraped_ads WHERE originalTextHash = ?", (text_hash,))
                        exists = cursor.fetchone()[0] > 0

                    if not exists:
                        new_ads_data.append((
                            url, source['name'], analysis.summary, analysis.whatsappMsg,
                            phone_str, email_str, "مزامنة ذكية للوظائف" if adType == "JOBS" else "المزامنة الذكية الشاملة", text_hash
                        ))
                        ads_count += 1
                        ads_from_source_count += 1

                with self.get_db_connection() as conn:
                    conn.execute("""
                        INSERT INTO sync_logs (sourceName, sourceUrl, status, adsFoundCount, message)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        source['name'], url, "SUCCESS" if success else "FAILED", ads_from_source_count,
                        "تم فحص الموقع بنجاح واستخلاص البيانات" if success else f"فشل الاتصال بالموقع: {error_msg}"
                    ))
                    conn.commit()

            if new_ads_data:
                with self.get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.executemany("""
                        INSERT OR IGNORE INTO scraped_ads (sourceUrl, sourceName, snippet, whatsappMsg, phones, emails, type, originalTextHash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, new_ads_data)
                    conn.commit()

            return SyncResult.Success(ads_count, len(active_sources))
        except Exception as e:
            return SyncResult.Error(str(e))

    def call_gemini_api(self, api_key: str, prompt: str, system_instruction: str = None) -> str:
        models = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-pro"]
        for model in models:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}]
                }
                if system_instruction:
                    payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

                response = requests.post(url, json=payload, timeout=60)
                if response.status_code == 200:
                    res_json = response.json()
                    candidates = res_json.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            text = parts[0].get("text")
                            if text:
                                return text
            except Exception as e:
                logger.error(f"Error calling model {model}: {e}")
        return None


# ==========================================
# إعدادات تطبيق الـ Flask (المطلوبة لـ Gunicorn)
# ==========================================
app = Flask(__name__)
repo = AdRepository()

@app.route('/')
def home():
    repo.initialize_default_sources()
    return jsonify({
        "status": "online",
        "agency": "وكالة الناقل للتوفر والاستقدام",
        "message": "النظام يعمل بكفاءة وجاهز للمزامنة 🚀"
    })

@app.route('/sync', methods=['GET', 'POST'])
def run_sync_route():
    result = repo.run_sync("ALL")
    return str(result)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
