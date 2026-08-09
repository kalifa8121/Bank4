import os
import sqlite3
import datetime
import random
import shutil
import sys
import time
import atexit
from flask import Flask, request, redirect, url_for, session, render_template_string, send_from_directory, jsonify, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "imana_free_interest_microfinance_secret_key"

# --- RENDER PERSISTENT DISK / LOCAL PATH SETUP ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RENDER_DISK_DIR = os.environ.get("RENDER_DISK_PATH", BASE_DIR)

UPLOAD_FOLDER = os.path.join(RENDER_DISK_DIR, 'uploads')
BACKUP_FOLDER = os.path.join(RENDER_DISK_DIR, 'backups')
DB_PATH = os.path.join(RENDER_DISK_DIR, "web_banking.db")

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['BACKUP_FOLDER'] = BACKUP_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(BACKUP_FOLDER, exist_ok=True)

# --- DATABASE CONNECTION OPTIMIZATION ---
def get_db_connection(max_retries=5, delay=0.2):
    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            conn.row_factory = sqlite3.Row
            # Fast write and concurrent read performance for SQLite
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA cache_size=-64000;") # 64MB Cache
            return conn
        except sqlite3.OperationalError as e:
            if attempt < max_retries - 1:
                time.sleep(delay)
            else:
                raise e

# --- AUTO BACKUP & RESTORE UTILITIES ---
def auto_backup_db():
    try:
        if os.path.exists(DB_PATH):
            now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"auto_backup_{now_str}.db"
            backup_file_path = os.path.join(BACKUP_FOLDER, backup_filename)
            with sqlite3.connect(DB_PATH) as src_conn:
                with sqlite3.connect(backup_file_path) as dst_conn:
                    src_conn.backup(dst_conn)
            latest_path = os.path.join(BACKUP_FOLDER, "auto_restore_latest.db")
            shutil.copyfile(backup_file_path, latest_path)
    except Exception as e:
        print(f"⚠️ [AUTO BACKUP ERROR]: {e}")

def auto_restore_db():
    try:
        latest_path = os.path.join(BACKUP_FOLDER, "auto_restore_latest.db")
        if not os.path.exists(DB_PATH) and os.path.exists(latest_path):
            shutil.copyfile(latest_path, DB_PATH)
    except Exception as e:
        print(f"⚠️ [AUTO RESTORE ERROR]: {e}")

auto_restore_db()
atexit.register(auto_backup_db)

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

def send_notification(message, created_by="SYSTEM"):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("INSERT INTO notifications (message, created_by, timestamp) VALUES (?, ?, ?)", (message, created_by, now))
            conn.commit()
    except Exception as e:
        print(f"Notification Error: {e}")

def send_sms_alert(phone_number, message):
    print(f"📱 [SMS SENT TO {phone_number}]: {message}")

