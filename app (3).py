import os
import sqlite3
import datetime
import random
import shutil
import sys
import time
import atexit
from io import BytesIO

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from flask import Flask, request, redirect, url_for, session, render_template_string, send_from_directory, jsonify, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "imana_free_interest_microfinance_secret_key"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
BACKUP_FOLDER = os.path.join(BASE_DIR, 'backups')
DB_PATH = os.path.join(BASE_DIR, "web_banking.db")

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['BACKUP_FOLDER'] = BACKUP_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(BACKUP_FOLDER, exist_ok=True)

NOTIFICATIONS = []

def compress_and_save_image(file_storage, target_filename, max_size=(300, 300), quality=35):
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], target_filename)
    filename = file_storage.filename.lower()
    
    if filename.endswith('.pdf') or not HAS_PIL:
        file_storage.save(filepath)
        return target_filename

    try:
        image = Image.open(file_storage)
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")
        
        image.thumbnail(max_size, Image.Resampling.LANCZOS)
        image.save(filepath, "JPEG", optimize=True, quality=quality)
        return target_filename
    except Exception as e:
        print(f"Image compression error: {e}")
        file_storage.save(filepath)
        return target_filename

def get_db_connection(max_retries=10, delay=0.5):
    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=60)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA busy_timeout = 30000;")
            conn.execute("PRAGMA cache_size = -64000;")
            conn.execute("PRAGMA mmap_size = 268435456;")
            return conn
        except sqlite3.OperationalError as e:
            if attempt < max_retries - 1:
                time.sleep(delay)
            else:
                raise e

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_commission(amount):
    if 1000 <= amount < 3000:
        return 50.0
    elif 3000 <= amount < 5000:
        return 100.0
    elif 7000 <= amount < 10000:
        return 200.0
    elif 10000 <= amount <= 20000:
        return 400.0
    return 0.0

def send_sms_alert(phone_number, message):
    print(f"📱 [SMS SENT TO {phone_number}]: {message}")

def add_notification(message):
    now = datetime.datetime.now().strftime("%H:%M:%S")
    NOTIFICATIONS.insert(0, f"[{now}] {message}")
    if len(NOTIFICATIONS) > 20:
        NOTIFICATIONS.pop()

def perform_auto_backup():
    try:
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file_path = os.path.join(BACKUP_FOLDER, f"auto_backup_{now_str}.db")
        latest_path = os.path.join(BACKUP_FOLDER, "latest_auto_backup.db")
        
        if os.path.exists(DB_PATH):
            with sqlite3.connect(DB_PATH) as src_conn:
                with sqlite3.connect(backup_file_path) as dst_conn:
                    src_conn.backup(dst_conn)
                with sqlite3.connect(latest_path) as dst_conn2:
                    src_conn.backup(dst_conn2)
            print("💾 Auto Backup completed.")
    except Exception as e:
        print(f"❌ Auto Backup failed: {e}")

def perform_auto_restore():
    latest_path = os.path.join(BACKUP_FOLDER, "latest_auto_backup.db")
    if not os.path.exists(DB_PATH) and os.path.exists(latest_path):
        try:
            shutil.copyfile(latest_path, DB_PATH)
            print("🔄 Persistent Auto Restore completed.")
        except Exception as e:
            print(f"❌ Auto Restore failed: {e}")

perform_auto_restore()
atexit.register(perform_auto_backup)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT DEFAULT 'ACTIVE'
        )
    """)

    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        default_users = [
            ('ceo', 'ceo999', 'CEO', 'ACTIVE'),
            ('manager1', 'manager123', 'MANAGER', 'ACTIVE'),
            ('maker1', 'maker123', 'MAKER', 'ACTIVE'),
            ('auditor1', 'auditor123', 'AUDITOR', 'ACTIVE'),
            ('officer1', 'officer123', 'LOAN_OFFICER', 'ACTIVE')
        ]
        cursor.executemany("INSERT INTO users VALUES (?, ?, ?, ?)", default_users)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id TEXT PRIMARY KEY,
            full_name TEXT,
            phone TEXT,
            gender TEXT DEFAULT 'Dhiira',
            account_type TEXT DEFAULT 'WADIA',
            photo_path TEXT,
            signature_path TEXT,
            national_id_path TEXT DEFAULT '',
            balance REAL DEFAULT 0.0,
            status TEXT DEFAULT 'PENDING_APPROVAL',
            freeze_status TEXT DEFAULT 'UNFROZEN',
            freeze_reason TEXT DEFAULT '',
            created_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            txn_id TEXT PRIMARY KEY,
            txn_type TEXT,
            customer_id TEXT,
            customer_name TEXT,
            target_account TEXT,
            amount REAL,
            commission REAL DEFAULT 0.0,
            bank_name TEXT,
            ft_reference TEXT,
            status TEXT DEFAULT 'PENDING_MANAGER',
            created_by TEXT,
            timestamp TEXT,
            audited_status TEXT DEFAULT 'OPEN'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reversals (
            reversal_id TEXT PRIMARY KEY,
            txn_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            manager_approved INTEGER DEFAULT 0,
            ceo_approved INTEGER DEFAULT 0,
            status TEXT DEFAULT 'PENDING_APPROVAL',
            timestamp TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS islamic_financing (
            loan_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            customer_name TEXT,
            financing_type TEXT NOT NULL,
            principal_amount REAL NOT NULL,
            profit_margin REAL DEFAULT 0.0,
            total_repayment REAL NOT NULL,
            tenure_months INTEGER,
            monthly_installment REAL,
            status TEXT DEFAULT 'PENDING_MANAGER',
            manager_approved INTEGER DEFAULT 0,
            ceo_approved INTEGER DEFAULT 0,
            agent_notes TEXT,
            created_by TEXT,
            timestamp TEXT
        )
    """)

    conn.commit()
    conn.close()

init_db()

def get_bank_capital():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE status='APPROVED' AND txn_type='DEPOSIT'")
    total_deposit = cursor.fetchone()[0] or 0.0
    
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE status='APPROVED' AND txn_type IN ('WITHDRAWAL', 'T24_TRANSFER')")
    total_withdraw = cursor.fetchone()[0] or 0.0
    
    cursor.execute("SELECT SUM(balance) FROM customers WHERE status='ACTIVE'")
    total_cust_balance = cursor.fetchone()[0] or 0.0

    cursor.execute("SELECT SUM(commission) FROM transactions WHERE status='APPROVED'")
    total_commission = cursor.fetchone()[0] or 0.0

    cursor.execute("SELECT SUM(balance) FROM customers WHERE status='ACTIVE' AND account_type='MUDARABA'")
    total_mudaraba_deposits = cursor.fetchone()[0] or 0.0

    mudaraba_gross_profit = total_mudaraba_deposits * 0.10
    mudaraba_ceo_share = mudaraba_gross_profit * 0.50
    mudaraba_customer_share = mudaraba_gross_profit * 0.50
    
    net_capital = total_deposit - total_withdraw + total_commission
    conn.close()
    return max(0.0, net_capital), total_deposit, total_withdraw, total_cust_balance, total_commission, total_mudaraba_deposits, mudaraba_gross_profit, mudaraba_ceo_share, mudaraba_customer_share

