import os
import psycopg2
from psycopg2.extras import RealDictCursor
import datetime
import random
import sys
import time
from io import BytesIO

# PIL (Pillow) exception handling for Render deployment stability
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from flask import Flask, request, redirect, url_for, session, render_template_string, send_from_directory, jsonify, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "imana_free_interest_microfinance_secret_key")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

NOTIFICATIONS = []

# --- POSTGRESQL DATABASE CONNECTION (NEON DB COMPATIBLE) ---
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db_connection(max_retries=5, delay=1):
    """Establishes connection strictly to PostgreSQL database using DATABASE_URL"""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set!")
    
    # Neon.tech connections require sslmode=require
    db_url = DATABASE_URL
    if "sslmode=" not in db_url:
        if "?" in db_url:
            db_url += "&sslmode=require"
        else:
            db_url += "?sslmode=require"

    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
            return conn
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(delay)
            else:
                raise e

# --- IMAGE COMPRESSION & NETWORK OPTIMIZATION ---
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

# --- DATABASE SETUP & AUTO MIGRATION (POSTGRESQL) ---
def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username VARCHAR(100) PRIMARY KEY,
                password VARCHAR(255) NOT NULL,
                role VARCHAR(50) NOT NULL,
                status VARCHAR(50) DEFAULT 'ACTIVE'
            );
        """)

        cursor.execute("SELECT COUNT(*) FROM users;")
        if cursor.fetchone()['count'] == 0:
            default_users = [
                ('ceo', 'ceo999', 'CEO', 'ACTIVE'),
                ('manager1', 'manager123', 'MANAGER', 'ACTIVE'),
                ('maker1', 'maker123', 'MAKER', 'ACTIVE'),
                ('auditor1', 'auditor123', 'AUDITOR', 'ACTIVE'),
                ('officer1', 'officer123', 'LOAN_OFFICER', 'ACTIVE')
            ]
            cursor.executemany("INSERT INTO users VALUES (%s, %s, %s, %s);", default_users)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                customer_id VARCHAR(100) PRIMARY KEY,
                full_name VARCHAR(255),
                phone VARCHAR(50),
                gender VARCHAR(20) DEFAULT 'Dhiira',
                account_type VARCHAR(50) DEFAULT 'WADIA',
                photo_path TEXT,
                signature_path TEXT,
                national_id_path TEXT DEFAULT '',
                balance DOUBLE PRECISION DEFAULT 0.0,
                status VARCHAR(50) DEFAULT 'PENDING_APPROVAL',
                freeze_status VARCHAR(50) DEFAULT 'UNFROZEN',
                freeze_reason TEXT DEFAULT '',
                created_at VARCHAR(100)
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                txn_id VARCHAR(100) PRIMARY KEY,
                txn_type VARCHAR(50),
                customer_id VARCHAR(100),
                customer_name VARCHAR(255),
                target_account VARCHAR(100),
                amount DOUBLE PRECISION,
                commission DOUBLE PRECISION DEFAULT 0.0,
                bank_name VARCHAR(255),
                ft_reference VARCHAR(100),
                status VARCHAR(50) DEFAULT 'PENDING_MANAGER',
                created_by VARCHAR(100),
                timestamp VARCHAR(100),
                audited_status VARCHAR(50) DEFAULT 'OPEN'
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reversals (
                reversal_id VARCHAR(100) PRIMARY KEY,
                txn_id VARCHAR(100) NOT NULL,
                reason TEXT NOT NULL,
                requested_by VARCHAR(100) NOT NULL,
                manager_approved INTEGER DEFAULT 0,
                ceo_approved INTEGER DEFAULT 0,
                status VARCHAR(50) DEFAULT 'PENDING_APPROVAL',
                timestamp VARCHAR(100)
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS islamic_financing (
                loan_id VARCHAR(100) PRIMARY KEY,
                customer_id VARCHAR(100) NOT NULL,
                customer_name VARCHAR(255),
                financing_type VARCHAR(50) NOT NULL,
                principal_amount DOUBLE PRECISION NOT NULL,
                profit_margin DOUBLE PRECISION DEFAULT 0.0,
                total_repayment DOUBLE PRECISION NOT NULL,
                tenure_months INTEGER,
                monthly_installment DOUBLE PRECISION,
                status VARCHAR(50) DEFAULT 'PENDING_MANAGER',
                manager_approved INTEGER DEFAULT 0,
                ceo_approved INTEGER DEFAULT 0,
                agent_notes TEXT,
                created_by VARCHAR(100),
                timestamp VARCHAR(100)
            );
        """)

        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Database init error: {e}")