# --- DATABASE SETUP & INDEXING ---
def init_db():
    with get_db_connection() as conn:
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
                ('auditor1', 'auditor123', 'AUDITOR', 'ACTIVE')
            ]
            cursor.executemany("INSERT INTO users VALUES (?, ?, ?, ?)", default_users)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                customer_id TEXT PRIMARY KEY,
                full_name TEXT,
                phone TEXT,
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
                status TEXT DEFAULT 'PENDING_APPROVAL',
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
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                created_by TEXT,
                timestamp TEXT
            )
        """)

        # Speed up approval queries with Indexing
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_txn_status ON transactions(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cust_status ON customers(status);")
        conn.commit()

init_db()

def get_bank_capital():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT SUM(amount) FROM transactions WHERE status='APPROVED' AND txn_type='DEPOSIT'")
        total_deposit = cursor.fetchone()[0] or 0.0
        
        cursor.execute("SELECT SUM(amount) FROM transactions WHERE status='APPROVED' AND txn_type IN ('WITHDRAWAL', 'T24_TRANSFER')")
        total_withdraw = cursor.fetchone()[0] or 0.0
        
        cursor.execute("SELECT SUM(balance) FROM customers WHERE status='ACTIVE'")
        total_cust_balance = cursor.fetchone()[0] or 0.0

        cursor.execute("SELECT SUM(commission) FROM transactions WHERE status='APPROVED'")
        total_commission = cursor.fetchone()[0] or 0.0
        
        net_capital = total_deposit - total_withdraw + total_commission
        return net_capital, total_deposit, total_withdraw, total_cust_balance, total_commission

# --- UI TEMPLATE ---
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
        .card-net { background: linear-gradient(135deg, #064e3b, #047857); color: white; border-radius: 16px; padding: 20px; box-shadow: 0 10px 15px -3px rgba(6,78,59,0.3); margin-bottom: 20px; }
        .net-title { font-size: 12px; opacity: 0.9; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
        .net-amount { font-size: 32px; font-weight: 800; color: #fbbf24; }
        .net-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 16px; pt: 12px; border-top: 1px solid rgba(255,255,255,0.2); font-size: 12px; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
        .btn-card { background: white; padding: 16px; border-radius: 12px; border: 1px solid #e2e8f0; display: flex; flex-direction: column; align-items: center; text-decoration: none; color: #334155; font-weight: bold; font-size: 13px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05); transition: 0.2s; }
        .btn-card:active { transform: scale(0.98); }
        .btn-card span.icon { font-size: 24px; margin-bottom: 8px; }
        .btn-card-ceo { background: #faf5ff; border-color: #e9d5ff; color: #581c87; }
        .btn-card-auditor { background: #fff7ed; border-color: #ffedd5; color: #c2410c; }
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
        .item-card { background: white; border-radius: 12px; padding: 14px; margin-bottom: 12px; border: 1px solid #e2e8f0; }
        .img-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; margin: 10px 0; }
        .img-grid img { width: 100%; height: 80px; object-fit: cover; border-radius: 6px; border: 1px solid #e2e8f0; }
        .btn-action { padding: 6px 12px; border-radius: 6px; color: white; text-decoration: none; font-size: 12px; font-weight: bold; display: inline-block; border:none; cursor:pointer; }
        .btn-blue { background: #2563eb; }
        .btn-green { background: #16a34a; }
        .btn-red { background: #dc2626; }
        .btn-orange { background: #ea580c; }
        .btn-purple { background: #7c3aed; }
        .pwd-toggle { position: absolute; right: 10px; top: 32px; cursor: pointer; user-select: none; font-size: 14px; }
        .modal { display: none; position: fixed; z-index: 100; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); align-items: center; justify-content: center; }
        .modal-content { background: white; padding: 20px; border-radius: 12px; max-width: 450px; width: 90%; max-height: 85vh; overflow-y: auto; }
        .notif-box { background: #e0f2fe; border-left: 4px solid #0284c7; padding: 8px 12px; border-radius: 6px; font-size: 11px; margin-bottom: 12px; }
    </style>
</head>
<body>
    <nav>
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
                <a href="/logout" style="color: #fca5a5; margin-left:8px; text-decoration:none;">Logout</a>
            </div>
        {% endif %}
    </nav>

    <div class="container">
        {% block content %}{% endblock %}
    </div>

    {% if session.get('role') %}
    <div class="bottom-nav">
        <a href="/"><span class="icon">🏠</span>Dashboard</a>
        {% if session['role'] == 'MAKER' %}
            <a href="/register"><span class="icon">👤</span>Galmee</a>
            <a href="/transaction"><span class="icon">💸</span>Kaffaltii</a>
            <a href="/maker_receipts"><span class="icon">🧾</span>Nagahee</a>
        {% endif %}
        {% if session['role'] in ['MANAGER', 'AUDITOR'] %}
            <a href="/pending"><span class="icon">📋</span>Approvals</a>
            <a href="/reversals_list"><span class="icon">🔄</span>Reversals</a>
        {% endif %}
        {% if session['role'] == 'AUDITOR' %}
            <a href="/auditor_reversal_request"><span class="icon">⚠️</span>Reversal Gaafachuu</a>
            <a href="/auditor_close"><span class="icon">🔒</span>Cufiinsa</a>
        {% endif %}
        {% if session['role'] == 'CEO' %}
            <a href="/reversals_list" style="color: #581c87;"><span class="icon">🔄</span>Reversal CEO</a>
            <a href="/ceo_commission" style="color: #581c87;"><span class="icon">💰</span>Comishina</a>
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

# --- ROUTES & VIEWS ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT username, role, status FROM users WHERE username = ? AND password = ?", (username, password))
            user = cursor.fetchone()

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
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content))

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/')
def dashboard():
    if 'role' not in session:
        return redirect('/login')
    
    net_cap, deposits, withdraws, cust_bal, total_comm = get_bank_capital()
    role = session['role']

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT message, created_by, timestamp FROM notifications ORDER BY id DESC LIMIT 3")
        notifs = cursor.fetchall()

    notif_html = ""
    if notifs:
        notif_html = "<div style='margin-bottom:12px;'>"
        for n in notifs:
            notif_html += f"<div class='notif-box'>🔔 <b>[{n['timestamp']}]</b> {n['message']} (By: {n['created_by']})</div>"
        notif_html += "</div>"

    maker_btns = ""
    if role == 'MAKER':
        maker_btns = """
        <a href="/register" class="btn-card"><span class="icon">👤</span><span>Galmee Maammilaa</span></a>
        <a href="/transaction" class="btn-card"><span class="icon">💸</span><span>Deposit / Transfer / Withdraw</span></a>
        <a href="/maker_receipts" class="btn-card"><span class="icon">🧾</span><span>Nagahee Maxxansi</span></a>
        """

    manager_btns = ""
    if role in ['MANAGER', 'AUDITOR']:
        manager_btns = f"""
        <a href="/pending" class="btn-card"><span class="icon">🔍</span><span>{role} Approval</span></a>
        <a href="/reversals_list" class="btn-card"><span class="icon">🔄</span><span>Reversal Approvals</span></a>
        """

    auditor_btns = ""
    if role == 'AUDITOR':
        auditor_btns = """
        <a href="/auditor_reversal_request" class="btn-card btn-card-auditor"><span class="icon">⚠️</span><span>Transaction Reversal Gaafachu</span></a>
        <a href="/auditor_close" class="btn-card btn-card-auditor"><span class="icon">🔒</span><span>Cufiinsa Herrega Galgalaa</span></a>
        """

    ceo_btn = ""
    if role == 'CEO':
        ceo_btn = """
        <a href="/ceo_commission" class="btn-card btn-card-ceo"><span class="icon">💰</span><span>Comishina Guyyaa</span></a>
        <a href="/ceo_blank_form" target="_blank" class="btn-card btn-card-ceo"><span class="icon">🖨️</span><span>Formii Duwwaa Maxxansi</span></a>
        <a href="/reversals_list" class="btn-card btn-card-ceo"><span class="icon">🔄</span><span>CEO Reversal Approval</span></a>
        <a href="/manage_users" class="btn-card btn-card-ceo"><span class="icon">⚙️</span><span>Bulchiinsa Hojjattootaa</span></a>
        <a href="/ceo_backup" class="btn-card btn-card-ceo"><span class="icon">💾</span><span>Save / Restore DB</span></a>
        <a href="/ceo_audit" class="btn-card btn-card-ceo"><span class="icon">🌙</span><span>CEO Audit & Reports</span></a>
        """

    content = f"""
    {notif_html}

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
        <a href="/customers" class="btn-card"><span class="icon">👥</span><span>Listii Maammiltootaa</span></a>
        {ceo_btn}
    </div>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content))