HTML_LAYOUT = """
<!DOCTYPE html>
<html lang="om">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Imana Free Interest Microfinance</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background-color: #f8fafc; padding-bottom: 75px; color: #0f172a; }
        nav { background: linear-gradient(135deg, #065f46, #047857); color: white; padding: 12px 16px; position: sticky; top: 0; z-index: 50; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
        .logo-container { display: flex; align-items: center; gap: 10px; }
        .logo-svg { width: 32px; height: 32px; fill: #fbbf24; }
        nav h1 { font-size: 15px; font-weight: 800; letter-spacing: 0.3px; color: #ffffff; }
        .role-badge { background: #0284c7; padding: 3px 8px; border-radius: 4px; font-weight: 600; font-size: 11px; }
        .container { max-width: 600px; margin: 0 auto; padding: 16px; }
        .notification-bar { background: #fef3c7; color: #92400e; padding: 8px 12px; border-radius: 8px; font-size: 11px; margin-bottom: 12px; font-weight: bold; border: 1px solid #fde68a; }
        .card-net { background: linear-gradient(135deg, #064e3b, #047857); color: white; border-radius: 16px; padding: 20px; box-shadow: 0 10px 15px -3px rgba(6,78,59,0.3); margin-bottom: 20px; }
        .card-ceo-profit { background: linear-gradient(135deg, #4c1d95, #6b21a8); color: white; border-radius: 16px; padding: 20px; box-shadow: 0 10px 15px -3px rgba(76,29,149,0.3); margin-bottom: 20px; }
        .net-title { font-size: 12px; opacity: 0.9; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
        .net-amount { font-size: 32px; font-weight: 800; color: #fbbf24; }
        .net-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 16px; pt: 12px; border-top: 1px solid rgba(255,255,255,0.2); font-size: 12px; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
        .btn-card { background: white; padding: 16px; border-radius: 12px; border: 1px solid #e2e8f0; display: flex; flex-direction: column; align-items: center; text-decoration: none; color: #334155; font-weight: bold; font-size: 13px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05); transition: 0.2s; }
        .btn-card:active { transform: scale(0.98); }
        .btn-card span.icon { font-size: 24px; margin-bottom: 8px; }
        .btn-card-ceo { background: #faf5ff; border-color: #e9d5ff; color: #581c87; }
        .btn-card-auditor { background: #fff7ed; border-color: #ffedd5; color: #c2410c; }
        .btn-card-loan { background: #f0fdf4; border-color: #bbf7d0; color: #15803d; }
        .bottom-nav { position: fixed; bottom: 0; left: 0; right: 0; background: white; border-top: 1px solid #e2e8f0; display: flex; justify-content: space-around; padding: 10px 0; z-index: 50; }
        .bottom-nav a { text-align: center; color: #64748b; text-decoration: none; font-size: 11px; flex: 1; font-weight: 500; }
        .bottom-nav a span.icon { display: block; font-size: 18px; margin-bottom: 2px; }
        .box { background: white; padding: 20px; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 16px; }
        .form-group { margin-bottom: 12px; position: relative; }
        .form-group label { display: block; font-size: 12px; font-weight: bold; color: #475569; margin-bottom: 4px; }
        .input-field { width: 100%; padding: 10px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 14px; outline: none; }
        .btn-submit { width: 100%; background: #047857; color: white; border: none; padding: 12px; border-radius: 8px; font-weight: bold; font-size: 14px; cursor: pointer; }
        .badge { padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: bold; display: inline-block; }
        .badge-pending { background: #fef3c7; color: #92400e; }
        .badge-active { background: #dcfce7; color: #166534; }
        .badge-danger { background: #fee2e2; color: #991b1b; }
        .badge-frozen { background: #dbeafe; color: #1e40af; border: 1px solid #93c5fd; }
        .badge-mudaraba { background: #f3e8ff; color: #6b21a8; border: 1px solid #d8b4fe; }
        .badge-wadia { background: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd; }
        .item-card { background: white; border-radius: 12px; padding: 14px; margin-bottom: 12px; border: 1px solid #e2e8f0; }
        .img-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin: 10px 0; }
        .img-grid img { width: 100%; height: 60px; object-fit: cover; border-radius: 6px; border: 1px solid #e2e8f0; }
        .btn-action { padding: 6px 12px; border-radius: 6px; color: white; text-decoration: none; font-size: 12px; font-weight: bold; display: inline-block; border:none; cursor:pointer; }
        .btn-blue { background: #2563eb; }
        .btn-green { background: #16a34a; }
        .btn-red { background: #dc2626; }
        .btn-orange { background: #ea580c; }
        .btn-purple { background: #7c3aed; }
        .pwd-toggle { position: absolute; right: 10px; top: 32px; cursor: pointer; user-select: none; font-size: 14px; }
        .modal { display: none; position: fixed; z-index: 100; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); align-items: center; justify-content: center; }
        .modal-content { background: white; padding: 20px; border-radius: 12px; max-width: 450px; width: 90%; max-height: 85vh; overflow-y: auto; }
        @media print {
            .bottom-nav, nav, .btn-print, .no-print { display: none !important; }
            body { padding-bottom: 0; background: white; }
            .box { border: none; box-shadow: none; }
        }
    </style>
</head>
<body>
    <nav class="no-print">
        <div class="logo-container">
            <svg class="logo-svg" viewBox="0 0 24 24">
                <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
            </svg>
            <h1>Imana Free Interest Microfinance</h1>
        </div>
        {% if session.get('role') %}
            <div style="font-size:12px;">
                <span style="margin-right:4px;"><b>{{ session['username'] }}</b></span>
                <span class="role-badge">{{ session['role'] }}</span>
                <a href="/change_password" style="color: #fde047; margin-left:8px; text-decoration:none;">🔑 Password</a>
                <a href="/logout" style="color: #fca5a5; margin-left:8px; text-decoration:none;">Logout</a>
            </div>
        {% endif %}
    </nav>

    <div class="container">
        {% if notifications %}
            <div class="notification-bar no-print">
                🔔 NOTIFICATION: {{ notifications[0] }}
            </div>
        {% endif %}
        {% block content %}{% endblock %}
    </div>

    {% if session.get('role') %}
    <div class="bottom-nav no-print">
        <a href="/"><span class="icon">🏠</span>Dashboard</a>
        {% if session['role'] == 'MAKER' %}
            <a href="/register"><span class="icon">👤</span>Galmee</a>
            <a href="/transaction"><span class="icon">💸</span>Kaffaltii</a>
            <a href="/maker_receipts"><span class="icon">🧾</span>Nagahee</a>
        {% endif %}
        {% if session['role'] == 'MANAGER' %}
            <a href="/pending"><span class="icon">📋</span>Manager Appr</a>
            <a href="/reversals_list"><span class="icon">🔄</span>Reversals</a>
            <a href="/print_receipt_search"><span class="icon">🖨️</span>Nagahee</a>
        {% endif %}
        {% if session['role'] == 'AUDITOR' %}
            <a href="/pending"><span class="icon">📋</span>Auditor View</a>
            <a href="/auditor_reversal_request"><span class="icon">⚠️</span>Reversal Gaafachu</a>
            <a href="/print_receipt_search"><span class="icon">🖨️</span>Nagahee</a>
        {% endif %}
        {% if session['role'] in ['LOAN_OFFICER', 'CEO', 'MANAGER'] %}
            <a href="/islamic_loan"><span class="icon">📜</span>Liqaa Islaamaa</a>
        {% endif %}
        {% if session['role'] == 'CEO' %}
            <a href="/reversals_list" style="color: #581c87;"><span class="icon">🔄</span>Reversal CEO</a>
            <a href="/ceo_commission" style="color: #581c87;"><span class="icon">💰</span>Commission</a>
            <a href="/manage_users" style="color: #6b21a8;"><span class="icon">⚙️</span>Hojjattoota</a>
        {% endif %}
    </div>
    {% endif %}

    <script>
    function togglePasswordVisibility(inputId, toggleIconId) {
        var input = document.getElementById(inputId);
        var icon = document.getElementById(toggleIconId);
        if (input.type === "password") {
            input.type = "text";
            icon.textContent = "🙈";
        } else {
            input.type = "password";
            icon.textContent = "👁️";
        }
    }
    </script>
</body>
</html>
"""

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/api/get_customer/<cust_id>')
def api_get_customer(cust_id):
    if 'role' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT customer_id, full_name, phone, photo_path, signature_path, freeze_status, freeze_reason, balance FROM customers WHERE customer_id = ?", (cust_id,))
    cust = cursor.fetchone()
    conn.close()
    
    if cust:
        return jsonify({
            'success': True,
            'customer_id': cust['customer_id'],
            'full_name': cust['full_name'],
            'phone': cust['phone'],
            'photo_path': cust['photo_path'],
            'signature_path': cust['signature_path'],
            'freeze_status': cust['freeze_status'],
            'freeze_reason': cust['freeze_reason'],
            'balance': cust['balance']
        })
    return jsonify({'success': False, 'message': 'Maammilli hin argamne'})

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username, role, status FROM users WHERE username = ? AND password = ?", (username, password))
        user = cursor.fetchone()
        conn.close()

        if user:
            if user['status'] == 'BLOCKED':
                error = "🚫 Akkaawunttii keessan UGGURAMEERA! CEO qunnamaa."
            else:
                session['username'] = user['username']
                session['role'] = user['role']
                return redirect('/')
        else:
            error = "Username ykn Password dogoggoraa!"

    err_html = f"<p style='color:red; font-size:12px; text-align:center; margin-bottom:12px;'>{error}</p>" if error else ""
    content = f"""
    <div class="box" style="margin-top: 30px; text-align: center;">
        <div style="font-size: 40px; margin-bottom: 10px;">🏦</div>
        <h2 style="font-size: 17px; margin-bottom: 4px; color:#065f46;">Imana Free Interest Microfinance</h2>
        <p style="font-size: 12px; color: #64748b; margin-bottom: 16px;">Seensa Systema (Login)</p>
        {err_html}
        <form method="POST">
            <div class="form-group" style="text-align:left;">
                <label>Username</label>
                <input type="text" name="username" placeholder="Fkn: ceo, manager1, maker1" class="input-field" required>
            </div>
            <div class="form-group" style="text-align:left;">
                <label>Password</label>
                <input type="password" id="login_password" name="password" placeholder="Password" class="input-field" required>
                <span id="login_pwd_toggle" class="pwd-toggle" onclick="togglePasswordVisibility('login_password', 'login_pwd_toggle')">👁️</span>
            </div>
            <button type="submit" class="btn-submit">Seeni (Login)</button>
        </form>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# --- HOJJATAAN PASSWORD MATAA ISAA JIJJIRRACHUUF ---
@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'role' not in session:
        return redirect('/login')

    msg = None
    msg_type = "green"

    if request.method == 'POST':
        old_pwd = request.form.get('old_password', '').strip()
        new_pwd = request.form.get('new_password', '').strip()
        confirm_pwd = request.form.get('confirm_password', '').strip()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT password FROM users WHERE username = ?", (session['username'],))
        user = cursor.fetchone()

        if not user or user['password'] != old_pwd:
            msg = "❌ Password duraanii dogoggoraa!"
            msg_type = "red"
        elif new_pwd != confirm_pwd:
            msg = "❌ Password-ni haaraa fi Mirkaneessaan wal hin simne!"
            msg_type = "red"
        elif len(new_pwd) < 4:
            msg = "❌ Password-ni haaraa xiqqaate gabaabaa dha (Minimum 4 characters)!"
            msg_type = "red"
        else:
            cursor.execute("UPDATE users SET password = ? WHERE username = ?", (new_pwd, session['username']))
            conn.commit()
            msg = "✅ Password keessan milkaa'inaan jijjiiramtaniirra!"
            msg_type = "green"

        conn.close()

    content = f"""
    <div class="box">
        <h2 style="font-size: 16px; color:#065f46; margin-bottom: 12px;">🔑 Password Mataa Keetii Jijjiiri</h2>
        
        {f"<p style='background:{'#dcfce7' if msg_type=='green' else '#fee2e2'}; color:{'#166534' if msg_type=='green' else '#991b1b'}; padding:10px; border-radius:6px; font-size:12px; font-weight:bold; margin-bottom:12px;'>{msg}</p>" if msg else ""}

        <form method="POST">
            <div class="form-group">
                <label>Password Duraanii (Current Password)</label>
                <input type="password" id="old_pwd" name="old_password" required class="input-field">
                <span id="old_pwd_toggle" class="pwd-toggle" onclick="togglePasswordVisibility('old_pwd', 'old_pwd_toggle')">👁️</span>
            </div>
            <div class="form-group">
                <label>Password Haaraa (New Password)</label>
                <input type="password" id="new_pwd" name="new_password" required class="input-field">
                <span id="new_pwd_toggle" class="pwd-toggle" onclick="togglePasswordVisibility('new_pwd', 'new_pwd_toggle')">👁️</span>
            </div>
            <div class="form-group">
                <label>Password Haaraa Mirkaneessi (Confirm Password)</label>
                <input type="password" id="conf_pwd" name="confirm_password" required class="input-field">
                <span id="conf_pwd_toggle" class="pwd-toggle" onclick="togglePasswordVisibility('conf_pwd', 'conf_pwd_toggle')">👁️</span>
            </div>
            <button type="submit" class="btn-submit">💾 Password Jijjiiri</button>
        </form>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

