from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
import os

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
        if action == 'add':
            title = request.form.get('title')
            content = request.form.get('content')
            category = request.form.get('category')
            phone = request.form.get('phone')
            
            clean_phone = phone.strip().replace(' ', '').replace('+', '')
            if clean_phone.startswith('05'):
                wa_num = '966' + clean_phone[1:]
            elif clean_phone.startswith('966'):
                wa_num = clean_phone
            else:
                wa_num = '966' + clean_phone
                
            wa_link = f"https://wa.me/{wa_num}"
            
            conn = get_db_connection()
            try:
                conn.execute('''
                    INSERT INTO ads (source_name, title, content, category, phone, whatsapp_link)
                    VALUES ('إضافة يدوية', ?, ?, ?, ?, ?)
                ''', (title, content, category, phone, wa_link))
                conn.commit()
                flash('✅ تم إضافة الإعلان بنجاح!', 'success')
            except Exception as e:
                flash(f'❌ حدث خطأ (ربما الإعلان مكرر): {e}', 'error')
            conn.close()
        elif action == 'clear':
            conn = get_db_connection()
            conn.execute('DELETE FROM ads')
            conn.commit()
            conn.close()
            flash('🗑️ تم تفريغ قاعدة البيانات بالكامل.', 'warning')
            
        return redirect(url_for('admin'))
        
    conn = get_db_connection()
    ads = conn.execute("SELECT * FROM ads ORDER BY id DESC").fetchall()
    conn.close()
    return render_template('admin.html', ads=ads)

if __name__ == '__main__':
    setup_database()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