if DATABASE_URL:
    init_db()

def get_bank_capital():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(amount) AS total FROM transactions WHERE status='APPROVED' AND txn_type='DEPOSIT';")
    row = cursor.fetchone()
    total_deposit = row['total'] if row and row['total'] is not None else 0.0
    
    cursor.execute("SELECT SUM(amount) AS total FROM transactions WHERE status='APPROVED' AND txn_type IN ('WITHDRAWAL', 'T24_TRANSFER');")
    row = cursor.fetchone()
    total_withdraw = row['total'] if row and row['total'] is not None else 0.0
    
    cursor.execute("SELECT SUM(balance) AS total FROM customers WHERE status='ACTIVE';")
    row = cursor.fetchone()
    total_cust_balance = row['total'] if row and row['total'] is not None else 0.0

    cursor.execute("SELECT SUM(commission) AS total FROM transactions WHERE status='APPROVED';")
    row = cursor.fetchone()
    total_commission = row['total'] if row and row['total'] is not None else 0.0

    cursor.execute("SELECT SUM(balance) AS total FROM customers WHERE status='ACTIVE' AND account_type='MUDARABA';")
    row = cursor.fetchone()
    total_mudaraba_deposits = row['total'] if row and row['total'] is not None else 0.0

    mudaraba_gross_profit = total_mudaraba_deposits * 0.10
    mudaraba_ceo_share = mudaraba_gross_profit * 0.50
    mudaraba_customer_share = mudaraba_gross_profit * 0.50
    
    net_capital = total_deposit - total_withdraw + total_commission
    cursor.close()
    conn.close()
    return max(0.0, net_capital), total_deposit, total_withdraw, total_cust_balance, total_commission, total_mudaraba_deposits, mudaraba_gross_profit, mudaraba_ceo_share, mudaraba_customer_share

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
        .bottom-nav { position: fixed; bottom: 0; left: 0; right: 0; background: white; border-top: 1px solid #e2e8f0; display: flex; justify-around: font-size: 11px; flex: 1; font-weight: 500; }
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
        .img-grid img { width: 100%; height: 60px; object-fit: cover; border-radius: 6px; border: 1px solid #e2e8f0; loading: lazy; }
        .btn-action { padding: 6px 12px; border-radius: 6px; color: white; text-decoration: none; font-size: 12px; font-weight: bold; display: inline-block; border:none; cursor:pointer; }
        .btn-blue { background: #2563eb; }
        .btn-green { background: #16a34a; }
        .btn-red { background: #dc2626; }
        .btn-orange { background: #ea580c; }
        .btn-purple { background: #7c3aed; }
        .pwd-toggle { position: absolute; right: 10px; top: 32px; cursor: pointer; user-select: none; font-size: 14px; }
        .modal { display: none; position: fixed; z-index: 100; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); align-items: center; justify-content: center; }
        .modal-content { background: white; padding: 20px; border-radius: 12px; max-width: 450px; width: 90%; max-height: 85vh; overflow-y: auto; }
        @media print { .bottom-nav, nav, .btn-print, .no-print { display: none !important; } body { padding-bottom: 0; background: white; } .box { border: none; box-shadow: none; } }
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
        {% endif %}
        {% if session['role'] == 'AUDITOR' %}
            <a href="/pending"><span class="icon">📋</span>Auditor View</a>
            <a href="/auditor_reversal_request"><span class="icon">⚠️</span>Reversal Gaafachu</a>
        {% endif %}
        {% if session['role'] in ['LOAN_OFFICER', 'CEO', 'MANAGER'] %}
            <a href="/islamic_loan"><span class="icon">📜</span>Liqaa Islaamaa</a>
        {% endif %}
        {% if session['role'] == 'CEO' %}
            <a href="/reversals_list" style="color: #581c87;"><span class="icon">🔄</span>Reversal CEO</a>
            <a href="/ceo_mudaraba_list" style="color: #581c87;"><span class="icon">🤝</span>Mudaraba List</a>
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
        cursor.execute("SELECT username, role, status FROM users WHERE username = %s AND password = %s;", (username, password))
        user = cursor.fetchone()
        cursor.close()
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

# --- TRANSACTION ROUTE ---
@app.route('/transaction', methods=['GET', 'POST'])
def transaction():
    if 'role' not in session or session['role'] != 'MAKER':
        return "🚫 Shoora MAKER qofatu transaction raawwachuu danda'a", 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT customer_id, full_name, balance, freeze_status FROM customers WHERE status='ACTIVE';")
    customers = cursor.fetchall()

    msg = None
    msg_type = "green"

    if request.method == 'POST':
        txn_type = request.form.get('txn_type')
        cust_id = request.form.get('customer_id')
        target_acc = request.form.get('target_account', '').strip()
        amount = float(request.form.get('amount', 0.0))
        bank_name = request.form.get('bank_name', 'Imana Microfinance Core')

        cursor.execute("SELECT full_name, balance, freeze_status FROM customers WHERE customer_id = %s;", (cust_id,))
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
                ft_ref = f"FT{datetime.datetime.now().strftime('%y%j')}{random.randint(10000, 99999)}"
                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                txn_id = f"TXN-{timestamp_str}"

                cursor.execute("""
                    INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name, target_account, amount, commission, bank_name, ft_reference, status, created_by, timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING_MANAGER', %s, %s);
                """, (txn_id, txn_type, cust_id, cust['full_name'], target_acc, amount, commission, bank_name, ft_ref, session['username'], now))

                conn.commit()
                msg = f"✅ Transaction ({txn_type}) {amount:,.2f} Birr galmaa'eera (Ref: {ft_ref}). Approval Manager eegaa jira!"
                add_notification(f"Maker transaction haaraa uumeera: {ft_ref} ({txn_type})")

    cursor.close()
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
                <label>Maammila Filadhu (Source Account)</label>
                <select name="customer_id" required class="input-field">
                    {cust_options}
                </select>
            </div>
            <div class="form-group" id="target_acc_group" style="display:none;">
                <label>Account ID Nama Fudhatuu (Target Account ID)</label>
                <input type="text" name="target_account" placeholder="Fkn: 100099008801" class="input-field">
            </div>
            <div class="form-group">
                <label>Hamma Maallaqaa (Amount in Birr)</label>
                <input type="number" step="0.01" name="amount" placeholder="0.00" required class="input-field">
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
    </script>
    """
    return render_template_string(HTML_LAYOUT.replace("{% block content %}{% endblock %}", content), notifications=NOTIFICATIONS)

# --- REGISTER CUSTOMER ROUTE ---
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
            
            cursor.execute("SELECT MAX(CAST(customer_id AS BIGINT)) AS max_id FROM customers WHERE customer_id >= '100099008800';")
            row = cursor.fetchone()
            max_id = row['max_id'] if row else None

            cust_id = str(START_ID) if max_id is None or max_id < START_ID else str(max_id + 1)
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute("""
                INSERT INTO customers (customer_id, full_name, phone, gender, account_type, photo_path, signature_path, national_id_path, balance, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING_APPROVAL', %s);
            """, (cust_id, full_name, phone, gender, account_type, photo_filename, sig_filename, nat_id_filename, initial_balance, now))

            if initial_balance > 0:
                ft_ref = f"FT{datetime.datetime.now().strftime('%y%j')}{random.randint(10000, 99999)}"
                cursor.execute("""
                    INSERT INTO transactions (txn_id, txn_type, customer_id, customer_name, amount, bank_name, ft_reference, status, created_by, timestamp)
                    VALUES (%s, 'DEPOSIT', %s, %s, %s, 'Imana Microfinance Core', %s, 'APPROVED', %s, %s);
                """, (f"TXN-INIT-{timestamp_str}", cust_id, full_name, initial_balance, ft_ref, session['username'], now))

            conn.commit()
            cursor.close()
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