@app.route('/')
def dashboard():
    if 'role' not in session:
        return redirect('/login')
    
    net_cap, deposits, withdraws, cust_bal, total_comm, mud_dep, mud_gross, mud_ceo, mud_cust = get_bank_capital()
    role = session['role']

    maker_btns = ""
    if role == 'MAKER':
        maker_btns = """
        <a href="/register" class="btn-card"><span class="icon">👤</span><span>Galmee Maammilaa</span></a>
        <a href="/transaction" class="btn-card"><span class="icon">💸</span><span>Deposit / Transfer / Withdraw</span></a>
        <a href="/maker_receipts" class="btn-card"><span class="icon">🧾</span><span>Nagahee Maxxansi</span></a>
        """

    manager_btns = ""
    if role == 'MANAGER':
        manager_btns = """
        <a href="/pending" class="btn-card"><span class="icon">🔍</span><span>Manager Approval</span></a>
        <a href="/reversals_list" class="btn-card"><span class="icon">🔄</span><span>Reversal Approvals</span></a>
        <a href="/print_receipt_search" class="btn-card"><span class="icon">🖨️</span><span>Barbaadi & Nagahee Maxxansi</span></a>
        """

    auditor_btns = ""
    if role == 'AUDITOR':
        auditor_btns = """
        <a href="/pending" class="btn-card btn-card-auditor"><span class="icon">📋</span><span>View Maammilaa & Approve</span></a>
        <a href="/auditor_reversal_request" class="btn-card btn-card-auditor"><span class="icon">⚠️</span><span>Transaction Reversal Gaafachu</span></a>
        <a href="/auditor_eod" class="btn-card btn-card-auditor"><span class="icon">📊</span><span>EOD Cufiinsa & Gabaasa Maker</span></a>
        <a href="/print_receipt_search" class="btn-card btn-card-auditor"><span class="icon">🖨️</span><span>Txn Nagahee Maxxansi</span></a>
        """

    loan_btn = ""
    if role in ['LOAN_OFFICER', 'CEO', 'MANAGER']:
        loan_btn = """
        <a href="/islamic_loan" class="btn-card btn-card-loan"><span class="icon">📜</span><span>Mudaraba & Murabaha Loan</span></a>
        """

    ceo_btn = ""
    ceo_mudaraba_dashboard = ""
    net_capital_html = ""
    
    if role == 'CEO':
        ceo_mudaraba_dashboard = f"""
        <div class="card-ceo-profit">
            <div class="net-title">📊 CEO Private View: Mudaraba 50/50 Profit Share</div>
            <div class="net-amount">{mud_ceo:,.2f} Birr</div>
            <p style="font-size:11px; opacity:0.9; margin-top:4px;">Qoodda Bu'aa Baankii/CEO (50% Share)</p>
            <div class="net-grid">
                <div>📈 Waliigala Kuusaa Mudaraba: <b>{mud_dep:,.2f} Birr</b></div>
                <div>🤝 Qoodda Maammiltootaa (50%): <b>{mud_cust:,.2f} Birr</b></div>
            </div>
        </div>
        """
        net_capital_html = f"""
        <div class="card-net">
            <div class="net-title">Waliigala Kaabitaala Baankii (Net Capital)</div>
            <div class="net-amount">{net_cap:,.2f} Birr</div>
            <div class="net-grid">
                <div>📥 Deposit: <b>{deposits:,.2f} Birr</b></div>
                <div>📤 Withdraw/FT: <b>{withdraws:,.2f} Birr</b></div>
            </div>
        </div>
        """
        ceo_btn = """
        <a href="/ceo_commission" class="btn-card btn-card-ceo"><span class="icon">💰</span><span>Comishina Guyyaa (Filtara)</span></a>
        <a href="/ceo_mudaraba_list" class="btn-card btn-card-ceo"><span class="icon">🤝</span><span>Mudaraba Private List</span></a>
        <a href="/ceo_blank_form" target="_blank" class="btn-card btn-card-ceo"><span class="icon">🖨️</span><span>Formii Duwwaa Maxxansi</span></a>
        <a href="/reversals_list" class="btn-card btn-card-ceo"><span class="icon">🔄</span><span>CEO Reversal Approval</span></a>
        <a href="/manage_users" class="btn-card btn-card-ceo"><span class="icon">⚙️</span><span>Bulchiinsa Hojjattootaa</span></a>
        <a href="/ceo_backup" class="btn-card btn-card-ceo"><span class="icon">💾</span><span>Save / Restore DB</span></a>
        """

    content = f"""
    {ceo_mudaraba_dashboard}
    {net_capital_html}

    <h3 style="font-size: 14px; margin-bottom: 12px; color: #475569;">Menu Hojii ({role})</h3>
    <div class="grid-2">
        {maker_btns}
        {manager_btns}
        {auditor_btns}
        {loan_btn}
        <a href="/customers" class="btn-card"><span class="icon">👥</span><span>Listii Maammiltootaa</span></a>
        {ceo_btn}
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

# --- CEO FEATURE 1: COMMISSION WITH DATE RANGE FILTER ---
@app.route('/ceo_commission')
def ceo_commission():
    if 'role' not in session or session['role'] != 'CEO':
        return "🚫 Hayyama CEO Qofa!", 403

    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT txn_id, ft_reference, customer_name, amount, commission, timestamp FROM transactions WHERE status='APPROVED' AND commission > 0"
    params = []

    if start_date:
        query += " AND timestamp >= ?"
        params.append(start_date + " 00:00:00")
    if end_date:
        query += " AND timestamp <= ?"
        params.append(end_date + " 23:59:59")

    query += " ORDER BY timestamp DESC"
    cursor.execute(query, params)
    txns = cursor.fetchall()
    conn.close()

    total_comm = sum([t['commission'] for t in txns])
    rows_html = ""
    for t in txns:
        rows_html += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:12px;">
            <td style="padding:8px;">{t['timestamp']}</td>
            <td style="padding:8px; font-weight:bold;">{t['ft_reference']}</td>
            <td style="padding:8px;">{t['customer_name']}</td>
            <td style="padding:8px;">{t['amount']:,.2f} Birr</td>
            <td style="padding:8px; font-weight:bold; color:#047857;">+{t['commission']:,.2f} Birr</td>
        </tr>
        """

    content = f"""
    <div class="card-ceo-profit">
        <div class="net-title">💰 CEO VIEW: COMMISION KUUSAMEE</div>
        <div class="net-amount">{total_comm:,.2f} Birr</div>
        <p style="font-size:11px; opacity:0.9; margin-top:4px;">Gabaasa Comishina Kaffaltii Baasii (Withdrawal Commission)</p>
    </div>

    <div class="box">
        <h3 style="font-size:13px; margin-bottom:8px; color:#475569;">📅 Filter Guyyaa Galii Comishinaa</h3>
        <form method="GET" style="display:flex; gap:8px; align-items:flex-end;">
            <div style="flex:1;">
                <label style="font-size:11px; font-weight:bold;">Guyyaa Jalqabaa</label>
                <input type="date" name="start_date" value="{start_date}" class="input-field">
            </div>
            <div style="flex:1;">
                <label style="font-size:11px; font-weight:bold;">Guyyaa Dhumaa</label>
                <input type="date" name="end_date" value="{end_date}" class="input-field">
            </div>
            <button type="submit" class="btn-action btn-purple" style="padding:10px 14px;">Filter</button>
        </form>
    </div>

    <div class="box" style="padding:0; overflow-x:auto;">
        <table style="width:100%; border-collapse:collapse; text-align:left;">
            <thead>
                <tr style="background:#f8fafc; font-size:11px; color:#64748b; border-bottom:1px solid #e2e8f0;">
                    <th style="padding:8px;">Guyyaa</th>
                    <th style="padding:8px;">Ref</th>
                    <th style="padding:8px;">Maammila</th>
                    <th style="padding:8px;">Hamma Txn</th>
                    <th style="padding:8px;">Commission</th>
                </tr>
            </thead>
            <tbody>
                {rows_html if rows_html else '<tr><td colspan="5" style="padding:16px; text-align:center; color:#64748b;">Comishiniin galmaa\'e hin jiru.</td></tr>'}
            </tbody>
        </table>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

# --- CEO FEATURE 2: BULCHIINSA HOJJATTOOTAA (ROLE EDIT & RESET PASSWORD ADDED) ---
@app.route('/manage_users', methods=['GET', 'POST'])
def manage_users():
    if 'role' not in session or session['role'] != 'CEO':
        return "🚫 Hayyama CEO Qofa!", 403

    msg = None
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        action = request.form.get('action')
        uname = request.form.get('username')

        if action == 'add':
            pwd = request.form.get('password').strip()
            urole = request.form.get('role')
            try:
                cursor.execute("INSERT INTO users (username, password, role, status) VALUES (?, ?, ?, 'ACTIVE')", (uname, pwd, urole))
                conn.commit()
                msg = f"✅ Hojjataa haaraan ({uname} - {urole}) galmaa'eera!"
            except Exception as e:
                msg = f"❌ Error: Username '{uname}' duraan jira!"
        elif action == 'change_role':
            new_role = request.form.get('new_role')
            cursor.execute("UPDATE users SET role = ? WHERE username = ?", (new_role, uname))
            conn.commit()
            msg = f"🔄 Shoorri (Role) Hojjataa '{uname}' gara '{new_role}'itti jijjiirameera!"
        elif action == 'reset_password':
            new_pwd = request.form.get('new_password').strip()
            if new_pwd:
                cursor.execute("UPDATE users SET password = ? WHERE username = ?", (new_pwd, uname))
                conn.commit()
                msg = f"🔑 Password hojjataa '{uname}' milkaa'inaan Reset ta'ee jira!"
        elif action == 'block':
            cursor.execute("UPDATE users SET status = 'BLOCKED' WHERE username = ?", (uname,))
            conn.commit()
            msg = f"🚫 User {uname} Blocked ta'ee jira!"
        elif action == 'unblock':
            cursor.execute("UPDATE users SET status = 'ACTIVE' WHERE username = ?", (uname,))
            conn.commit()
            msg = f"✅ User {uname} Unblocked ta'ee jira!"

    cursor.execute("SELECT username, role, status FROM users")
    users = cursor.fetchall()
    conn.close()

    rows_html = ""
    for u in users:
        if u['username'] == 'ceo':
            st_btn = '<b>Master Admin</b>'
        else:
            st_btn = f'''
            <div style="display:flex; gap:4px; justify-content:flex-end; flex-wrap:wrap;">
                <!-- Role Change Form -->
                <form method="POST" style="display:inline;">
                    <input type="hidden" name="username" value="{u['username']}">
                    <input type="hidden" name="action" value="change_role">
                    <select name="new_role" style="font-size:10px; padding:3px;" onchange="this.form.submit()">
                        <option value="MAKER" {'selected' if u['role']=='MAKER' else ''}>MAKER</option>
                        <option value="MANAGER" {'selected' if u['role']=='MANAGER' else ''}>MANAGER</option>
                        <option value="AUDITOR" {'selected' if u['role']=='AUDITOR' else ''}>AUDITOR</option>
                        <option value="LOAN_OFFICER" {'selected' if u['role']=='LOAN_OFFICER' else ''}>LOAN_OFFICER</option>
                    </select>
                </form>

                <!-- Reset Password Form -->
                <form method="POST" style="display:inline;" onsubmit="return confirm('Password reset gochuu barbaaddaa?')">
                    <input type="hidden" name="username" value="{u['username']}">
                    <input type="hidden" name="action" value="reset_password">
                    <input type="text" name="new_password" placeholder="Pass Haaraa" required style="width:70px; font-size:10px; padding:3px;">
                    <button type="submit" class="btn-action btn-blue" style="padding:3px 6px; font-size:10px;">Reset Pass</button>
                </form>

                <!-- Block / Unblock Form -->
                <form method="POST" style="display:inline;">
                    <input type="hidden" name="username" value="{u['username']}">
                    <input type="hidden" name="action" value="{"unblock" if u["status"]=="BLOCKED" else "block"}">
                    <button type="submit" class="btn-action {"btn-green" if u["status"]=="BLOCKED" else "btn-red"}" style="padding:3px 6px; font-size:10px;">
                        {"Unblock" if u["status"]=="BLOCKED" else "Block"}
                    </button>
                </form>
            </div>
            '''

        rows_html += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:12px;">
            <td style="padding:8px; font-weight:bold;">{u['username']}</td>
            <td style="padding:8px;"><span class="role-badge">{u['role']}</span></td>
            <td style="padding:8px;">{u['status']}</td>
            <td style="padding:8px; text-align:right;">{st_btn}</td>
        </tr>
        """

    content = f"""
    <div class="box">
        <h2 style="font-size:16px; color:#581c87; margin-bottom:12px;">⚙️ Bulchiinsa Hojjattootaa (Users Management)</h2>
        {f"<p style='background:#dcfce7; color:#166534; padding:10px; border-radius:6px; font-size:12px; font-weight:bold; margin-bottom:12px;'>{msg}</p>" if msg else ""}

        <form method="POST" style="margin-bottom:20px;">
            <input type="hidden" name="action" value="add">
            <div class="form-group">
                <label>Username Haaraa</label>
                <input type="text" name="username" required class="input-field">
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" required class="input-field">
            </div>
            <div class="form-group">
                <label>Shoora (Role)</label>
                <select name="role" class="input-field" required>
                    <option value="MAKER">MAKER (Galmeessaa / Teller)</option>
                    <option value="MANAGER">MANAGER (Mirkaneessaa)</option>
                    <option value="AUDITOR">AUDITOR (To'ataa)</option>
                    <option value="LOAN_OFFICER">LOAN_OFFICER (Mijjeessaa Liqaa)</option>
                </select>
            </div>
            <button type="submit" class="btn-submit" style="background:#7c3aed;">➕ Hojjataa Haaraa Galmeessi</button>
        </form>

        <h3 style="font-size:13px; margin-bottom:8px; color:#475569;">📋 Tarree Hojjattoota Systema</h3>
        <table style="width:100%; border-collapse:collapse; text-align:left;">
            <thead>
                <tr style="background:#f8fafc; font-size:11px; color:#64748b; border-bottom:1px solid #e2e8f0;">
                    <th style="padding:8px;">Username</th>
                    <th style="padding:8px;">Role</th>
                    <th style="padding:8px;">Status</th>
                    <th style="padding:8px; text-align:right;">Tarkaanfii / Role Jijjiiri / Reset Pass</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

# --- TRANSACTION PRINT SEARCH (MANAGER & AUDITOR RECEIPT PRINT) ---
@app.route('/print_receipt_search', methods=['GET', 'POST'])
def print_receipt_search():
    if 'role' not in session or session['role'] not in ['MANAGER', 'AUDITOR', 'CEO', 'MAKER']:
        return "🚫 Hayyama Qabu Qofa!", 403

    txn = None
    msg = None
    if request.method == 'POST':
        search_id = request.form.get('txn_search_id', '').strip()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE txn_id = ? OR ft_reference = ?", (search_id, search_id))
        txn = cursor.fetchone()
        conn.close()
        if not txn:
            msg = "❌ Transaction ID / FT Reference kanaan nagaheen argame hin jiru!"

    content = f"""
    <div class="box">
        <h2 style="font-size:16px; color:#065f46; margin-bottom:8px;">🖨️ Transaction ID-n Nagahee Barbaadi Maxxansi</h2>
        <p style="font-size:11px; color:#64748b; margin-bottom:14px;">Auditor ykn Manager-ni Txn ID ykn FT Reference galchuun nagahee maxxansuu danda'u.</p>
        
        {f"<p style='background:#fee2e2; color:#991b1b; padding:10px; border-radius:6px; font-size:12px; font-weight:bold; margin-bottom:12px;'>{msg}</p>" if msg else ""}

        <form method="POST">
            <div class="form-group">
                <label>Txn ID ykn FT Reference</label>
                <input type="text" name="txn_search_id" placeholder="Fkn: TXN-1724200000 ykn TT2621412345" required class="input-field">
            </div>
            <button type="submit" class="btn-submit">🔍 Barbaadi Nagahee</button>
        </form>
    </div>
    """
    if txn:
        content += f"""
        <div class="item-card" style="border-left: 4px solid #7c3aed;">
            <div style="font-size:13px; font-weight:bold; color:#065f46;">Ref: {txn['ft_reference']} | ID: {txn['txn_id']}</div>
            <div style="font-size:12px; margin-top:4px;"><b>Maammila:</b> {txn['customer_name']} ({txn['customer_id']})</div>
            <div style="font-size:12px;"><b>Gosa & Hamma:</b> {txn['txn_type']} - {txn['amount']:,.2f} Birr</div>
            <div style="font-size:11px; color:#64748b;"><b>Status:</b> {txn['status']} | {txn['timestamp']}</div>
            <div style="text-align:right; margin-top:10px;">
                <a href="/receipt/{txn['txn_id']}" target="_blank" class="btn-action btn-purple">🖨️ Nagahee Maxxansi (Print)</a>
            </div>
        </div>
        """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

# --- SINGLE RECEIPT PRINT TEMPLATE (WITH SENDER & RECEIVER NAME) ---
@app.route('/receipt/<txn_id>')
def print_receipt(txn_id):
    if 'role' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions WHERE txn_id = ?", (txn_id,))
    txn = cursor.fetchone()
    
    if not txn:
        conn.close()
        return "Nagaheen Hin Argamne", 404

    cursor.execute("SELECT phone, balance FROM customers WHERE customer_id = ?", (txn['customer_id'],))
    cust = cursor.fetchone()

    # If transaction is T24_TRANSFER, get receiver customer details
    target_cust_name = ""
    if txn['txn_type'] == 'T24_TRANSFER' and txn['target_account']:
        cursor.execute("SELECT full_name FROM customers WHERE customer_id = ?", (txn['target_account'],))
        t_cust = cursor.fetchone()
        if t_cust:
            target_cust_name = t_cust['full_name']

    conn.close()

    phone = cust['phone'] if cust else ""
    bal = cust['balance'] if cust else 0.0

    # Sender and Receiver Name logic
    sender_info = f"{txn['customer_name']} ({txn['customer_id']})"
    receiver_info = f"{target_cust_name} ({txn['target_account']})" if target_cust_name else (txn['target_account'] if txn['target_account'] else "-")

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Nagahee - {txn['ft_reference']}</title>
        <style>
            body {{ font-family: sans-serif; padding: 20px; max-width: 500px; margin: 0 auto; border: 1px solid #cbd5e1; border-radius: 8px; background: white; }}
            .header {{ text-align: center; border-bottom: 2px solid #065f46; padding-bottom: 10px; margin-bottom: 15px; }}
            .row {{ display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 8px; border-bottom: 1px dashed #e2e8f0; padding-bottom: 4px; }}
            .btn-print {{ background: #065f46; color: white; border: none; padding: 10px; width: 100%; font-weight: bold; cursor: pointer; border-radius: 6px; margin-top: 15px; }}
            @media print {{ .btn-print {{ display: none; }} body {{ border: none; }} }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2 style="color:#065f46; margin:0; font-size:18px;">IMANA MICROFINANCE</h2>
            <p style="font-size:11px; color:#64748b;">NAGAHEE KAFFALTII (TRANSACTION RECEIPT)</p>
        </div>

        <div class="row"><span>FT Reference:</span><b>{txn['ft_reference']}</b></div>
        <div class="row"><span>Txn ID:</span><b>{txn['txn_id']}</b></div>
        <div class="row"><span>Guyyaa:</span><b>{txn['timestamp']}</b></div>
        <div class="row"><span>Gosa Kaffaltii:</span><b>{txn['txn_type']}</b></div>
        <div class="row"><span>Maqaa Nama Erguu (Sender):</span><b>{sender_info}</b></div>
        <div class="row"><span>Maqaa Nama Fudhatuu (Receiver):</span><b>{receiver_info}</b></div>
        <div class="row"><span>Bilbila Sender:</span><b>{phone}</b></div>
        <div class="row"><span>Hamma Qarshii:</span><b style="font-size:15px; color:#065f46;">{txn['amount']:,.2f} Birr</b></div>
        <div class="row"><span>Commission:</span><b>{txn['commission']:,.2f} Birr</b></div>
        <div class="row"><span>Haftee Akkaawuntii:</span><b>{bal:,.2f} Birr</b></div>
        <div class="row"><span>Status:</span><b>{txn['status']}</b></div>
        <div class="row"><span>Hojjataa (Maker):</span><b>{txn['created_by']}</b></div>

        <div style="margin-top: 30px; display: flex; justify-content: space-between; font-size: 11px;">
            <div>__________________<br>Mallattoo Maker</div>
            <div>__________________<br>Mallattoo Maammilaa</div>
        </div>

        <button onclick="window.print()" class="btn-print">🖨️ Nagahee Maxxansi (Print Receipt)</button>
    </body>
    </html>
    """