# --- APPROVAL DASHBOARD OPTIMIZED ---
@app.route('/pending')
def pending():
    if 'role' not in session or session['role'] not in ['MANAGER', 'AUDITOR']:
        return "🚫 Hayyama Manager ykn Auditor Qofa!", 403

    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT customer_id, full_name, phone, photo_path, signature_path, national_id_path FROM customers WHERE status='PENDING_APPROVAL'")
        pending_custs = cursor.fetchall()

        cursor.execute("""
            SELECT 
                t.txn_id, t.txn_type, t.customer_name, t.amount, t.bank_name, t.status,
                c.photo_path, c.signature_path, c.national_id_path, c.phone, t.customer_id, t.ft_reference, t.target_account, t.commission,
                c.freeze_status, c.freeze_reason
            FROM transactions t
            LEFT JOIN customers c ON t.customer_id = c.customer_id
            WHERE t.status = 'PENDING_APPROVAL'
            ORDER BY t.timestamp DESC
        """)
        pending_txns = cursor.fetchall()

    cards_html = ""

    if pending_custs:
        cards_html += "<h3 style='font-size:12px; color:#1e40af; margin-bottom:8px;'>👤 Galmee Maammiltoota Eeggamaa Jiran</h3>"
        for c in pending_custs:
            nid_link = f"<a href='/uploads/{c['national_id_path']}' target='_blank' style='font-size:10px;'>📄 ID Ilaali</a>" if c['national_id_path'] else "N/A"
            cards_html += f"""
            <div class="item-card" style="background:#eff6ff; border-color:#bfdbfe;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                    <span style="font-size:12px; font-weight:bold; color:#1e3a8a;">Acc: {c['customer_id']}</span>
                    <span class="badge badge-pending">PENDING</span>
                </div>
                <div style="font-size:13px; font-weight:bold; margin-bottom:6px;">Maqaa: {c['full_name']} (📞 {c['phone']})</div>
                <div class="img-grid">
                    <div style="text-align:center;"><img src="/uploads/{c['photo_path']}"><span style="font-size:10px; color:#64748b;">Fuula</span></div>
                    <div style="text-align:center;"><img src="/uploads/{c['signature_path']}"><span style="font-size:10px; color:#1e40af; font-weight:bold;">Mallattoo ✍️</span></div>
                    <div style="text-align:center; font-size:10px;">{nid_link}<br><span style="color:#64748b;">National ID</span></div>
                </div>
                <div style="text-align:right; margin-top:8px;">
                    <a href="/approve_cust/{c['customer_id']}" class="btn-action btn-blue">✅ Approve Customer</a>
                </div>
            </div>
            """

    if pending_txns:
        cards_html += f"<h3 style='font-size:12px; color:#b45309; margin-top:16px; margin-bottom:8px;'>💵 Kaffaltii Maker Uume - Mirkaneessa {session['role']} Eeggatu</h3>"
        for r in pending_txns:
            freeze_info = f"<span class='badge badge-frozen'>🔒 UGGURAMEERA ({r['freeze_reason']})</span>" if r['freeze_status'] == 'FROZEN' else "<span class='badge badge-active'>✅ Active</span>"
            
            cards_html += f"""
            <div class="item-card">
                <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
                    <span style="font-size:12px; font-weight:bold; color:#065f46;">FT Ref: {r['ft_reference']}</span>
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
        cards_html = f"<p style='text-align:center; color:#64748b; padding:20px; font-size:13px;'>✅ Transaction-ni {session['role']} Approval eeggatu hin jiru!</p>"

    content = f"""
    <h2 style="font-size: 16px; margin-bottom: 12px;">📋 {session['role']} Approval Dashboard</h2>
    {cards_html}

    <div id="infoModal" class="modal">
        <div class="modal-content">
            <h3 id="modalName" style="font-size:15px; color:#065f46; margin-bottom:10px;"></h3>
            <div id="modalFreeze" style="margin-bottom:10px; font-size:12px;"></div>
            <div class="img-grid">
                <div><p style="font-size:10px; font-weight:bold;">Suuraa Fuulaa:</p><img id="modalPhoto" src="" style="width:100%; height:100px; object-fit:cover;"></div>
                <div><p style="font-size:10px; font-weight:bold;">Mallattoo:</p><img id="modalSig" src="" style="width:100%; height:100px; object-fit:cover;"></div>
                <div id="nidBox" style="text-align:center;"><p style="font-size:10px; font-weight:bold;">National ID:</p><a id="modalNidLink" href="#" target="_blank" class="btn-action btn-blue" style="font-size:10px; margin-top:10px;">📄 Download/View</a></div>
            </div>
            <button onclick="closeModal()" class="btn-submit" style="background:#64748b; margin-top:12px;">Cufi (Close)</button>
        </div>
    </div>

    <script>
    function openModal(name, photo, sig, nid, freezeSt, freezeRs) {{
        document.getElementById('modalName').innerText = "Maammila: " + name;
        document.getElementById('modalPhoto').src = "/uploads/" + photo;
        document.getElementById('modalSig').src = "/uploads/" + sig;
        if(nid) {{
            document.getElementById('modalNidLink').href = "/uploads/" + nid;
            document.getElementById('nidBox').style.display = 'block';
        }} else {{
            document.getElementById('nidBox').style.display = 'none';
        }}
        
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
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content))

@app.route('/manager_action/<act>/<txn_id>')
def manager_action(act, txn_id):
    if 'role' not in session or session['role'] not in ['MANAGER', 'AUDITOR']:
        return redirect('/login')

    with get_db_connection() as conn:
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
                    send_sms_alert(phone, f"Kabajamoo {name}, {txn_type} {amount:,.2f} Birr (Ref: {ft_ref}) mirkanaa'ee xumurameera.")
                    send_notification(f"Transaction {ft_ref} ({txn_type} {amount} Birr) APPROVED ta'ee jira.", session['username'])

        elif act == 'reject':
            cursor.execute("UPDATE transactions SET status = 'REJECTED' WHERE txn_id = ?", (txn_id,))

        conn.commit()
    return redirect('/pending')

# --- ROUTES DABLALATAA (Flask Endpoints) ---
@app.route('/uploads/<path:filename>')
def custom_static(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
