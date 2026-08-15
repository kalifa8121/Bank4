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

def compress_and_save_image(file_storage, target_filename, max_size=(600, 600), quality=60):
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

def get_db_connection(max_retries=10, delay=0.2):
    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=60)
            conn.row_factory = sqlite3.Row
            # Optimized for weak networks & high performance
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
    if 1000 <= amount <= 3000:
        return 50.0
    elif 3001 <= amount <= 5000:
        return 100.0
    elif 5001 <= amount <= 10000:
        return 200.0
    elif 10001 <= amount <= 20000:
        return 300.0
    elif 20001 <= amount <= 50000:
        return 500.0
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

    try:
        cursor.execute("ALTER TABLE customers ADD COLUMN gender TEXT DEFAULT 'Dhiira'")
    except sqlite3.OperationalError: pass

    try:
        cursor.execute("ALTER TABLE customers ADD COLUMN account_type TEXT DEFAULT 'WADIA'")
    except sqlite3.OperationalError: pass

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
        body { background-color: #f8fafc; padding-bottom: 80px; color: #0f172a; }
        
        nav { background: linear-gradient(135deg, #065f46, #047857); color: white; padding: 12px 16px; position: sticky; top: 0; z-index: 50; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
        .nav-top-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        .logo-container { display: flex; align-items: center; gap: 10px; }
        .logo-svg { width: 28px; height: 28px; fill: #fbbf24; }
        nav h1 { font-size: 15px; font-weight: 800; color: #ffffff; }
        .role-badge { background: #0284c7; padding: 3px 8px; border-radius: 4px; font-weight: 600; font-size: 11px; }

        .top-action-bar { display: flex; gap: 8px; overflow-x: auto; padding-top: 4px; border-top: 1px solid rgba(255,255,255,0.2); }
        .top-action-bar a { background: rgba(255,255,255,0.15); color: white; padding: 6px 12px; border-radius: 6px; text-decoration: none; font-size: 11px; font-weight: bold; white-space: nowrap; display: flex; align-items: center; gap: 4px; }
        .top-action-bar a:hover { background: rgba(255,255,255,0.3); }

        .container { max-width: 650px; margin: 0 auto; padding: 16px; }
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
        
        .bottom-nav { position: fixed; bottom: 0; left: 0; right: 0; background: white; border-top: 1px solid #e2e8f0; display: flex; justify-content: space-between; align-items: center; padding: 8px 16px; z-index: 50; }
        .logout-btn-bottom { background: #fee2e2; color: #991b1b; padding: 8px 14px; border-radius: 8px; text-decoration: none; font-size: 12px; font-weight: bold; display: flex; align-items: center; gap: 4px; }
        
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
        <div class="nav-top-header">
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
                </div>
            {% endif %}
        </div>

        {% if session.get('role') %}
        <div class="top-action-bar">
            <a href="/">🏠 Dashboard</a>
            {% if session['role'] == 'MAKER' %}
                <a href="/register">👤 Galmee Maammilaa</a>
                <a href="/transaction">💸 Transaction (Kaffaltii)</a>
                <a href="/maker_receipts">🧾 Nagahee Maxxansi</a>
            {% endif %}
            {% if session['role'] == 'MANAGER' %}
                <a href="/pending">📋 Manager Approval</a>
                <a href="/reversals_list">🔄 Reversals</a>
            {% endif %}
            {% if session['role'] == 'AUDITOR' %}
                <a href="/pending">📋 Auditor View</a>
                <a href="/auditor_reversal_request">⚠️ Reversal Gaafachu</a>
            {% endif %}
            {% if session['role'] in ['LOAN_OFFICER', 'CEO', 'MANAGER'] %}
                <a href="/islamic_loan">📜 Liqaa Islaamaa</a>
            {% endif %}
            {% if session['role'] == 'CEO' %}
                <a href="/reversals_list">🔄 Reversal CEO</a>
                <a href="/ceo_mudaraba_list">🤝 Mudaraba List</a>
                <a href="/manage_users">⚙️ Hojjattoota</a>
            {% endif %}
            <a href="/customers">👥 Listii Maammiltootaa</a>
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
        <span style="font-size:11px; color:#64748b; font-weight:bold;">Imana Microfinance Core</span>
        <a href="/logout" class="logout-btn-bottom">🚪 Logout (Cufi)</a>
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
        """

    auditor_btns = ""
    if role == 'AUDITOR':
        auditor_btns = """
        <a href="/pending" class="btn-card btn-card-auditor"><span class="icon">📋</span><span>View Maammilaa & Approve</span></a>
        <a href="/auditor_reversal_request" class="btn-card btn-card-auditor"><span class="icon">⚠️</span><span>Transaction Reversal Gaafachu</span></a>
        """

    loan_btn = ""
    if role in ['LOAN_OFFICER', 'CEO', 'MANAGER']:
        loan_btn = """
        <a href="/islamic_loan" class="btn-card btn-card-loan"><span class="icon">📜</span><span>Mudaraba & Murabaha Loan</span></a>
        """

    ceo_btn = ""
    ceo_mudaraba_dashboard = ""
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
        ceo_btn = """
        <a href="/ceo_commission" class="btn-card btn-card-ceo"><span class="icon">💰</span><span>Comishina Guyyaa</span></a>
        <a href="/ceo_mudaraba_list" class="btn-card btn-card-ceo"><span class="icon">🤝</span><span>Mudaraba Private List</span></a>
        <a href="/ceo_blank_form" target="_blank" class="btn-card btn-card-ceo"><span class="icon">🖨️</span><span>Formii Duwwaa Maxxansi</span></a>
        <a href="/reversals_list" class="btn-card btn-card-ceo"><span class="icon">🔄</span><span>CEO Reversal Approval</span></a>
        <a href="/manage_users" class="btn-card btn-card-ceo"><span class="icon">⚙️</span><span>Bulchiinsa Hojjattootaa</span></a>
        <a href="/ceo_backup" class="btn-card btn-card-ceo"><span class="icon">💾</span><span>Save / Restore DB</span></a>
        """

    content = f"""
    {ceo_mudaraba_dashboard}

    <div class="card-net">
        <div class="net-title">Waliigala Kaabitaala Baankii (Net Capital)</div>
        <div class="net-amount">{net_cap:,.2f} Birr</div>
        <div class="net-grid">
            <div>📥 Deposit: <b>{deposits:,.2f} Birr</b></div>
            <div>📤 Withdraw/FT: <b>{withdraws:,.2f} Birr</b></div>
        </div>
    </div>

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

@app.route('/api/get_customer/<cust_id>')
def api_get_customer(cust_id):
    if 'role' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT customer_id, full_name, phone, gender, account_type, photo_path, signature_path, national_id_path, balance, freeze_status FROM customers WHERE customer_id = ?", (cust_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return jsonify({
            'success': True,
            'customer_id': row['customer_id'],
            'full_name': row['full_name'],
            'phone': row['phone'],
            'gender': row['gender'],
            'account_type': row['account_type'],
            'photo_path': row['photo_path'],
            'signature_path': row['signature_path'],
            'national_id_path': row['national_id_path'],
            'balance': row['balance'],
            'freeze_status': row['freeze_status']
        })
    return jsonify({'success': False, 'message': 'Maammilli hin argamne'})

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
    created_txn_id = None

    if request.method == 'POST':
        txn_type = request.form.get('txn_type')
        cust_id = request.form.get('customer_id')
        target_acc = request.form.get('target_account', '').strip()
        amount1 = float(request.form.get('amount', 0.0))
        amount2 = float(request.form.get('amount_confirm', 0.0))
        bank_name = request.form.get('bank_name', 'Imana Microfinance Core')

        if amount1 != amount2:
            msg = "❌ Haammi maallaqaa bakka lamatti barreesitan walsimachuun itti jira!"
            msg_type = "red"
        else:
            amount = amount1
            cursor.execute("SELECT full_name, balance, freeze_status FROM customers WHERE customer_id = ?", (cust_id,))
            cust = cursor.fetchone()

            if not cust:
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
                    random_num = random.randint(10000, 99999)
                    date_prefix = datetime.datetime.now().strftime('%y%j')
                    
                    # Random Transaction IDs with specific prefixes
                    if txn_type == 'T24_TRANSFER':
                        ft_ref = f"FT{date_prefix}{random_num}"
                    elif txn_type == 'DEPOSIT':
                        ft_ref = f"DEPTT{date_prefix}{random_num}"
                    elif txn_type == 'WITHDRAWAL':
                        ft_ref = f"WITHT{date_prefix}{random_num}"
                    else:
                        ft_ref = f"TXN{date_prefix}{random_num}"

                    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    txn_id = f"TXN-{timestamp_str}"
                    created_txn_id = txn_id

                    cursor.execute("""
                        INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name, target_account, amount, commission, bank_name, ft_reference, status, created_by, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_MANAGER', ?, ?)
                    """, (txn_id, txn_type, cust_id, cust['full_name'], target_acc, amount, commission, bank_name, ft_ref, session['username'], now))

                    conn.commit()
                    msg = f"✅ Transaction ({txn_type}) {amount:,.2f} Birr galmaa'eera (Ref: {ft_ref}). Manager Approve eegaa jira!"
                    add_notification(f"Maker transaction haaraa uumeera: {ft_ref} ({txn_type})")

    conn.close()

    cust_options = "".join([f'<option value="{c["customer_id"]}">{c["full_name"]} - {c["customer_id"]}</option>' for c in customers])

    preview_receipt_btn = ""
    if created_txn_id:
        preview_receipt_btn = f"""
        <div style="margin-top:16px; padding:12px; background:#f0fdf4; border:1px solid #bbf7d0; border-radius:8px; text-align:center;">
            <p style="color:#15803d; font-weight:bold; font-size:12px; margin-bottom:8px;">🧾 Transaction Galmeessite Maxxansi / Preview Godhi</p>
            <a href="/receipt/{created_txn_id}" target="_blank" class="btn-action btn-purple">🖨️ Nagahee Maxxansi (Print Receipt)</a>
        </div>
        """

    content = f"""
    <div class="box">
        <h2 style="font-size: 16px; color:#065f46; margin-bottom: 12px;">💸 Transaction Raawwadhu (Maker T24)</h2>
        
        {f"<p style='background:{'#dcfce7' if msg_type=='green' else '#fee2e2'}; color:{'#166534' if msg_type=='green' else '#991b1b'}; padding:10px; border-radius:6px; font-size:12px; font-weight:bold; margin-bottom:12px;'>{msg}</p>" if msg else ""}

        <form method="POST" id="txnForm">
            <div class="form-group">
                <label>Gosa Kaffaltii (Transaction Type)</label>
                <select name="txn_type" id="txn_type" class="input-field" onchange="toggleTargetAcc()">
                    <option value="DEPOSIT">📥 Deposit (Galii Maallaqaa - DEPTT)</option>
                    <option value="WITHDRAWAL">📤 Withdrawal (Baasii Maallaqaa - WITHT)</option>
                    <option value="T24_TRANSFER">🔄 T24 Account Transfer (Akaawuntii irraa Akaawuntiitti - FT)</option>
                </select>
            </div>

            <div class="form-group">
                <label>Maammila Filadhu (Source Account)</label>
                <div style="display:flex; gap:8px;">
                    <select name="customer_id" id="customer_id" required class="input-field">
                        <option value="">-- Maammila Filadhu --</option>
                        {cust_options}
                    </select>
                    <button type="button" onclick="verifyCustomer()" class="btn-action btn-purple" style="white-space:nowrap;">🔍 View Info & ID</button>
                </div>
            </div>

            <div class="form-group" id="target_acc_group" style="display:none;">
                <label>Account ID Nama Fudhatuu (Target Account ID)</label>
                <div style="display:flex; gap:8px;">
                    <input type="text" name="target_account" id="target_account" placeholder="Fkn: 100099008801" class="input-field">
                    <button type="button" onclick="verifyTargetCustomer()" class="btn-action btn-blue" style="white-space:nowrap;">Mirkaneessi ID</button>
                </div>
                <p id="target_name_display" style="font-size:12px; font-weight:bold; color:#047857; margin-top:4px;"></p>
            </div>

            <div class="form-group">
                <label>1. Hamma Maallaqaa (Amount in Birr)</label>
                <input type="number" step="0.01" name="amount" id="amount" placeholder="0.00" required class="input-field" onkeyup="calculateCommission(); updatePreview();">
            </div>

            <div class="form-group">
                <label>2. Hamma Maallaqaa Mirkaneessi (Confirm Amount in Birr)</label>
                <input type="number" step="0.01" name="amount_confirm" id="amount_confirm" placeholder="0.00 Irra deebi'ii galchi" required class="input-field" onkeyup="updatePreview();">
                <span id="amount_match_msg" style="font-size:11px; font-weight:bold;"></span>
            </div>

            <div class="form-group">
                <label>Moggaasa Baankii / Note</label>
                <input type="text" name="bank_name" value="Imana Microfinance Core" class="input-field">
            </div>

            <div style="background:#f8fafc; border:1px dashed #cbd5e1; padding:12px; border-radius:8px; margin-bottom:12px; font-size:12px;">
                <h4 style="color:#065f46; margin-bottom:4px;">🧾 Nagahee Preview (Raaggaa Kaffaltii)</h4>
                <p>Comishina Madaalawaa: <b id="comm_view" style="color:#2563eb;">0.00 Birr</b></p>
                <p>Waliigala Barbaadamu: <b id="total_req_view" style="color:#dc2626;">0.00 Birr</b></p>
            </div>

            <button type="submit" class="btn-submit">⚡ Transaction Galmeessi (Send to Manager)</button>
        </form>

        {preview_receipt_btn}
    </div>

    <div id="custModal" class="modal">
        <div class="modal-content">
            <h3 style="font-size:15px; color:#065f46; margin-bottom:8px;">👤 Odeeffannoo Maammilaa</h3>
            <div id="custModalBody" style="font-size:12px;"></div>
            <button onclick="closeCustModal()" class="btn-submit" style="background:#64748b; margin-top:12px;">Cufi (Close)</button>
        </div>
    </div>

    <script>
    function toggleTargetAcc() {
        var type = document.getElementById('txn_type').value;
        var group = document.getElementById('target_acc_group');
        group.style.display = (type === 'T24_TRANSFER') ? 'block' : 'none';
        calculateCommission();
    }

    function calculateCommission() {
        var type = document.getElementById('txn_type').value;
        var amt = parseFloat(document.getElementById('amount').value) || 0;
        var comm = 0;

        if (type === 'WITHDRAWAL') {
            if (amt >= 1000 && amt <= 3000) comm = 50;
            else if (amt >= 3001 && amt <= 5000) comm = 100;
            else if (amt >= 5001 && amt <= 10000) comm = 200;
            else if (amt >= 10001 && amt <= 20000) comm = 300;
            else if (amt >= 20001 && amt <= 50000) comm = 500;
        }

        document.getElementById('comm_view').innerText = comm.toFixed(2) + " Birr";
        document.getElementById('total_req_view').innerText = (amt + comm).toFixed(2) + " Birr";
    }

    function updatePreview() {
        var a1 = document.getElementById('amount').value;
        var a2 = document.getElementById('amount_confirm').value;
        var msg = document.getElementById('amount_match_msg');

        if (a2.length > 0) {
            if (a1 === a2) {
                msg.style.color = "#16a34a";
                msg.innerText = "✅ Hamma maallaqaa walsimata!";
            } else {
                msg.style.color = "#dc2626";
                msg.innerText = "❌ Hamma maallaqaa walisiggeera! Irra deebi'ii mirkaneessi.";
            }
        } else {
            msg.innerText = "";
        }
    }

    function verifyCustomer() {
        var custId = document.getElementById('customer_id').value;
        if (!custId) { alert("Mee jalqaba maammila filadhu!"); return; }
        
        fetch('/api/get_customer/' + custId)
            .then(res => res.json())
            .then(data => {
                if(data.success) {
                    var html = "<p><b>Maqaa:</b> " + data.full_name + "</p>";
                    html += "<p><b>Account ID:</b> " + data.customer_id + "</p>";
                    html += "<p><b>Balansii Current:</b> " + data.balance.toLocaleString() + " Birr</p>";
                    html += "<p><b>Status Ugguraa:</b> " + data.freeze_status + "</p>";
                    html += "<div class='img-grid'>";
                    html += "<div><p style='font-size:10px;'>Fuula:</p><img src='/uploads/" + data.photo_path + "'></div>";
                    html += "<div><p style='font-size:10px;'>Mallattoo:</p><img src='/uploads/" + data.signature_path + "'></div>";
                    html += "<div><p style='font-size:10px;'>National ID:</p><img src='/uploads/" + (data.national_id_path || '') + "'></div>";
                    html += "</div>";
                    document.getElementById('custModalBody').innerHTML = html;
                    document.getElementById('custModal').style.display = 'flex';
                } else {
                    alert(data.message);
                }
            });
    }

    function verifyTargetCustomer() {
        var custId = document.getElementById('target_account').value;
        var display = document.getElementById('target_name_display');
        if (!custId) { alert("Mee target Account ID galchi!"); return; }
        fetch('/api/get_customer/' + custId)
            .then(res => res.json())
            .then(data => {
                if(data.success) {
                    display.innerText = "✅ Target Account: " + data.full_name + " (ID: " + data.customer_id + ")";
                } else {
                    display.innerText = "❌ Target Account ID hin argamne!";
                    alert("❌ Target Account hin argamne!");
                }
            });
    }

    function closeCustModal() {
        document.getElementById('custModal').style.display = 'none';
    }
    </script>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

@app.route('/receipt/<txn_id>')
def print_receipt(txn_id):
    if 'role' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions WHERE txn_id = ?", (txn_id,))
    txn = cursor.fetchone()
    conn.close()

    if not txn:
        return "Receipt Hin Argamne", 404

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Nagahee Kaffaltii - {txn['ft_reference']}</title>
        <style>
            body {{ font-family: sans-serif; padding: 20px; max-width: 400px; margin: 0 auto; border: 1px dashed #000; font-size: 13px; }}
            .center {{ text-align: center; }}
            .line {{ border-bottom: 1px dashed #000; margin: 10px 0; }}
            .row {{ display: flex; justify-content: space-between; margin-bottom: 5px; }}
            .btn-print {{ background: #065f46; color: white; border: none; padding: 10px; width: 100%; font-weight: bold; cursor: pointer; border-radius: 6px; margin-top: 15px; }}
            @media print {{ .btn-print {{ display: none; }} body {{ border: none; }} }}
        </style>
    </head>
    <body>
        <div class="center">
            <h2>IMANA MICROFINANCE</h2>
            <p>Nagahee Transaction Kaffaltii</p>
        </div>
        <div class="line"></div>
        <div class="row"><span>Reference:</span> <b>{txn['ft_reference']}</b></div>
        <div class="row"><span>Guyyaa:</span> <span>{txn['timestamp']}</span></div>
        <div class="row"><span>Transaction Type:</span> <b>{txn['txn_type']}</b></div>
        <div class="row"><span>Maammila:</span> <span>{txn['customer_name']}</span></div>
        <div class="row"><span>Account ID:</span> <span>{txn['customer_id']}</span></div>
        {f'<div class="row"><span>Target Account:</span> <span>{txn["target_account"]}</span></div>' if txn['target_account'] else ''}
        <div class="line"></div>
        <div class="row"><span>Hamma Maallaqaa:</span> <b>{txn['amount']:,.2f} Birr</b></div>
        <div class="row"><span>Comishina:</span> <span>{txn['commission']:,.2f} Birr</span></div>
        <div class="row"><span>Status:</span> <b>{txn['status']}</b></div>
        <div class="line"></div>
        <div class="row"><span>Maker/Teller:</span> <span>{txn['created_by']}</span></div>
        <div class="center" style="margin-top:15px; font-size:11px;">
            <p>Galatoomaa! / Thank you!</p>
        </div>
        <button onclick="window.print()" class="btn-print">🖨️ Maxxansi (Print)</button>
    </body>
    </html>
    """

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
                ft_ref = f"DEPTT{datetime.datetime.now().strftime('%y%j')}{random.randint(10000, 99999)}"
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

@app.route('/customers')
def customers():
    if 'role' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers ORDER BY created_at DESC")
    custs = cursor.fetchall()
    conn.close()

    rows_html = ""
    for c in custs:
        status_badge = f"<span class='badge badge-active'>{c['status']}</span>" if c['status'] == 'ACTIVE' else f"<span class='badge badge-pending'>{c['status']}</span>"
        freeze_badge = f"<span class='badge badge-frozen'>FROZEN</span>" if c['freeze_status'] == 'FROZEN' else ""
        account_badge = "badge-mudaraba" if c['account_type'] == 'MUDARABA' else "badge-wadia"

        edit_btn = f'<a href="/edit_customer/{c["customer_id"]}" class="btn-action btn-blue">✏️ Edit</a>' if session['role'] == 'MANAGER' else ''
        
        freeze_form = ""
        if session['role'] == 'CEO':
            if c['freeze_status'] == 'FROZEN':
                freeze_form = f"""
                <form method="POST" action="/freeze_customer/{c['customer_id']}" style="display:inline;">
                    <input type="hidden" name="action_type" value="unfreeze">
                    <button type="submit" class="btn-action btn-green">🔓 Unfreeze</button>
                </form>
                """
            else:
                freeze_form = f"""
                <button onclick="openFreezeModal('{c['customer_id']}')" class="btn-action btn-orange">🔒 Freeze</button>
                """

        rows_html += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:12px;">
            <td style="padding:8px; font-weight:bold;">{c['customer_id']}</td>
            <td style="padding:8px;">{c['full_name']} <br><span class="badge {account_badge}">{c['account_type']}</span> {freeze_badge}</td>
            <td style="padding:8px;">{c['phone']}</td>
            <td style="padding:8px; font-weight:bold; color:#065f46;">{c['balance']:,.2f} Birr</td>
            <td style="padding:8px;">{status_badge}</td>
            <td style="padding:8px; text-align:right;">
                <a href="/statement/{c['customer_id']}" class="btn-action btn-purple">📜 Statement</a>
                {edit_btn}
                {freeze_form}
            </td>
        </tr>
        """

    content = f"""
    <div class="box">
        <h2 style="font-size: 16px; color:#065f46; margin-bottom: 12px;">👥 Listii Maammiltootaa Guutuu</h2>
        <div style="overflow-x:auto;">
            <table style="width:100%; border-collapse:collapse; text-align:left;">
                <thead>
                    <tr style="background:#f8fafc; font-size:11px; color:#64748b; border-bottom:1px solid #e2e8f0;">
                        <th style="padding:8px;">Account ID</th>
                        <th style="padding:8px;">Maqaa Guutuu</th>
                        <th style="padding:8px;">Bilbila</th>
                        <th style="padding:8px;">Balance</th>
                        <th style="padding:8px;">Status</th>
                        <th style="padding:8px; text-align:right;">Tarkaanfii</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html if rows_html else '<tr><td colspan="6" style="padding:16px; text-align:center; color:#64748b;">Maammilli galmaa\'e hin jiru.</td></tr>'}
                </tbody>
            </table>
        </div>
    </div>

    <div id="freezeModal" class="modal">
        <div class="modal-content">
            <h3 style="font-size:15px; color:#c2410c; margin-bottom:8px;">🔒 Akkaawuntii Ugguri (Freeze)</h3>
            <form id="freezeForm" method="POST" action="">
                <input type="hidden" name="action_type" value="freeze">
                <div class="form-group">
                    <label>Sababa Ugguraa (Reason)</label>
                    <textarea name="freeze_reason" required class="input-field" placeholder="Sababa..."></textarea>
                </div>
                <button type="submit" class="btn-submit" style="background:#ea580c;">🔒 Ugguri</button>
            </form>
            <button onclick="closeFreezeModal()" class="btn-submit" style="background:#64748b; margin-top:8px;">Cufi</button>
        </div>
    </div>

    <script>
    function openFreezeModal(custId) {{
        document.getElementById('freezeForm').action = "/freeze_customer/" + custId;
        document.getElementById('freezeModal').style.display = 'flex';
    }}
    function closeFreezeModal() {{
        document.getElementById('freezeModal').style.display = 'none';
    }}
    </script>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

@app.route('/statement/<cust_id>')
def statement(cust_id):
    if 'role' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers WHERE customer_id = ?", (cust_id,))
    c = cursor.fetchone()

    if not c:
        conn.close()
        return "Maammilli Hin Argamne", 404

    cursor.execute("""
        SELECT txn_id, txn_type, amount, commission, ft_reference, status, created_by, timestamp
        FROM transactions
        WHERE customer_id = ? OR target_account = ?
        ORDER BY timestamp DESC
    """, (cust_id, cust_id))
    txns = cursor.fetchall()
    conn.close()

    rows_html = ""
    for t in txns:
        badge_cls = "badge-active" if t['status'] == 'APPROVED' else ("badge-danger" if 'REJECTED' in t['status'] else "badge-pending")
        rows_html += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:11px;">
            <td style="padding:8px;">{t['timestamp']}</td>
            <td style="padding:8px; font-weight:bold;">{t['ft_reference']}</td>
            <td style="padding:8px;">{t['txn_type']}</td>
            <td style="padding:8px; font-weight:bold;">{t['amount']:,.2f}</td>
            <td style="padding:8px;">{t['commission']:,.2f}</td>
            <td style="padding:8px;"><span class="badge {badge_cls}">{t['status']}</span></td>
        </tr>
        """

    content = f"""
    <div class="box">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <div>
                <h2 style="font-size: 16px; color:#065f46; margin-bottom:4px;">📜 Account Statement</h2>
                <p style="font-size: 12px; font-weight:bold;">{c['full_name']} (Acc: {c['customer_id']})</p>
                <p style="font-size: 11px; color:#64748b;">Saala: <b>{c['gender']}</b> | Scheme: <b>{c['account_type']}</b></p>
                <p style="font-size: 11px; color:#64748b;">Haafe (Current Balance): <b style="color:#065f46;">{c['balance']:,.2f} Birr</b></p>
            </div>
            <button onclick="window.print()" class="btn-action btn-purple no-print">🖨️ Print Statement</button>
        </div>
    </div>

    <div class="box" style="padding:0; overflow-x:auto;">
        <table style="width:100%; border-collapse:collapse; text-align:left;">
            <thead>
                <tr style="background:#f8fafc; font-size:11px; color:#64748b; border-bottom:1px solid #e2e8f0;">
                    <th style="padding:8px;">Guyyaa</th>
                    <th style="padding:8px;">Ref</th>
                    <th style="padding:8px;">Type</th>
                    <th style="padding:8px;">Hamma</th>
                    <th style="padding:8px;">Comm</th>
                    <th style="padding:8px;">Status</th>
                </tr>
            </thead>
            <tbody>
                {rows_html if rows_html else '<tr><td colspan="6" style="padding:16px; text-align:center; color:#64748b;">Transaction-ni socho\'e hin jiru.</td></tr>'}
            </tbody>
        </table>
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
            .header {{ text-align: center; border-bottom: 2px solid #065f46; padding-bottom: 12px; margin-bottom: 20px; }}
            .row {{ display: flex; justify-content: space-between; margin-bottom: 20px; font-size: 14px; }}
            .field-line {{ border-bottom: 1px dotted #000; width: 60%; display: inline-block; }}
            .box-area {{ border: 1px solid #000; height: 100px; margin-top: 10px; border-radius: 4px; padding: 10px; font-size: 12px; color: #888; }}
            .btn-print {{ background: #065f46; color: white; border: none; padding: 12px; width: 100%; font-size: 16px; font-weight: bold; cursor: pointer; border-radius: 6px; margin-top: 30px; }}
            @media print {{ .btn-print {{ display: none; }} body {{ border: none; }} }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1 style="color:#065f46; margin:0;">IMANA FREE INTEREST MICROFINANCE</h1>
            <h3>FOORMII GALMEESSA MAAMMILAAGAA FI BAASII-GALII (MAKER FORM)</h3>
        </div>

        <div style="font-size:14px; line-height: 2.2;">
            <div><b>Guyyaa:</b> <span class="field-line"></span></div>
            <div><b>Gosa Foormii:</b> [  ] Galmee Maammilaa &nbsp;&nbsp;&nbsp; [  ] Deposit (Galii) &nbsp;&nbsp;&nbsp; [  ] Withdrawal (Baasii)</div>
            <div><b>Maqaa Guutuu Maammilaa:</b> <span class="field-line"></span></div>
            <div><b>Lakkoofsa Akkaawuntii (T24 ID):</b> <span class="field-line"></span></div>
            <div><b>Lakkoofsa Bilbilaa:</b> <span class="field-line"></span></div>
            <div><b>Hamma Qarshii (Jechaan):</b> <span class="field-line"></span></div>
            <div><b>Hamma Qarshii (Lakkoofsaan):</b> <span class="field-line"></span> Birr</div>
            <div><b>Yaada / Sababa Kaffaltii:</b></div>
            <div class="box-area">Yaada maammilli barreesse bakka kana...</div>
        </div>

        <div style="margin-top: 50px; display: flex; justify-content: space-between; font-size: 13px;">
            <div>________________________<br>Mallattoo Maammilaa</div>
            <div>________________________<br>Mallattoo Maker (Hojjataa)</div>
            <div>________________________<br>Mallattoo Manager</div>
        </div>

        <button onclick="window.print()" class="btn-print">🖨️ Formii Duwwaa Maxxansi (Print Blank Form)</button>
    </body>
    </html>
    """

@app.route('/freeze_customer/<cust_id>', methods=['POST'])
def freeze_customer(cust_id):
    if 'role' not in session or session['role'] != 'CEO':
        return redirect('/login')

    action_type = request.form.get('action_type')
    reason = request.form.get('freeze_reason', '').strip()

    conn = get_db_connection()
    cursor = conn.cursor()

    if action_type == 'freeze':
        cursor.execute("UPDATE customers SET freeze_status = 'FROZEN', freeze_reason = ? WHERE customer_id = ?", (reason, cust_id))
    elif action_type == 'unfreeze':
        cursor.execute("UPDATE customers SET freeze_status = 'UNFROZEN', freeze_reason = '' WHERE customer_id = ?", (reason, cust_id))

    conn.commit()
    conn.close()
    return redirect('/customers')

@app.route('/auditor_reversal_request', methods=['GET', 'POST'])
def auditor_reversal_request():
    if 'role' not in session or session['role'] != 'AUDITOR':
        return "🚫 Hayyama Auditor Qofa!", 403

    msg = None
    if request.method == 'POST':
        txn_id = request.form.get('txn_id').strip()
        reason = request.form.get('reason').strip()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT txn_id, status FROM transactions WHERE txn_id = ? OR ft_reference = ?", (txn_id, txn_id))
        txn = cursor.fetchone()

        if not txn:
            msg = "❌ Transaction-ni koodii/FT reference kanaan argame hin jiru!"
        elif txn['status'] != 'APPROVED':
            msg = f"❌ Transaction-ni sun status '{txn['status']}' irratti argama. Status APPROVED qofatu reversal ta'uu danda'a."
        else:
            rev_id = f"REV-{int(datetime.datetime.now().timestamp())}"
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                INSERT INTO reversals (reversal_id, txn_id, reason, requested_by, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (rev_id, txn['txn_id'], reason, session['username'], now))
            conn.commit()
            msg = "✅ Gaaffiin Reversal sababa gahaa waliin ergameera! Manager fi CEO approval eegaa jira."
            add_notification(f"Reversal gaafatameera txn_id: {txn['txn_id']} auditor: {session['username']}")
        conn.close()

    content = f"""
    <div class="box">
        <h2 style="font-size: 16px; color:#c2410c; margin-bottom: 4px;">⚠️ Transaction Reversal Gaafachu (Auditor)</h2>
        <p style="font-size: 11px; color:#64748b; margin-bottom: 14px;">Transaction dogoggoraan raawwatame Reversal sababa gahaa waliin galchi.</p>
        
        {f"<p style='background:#fef3c7; color:#92400e; padding:10px; border-radius:6px; font-size:12px; font-weight:bold; margin-bottom:12px;'>{msg}</p>" if msg else ""}

        <form method="POST">
            <div class="form-group">
                <label>Txn ID ykn FT Reference</label>
                <input type="text" name="txn_id" placeholder="Fkn: FT2621412345" required class="input-field">
            </div>
            <div class="form-group">
                <label>Sababa Gahaa (Reversal Reason)</label>
                <textarea name="reason" rows="3" placeholder="Sababa reversal..." required class="input-field"></textarea>
            </div>
            <button type="submit" class="btn-submit" style="background:#ea580c;">🔄 Gaaffii Reversal Ergi</button>
        </form>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

@app.route('/reversals_list')
def reversals_list():
    if 'role' not in session or session['role'] not in ['MANAGER', 'CEO']:
        return "🚫 Hayyama Manager ykn CEO Qofa!", 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.reversal_id, r.txn_id, r.reason, r.requested_by, r.manager_approved, r.ceo_approved, r.status, r.timestamp,
               t.ft_reference, t.txn_type, t.amount, t.customer_name, t.customer_id
        FROM reversals r
        JOIN transactions t ON r.txn_id = t.txn_id
        ORDER BY r.timestamp DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    cards_html = ""
    for r in rows:
        mgr_st = "✅ Approved" if r['manager_approved'] else "⏳ Pending"
        ceo_st = "✅ Approved" if r['ceo_approved'] else "⏳ Pending"

        action_btn = ""
        if session['role'] == 'MANAGER' and not r['manager_approved'] and r['status'] == 'PENDING_APPROVAL':
            action_btn = f'<a href="/approve_reversal/manager/{r["reversal_id"]}" class="btn-action btn-blue">✅ Manager Approve</a>'
        elif session['role'] == 'CEO' and not r['ceo_approved'] and r['status'] == 'PENDING_APPROVAL':
            action_btn = f'<a href="/approve_reversal/ceo/{r["reversal_id"]}" class="btn-action btn-purple">✅ CEO Approve & Execute</a>'

        cards_html += f"""
        <div class="item-card" style="border-left: 4px solid #ea580c;">
            <div style="display:flex; justify-content:space-between;">
                <span style="font-size:12px; font-weight:bold; color:#ea580c;">Ref: {r['ft_reference']}</span>
                <span class="badge badge-pending">{r['status']}</span>
            </div>
            <div style="font-size:13px; font-weight:bold; margin-top:4px;">{r['txn_type']}: {r['amount']:,.2f} Birr (Maammila: {r['customer_name']})</div>
            <div style="font-size:11px; color:#64748b; margin-top:4px;"><b>Sababa Reversal:</b> {r['reason']}</div>
            <div style="font-size:11px; color:#475569; margin-top:4px;">By: {r['requested_by']} | Mgr: <b>{mgr_st}</b> | CEO: <b>{ceo_st}</b></div>
            <div style="text-align:right; margin-top:8px;">
                {action_btn}
            </div>
        </div>
        """

    content = f"""
    <h2 style="font-size: 16px; margin-bottom: 12px; color:#c2410c;">🔄 Gaaffiiwwan Reversal Transactions</h2>
    {cards_html if cards_html else "<p style='text-align:center; padding:20px; font-size:12px; color:#64748b;'>Gaaffiin Reversal eeggatu hin jiru.</p>"}
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

@app.route('/approve_reversal/<role_type>/<rev_id>')
def approve_reversal(role_type, rev_id):
    if 'role' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reversals WHERE reversal_id = ?", (rev_id,))
    rev = cursor.fetchone()

    if not rev:
        conn.close()
        return "Reversal Hin Argamne", 404

    mgr_appr = rev['manager_approved']
    ceo_appr = rev['ceo_approved']

    if role_type == 'manager' and session['role'] == 'MANAGER':
        mgr_appr = 1
    elif role_type == 'ceo' and session['role'] == 'CEO':
        ceo_appr = 1

    if mgr_appr == 1 and ceo_appr == 1:
        cursor.execute("SELECT * FROM transactions WHERE txn_id = ?", (rev['txn_id'],))
        txn = cursor.fetchone()
        
        if txn and txn['status'] == 'APPROVED':
            amount = txn['amount']
            cust_id = txn['customer_id']
            target_acc = txn['target_account']
            txn_type = txn['txn_type']
            comm = txn['commission']

            if txn_type == 'DEPOSIT':
                cursor.execute("UPDATE customers SET balance = MAX(0.0, balance - ?) WHERE customer_id = ?", (amount, cust_id))
            elif txn_type == 'WITHDRAWAL':
                cursor.execute("UPDATE customers SET balance = balance + ? WHERE customer_id = ?", (amount + comm, cust_id))
            elif txn_type == 'T24_TRANSFER':
                cursor.execute("UPDATE customers SET balance = balance + ? WHERE customer_id = ?", (amount, cust_id))
                cursor.execute("UPDATE customers SET balance = MAX(0.0, balance - ?) WHERE customer_id = ?", (amount, target_acc))

            cursor.execute("UPDATE transactions SET status = 'REVERSED' WHERE txn_id = ?", (rev['txn_id'],))
            cursor.execute("UPDATE reversals SET status = 'COMPLETED_REVERSED', manager_approved = 1, ceo_approved = 1 WHERE reversal_id = ?", (rev_id,))
            add_notification(f"Reversal txn_id: {rev['txn_id']} guutumaatti REVERSED ta'ee jira.")
    else:
        cursor.execute("UPDATE reversals SET manager_approved = ?, ceo_approved = ? WHERE reversal_id = ?", (mgr_appr, ceo_appr, rev_id))

    conn.commit()
    conn.close()
    return redirect('/reversals_list')

@app.route('/ceo_commission')
def ceo_commission():
    if 'role' not in session or session['role'] != 'CEO':
        return "🚫 Hayyama CEO Qofa!", 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT txn_id, ft_reference, txn_type, amount, commission, created_by, timestamp 
        FROM transactions 
        WHERE status='APPROVED' AND commission > 0 
        ORDER BY timestamp DESC
    """)
    rows = cursor.fetchall()
    
    cursor.execute("SELECT SUM(commission) FROM transactions WHERE status='APPROVED'")
    total_comm = cursor.fetchone()[0] or 0.0
    conn.close()

    rows_html = ""
    for r in rows:
        rows_html += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:12px;">
            <td style="padding:8px;">{r['timestamp']}</td>
            <td style="padding:8px; font-weight:bold;">{r['ft_reference']}</td>
            <td style="padding:8px;">{r['created_by']}</td>
            <td style="padding:8px;">{r['amount']:,.2f} Birr</td>
            <td style="padding:8px; font-weight:bold; color:#065f46;">+{r['commission']:,.2f} Birr</td>
        </tr>
        """

    content = f"""
    <div class="card-ceo-profit">
        <div class="net-title">💰 Waliigala Comishina Galii Baankii</div>
        <div class="net-amount">{total_comm:,.2f} Birr</div>
    </div>

    <h3 style="font-size: 14px; margin-bottom: 8px; color: #334155;">📋 Tarree Comishina Galmaa'ee</h3>
    <div class="box" style="padding:0; overflow-x:auto;">
        <table style="width:100%; border-collapse:collapse; text-align:left;">
            <thead>
                <tr style="background:#f8fafc; font-size:11px; color:#64748b; border-bottom:1px solid #e2e8f0;">
                    <th style="padding:8px;">Guyyaa</th>
                    <th style="padding:8px;">Ref</th>
                    <th style="padding:8px;">Maker</th>
                    <th style="padding:8px;">Hamma Txn</th>
                    <th style="padding:8px;">Comishina</th>
                </tr>
            </thead>
            <tbody>
                {rows_html if rows_html else '<tr><td colspan="5" style="padding:16px; text-align:center; color:#64748b;">Comishiniin galmaa\'e hin jiru.</td></tr>'}
            </tbody>
        </table>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

@app.route('/manage_users', methods=['GET', 'POST'])
def manage_users():
    if 'role' not in session or session['role'] != 'CEO':
        return "🚫 Hayyama CEO Qofa!", 403

    conn = get_db_connection()
    cursor = conn.cursor()
    msg = None

    if request.method == 'POST':
        action = request.form.get('action')
        username = request.form.get('username', '').strip()
        
        if action == 'add':
            password = request.form.get('password', '').strip()
            role = request.form.get('role')
            try:
                cursor.execute("INSERT INTO users (username, password, role, status) VALUES (?, ?, ?, 'ACTIVE')", (username, password, role))
                conn.commit()
                msg = f"✅ Hojjataa haaraa '{username}' ({role}) milkaa'inaan galmeeffameera."
            except sqlite3.IntegrityError:
                msg = f"❌ Username '{username}' duraan galmaa'eera!"
        elif action == 'toggle_status':
            cursor.execute("SELECT status FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()
            if user:
                new_st = 'BLOCKED' if user['status'] == 'ACTIVE' else 'ACTIVE'
                cursor.execute("UPDATE users SET status = ? WHERE username = ?", (new_st, username))
                conn.commit()
                msg = f"🔄 Status hojjataa '{username}' gara '{new_st}' jijjiirameera."

    cursor.execute("SELECT username, role, status FROM users WHERE username != 'ceo'")
    users_list = cursor.fetchall()
    conn.close()

    users_html = ""
    for u in users_list:
        btn_cls = "btn-red" if u['status'] == 'ACTIVE' else "btn-green"
        btn_txt = "🚫 Block" if u['status'] == 'ACTIVE' else "🔓 Unblock"
        users_html += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:12px;">
            <td style="padding:8px; font-weight:bold;">{u['username']}</td>
            <td style="padding:8px;">{u['role']}</td>
            <td style="padding:8px;"><span class="badge {'badge-active' if u['status']=='ACTIVE' else 'badge-danger'}">{u['status']}</span></td>
            <td style="padding:8px; text-align:right;">
                <form method="POST" style="display:inline;">
                    <input type="hidden" name="action" value="toggle_status">
                    <input type="hidden" name="username" value="{u['username']}">
                    <button type="submit" class="btn-action {btn_cls}">{btn_txt}</button>
                </form>
            </td>
        </tr>
        """

    content = f"""
    <div class="box">
        <h2 style="font-size: 16px; color:#065f46; margin-bottom: 12px;">⚙️ Bulchiinsa Hojjattootaa (CEO User Admin)</h2>
        {f"<p style='background:#dcfce7; color:#166534; padding:10px; border-radius:6px; font-size:12px; font-weight:bold; margin-bottom:12px;'>{msg}</p>" if msg else ""}

        <form method="POST" style="margin-bottom:20px; background:#f8fafc; padding:12px; border-radius:8px; border:1px solid #cbd5e1;">
            <input type="hidden" name="action" value="add">
            <h3 style="font-size:13px; color:#065f46; margin-bottom:8px;">➕ Hojjataa Haaraa Galmeessi</h3>
            <div class="form-group">
                <label>Username</label>
                <input type="text" name="username" required class="input-field">
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" id="new_user_password" name="password" required class="input-field">
                <span id="new_pwd_toggle" class="pwd-toggle" onclick="togglePasswordVisibility('new_user_password', 'new_pwd_toggle')">👁️</span>
            </div>
            <div class="form-group">
                <label>Shoora (Role)</label>
                <select name="role" class="input-field">
                    <option value="MAKER">MAKER (Teller / Galmeessaa)</option>
                    <option value="MANAGER">MANAGER (Approver / Mirkaneessaa)</option>
                    <option value="AUDITOR">AUDITOR (To'ataa Internal Audit)</option>
                    <option value="LOAN_OFFICER">LOAN_OFFICER (Mijjeessaa Liqaa)</option>
                </select>
            </div>
            <button type="submit" class="btn-submit">➕ Hojjataa Galmeessi</button>
        </form>

        <h3 style="font-size: 14px; margin-bottom: 8px;">📋 Tarree Hojjattoota Systema</h3>
        <div style="overflow-x:auto;">
            <table style="width:100%; border-collapse:collapse; text-align:left;">
                <thead>
                    <tr style="background:#f8fafc; font-size:11px; color:#64748b; border-bottom:1px solid #e2e8f0;">
                        <th style="padding:8px;">Username</th>
                        <th style="padding:8px;">Role</th>
                        <th style="padding:8px;">Status</th>
                        <th style="padding:8px; text-align:right;">Tarkaanfii</th>
                    </tr>
                </thead>
                <tbody>
                    {users_html}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

@app.route('/ceo_backup', methods=['GET', 'POST'])
def ceo_backup():
    if 'role' not in session or session['role'] != 'CEO':
        return "🚫 Hayyama CEO Qofa!", 403

    msg = None
    msg_type = "green"

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'restore':
            file = request.files.get('backup_file')
            if file and file.filename.endswith('.db'):
                temp_path = os.path.join(app.config['BACKUP_FOLDER'], "temp_restore.db")
                file.save(temp_path)
                try:
                    test_conn = sqlite3.connect(temp_path)
                    test_conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
                    test_conn.close()

                    shutil.copyfile(temp_path, DB_PATH)
                    init_db()
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    msg = "✅ Database-ni milkaa'inaan deebi'eera (Restore Complete)!"
                    add_notification("CEO database restore godhee jira.")
                except Exception as e:
                    msg = f"❌ Database restore ta'uu hin dandeenye: {str(e)}"
                    msg_type = "red"
            else:
                msg = "❌ Faayila '.db' sirrii ta'e qofa ol-fe'aa!"
                msg_type = "red"

    msg_html = f"<p style='background:{'#dcfce7' if msg_type=='green' else '#fee2e2'}; color:{'#166534' if msg_type=='green' else '#991b1b'}; padding:10px; border-radius:6px; font-size:12px; font-weight:bold; margin-bottom:12px;'>{msg}</p>" if msg else ""

    content = f"""
    <div class="box">
        <h2 style="font-size: 16px; color:#581c87; margin-bottom: 4px;">💾 Safe Data Backup & Restore (CEO)</h2>
        <p style="font-size: 11px; color:#64748b; margin-bottom: 16px;">System-ni Python osoo hin dhaamne nagaani SQLite DB download / save godhaa.</p>
        
        {msg_html}

        <div style="background:#faf5ff; border:1px solid #e9d5ff; padding:16px; border-radius:10px; margin-bottom:16px;">
            <h3 style="font-size:13px; color:#581c87; margin-bottom:4px;">📥 1. Save Database (Download)</h3>
            <p style="font-size:11px; color:#64748b; margin-bottom:10px;">Data kuufame saafiyyaan save godhachuuf button kana tuqaa.</p>
            <a href="/download_db" class="btn-submit" style="background:#7c3aed; text-align:center; text-decoration:none; display:block;">💾 Download Database Backup (.db)</a>
        </div>

        <div style="background:#fff7ed; border:1px solid #ffedd5; padding:16px; border-radius:10px;">
            <h3 style="font-size:13px; color:#c2410c; margin-bottom:4px;">📤 2. Restore Database</h3>
            <form method="POST" enctype="multipart/form-data">
                <input type="hidden" name="action" value="restore">
                <div class="form-group">
                    <input type="file" name="backup_file" accept=".db" required class="input-field">
                </div>
                <button type="submit" class="btn-submit" style="background:#c2410c;">🔄 Database Restore Godhi</button>
            </form>
        </div>
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

@app.route('/download_db')
def download_db():
    if 'role' not in session or session['role'] != 'CEO':
        return "🚫 Hayyama CEO Qofa!", 403

    if os.path.exists(DB_PATH):
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return send_file(DB_PATH, as_attachment=True, download_name=f"imana_bank_backup_{now_str}.db")
    return "Database Hin Argamne", 404

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