# --- STATEMENT WITH DATE RANGE FILTER ---
@app.route('/statement/<cust_id>')
def statement(cust_id):
    if 'role' not in session:
        return redirect('/login')

    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers WHERE customer_id = ?", (cust_id,))
    c = cursor.fetchone()

    if not c:
        conn.close()
        return "Maammilli Hin Argamne", 404

    query = """
        SELECT txn_id, txn_type, amount, commission, ft_reference, status, created_by, timestamp, customer_id, target_account
        FROM transactions
        WHERE (customer_id = ? OR target_account = ?) AND status = 'APPROVED'
    """
    params = [cust_id, cust_id]

    if start_date:
        query += " AND timestamp >= ?"
        params.append(start_date + " 00:00:00")
    if end_date:
        query += " AND timestamp <= ?"
        params.append(end_date + " 23:59:59")

    query += " ORDER BY timestamp ASC"
    cursor.execute(query, params)
    txns = cursor.fetchall()
    conn.close()

    running_balance = 0.0
    rows_html = ""
    for t in txns:
        amount = t['amount']
        comm = t['commission']
        t_type = t['txn_type']

        if t_type == 'DEPOSIT' or (t_type == 'T24_TRANSFER' and t['target_account'] == cust_id):
            running_balance += amount
            impact = f"+{amount:,.2f}"
        elif t_type == 'WITHDRAWAL':
            running_balance -= (amount + comm)
            impact = f"-{(amount + comm):,.2f}"
        elif t_type == 'T24_TRANSFER' and t['customer_id'] == cust_id:
            running_balance -= amount
            impact = f"-{amount:,.2f}"
        else:
            impact = f"{amount:,.2f}"

        rows_html = f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:11px;">
            <td style="padding:8px;">{t['timestamp']}</td>
            <td style="padding:8px; font-weight:bold;">{t['ft_reference']}</td>
            <td style="padding:8px;">{t_type}</td>
            <td style="padding:8px; font-weight:bold;">{impact}</td>
            <td style="padding:8px;">{comm:,.2f}</td>
            <td style="padding:8px; font-weight:bold; color:#065f46;">{running_balance:,.2f} Birr</td>
        </tr>
        """ + rows_html

    content = f"""
    <div class="box">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <div>
                <h2 style="font-size: 16px; color:#065f46; margin-bottom:4px;">📜 Account Statement</h2>
                <p style="font-size: 12px; font-weight:bold;">{c['full_name']} (Acc: {c['customer_id']})</p>
                <p style="font-size: 11px; color:#64748b;">Saala: <b>{c['gender']}</b> | Scheme: <b>{c['account_type']}</b></p>
                <p style="font-size: 11px; color:#64748b;">Haftee Amajji/Ammaa: <b style="color:#065f46;">{c['balance']:,.2f} Birr</b></p>
            </div>
            <button onclick="window.print()" class="btn-action btn-purple no-print">🖨️ Print Statement</button>
        </div>
    </div>

    <div class="box no-print">
        <h3 style="font-size:12px; margin-bottom:6px; color:#475569;">📅 Filter Guyyaa Statement</h3>
        <form method="GET" style="display:flex; gap:8px; align-items:flex-end;">
            <div style="flex:1;">
                <label style="font-size:10px; font-weight:bold;">Guyyaa Jalqabaa</label>
                <input type="date" name="start_date" value="{start_date}" class="input-field">
            </div>
            <div style="flex:1;">
                <label style="font-size:10px; font-weight:bold;">Guyyaa Dhumaa</label>
                <input type="date" name="end_date" value="{end_date}" class="input-field">
            </div>
            <button type="submit" class="btn-action btn-blue" style="padding:10px 14px;">Filter</button>
        </form>
    </div>

    <div class="box" style="padding:0; overflow-x:auto;">
        <table style="width:100%; border-collapse:collapse; text-align:left;">
            <thead>
                <tr style="background:#f8fafc; font-size:11px; color:#64748b; border-bottom:1px solid #e2e8f0;">
                    <th style="padding:8px;">Guyyaa</th>
                    <th style="padding:8px;">Ref</th>
                    <th style="padding:8px;">Type</th>
                    <th style="padding:8px;">Socho'iinsa</th>
                    <th style="padding:8px;">Comm</th>
                    <th style="padding:8px;">Haftee Balance</th>
                </tr>
            </thead>
            <tbody>
                {rows_html if rows_html else '<tr><td colspan="6" style="padding:16px; text-align:center; color:#64748b;">Transaction-ni socho\'e hin jiru.</td></tr>'}
            </tbody>
        </table>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

# --- AUDITOR EOD SUMMARY ---
@app.route('/auditor_eod', methods=['GET', 'POST'])
def auditor_eod():
    if 'role' not in session or session['role'] != 'AUDITOR':
        return "🚫 Hayyama Auditor Qofa!", 403

    conn = get_db_connection()
    cursor = conn.cursor()

    msg = None
    if request.method == 'POST':
        cursor.execute("UPDATE transactions SET audited_status = 'CLOSED' WHERE audited_status = 'OPEN' AND status = 'APPROVED'")
        conn.commit()
        msg = "✅ Herregni guyyaa har'aa cuufameera (EOD Closed)!"
        add_notification("Auditor herrega guyyaa cufeera.")

    cursor.execute("""
        SELECT created_by, 
               SUM(CASE WHEN txn_type='DEPOSIT' THEN amount ELSE 0 END) as total_dep,
               SUM(CASE WHEN txn_type='WITHDRAWAL' THEN amount ELSE 0 END) as total_with
        FROM transactions 
        WHERE audited_status = 'OPEN' AND status = 'APPROVED'
        GROUP BY created_by
    """)
    eod_data = cursor.fetchall()
    conn.close()

    rows_html = ""
    total_cash_expected = 0.0
    for r in eod_data:
        net_cash = r['total_dep'] - r['total_with']
        total_cash_expected += net_cash
        rows_html += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:12px;">
            <td style="padding:8px; font-weight:bold;">{r['created_by']}</td>
            <td style="padding:8px; color:#047857;">+{r['total_dep']:,.2f}</td>
            <td style="padding:8px; color:#dc2626;">-{r['total_with']:,.2f}</td>
            <td style="padding:8px; font-weight:bold;">{net_cash:,.2f} Birr</td>
        </tr>
        """

    content = f"""
    <div class="box">
        <h2 style="font-size: 16px; color:#c2410c; margin-bottom: 4px;">📊 Gabaasa Maker & Cufiinsa Guyyaa (EOD)</h2>
        <p style="font-size: 11px; color:#64748b; margin-bottom: 14px;">Maker meeqa akka deebisuu qabu asirraa to'adhu.</p>
        {f"<p style='background:#dcfce7; color:#166534; padding:10px; border-radius:6px; font-size:12px; font-weight:bold; margin-bottom:12px;'>{msg}</p>" if msg else ""}
    </div>
    
    <div class="box" style="padding:0; overflow-x:auto; margin-bottom:16px;">
        <table style="width:100%; border-collapse:collapse; text-align:left;">
            <thead>
                <tr style="background:#f8fafc; font-size:11px; color:#64748b; border-bottom:1px solid #e2e8f0;">
                    <th style="padding:8px;">Maker (Hojjataa)</th>
                    <th style="padding:8px;">Galii (Deposit)</th>
                    <th style="padding:8px;">Baasii (Withdraw)</th>
                    <th style="padding:8px;">Qarshii Deebisuu Qabu (Net)</th>
                </tr>
            </thead>
            <tbody>
                {rows_html if rows_html else '<tr><td colspan="4" style="padding:16px; text-align:center; color:#64748b;">Har\'a transaction haaraan hin jiru.</td></tr>'}
            </tbody>
        </table>
    </div>

    <div class="box" style="text-align:center;">
        <h3 style="font-size:14px; margin-bottom:12px;">Waliigala Qarshii Deebi'u: <b style="color:#047857;">{total_cash_expected:,.2f} Birr</b></h3>
        <form method="POST">
            <button type="submit" class="btn-submit" style="background:#ea580c;" onclick="return confirm('Dhuguma herrega guyyaa kanaa cufuu barbaaddaa?')">🔒 Herrega Guyyaa Cufi (Close EOD)</button>
        </form>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

# --- MAKER TRANSACTION ROUTE WITH AUTO TARGET ACCOUNT VERIFY ---
@app.route('/transaction', methods=['GET', 'POST'])
def transaction():
    if 'role' not in session or session['role'] != 'MAKER':
        return "🚫 Shoora MAKER qofatu transaction raawwachuu danda'a", 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT customer_id, full_name, balance, freeze_status FROM customers WHERE status='ACTIVE'")
    customers = cursor.fetchall()

    msg = None
    msg_type = "green"

    if request.method == 'POST':
        txn_type = request.form.get('txn_type')
        cust_id = request.form.get('customer_id')
        target_acc = request.form.get('target_account', '').strip()
        amount = float(request.form.get('amount', 0.0))
        confirm_amount = float(request.form.get('confirm_amount', 0.0))
        bank_name = request.form.get('bank_name', 'Imana Microfinance Core')

        cursor.execute("SELECT full_name, balance, freeze_status FROM customers WHERE customer_id = ?", (cust_id,))
        cust = cursor.fetchone()

        if amount != confirm_amount:
            msg = "❌ Hammi maallaqaa bakka lamatti galchitan wal hin simne (Amount Mismatch)!"
            msg_type = "red"
        elif not cust:
            msg = "❌ Maammilli hin argamne!"
            msg_type = "red"
        elif cust['freeze_status'] == 'FROZEN' and txn_type in ['WITHDRAWAL', 'T24_TRANSFER']:
            msg = "🔒 Akkaawuntiin maammila kanaa UGGURAMEERA! Baasii ykn Transfer gochuun hin danda'amu."
            msg_type = "red"
        elif amount <= 0:
            msg = "❌ Hamma maallaqaa sirrii ta'e galchaa!"
            msg_type = "red"
        else:
            commission = get_commission(amount) if txn_type == 'WITHDRAWAL' else 0.0
            total_req = amount + commission

            if txn_type in ['WITHDRAWAL', 'T24_TRANSFER'] and cust['balance'] < total_req:
                msg = f"❌ Balansii gahaa miti! Balansii jiru: {cust['balance']:,.2f} Birr, Hamma Barbaadamu (fi commishina): {total_req:,.2f} Birr"
                msg_type = "red"
            else:
                timestamp_str = int(datetime.datetime.now().timestamp())
                if txn_type == 'DEPOSIT':
                    ft_ref = f"TT{datetime.datetime.now().strftime('%y%j')}{random.randint(10000, 99999)}"
                elif txn_type == 'WITHDRAWAL':
                    ft_ref = f"WITH{datetime.datetime.now().strftime('%y%j')}{random.randint(10000, 99999)}"
                else:
                    ft_ref = f"FT{datetime.datetime.now().strftime('%y%j')}{random.randint(10000, 99999)}"

                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                txn_id = f"TXN-{timestamp_str}"

                cursor.execute("""
                    INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name, target_account, amount, commission, bank_name, ft_reference, status, created_by, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_MANAGER', ?, ?)
                """, (txn_id, txn_type, cust_id, cust['full_name'], target_acc, amount, commission, bank_name, ft_ref, session['username'], now))

                conn.commit()
                msg = f"✅ Transaction ({txn_type}) {amount:,.2f} Birr galmaa'eera (Ref: {ft_ref}). Approval Manager eegaa jira!"
                add_notification(f"Maker transaction haaraa uumeera: {ft_ref} ({txn_type})")

    conn.close()

    cust_options = "".join([f'<option value="{c["customer_id"]}">{c["full_name"]} - {c["customer_id"]} (Bal: {c["balance"]:,.2f} Birr)</option>' for c in customers])

    content = f"""
    <div class="box">
        <h2 style="font-size: 16px; color:#065f46; margin-bottom: 12px;">💸 Transaction Raawwadhu (Maker T24)</h2>
        
        {f"<p style='background:{'#dcfce7' if msg_type=='green' else '#fee2e2'}; color:{'#166534' if msg_type=='green' else '#991b1b'}; padding:10px; border-radius:6px; font-size:12px; font-weight:bold; margin-bottom:12px;'>{msg}</p>" if msg else ""}

        <form method="POST">
            <div class="form-group">
                <label>Gosa Kaffaltii (Transaction Type)</label>
                <select name="txn_type" id="txn_type" class="input-field" onchange="toggleTargetAcc()">
                    <option value="DEPOSIT">📥 Deposit (Galii Maallaqaa)</option>
                    <option value="WITHDRAWAL">📤 Withdrawal (Baasii Maallaqaa)</option>
                    <option value="T24_TRANSFER">🔄 T24 Account Transfer (Akaawuntii irraa gara Akaawuntiitti)</option>
                </select>
            </div>
            
            <div class="form-group">
                <label>Maammila Filadhu ykn Barbaadi (Search)</label>
                <input list="cust_list" name="customer_id" id="customer_id_select" required class="input-field" oninput="fetchCustomerVerification()" placeholder="Maqaa ykn ID barreessi...">
                <datalist id="cust_list">
                    {cust_options}
                </datalist>
            </div>

            <div id="verification_box" style="display:none; background:#f0fdf4; border:1px solid #bbf7d0; padding:12px; border-radius:8px; margin-bottom:12px;">
                <h4 style="font-size:11px; color:#166534; margin-bottom:6px;">🛡️ MIRKANEESSA MAAMMILAA (MAKER ANTI-FRAUD CHECK)</h4>
                <div style="display:flex; align-items:center; gap:12px;">
                    <img id="v_photo" src="" style="width:60px; height:60px; border-radius:6px; object-fit:cover; border:1px solid #cbd5e1;">
                    <img id="v_signature" src="" style="width:100px; height:50px; border-radius:4px; object-fit:contain; border:1px solid #cbd5e1; background:white;">
                    <div style="font-size:11px;">
                        <p><b>Maqaa:</b> <span id="v_name"></span></p>
                        <p><b>Bilbila:</b> <span id="v_phone"></span></p>
                        <p><b>Status:</b> <span id="v_status"></span></p>
                    </div>
                </div>
                <div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #bbf7d0;">
                    <label style="font-size:12px; font-weight:bold; color:#166534; display:flex; align-items:center; gap:6px;">
                        <input type="checkbox" required name="verify_check"> Ani suuraa fi mallattoo maammilaa sirriitti mirkaneesseera.
                    </label>
                </div>
            </div>

            <div class="form-group" id="target_acc_group" style="display:none;">
                <label>Account ID Nama Fudhatuu (Target Account ID)</label>
                <input type="text" name="target_account" id="target_account_input" placeholder="Fkn: 100099008801" class="input-field" oninput="verifyTargetAccount()">
                <div id="target_verify_res" style="font-size:11px; font-weight:bold; margin-top:4px;"></div>
            </div>
            
            <div class="form-group">
                <label>Hamma Maallaqaa (Amount in Birr)</label>
                <input type="number" step="0.01" name="amount" placeholder="0.00" required class="input-field">
            </div>
            
            <div class="form-group">
                <label>Hamma Maallaqaa Mirkaneessi (Confirm Amount)</label>
                <input type="number" step="0.01" name="confirm_amount" placeholder="0.00" required class="input-field">
            </div>

            <div class="form-group">
                <label>Moggaasa Baankii / Note</label>
                <input type="text" name="bank_name" value="Imana Microfinance Core" class="input-field">
            </div>
            <button type="submit" class="btn-submit">⚡ Transaction Galmeessi (Send to Manager)</button>
        </form>
    </div>

    <script>
    function toggleTargetAcc() {{
        var type = document.getElementById('txn_type').value;
        var group = document.getElementById('target_acc_group');
        if (type === 'T24_TRANSFER') {{
            group.style.display = 'block';
        }} else {{
            group.style.display = 'none';
        }}
    }}

    function verifyTargetAccount() {{
        var targetId = document.getElementById('target_account_input').value;
        var resDiv = document.getElementById('target_verify_res');
        if(targetId.length < 5) {{
            resDiv.innerHTML = '';
            return;
        }}
        fetch('/api/get_customer/' + targetId)
        .then(response => response.json())
        .then(data => {{
            if(data.success) {{
                resDiv.innerHTML = '<span style="color:#047857;">✅ Target Acc Verified: ' + data.full_name + ' (Phone: ' + data.phone + ')</span>';
            }} else {{
                resDiv.innerHTML = '<span style="color:#dc2626;">❌ Target Account ID dogoggoraa ykn hin argamne!</span>';
            }}
        }});
    }}

    function fetchCustomerVerification() {{
        var custId = document.getElementById('customer_id_select').value;
        var box = document.getElementById('verification_box');
        if(custId.length < 5) {{
            box.style.display = 'none';
            return;
        }}
        fetch('/api/get_customer/' + custId)
        .then(response => response.json())
        .then(data => {{
            if(data.success) {{
                document.getElementById('v_name').innerText = data.full_name;
                document.getElementById('v_phone').innerText = data.phone;
                document.getElementById('v_photo').src = '/uploads/' + data.photo_path;
                document.getElementById('v_signature').src = '/uploads/' + data.signature_path;
                
                var stElem = document.getElementById('v_status');
                if(data.freeze_status === 'FROZEN') {{
                    stElem.innerHTML = '<b style="color:red;">🔒 FROZEN (' + data.freeze_reason + ')</b>';
                }} else {{
                    stElem.innerHTML = '<b style="color:green;">✅ ACTIVE</b>';
                }}
                box.style.display = 'block';
            }} else {{
                box.style.display = 'none';
            }}
        }});
    }}
    </script>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

@app.route('/maker_receipts')
def maker_receipts():
    if 'role' not in session or session['role'] != 'MAKER':
        return "🚫 Shoora MAKER qofa!", 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT txn_id, ft_reference, txn_type, customer_name, amount, status, timestamp 
        FROM transactions 
        WHERE created_by = ? 
        ORDER BY timestamp DESC
    """, (session['username'],))
    txns = cursor.fetchall()
    conn.close()

    cards_html = ""
    for t in txns:
        badge_cls = "badge-active" if t['status'] == 'APPROVED' else ("badge-danger" if 'REJECTED' in t['status'] else "badge-pending")
        cards_html += f"""
        <div class="item-card">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:12px; font-weight:bold; color:#065f46;">Ref: {t['ft_reference']}</span>
                <span class="badge {badge_cls}">{t['status']}</span>
            </div>
            <div style="font-size:13px; font-weight:bold; margin-top:4px;">{t['txn_type']}: {t['amount']:,.2f} Birr</div>
            <div style="font-size:11px; color:#64748b; margin-top:2px;">Maammila: {t['customer_name']} | {t['timestamp']}</div>
            <div style="text-align:right; margin-top:8px;">
                <a href="/receipt/{t['txn_id']}" target="_blank" class="btn-action btn-purple">🖨️ Nagahee Maxxansi</a>
            </div>
        </div>
        """

    content = f"""
    <h2 style="font-size: 16px; margin-bottom: 12px; color:#065f46;">🧾 Nagaheewwan Kaffaltii (Maker Receipts)</h2>
    {cards_html if cards_html else "<p style='text-align:center; padding:20px; color:#64748b; font-size:12px;'>Nagaheen galmaa'e hin jiru.</p>"}
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

@app.route('/ceo_mudaraba_list')
def ceo_mudaraba_list():
    if 'role' not in session or session['role'] != 'CEO':
        return "🚫 Addatti CEO Qofatu Listii Mudarabaa Ilaaluu Danda'a!", 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT customer_id, full_name, phone, gender, balance, created_at FROM customers WHERE account_type='MUDARABA' AND status='ACTIVE'")
    mudaraba_custs = cursor.fetchall()
    conn.close()

    rows_html = ""
    total_mudaraba_bal = 0.0

    for c in mudaraba_custs:
        bal = c['balance']
        total_mudaraba_bal += bal
        cust_profit = (bal * 0.10) * 0.50
        ceo_profit = (bal * 0.10) * 0.50

        rows_html += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:12px;">
            <td style="padding:8px; font-weight:bold;">{c['customer_id']}</td>
            <td style="padding:8px;">{c['full_name']} ({c['gender']})</td>
            <td style="padding:8px;">{c['phone']}</td>
            <td style="padding:8px; font-weight:bold; color:#065f46;">{bal:,.2f} Birr</td>
            <td style="padding:8px; color:#6b21a8; font-weight:bold;">+{cust_profit:,.2f} Birr</td>
            <td style="padding:8px; color:#047857; font-weight:bold;">+{ceo_profit:,.2f} Birr</td>
        </tr>
        """

    content = f"""
    <div class="card-ceo-profit">
        <div class="net-title">🔒 CEO PRIVATE: LISTII MAAMMILTOOTAA MUDARABA</div>
        <div class="net-amount">{total_mudaraba_bal:,.2f} Birr</div>
        <p style="font-size:11px; opacity:0.9; margin-top:4px;">Kuusaa Waliigala Maammiltoota Mudaraba Investment</p>
    </div>

    <h3 style="font-size:14px; margin-bottom:8px; color:#334155;">📋 Tarree Maammiltoota Mudarabaa (50/50 Profit Split)</h3>
    <div class="box" style="padding:0; overflow-x:auto;">
        <table style="width:100%; border-collapse:collapse; text-align:left;">
            <thead>
                <tr style="background:#f8fafc; font-size:11px; color:#64748b; border-bottom:1px solid #e2e8f0;">
                    <th style="padding:8px;">Acc ID</th>
                    <th style="padding:8px;">Maqaa Guutuu</th>
                    <th style="padding:8px;">Bilbila</th>
                    <th style="padding:8px;">Balance</th>
                    <th style="padding:8px;">Qooda Maammilaa (50%)</th>
                    <th style="padding:8px;">Qooda CEO/Bank (50%)</th>
                </tr>
            </thead>
            <tbody>
                {rows_html if rows_html else '<tr><td colspan="6" style="padding:16px; text-align:center; color:#64748b;">Maammilli Mudarabaa galmaa\'e hin jiru.</td></tr>'}
            </tbody>
        </table>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'role' not in session or session['role'] != 'MAKER':
        return "🚫 Shoora MAKER qofatu maammila galmeessuu danda'a", 403

    msg = None
    if request.method == 'POST':
        full_name = request.form.get('full_name').strip()
        phone = request.form.get('phone').strip()
        gender = request.form.get('gender')
        account_type = request.form.get('account_type')
        initial_balance = max(0.0, float(request.form.get('initial_balance', 0.0)))
        photo_file = request.files.get('photo')
        sig_file = request.files.get('signature')
        nat_id_file = request.files.get('national_id')

        if photo_file and sig_file and allowed_file(photo_file.filename) and allowed_file(sig_file.filename):
            timestamp_str = int(datetime.datetime.now().timestamp())
            
            photo_filename = compress_and_save_image(photo_file, f"face_{timestamp_str}_" + secure_filename(photo_file.filename))
            sig_filename = compress_and_save_image(sig_file, f"sig_{timestamp_str}_" + secure_filename(sig_file.filename))
            
            nat_id_filename = ""
            if nat_id_file and allowed_file(nat_id_file.filename):
                nat_id_filename = compress_and_save_image(nat_id_file, f"nat_{timestamp_str}_" + secure_filename(nat_id_file.filename))

            START_ID = 100099008800
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT MAX(CAST(customer_id AS INTEGER)) FROM customers WHERE customer_id >= '100099008800'")
            max_id = cursor.fetchone()[0]

            cust_id = str(START_ID) if max_id is None or max_id < START_ID else str(max_id + 1)
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute("""
                INSERT INTO customers (customer_id, full_name, phone, gender, account_type, photo_path, signature_path, national_id_path, balance, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_APPROVAL', ?)
            """, (cust_id, full_name, phone, gender, account_type, photo_filename, sig_filename, nat_id_filename, initial_balance, now))

            if initial_balance > 0:
                ft_ref = f"TT{datetime.datetime.now().strftime('%y%j')}{random.randint(10000, 99999)}"
                cursor.execute("""
                    INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name, amount, bank_name, ft_reference, status, created_by, timestamp)
                    VALUES (?, 'DEPOSIT', ?, ?, ?, 'Imana Microfinance Core', ?, 'APPROVED', ?, ?)
                """, (f"TXN-INIT-{timestamp_str}", cust_id, full_name, initial_balance, ft_ref, session['username'], now))

            conn.commit()
            conn.close()
            msg = f"⚡ Maammilli {full_name} ({account_type} / {gender}) dafee galmaa'eera! (T24 Acc: {cust_id})."
            add_notification(f"Galmeen maammila haaraa ({full_name}) raawwatameera.")

    content = f"""
    <div class="box">
        <h2 style="font-size: 16px; margin-bottom: 12px; color:#065f46;">⚡ Galmee Maammilaa Saffisaa (Maker T24)</h2>
        {f"<p style='background:#dcfce7; color:#166534; padding:10px; border-radius:6px; font-size:12px; font-weight:bold; margin-bottom:12px;'>{msg}</p>" if msg else ""}
        <form method="POST" enctype="multipart/form-data">
            <div class="form-group">
                <label>Maqaa Guutuu Maammilaa</label>
                <input type="text" name="full_name" required class="input-field">
            </div>
            <div class="form-group">
                <label>Saala (Sex / Gender)</label>
                <select name="gender" class="input-field" required>
                    <option value="Dhiira">Dhiira (Male)</option>
                    <option value="Dubartii">Dubartii (Female)</option>
                </select>
            </div>
            <div class="form-group">
                <label>Gosa Akkaawuntii (Account Scheme)</label>
                <select name="account_type" class="input-field" required>
                    <option value="WADIA">A, Wadia Savings (Yeroo Gabaabduu / Waadiaa Faaydaa Malee)</option>
                    <option value="MUDARABA">B, Mudaraba Investment (50%, 50% Profit Share)</option>
                </select>
            </div>
            <div class="form-group">
                <label>Lakkoofsa Bilbilaa</label>
                <input type="text" name="phone" required class="input-field">
            </div>
            <div class="form-group">
                <label>Balansii Jalqabaa (Initial Balance in Birr)</label>
                <input type="number" step="0.01" min="0" name="initial_balance" value="0.00" required class="input-field">
            </div>
            <div class="form-group">
                <label>📸 Suuraa Fuula Maammilaa</label>
                <input type="file" name="photo" accept="image/*" required class="input-field">
            </div>
            <div class="form-group">
                <label>✍️ Mallattoo Galmee (Signature)</label>
                <input type="file" name="signature" accept="image/*" required class="input-field">
            </div>
            <div class="form-group">
                <label>🆔 Waraqaa Eenyummaa (National ID / Fayda / Passport)</label>
                <input type="file" name="national_id" accept="image/*,.pdf" class="input-field">
            </div>
            <button type="submit" class="btn-submit">⚡ Dafeen Galmeessi (Create T24 Account)</button>
        </form>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

@app.route('/edit_customer/<cust_id>', methods=['GET', 'POST'])
def edit_customer(cust_id):
    if 'role' not in session or session['role'] != 'MANAGER':
        return "🚫 Shoora MANAGER qofatu odeeffannoo maammilaa edituu danda'a", 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers WHERE customer_id = ?", (cust_id,))
    customer = cursor.fetchone()

    if not customer:
        conn.close()
        return "Maammilli Hin Argamne", 404

    msg = None
    if request.method == 'POST':
        full_name = request.form.get('full_name').strip()
        phone = request.form.get('phone').strip()
        gender = request.form.get('gender')
        account_type = request.form.get('account_type')

        photo_file = request.files.get('photo')
        sig_file = request.files.get('signature')
        nat_id_file = request.files.get('national_id')

        photo_filename = customer['photo_path']
        sig_filename = customer['signature_path']
        nat_id_filename = customer['national_id_path']

        timestamp_str = int(datetime.datetime.now().timestamp())

        if photo_file and photo_file.filename and allowed_file(photo_file.filename):
            photo_filename = compress_and_save_image(photo_file, f"face_edit_{timestamp_str}_" + secure_filename(photo_file.filename))

        if sig_file and sig_file.filename and allowed_file(sig_file.filename):
            sig_filename = compress_and_save_image(sig_file, f"sig_edit_{timestamp_str}_" + secure_filename(sig_file.filename))

        if nat_id_file and nat_id_file.filename and allowed_file(nat_id_file.filename):
            nat_id_filename = compress_and_save_image(nat_id_file, f"nat_edit_{timestamp_str}_" + secure_filename(nat_id_file.filename))

        cursor.execute("""
            UPDATE customers 
            SET full_name = ?, phone = ?, gender = ?, account_type = ?, photo_path = ?, signature_path = ?, national_id_path = ?
            WHERE customer_id = ?
        """, (full_name, phone, gender, account_type, photo_filename, sig_filename, nat_id_filename, cust_id))
        conn.commit()
        
        cursor.execute("SELECT * FROM customers WHERE customer_id = ?", (cust_id,))
        customer = cursor.fetchone()
        msg = f"✅ Odeeffannoon maammilaa ({cust_id}) milkaa'inaan foyya'eera (Edited)!"
        add_notification(f"Manager odeeffannoo maammilaa ({cust_id}) jijjiiree jira.")

    conn.close()
    nat_id_img = f"/uploads/{customer['national_id_path']}" if customer['national_id_path'] else ""

    content = f"""
    <div class="box">
        <h2 style="font-size: 16px; color:#2563eb; margin-bottom: 4px;">✏️ Odeeffannoo Maammilaa Foyyeessi (Edit Customer)</h2>
        <p style="font-size: 11px; color:#64748b; margin-bottom: 14px;">Acc ID: <b>{customer['customer_id']}</b></p>
        
        {f"<p style='background:#dcfce7; color:#166534; padding:10px; border-radius:6px; font-size:12px; font-weight:bold; margin-bottom:12px;'>{msg}</p>" if msg else ""}

        <form method="POST" enctype="multipart/form-data">
            <div class="form-group">
                <label>Maqaa Guutuu Maammilaa</label>
                <input type="text" name="full_name" value="{customer['full_name']}" required class="input-field">
            </div>
            <div class="form-group">
                <label>Lakkoofsa Bilbilaa</label>
                <input type="text" name="phone" value="{customer['phone']}" required class="input-field">
            </div>
            <div class="form-group">
                <label>Saala (Gender)</label>
                <select name="gender" class="input-field">
                    <option value="Dhiira" {'selected' if customer['gender']=='Dhiira' else ''}>Dhiira</option>
                    <option value="Dubartii" {'selected' if customer['gender']=='Dubartii' else ''}>Dubartii</option>
                </select>
            </div>
            <div class="form-group">
                <label>Gosa Akkaawuntii (Account Scheme)</label>
                <select name="account_type" class="input-field">
                    <option value="WADIA" {'selected' if customer['account_type']=='WADIA' else ''}>A, Wadia Savings (Yeroo Gabaabduu / Faaydaa Malee)</option>
                    <option value="MUDARABA" {'selected' if customer['account_type']=='MUDARABA' else ''}>B, Mudaraba Investment (50%, 50% Profit Share)</option>
                </select>
            </div>
            
            <div class="form-group">
                <label>📸 Suuraa Fuulaa Jijjiiri (Optional)</label>
                <input type="file" name="photo" accept="image/*" class="input-field">
                <p style="font-size:10px; color:#64748b;">Suuraa Duraan Jiru: <a href="/uploads/{customer['photo_path']}" target="_blank">Ilaali</a></p>
            </div>
            <div class="form-group">
                <label>✍️ Mallattoo Jijjiiri (Optional)</label>
                <input type="file" name="signature" accept="image/*" class="input-field">
                <p style="font-size:10px; color:#64748b;">Mallattoo Duraan Jiru: <a href="/uploads/{customer['signature_path']}" target="_blank">Ilaali</a></p>
            </div>
            <div class="form-group">
                <label>🆔 National ID / Fayda Jijjiiri (Optional)</label>
                <input type="file" name="national_id" accept="image/*,.pdf" class="input-field">
                <p style="font-size:10px; color:#64748b;">National ID Duraan Jiru: {f'<a href="{nat_id_img}" target="_blank">Ilaali</a>' if nat_id_img else 'Hin Jiru'}</p>
            </div>

            <button type="submit" class="btn-submit" style="background:#2563eb;">💾 Odeeffannoo Foyya'e Save Godhi</button>
        </form>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

@app.route('/islamic_loan', methods=['GET', 'POST'])
def islamic_loan():
    if 'role' not in session or session['role'] not in ['LOAN_OFFICER', 'CEO', 'MANAGER']:
        return "🚫 Shoora Hayyama Qabu Qofatu Kanatti Fayyadama", 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT customer_id, full_name, balance FROM customers WHERE status='ACTIVE'")
    active_customers = cursor.fetchall()

    msg = None
    if request.method == 'POST':
        cust_id = request.form.get('customer_id')
        financing_type = request.form.get('financing_type')
        principal = float(request.form.get('principal_amount', 0))
        profit_rate = float(request.form.get('profit_margin', 0))
        tenure = int(request.form.get('tenure_months', 12))
        notes = request.form.get('agent_notes', '').strip()

        cursor.execute("SELECT full_name FROM customers WHERE customer_id = ?", (cust_id,))
        cust_row = cursor.fetchone()
        cust_name = cust_row['full_name'] if cust_row else "Unknown"

        profit_amount = principal * (profit_rate / 100.0)
        total_repayment = principal + profit_amount
        monthly_installment = total_repayment / tenure if tenure > 0 else total_repayment

        loan_id = f"LN-{financing_type[:3]}-{int(datetime.datetime.now().timestamp())}"
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO islamic_financing (loan_id, customer_id, customer_name, financing_type, principal_amount, profit_margin, total_repayment, tenure_months, monthly_installment, status, agent_notes, created_by, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_MANAGER', ?, ?, ?)
        """, (loan_id, cust_id, cust_name, financing_type, principal, profit_amount, total_repayment, tenure, monthly_installment, notes, session['username'], now))

        conn.commit()
        msg = f"📜 Liqaa Islaamaa {financing_type} ({principal:,.2f} Birr) Maammila {cust_name}-f mijeesseera! Mirkaneessa Manager & CEO eegaa jira."
        add_notification(f"Gaaffii liqaa {financing_type} uumameera ID: {loan_id}")

    cursor.execute("SELECT * FROM islamic_financing ORDER BY timestamp DESC")
    loans_list = cursor.fetchall()
    conn.close()

    options_html = "".join([f'<option value="{c["customer_id"]}">{c["full_name"]} (Acc: {c["customer_id"]})</option>' for c in active_customers])

    loans_html = ""
    for l in loans_list:
        badge_cls = "badge-pending" if 'PENDING' in l['status'] else ("badge-active" if l['status'] == 'APPROVED' else "badge-danger")
        
        approval_actions = ""
        if session['role'] == 'MANAGER' and l['status'] == 'PENDING_MANAGER':
            approval_actions = f"""
            <div style="margin-top:8px;">
                <a href="/approve_loan/manager/{l['loan_id']}" class="btn-action btn-blue">✅ Manager Approve</a>
                <a href="/reject_loan/{l['loan_id']}" class="btn-action btn-red">❌ Reject</a>
            </div>
            """
        elif session['role'] == 'CEO' and l['status'] == 'PENDING_CEO':
            approval_actions = f"""
            <div style="margin-top:8px;">
                <a href="/approve_loan/ceo/{l['loan_id']}" class="btn-action btn-purple">✅ CEO Final Approve</a>
                <a href="/reject_loan/{l['loan_id']}" class="btn-action btn-red">❌ Reject</a>
            </div>
            """

        loans_html += f"""
        <div class="item-card" style="border-left: 4px solid #16a34a;">
            <div style="display:flex; justify-content:space-between;">
                <span style="font-size:12px; font-weight:bold; color:#16a34a;">{l['loan_id']} ({l['financing_type']})</span>
                <span class="badge {badge_cls}">{l['status']}</span>
            </div>
            <div style="font-size:13px; font-weight:bold; margin-top:4px;">Maammila: {l['customer_name']}</div>
            <div style="font-size:11px; color:#475569; margin-top:4px;">
                Kaabitaala: <b>{l['principal_amount']:,.2f} Birr</b> | Dhala/Gabbii: <b>{l['profit_margin']:,.2f} Birr</b><br>
                Waliigala Deebi'u: <b>{l['total_repayment']:,.2f} Birr</b> | Baatiitti: <b>{l['monthly_installment']:,.2f} Birr ({l['tenure_months']} Baatii)</b>
            </div>
            {f'<div style="font-size:10px; color:#64748b; margin-top:4px;">Yaada Analysis: {l["agent_notes"]}</div>' if l['agent_notes'] else ''}
            {approval_actions}
        </div>
        """

    content = f"""
    <div class="box" style="background:#f0fdf4; border-color:#bbf7d0;">
        <h2 style="font-size: 16px; color:#15803d; margin-bottom: 4px;">📜 Mijjeessaa Liqaa Islaamaa (Mudaraba & Murabaha)</h2>
        <p style="font-size: 11px; color:#166534;">Liqaa dhala irraa bilisa ta'e (Interest Free) shallagii fi uumi.</p>
    </div>

    {f"<p style='background:#dcfce7; color:#166534; padding:10px; border-radius:6px; font-size:12px; font-weight:bold; margin-bottom:12px;'>{msg}</p>" if msg else ""}

    <div class="box">
        <form method="POST">
            <div class="form-group">
                <label>Maammila Filadhu</label>
                <select name="customer_id" required class="input-field">
                    {options_html}
                </select>
            </div>
            <div class="form-group">
                <label>Gosa Liqaa Islaamaa (Financing Scheme)</label>
                <select name="financing_type" class="input-field">
                    <option value="MUDARABA">MUDARABA (Shiraakaa Kaabitaalaa & Hojii)</option>
                    <option value="MURABAHA">MURABAHA (Gurgurtaa Gabbii / Cost-Plus Profit)</option>
                </select>
            </div>
            <div class="form-group">
                <label>Hamma Kaabitaala Liqaa (Principal Birr)</label>
                <input type="number" step="0.01" name="principal_amount" placeholder="Fkn: 50000" required class="input-field">
            </div>
            <div class="form-group">
                <label>Dhibbeentaa Gabbii / Bu'aa (Profit Margin %)</label>
                <input type="number" step="0.1" name="profit_margin" placeholder="Fkn: 5" required class="input-field">
            </div>
            <div class="form-group">
                <label>Turee Yeroo Deebii (Months / Baatii)</label>
                <input type="number" name="tenure_months" value="12" required class="input-field">
            </div>
            <div class="form-group">
                <label>Yaada / Qorannoo Liqaa (Analysis Notes)</label>
                <textarea name="agent_notes" rows="2" placeholder="Yaada..." class="input-field"></textarea>
            </div>
            <button type="submit" class="btn-submit" style="background:#16a34a;">📜 Liqaa Islaamaa Shallagi Uumi</button>
        </form>
    </div>

    <h3 style="font-size: 14px; margin-bottom: 8px; color: #334155;">📋 Listii Liqaa Islaamaa Uumamaan</h3>
    {loans_html if loans_html else "<p style='text-align:center; padding:16px; color:#64748b; font-size:12px;'>Liqaan galmaa'e hin jiru.</p>"}
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

@app.route('/approve_loan/<role_type>/<loan_id>')
def approve_loan(role_type, loan_id):
    if 'role' not in session or session['role'] not in ['MANAGER', 'CEO']:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM islamic_financing WHERE loan_id = ?", (loan_id,))
    loan = cursor.fetchone()

    if not loan:
        conn.close()
        return "Liqaan Hin Argamne", 404

    if role_type == 'manager' and session['role'] == 'MANAGER':
        cursor.execute("UPDATE islamic_financing SET status = 'PENDING_CEO', manager_approved = 1 WHERE loan_id = ?", (loan_id,))
        add_notification(f"Manager loan_id {loan_id} approve godheera. CEO approval eegaa jira.")
    elif role_type == 'ceo' and session['role'] == 'CEO':
        cursor.execute("UPDATE islamic_financing SET status = 'APPROVED', ceo_approved = 1 WHERE loan_id = ?", (loan_id,))
        cursor.execute("UPDATE customers SET balance = balance + ? WHERE customer_id = ?", (loan['principal_amount'], loan['customer_id']))
        add_notification(f"CEO loan_id {loan_id} FINAL APPROVED! Maallaqni maammilaaf dhangala'eera.")

    conn.commit()
    conn.close()
    return redirect('/islamic_loan')

@app.route('/reject_loan/<loan_id>')
def reject_loan(loan_id):
    if 'role' not in session or session['role'] not in ['MANAGER', 'CEO']:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE islamic_financing SET status = 'REJECTED' WHERE loan_id = ?", (loan_id,))
    conn.commit()
    conn.close()
    add_notification(f"Gaaffiin liqaa {loan_id} REJECTED ta'ee jira.")
    return redirect('/islamic_loan')

@app.route('/pending')
def pending():
    if 'role' not in session or session['role'] not in ['MANAGER', 'AUDITOR']:
        return "🚫 Hayyama Manager ykn Auditor Qofa!", 403

    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT customer_id, full_name, phone, gender, account_type, photo_path, signature_path, national_id_path FROM customers WHERE status='PENDING_APPROVAL'")
    pending_custs = cursor.fetchall()

    cursor.execute("""
        SELECT 
            t.txn_id, t.txn_type, t.customer_name, t.amount, t.bank_name, t.status,
            c.photo_path, c.signature_path, c.national_id_path, c.phone, t.customer_id, t.ft_reference, t.target_account, t.commission,
            c.freeze_status, c.freeze_reason, c.gender, c.account_type
        FROM transactions t
        LEFT JOIN customers c ON t.customer_id = c.customer_id
        WHERE t.status = 'PENDING_MANAGER'
        ORDER BY t.timestamp DESC
    """)
    pending_txns = cursor.fetchall()
    conn.close()

    cards_html = ""

    if pending_custs:
        cards_html += "<h3 style='font-size:12px; color:#1e40af; margin-bottom:8px;'>👤 Galmee Maammiltoota Eeggamaa Jiran</h3>"
        for c in pending_custs:
            nat_id = f"/uploads/{c['national_id_path']}" if c['national_id_path'] else "#"
            account_badge = "badge-mudaraba" if c['account_type'] == 'MUDARABA' else "badge-wadia"
            cards_html += f"""
            <div class="item-card" style="background:#eff6ff; border-color:#bfdbfe;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                    <span style="font-size:12px; font-weight:bold; color:#1e3a8a;">Acc: {c['customer_id']}</span>
                    <div>
                        <span class="badge {account_badge}">{c['account_type']}</span>
                        <span class="badge badge-pending">PENDING</span>
                    </div>
                </div>
                <div style="font-size:13px; font-weight:bold; margin-bottom:2px;">Maqaa: {c['full_name']} (📞 {c['phone']})</div>
                <div style="font-size:11px; color:#475569; margin-bottom:6px;">Saala: <b>{c['gender']}</b></div>
                <div class="img-grid">
                    <div style="text-align:center;"><img src="/uploads/{c['photo_path']}"><span style="font-size:10px; color:#64748b;">Fuula</span></div>
                    <div style="text-align:center;"><img src="/uploads/{c['signature_path']}"><span style="font-size:10px; color:#1e40af; font-weight:bold;">Mallattoo ✍️</span></div>
                    <div style="text-align:center;"><img src="{nat_id}"><span style="font-size:10px; color:#047857; font-weight:bold;">National ID 🆔</span></div>
                </div>
                <div style="text-align:right; margin-top:8px;">
                    <a href="/approve_cust/{c['customer_id']}" class="btn-action btn-blue">✅ Approve Customer</a>
                </div>
            </div>
            """

    if pending_txns:
        cards_html += "<h3 style='font-size:12px; color:#b45309; margin-top:16px; margin-bottom:8px;'>💵 Kaffaltii Maker Uume - Mirkaneessa Eeggatu</h3>"
        for r in pending_txns:
            freeze_info = f"<span class='badge badge-frozen'>🔒 UGGURAMEERA ({r['freeze_reason']})</span>" if r['freeze_status'] == 'FROZEN' else "<span class='badge badge-active'>✅ Active</span>"
            
            cards_html += f"""
            <div class="item-card">
                <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
                    <span style="font-size:12px; font-weight:bold; color:#065f46;">Ref: {r['ft_reference']}</span>
                    <span class="badge badge-pending">{r['status']}</span>
                </div>
                <div style="font-size:13px; font-weight:bold;">{r['txn_type']}: {r['amount']:,.2f} Birr ({r['bank_name']})</div>
                <div style="font-size:11px; color:#64748b; margin-bottom:8px;">Maammila: <b>{r['customer_name']}</b> ({r['customer_id']})</div>
                
                <div style="margin-bottom:8px;">Status Ugguraa: {freeze_info}</div>

                <div style="display:flex; justify-content:space-between; align-items:center; margin-top:8px;">
                    <button onclick="openModal('{r['customer_name']}', '{r['photo_path']}', '{r['signature_path']}', '{r['national_id_path']}', '{r['freeze_status']}', '{r['freeze_reason']}')" class="btn-action btn-purple">👁️ View Suuraa & Info</button>
                    <div>
                        <a href="/manager_action/approve/{r['txn_id']}" class="btn-action btn-green">✅ Approve</a>
                        <a href="/manager_action/reject/{r['txn_id']}" class="btn-action btn-red">❌ Reject</a>
                    </div>
                </div>
            </div>
            """

    if not cards_html:
        cards_html = "<p style='text-align:center; color:#64748b; padding:20px; font-size:13px;'>✅ Transaction-ni Approval eeggatu hin jiru!</p>"

    content = f"""
    <h2 style="font-size: 16px; margin-bottom: 12px;">📋 Manager / Auditor Approval Dashboard</h2>
    {cards_html}

    <div id="infoModal" class="modal">
        <div class="modal-content">
            <h3 id="modalName" style="font-size:15px; color:#065f46; margin-bottom:10px;"></h3>
            <div id="modalFreeze" style="margin-bottom:10px; font-size:12px;"></div>
            <div class="img-grid">
                <div><p style="font-size:10px; font-weight:bold;">Fuula:</p><img id="modalPhoto" src="" style="width:100%; height:80px; object-fit:cover;"></div>
                <div><p style="font-size:10px; font-weight:bold;">Mallattoo:</p><img id="modalSig" src="" style="width:100%; height:80px; object-fit:cover;"></div>
                <div><p style="font-size:10px; font-weight:bold;">National ID:</p><img id="modalNatId" src="" style="width:100%; height:80px; object-fit:cover;"></div>
            </div>
            <button onclick="closeModal()" class="btn-submit" style="background:#64748b; margin-top:12px;">Cufi (Close)</button>
        </div>
    </div>

    <script>
    function openModal(name, photo, sig, natId, freezeSt, freezeRs) {{
        document.getElementById('modalName').innerText = "Maammila: " + name;
        document.getElementById('modalPhoto').src = "/uploads/" + photo;
        document.getElementById('modalSig').src = "/uploads/" + sig;
        document.getElementById('modalNatId').src = "/uploads/" + natId;
        
        var freezeDiv = document.getElementById('modalFreeze');
        if(freezeSt === 'FROZEN') {{
            freezeDiv.innerHTML = "<p style='color:#dc2626; font-weight:bold; background:#fee2e2; padding:6px; border-radius:4px;'>🔒 UGGURAMEERA! Sababa: " + freezeRs + "</p>";
        }} else {{
            freezeDiv.innerHTML = "<p style='color:#16a34a; font-weight:bold; background:#dcfce7; padding:6px; border-radius:4px;'>✅ Uggura irra hin jiru (Active)</p>";
        }}
        document.getElementById('infoModal').style.display = 'flex';
    }}
    function closeModal() {{
        document.getElementById('infoModal').style.display = 'none';
    }}
    </script>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

@app.route('/approve_cust/<cust_id>')
def approve_cust(cust_id):
    if 'role' not in session or session['role'] not in ['MANAGER', 'AUDITOR']:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE customers SET status = 'ACTIVE' WHERE customer_id = ?", (cust_id,))
    conn.commit()
    conn.close()
    add_notification(f"Customer {cust_id} Manager'n ACTIVE ta'ee jira.")
    return redirect('/pending')

@app.route('/manager_action/<act>/<txn_id>')
def manager_action(act, txn_id):
    if 'role' not in session or session['role'] not in ['MANAGER', 'AUDITOR']:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()

    if act == 'approve':
        cursor.execute("SELECT txn_type, customer_id, target_account, amount, commission, ft_reference FROM transactions WHERE txn_id = ?", (txn_id,))
        row = cursor.fetchone()
        if row:
            txn_type = row['txn_type']
            cust_id = row['customer_id']
            target_acc = row['target_account']
            amount = row['amount']
            commission = row['commission']
            ft_ref = row['ft_reference']

            cursor.execute("SELECT balance, phone, full_name, freeze_status FROM customers WHERE customer_id = ?", (cust_id,))
            cust = cursor.fetchone()
            curr_bal = cust['balance'] if cust else 0.0
            phone = cust['phone'] if cust else ""
            name = cust['full_name'] if cust else ""
            freeze_st = cust['freeze_status'] if cust else "UNFROZEN"

            total_deduction = amount + commission

            if freeze_st == 'FROZEN' and txn_type in ['WITHDRAWAL', 'T24_TRANSFER']:
                cursor.execute("UPDATE transactions SET status = 'REJECTED_CUSTOMER_FROZEN' WHERE txn_id = ?", (txn_id,))
            elif txn_type in ['WITHDRAWAL', 'T24_TRANSFER'] and curr_bal < total_deduction:
                cursor.execute("UPDATE transactions SET status = 'REJECTED_INSUFFICIENT_FUNDS' WHERE txn_id = ?", (txn_id,))
            else:
                if txn_type == 'DEPOSIT':
                    cursor.execute("UPDATE customers SET balance = balance + ? WHERE customer_id = ?", (amount, cust_id))
                elif txn_type == 'WITHDRAWAL':
                    cursor.execute("UPDATE customers SET balance = balance - ? WHERE customer_id = ?", (total_deduction, cust_id))
                elif txn_type == 'T24_TRANSFER':
                    cursor.execute("UPDATE customers SET balance = balance - ? WHERE customer_id = ?", (amount, cust_id))
                    cursor.execute("UPDATE customers SET balance = balance + ? WHERE customer_id = ?", (amount, target_acc))

                cursor.execute("UPDATE transactions SET status = 'APPROVED' WHERE txn_id = ?", (txn_id,))

                msg_cust = f"Kabajamoo {name}, {txn_type} {amount:,.2f} Birr (Ref: {ft_ref}) mirkanaa'ee xumurameera."
                send_sms_alert(phone, msg_cust)
                add_notification(f"Transaction {ft_ref} ({txn_type} {amount:,.2f} Birr) APPROVED ta'ee jira.")

    elif act == 'reject':
        cursor.execute("UPDATE transactions SET status = 'REJECTED' WHERE txn_id = ?", (txn_id,))
        add_notification(f"Transaction {txn_id} REJECTED ta'ee jira.")

    conn.commit()
    conn.close()
    return redirect('/pending')

@app.route('/ceo_blank_form')
def ceo_blank_form():
    if 'role' not in session or session['role'] != 'CEO':
        return "🚫 Hayyama CEO Qofa!", 403

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Formii Risiita Duwwaa - Imana Microfinance</title>
        <style>
            body {{ font-family: sans-serif; padding: 30px; max-width: 750px; margin: 0 auto; border: 2px solid #065f46; border-radius: 8px; }}
        </style>
    </head>
    <body>
        <div style="text-align:center; border-bottom:2px solid #065f46; padding-bottom:10px;">
            <h2 style="color:#065f46; margin:0;">IMANA FREE INTEREST MICROFINANCE</h2>
            <p style="font-size:12px; color:#64748b;">FORMII GALMEE FI KAFFALTII DUWWAA (BLANK FORM)</p>
        </div>

        <div style="margin-top:20px; font-size:13px; line-height:2.2;">
            <p><b>Maqaa Guutuu Maammilaa:</b> ____________________________________________________</p>
            <p><b>Lakkoofsa Akkaawuntii (Acc ID):</b> _____________________________________________</p>
            <p><b>Lakkoofsa Bilbilaa:</b> _________________________ <b>Saala:</b> ________________________</p>
            <p><b>Gosa Akkaawuntii:</b> [ ] WADIA Savings &nbsp;&nbsp;&nbsp;&nbsp; [ ] MUDARABA Investment</p>
            <p><b>Gosa Kaffaltii:</b> [ ] Deposit &nbsp;&nbsp;&nbsp;&nbsp; [ ] Withdrawal &nbsp;&nbsp;&nbsp;&nbsp; [ ] Transfer</p>
            <p><b>Hamma Maallaqaa (Birr):</b> ____________________________________________________</p>
            <p><b>Hamma Maallaqaa Jechaan:</b> __________________________________________________</p>
        </div>

        <div style="margin-top:50px; display:flex; justify-content:space-between; font-size:12px;">
            <div>_____________________<br>Mallattoo Maammilaa</div>
            <div>_____________________<br>Mallattoo Teller / Maker</div>
            <div>_____________________<br>Mirkaneessaa Manager</div>
        </div>

        <div style="margin-top:30px; text-align:center;" class="no-print">
            <button onclick="window.print()" style="background:#065f46; color:white; border:none; padding:10px 20px; font-weight:bold; cursor:pointer; border-radius:6px;">🖨️ Formii Duwwaa Maxxansi</button>
        </div>
    </body>
    </html>
    """

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
