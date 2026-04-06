"""
SocialPay Web App v6.0
- SQLite database (replaces all JSON files)
- Auto-delete submissions after approval (admin can delete any submission)
- Multi-level referrals (L1 + L2)
- PalmPay-style design
- Sign-up reward, daily login, spin & win
- Admin super_admin role system
- PWA support, Telegram integration
- v6 security: werkzeug password hashing (backward-compat), CSRF tokens,
               hardened session config, proper error handlers, env-based secret
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort
import sqlite3, os, hashlib, secrets, random, string
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

_HERE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__,
            template_folder=os.path.join(_HERE, "templates"),
            static_folder=os.path.join(_HERE, "static"))

# ── Security: secret key MUST come from env in production ──────────────────
_fallback_key = secrets.token_hex(32)   # random per-process; fine for dev
app.secret_key = os.environ.get("SECRET_KEY", _fallback_key)

app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)   # was 10 years
app.config["SESSION_COOKIE_SECURE"]   = os.environ.get("FLASK_ENV") == "production"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

APP_NAME = "SocialPay"
VERSION  = "6.0"

TG_CHANNEL = "https://t.me/socialpaychannel"
TG_GROUP   = "https://t.me/socialearningpay"
TG_SUPPORT = "https://t.me/socialpaysupport"
TG_SUPPORT_USERNAME = "@socialpaysupport"

# ── Admin credentials: prefer env vars, fall back to defaults ──────────────
ADMIN_EMAIL    = os.environ.get("ADMIN_EMAIL",    "socialpay.app.ng@gmail.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "@ Ahmerdee4622")
ADMIN_NAME     = "SocialPay Admin"

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
VOLUME_DIR = "/data"
LOCAL_DIR  = os.path.join(BASE_DIR, "data")

if os.path.exists(VOLUME_DIR) and os.access(VOLUME_DIR, os.W_OK):
    DATA_DIR = VOLUME_DIR
else:
    DATA_DIR = LOCAL_DIR

os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "socialpay.db")

# ============================================================
# DATABASE
# ============================================================
def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db

def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0,
        role TEXT DEFAULT 'user',
        banned INTEGER DEFAULT 0,
        verified INTEGER DEFAULT 1,
        created TEXT,
        last_login TEXT,
        referral_code TEXT,
        referred_by TEXT,
        lang TEXT DEFAULT 'en',
        signup_reward_given INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS wallets (
        user_id TEXT PRIMARY KEY,
        naira REAL DEFAULT 0,
        dollar REAL DEFAULT 0,
        completed_tasks INTEGER DEFAULT 0,
        pending_tasks INTEGER DEFAULT 0,
        referral_count INTEGER DEFAULT 0,
        referral_count_l2 INTEGER DEFAULT 0,
        referral_bonus_earned REAL DEFAULT 0,
        total_earned REAL DEFAULT 0,
        total_withdrawn REAL DEFAULT 0,
        created TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT,
        platform TEXT,
        task_type TEXT,
        link TEXT,
        reward REAL DEFAULT 0,
        currency TEXT DEFAULT 'naira',
        max_users INTEGER DEFAULT 100,
        status TEXT DEFAULT 'active',
        auto_approve INTEGER DEFAULT 0,
        completed_count INTEGER DEFAULT 0,
        expires_at TEXT,
        created TEXT,
        created_by TEXT
    );
    CREATE TABLE IF NOT EXISTS task_completions (
        task_id TEXT,
        user_id TEXT,
        PRIMARY KEY(task_id, user_id)
    );
    CREATE TABLE IF NOT EXISTS submissions (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        task_id TEXT,
        proof TEXT,
        screenshot TEXT,
        status TEXT DEFAULT 'pending',
        reward REAL DEFAULT 0,
        currency TEXT DEFAULT 'naira',
        submitted_at TEXT,
        reviewed_at TEXT,
        note TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS withdrawals (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        amount REAL,
        fee REAL,
        net REAL,
        currency TEXT DEFAULT 'naira',
        bank_info TEXT,
        status TEXT DEFAULT 'pending',
        requested_at TEXT,
        processed_at TEXT,
        note TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS transfers (
        id TEXT PRIMARY KEY,
        sender_id TEXT,
        receiver_id TEXT,
        amount REAL,
        status TEXT DEFAULT 'completed',
        time TEXT,
        reversed_at TEXT,
        reversed_by TEXT
    );
    CREATE TABLE IF NOT EXISTS exchanges (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        from_currency TEXT,
        from_amount REAL,
        to_currency TEXT,
        to_amount REAL,
        rate REAL,
        time TEXT
    );
    CREATE TABLE IF NOT EXISTS pins (
        user_id TEXT PRIMARY KEY,
        pin_hash TEXT,
        created TEXT
    );
    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id TEXT,
        referred_id TEXT,
        level INTEGER DEFAULT 1,
        time TEXT,
        bonus_paid INTEGER DEFAULT 0,
        tasks_done INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS notifications (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        message TEXT,
        type TEXT DEFAULT 'info',
        time TEXT,
        read INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    CREATE TABLE IF NOT EXISTS audit_logs (
        id TEXT PRIMARY KEY,
        action TEXT,
        user_id TEXT,
        detail TEXT,
        amount REAL DEFAULT 0,
        time TEXT
    );
    CREATE TABLE IF NOT EXISTS support_tickets (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        user_name TEXT,
        user_email TEXT,
        subject TEXT,
        message TEXT,
        category TEXT DEFAULT 'general',
        status TEXT DEFAULT 'open',
        created TEXT
    );
    CREATE TABLE IF NOT EXISTS support_replies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id TEXT,
        from_role TEXT,
        name TEXT,
        message TEXT,
        time TEXT
    );
    CREATE TABLE IF NOT EXISTS transactions (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        type TEXT,
        amount REAL,
        currency TEXT,
        description TEXT,
        ref_id TEXT,
        time TEXT,
        status TEXT DEFAULT 'completed'
    );
    CREATE TABLE IF NOT EXISTS daily_logins (
        user_id TEXT PRIMARY KEY,
        last_date TEXT,
        total_days INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS spins (
        user_id TEXT PRIMARY KEY,
        last_spin TEXT,
        total_spins INTEGER DEFAULT 0,
        total_spent REAL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS bank_details (
        user_id TEXT PRIMARY KEY,
        bank_name TEXT,
        account_number TEXT,
        account_name TEXT,
        type TEXT DEFAULT 'bank',
        updated TEXT
    );
    """)
    db.commit()
    db.close()

# ============================================================
# TRANSLATIONS
# ============================================================
TRANSLATIONS = {
    "en": {
        "app_name":"SocialPay","tagline":"Earn Money via Social Media Tasks","login":"Login",
        "register":"Register","email":"Email Address","password":"Password",
        "full_name":"Full Name","confirm_password":"Confirm Password",
        "referral_code":"Referral Code (Optional)","create_account":"Create Account",
        "login_now":"Login Now","welcome_back":"Welcome back","total_balance":"Total Balance",
        "tasks":"Tasks","balance":"Balance","transfer":"Transfer","referrals":"Referrals",
        "withdraw":"Withdraw","exchange":"Exchange","profile":"Profile","history":"History",
        "notifications":"Notifications","logout":"Logout","available_tasks":"Available Tasks",
        "my_earnings":"My Earnings","completed_tasks":"Completed Tasks","pending_tasks":"Pending",
        "send_proof":"Submit Proof","proof_placeholder":"Link, username, screenshot URL...",
        "submit":"Submit for Review","withdraw_money":"Withdraw Money",
        "exchange_currency":"Exchange Currency","send_money":"Send Money",
        "receiver_id":"Receiver's User ID","amount":"Amount","pin":"4-digit PIN",
        "send_now":"Send Now","cancel":"Cancel","save":"Save","set_pin":"Set PIN",
        "change_pin":"Change PIN","bank_details":"Bank / Payment Details",
        "bank_name":"Bank Name","account_number":"Account Number","account_name":"Account Name",
        "payment_type":"Payment Type","referral_link":"Your Referral Link","copy":"Copy",
        "share_whatsapp":"WhatsApp","share_telegram":"Telegram",
        "how_referral_works":"How Referrals Work","reward":"Reward","status":"Status",
        "pending":"Pending","approved":"Approved","rejected":"Rejected",
        "no_tasks":"No Tasks Available","no_tasks_desc":"Check back soon! Admin will add new tasks.",
        "no_notifications":"No Notifications","admin_panel":"Admin Panel",
        "total_users":"Total Users","active_tasks":"Active Tasks",
        "pending_approvals":"Pending Approvals","pending_withdrawals":"Pending Withdrawals",
        "fill_all_fields":"Please fill all required fields",
        "password_short":"Password must be at least 8 characters",
        "task_submitted":"Task submitted! Awaiting admin review.",
        "already_submitted":"You already submitted this task",
        "insufficient_balance":"Insufficient balance","withdraw_min":"Minimum withdrawal is",
        "pin_required":"You need to set a PIN first","pin_wrong":"Wrong PIN",
        "pin_set":"PIN set successfully!","pin_4digits":"PIN must be exactly 4 digits",
        "profile_updated":"Profile updated!","bank_saved":"Bank details saved!",
        "balance_adjusted":"Balance adjusted!","user_banned":"User has been banned",
        "user_unbanned":"User has been unbanned","pin_reset":"PIN has been reset",
        "message_sent":"Message sent!","task_created":"Task created!","task_deleted":"Task deleted!",
        "submission_approved":"Submission approved! Payment added.",
        "submission_rejected":"Submission rejected.","withdrawal_approved":"Withdrawal approved!",
        "withdrawal_rejected":"Withdrawal rejected. Funds refunded.",
        "transfer_reversed":"Transfer reversed!","broadcast_sent":"Broadcast sent!",
        "settings_saved":"Settings saved!","money_sent":"Money sent successfully!",
        "exchanged":"Currency exchanged!","user_not_found":"User not found",
        "cannot_send_self":"Cannot send to yourself","admin_notice":"Admin Notice",
        "from_admin":"From Admin","referral_bonus_earned":"Referral bonus earned!",
        "withdrawal_request":"Withdrawal request submitted!","wrong_email_or_password":"Wrong email or password","approve":"Approve","reject":"Reject","reverse":"Reverse","transfers_log":"Transfers Log","refunded":"refunded",
        "account_banned":"Your account has been banned. Contact support.",
        "email_exists":"This email is already registered","my_id":"My User ID",
        "edit_profile":"Edit Profile","old_password":"Current Password","new_password":"New Password",
        "total_earned":"Total Earned","total_withdrawn":"Total Withdrawn",
        "referral_earned":"Referral Bonus Earned","select_language":"Language",
    },
    "ha": {
        "app_name":"SocialPay","tagline":"Samu Kuɗi ta Hanyar Ayyukan Social Media",
        "login":"Shiga","register":"Ƙirƙiri Account","email":"Adireshin Email","password":"Password",
        "full_name":"Cikakken Suna","confirm_password":"Tabbatar da Password",
        "referral_code":"Lambar Kiran Aboki (zaɓi)","create_account":"Ƙirƙiri Account Yanzu",
        "login_now":"Shiga Yanzu","welcome_back":"Barka da dawowa","total_balance":"Jimillar Kuɗi",
        "tasks":"Ayyuka","balance":"Kuɗi","transfer":"Aika","referrals":"Kiraye",
        "withdraw":"Cire","exchange":"Canza","profile":"Profile","history":"Tarihi",
        "notifications":"Sanarwa","logout":"Fita","available_tasks":"Ayyukan da Samu",
        "my_earnings":"Kuɗaɗena","completed_tasks":"Ayyuka Kammala","pending_tasks":"Jira",
        "send_proof":"Aika Shaida","proof_placeholder":"Link, username, ko hanyar screenshot...",
        "submit":"Aika don Bincike","withdraw_money":"Fitar da Kuɗi",
        "exchange_currency":"Canza Kuɗi","send_money":"Aika Kuɗi","receiver_id":"ID na Mai Karɓa",
        "amount":"Adadi","pin":"PIN haruffa 4","send_now":"Aika Yanzu","cancel":"Soke","save":"Ajiye",
        "set_pin":"Saita PIN","change_pin":"Canza PIN","bank_details":"Bayanin Banku / Kuɗi",
        "bank_name":"Sunan Banku","account_number":"Lambar Akwatin Kuɗi","account_name":"Suna a Banku",
        "payment_type":"Nau'in Kuɗi","referral_link":"Hanyar Kiran Ku","copy":"Kwafa",
        "share_whatsapp":"WhatsApp","share_telegram":"Telegram",
        "how_referral_works":"Yadda Ake Samun Lada","reward":"Lada","status":"Yanayi",
        "pending":"Jira","approved":"An Amince","rejected":"An Ƙi","no_tasks":"Babu Ayyuka a Yanzu",
        "no_tasks_desc":"Duba baya! Admin zai ƙara ayyuka sabon.","no_notifications":"Babu Sanarwa",
        "fill_all_fields":"Cika duk filayen da ake bukata",
        "password_short":"Password ya zama akalla haruffa 8",
        "task_submitted":"Aiki an aika! Ana jiran amincewa admin.",
        "already_submitted":"Kun riga kun aika wannan aiki","insufficient_balance":"Kudinka ba ya isawa",
        "withdraw_min":"Mafi ƙarancin ficewa shine","pin_required":"Kana buƙatar saita PIN da farko",
        "pin_wrong":"PIN ba daidai ba","pin_set":"PIN an saita cikin nasara!",
        "pin_4digits":"PIN dole ne ya zama lamba 4","profile_updated":"Profile an sabunta!",
        "bank_saved":"Bayanin banku an ajiye!","balance_adjusted":"Balance an gyara!",
        "user_banned":"User an hana shi","user_unbanned":"An sake bude account",
        "pin_reset":"PIN an share","message_sent":"Saƙo an aika!","task_created":"Aiki an ƙirƙira!",
        "task_deleted":"Aiki an goge!","submission_approved":"An amince! Kuɗi an ƙara.",
        "submission_rejected":"An ƙi buƙatar.","withdrawal_approved":"Ficewa an amince!",
        "withdrawal_rejected":"Ficewa an ƙi. Kuɗi an mayar.","transfer_reversed":"Transfer an mayar!",
        "broadcast_sent":"Sanarwa an aika!","settings_saved":"Settings an ajiye!",
        "money_sent":"Kuɗi an aika cikin nasara!","exchanged":"An canza kuɗi!",
        "user_not_found":"User ba ya wanzu","cannot_send_self":"Ba za ka iya aika wa kanka ba",
        "admin_notice":"Sanarwa daga Admin","from_admin":"Daga Admin",
        "referral_bonus_earned":"Lada kira an samu!","withdrawal_request":"Buƙatar ficewa an aika!",
        "wrong_email_or_password":"Email ko password ba daidai ba",
        "account_banned":"An hana account dinku. Tuntuɓi support.",
        "email_exists":"Email din nan an riga an yi rajistar da shi","my_id":"ID na",
        "edit_profile":"Gyara Profile","old_password":"Tsohon Password","new_password":"Sabon Password",
        "total_earned":"Jimlar Samun","total_withdrawn":"Jimlar Ficewa",
        "referral_earned":"Lada Kira da Aka Samu","select_language":"Harshe",
    },
    "ar": {
        "app_name":"سوشيال باي","tagline":"اكسب المال عبر مهام وسائل التواصل الاجتماعي",
        "login":"تسجيل الدخول","register":"إنشاء حساب","email":"البريد الإلكتروني",
        "password":"كلمة المرور","full_name":"الاسم الكامل","confirm_password":"تأكيد كلمة المرور",
        "referral_code":"رمز الإحالة (اختياري)","create_account":"إنشاء الحساب",
        "login_now":"تسجيل الدخول الآن","welcome_back":"مرحباً بعودتك","total_balance":"إجمالي الرصيد",
        "tasks":"المهام","balance":"الرصيد","transfer":"تحويل","referrals":"الإحالات",
        "withdraw":"سحب","exchange":"تبادل","profile":"الملف الشخصي","history":"التاريخ",
        "notifications":"الإشعارات","logout":"تسجيل الخروج","available_tasks":"المهام المتاحة",
        "my_earnings":"أرباحي","completed_tasks":"المهام المكتملة","pending_tasks":"قيد الانتظار",
        "send_proof":"إرسال الدليل","proof_placeholder":"رابط، اسم مستخدم...",
        "submit":"إرسال للمراجعة","withdraw_money":"سحب الأموال","exchange_currency":"تبادل العملات",
        "send_money":"إرسال المال","receiver_id":"معرّف المستلم","amount":"المبلغ",
        "pin":"رمز PIN المكون من 4 أرقام","send_now":"إرسال الآن","cancel":"إلغاء","save":"حفظ",
        "set_pin":"تعيين PIN","change_pin":"تغيير PIN","bank_details":"تفاصيل البنك / الدفع",
        "bank_name":"اسم البنك","account_number":"رقم الحساب","account_name":"اسم صاحب الحساب",
        "payment_type":"نوع الدفع","referral_link":"رابط الإحالة الخاص بك","copy":"نسخ",
        "share_whatsapp":"واتساب","share_telegram":"تيليغرام","how_referral_works":"كيف تعمل الإحالات",
        "reward":"المكافأة","status":"الحالة","pending":"قيد الانتظار","approved":"مقبول","rejected":"مرفوض",
        "no_tasks":"لا توجد مهام متاحة","no_tasks_desc":"تحقق لاحقاً!","no_notifications":"لا توجد إشعارات",
        "fill_all_fields":"يرجى ملء جميع الحقول المطلوبة",
        "password_short":"يجب أن تكون كلمة المرور 8 أحرف على الأقل",
        "task_submitted":"تم إرسال المهمة! في انتظار مراجعة المسؤول.",
        "already_submitted":"لقد أرسلت هذه المهمة بالفعل","insufficient_balance":"رصيد غير كافٍ",
        "withdraw_min":"الحد الأدنى للسحب هو","pin_required":"تحتاج إلى تعيين PIN أولاً",
        "pin_wrong":"PIN خاطئ","pin_set":"تم تعيين PIN بنجاح!",
        "pin_4digits":"يجب أن يكون PIN مكوناً من 4 أرقام بالضبط",
        "profile_updated":"تم تحديث الملف الشخصي!","bank_saved":"تم حفظ تفاصيل البنك!",
        "balance_adjusted":"تم تعديل الرصيد!","user_banned":"تم حظر المستخدم",
        "user_unbanned":"تم رفع الحظر عن المستخدم","pin_reset":"تم إعادة تعيين PIN",
        "message_sent":"تم إرسال الرسالة!","task_created":"تم إنشاء المهمة!","task_deleted":"تم حذف المهمة!",
        "submission_approved":"تمت الموافقة! تم إضافة الدفع.","submission_rejected":"تم رفض الطلب.",
        "withdrawal_approved":"تمت الموافقة على السحب!","withdrawal_rejected":"تم رفض السحب.",
        "transfer_reversed":"تم عكس التحويل!","broadcast_sent":"تم إرسال الرسالة الجماعية!",
        "settings_saved":"تم حفظ الإعدادات!","money_sent":"تم إرسال المال بنجاح!",
        "exchanged":"تم تبادل العملة!","user_not_found":"المستخدم غير موجود",
        "cannot_send_self":"لا يمكنك الإرسال لنفسك","admin_notice":"إشعار من الإدارة",
        "from_admin":"من الإدارة","referral_bonus_earned":"تم كسب مكافأة الإحالة!",
        "withdrawal_request":"تم تقديم طلب السحب!","wrong_email_or_password":"البريد الإلكتروني أو كلمة المرور خاطئة","approve":"موافقة","reject":"رفض","reverse":"عكس","transfers_log":"سجل التحويلات","refunded":"مُسترد",
        "account_banned":"تم حظر حسابك. تواصل مع الدعم.","email_exists":"هذا البريد الإلكتروني مسجل بالفعل",
        "my_id":"معرّف المستخدم","edit_profile":"تعديل الملف الشخصي",
        "old_password":"كلمة المرور الحالية","new_password":"كلمة مرور جديدة",
        "total_earned":"إجمالي الأرباح","total_withdrawn":"إجمالي المسحوب",
        "referral_earned":"مكافأة الإحالة المكتسبة","select_language":"اللغة",
    }
}

def t(key, lang=None):
    if lang is None:
        lang = session.get("lang", "en")
    # Fix #16: strict language separation
    # Arabic: only Arabic translations
    # Hausa: Hausa with English fallback (never Arabic)
    # English: only English
    lang_dict = TRANSLATIONS.get(lang, {})
    en_dict = TRANSLATIONS.get("en", {})
    if lang == "ar":
        return lang_dict.get(key, en_dict.get(key, key))
    elif lang == "ha":
        return lang_dict.get(key, en_dict.get(key, key))
    else:
        return en_dict.get(key, key)

app.jinja_env.globals["t"] = t
app.jinja_env.globals["session"] = session

# ============================================================
# UTILITIES
# ============================================================
def now_str(): return datetime.now().isoformat()
def short_id(): return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

# ── Password hashing (v6) ───────────────────────────────────────────────────
# New hashes use werkzeug pbkdf2:sha256.
# Existing v5 hashes (salt$hexdigest) are still verified so no forced reset.
def hash_pw(pw):
    """Hash password using werkzeug's secure pbkdf2:sha256."""
    return generate_password_hash(pw, method="pbkdf2:sha256:260000")

def verify_pw(pw, stored):
    """
    Verify password against stored hash.
    Supports both werkzeug format (new) and legacy salt$hex format (v5).
    """
    if not stored:
        return False
    try:
        if stored.startswith("pbkdf2:") or stored.startswith("scrypt:"):
            # werkzeug format
            return check_password_hash(stored, pw)
        # Legacy v5 format: salt$hexdigest
        parts = stored.split("$", 1)
        if len(parts) == 2:
            salt, sh = parts
            h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100000)
            return h.hex() == sh
        return False
    except Exception:
        return False

# ── CSRF helpers ────────────────────────────────────────────────────────────
def generate_csrf_token():
    """Generate and store a CSRF token in the session."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]

def validate_csrf():
    """
    Validate CSRF token on state-changing POST requests.
    Token can be sent as form field '_csrf_token' or header 'X-CSRF-Token'.
    JSON/AJAX requests that send the token via header are accepted.
    Returns True if valid, False otherwise.
    """
    expected = session.get("csrf_token")
    if not expected:
        return False
    received = (request.form.get("_csrf_token") or
                request.headers.get("X-CSRF-Token") or
                (request.json or {}).get("_csrf_token", "") if request.is_json else "")
    return secrets.compare_digest(expected, received) if received else False

# Expose generate_csrf_token to all templates
app.jinja_env.globals["csrf_token"] = generate_csrf_token

def get_app_name():
    """Get current app name from settings (falls back to APP_NAME constant)."""
    db = get_db()
    row = db.execute("SELECT value FROM settings WHERE key='site_name'").fetchone()
    db.close()
    return row["value"] if row and row["value"] else APP_NAME

app.jinja_env.globals["get_app_name"] = get_app_name

def get_settings():
    defaults = {
        "referral_bonus": "30", "referral_bonus_l2": "15",
        "referral_tasks_needed": "10", "withdrawal_fee_percent": "5",
        "min_withdrawal": "500", "max_withdrawal": "100000",
        "exchange_rate": "1500", "site_name": "SocialPay",
        "maintenance": "0", "announcement": "",
        "signup_reward_enabled": "1", "signup_reward_amount": "50",
        "daily_login_enabled": "1", "daily_login_reward": "10",
        "spin_enabled": "1", "spin_cost": "50",
        "spin_prizes": "10,50,100,200,500,1000",
        "spin_daily_limit": "0",
    }
    db = get_db()
    rows = db.execute("SELECT key, value FROM settings").fetchall()
    db.close()
    for r in rows:
        defaults[r["key"]] = r["value"]
    # Parse types
    result = {}
    for k, v in defaults.items():
        try:
            if k in ["maintenance","signup_reward_enabled","daily_login_enabled","spin_enabled"]:
                result[k] = bool(int(v))
            elif k == "spin_prizes":
                result[k] = [int(x.strip()) for x in str(v).split(",") if x.strip()]
            elif k in ["referral_bonus","referral_bonus_l2","withdrawal_fee_percent","min_withdrawal",
                       "max_withdrawal","exchange_rate","signup_reward_amount","daily_login_reward"]:
                result[k] = float(v)
            elif k in ["referral_tasks_needed","spin_cost","spin_daily_limit"]:
                result[k] = int(float(v))
            else:
                result[k] = v
        except:
            result[k] = v
    return result

def save_setting(key, value):
    db = get_db()
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str(value)))
    db.commit()
    db.close()

def add_notif(user_id, message, ntype="info"):
    db = get_db()
    nid = f"N_{short_id()}"
    db.execute("INSERT INTO notifications(id,user_id,message,type,time,read) VALUES(?,?,?,?,?,0)",
               (nid, user_id, message, ntype, now_str()))
    # Keep only last 50
    db.execute("""DELETE FROM notifications WHERE user_id=? AND id NOT IN
                  (SELECT id FROM notifications WHERE user_id=? ORDER BY time DESC LIMIT 50)""",
               (user_id, user_id))
    db.commit()
    db.close()

def log_audit(action, uid, detail="", amount=0):
    db = get_db()
    lid = f"L_{short_id()}"
    db.execute("INSERT INTO audit_logs(id,action,user_id,detail,amount,time) VALUES(?,?,?,?,?,?)",
               (lid, action, uid, detail, amount, now_str()))
    db.commit()
    db.close()

def add_transaction(uid, txtype, amount, currency, description, ref_id=""):
    db = get_db()
    txid = f"TX_{short_id()}"
    db.execute("INSERT INTO transactions(id,user_id,type,amount,currency,description,ref_id,time,status) VALUES(?,?,?,?,?,?,?,?,?)",
               (txid, uid, txtype, amount, currency, description, ref_id, now_str(), "completed"))
    db.commit()
    db.close()

def get_wallet(uid):
    db = get_db()
    w = db.execute("SELECT * FROM wallets WHERE user_id=?", (uid,)).fetchone()
    if not w:
        db.execute("INSERT OR IGNORE INTO wallets(user_id,naira,dollar,completed_tasks,pending_tasks,referral_count,referral_count_l2,referral_bonus_earned,total_earned,total_withdrawn,created) VALUES(?,0,0,0,0,0,0,0,0,0,?)",
                   (uid, now_str()))
        db.commit()
        w = db.execute("SELECT * FROM wallets WHERE user_id=?", (uid,)).fetchone()
    db.close()
    return dict(w) if w else {}

def upd_wallet(uid, field, amount, absolute=False):
    db = get_db()
    if absolute:
        db.execute(f"UPDATE wallets SET {field}=? WHERE user_id=?", (amount, uid))
    else:
        db.execute(f"UPDATE wallets SET {field}=MAX(0,{field}+?) WHERE user_id=?", (amount, uid))
    if db.execute("SELECT changes()").fetchone()[0] == 0:
        get_wallet(uid)
        db.execute(f"UPDATE wallets SET {field}=MAX(0,{field}+?) WHERE user_id=?", (amount, uid))
    db.commit()
    db.close()

def get_spin_prizes(settings=None):
    if settings is None:
        settings = get_settings()
    prizes_amounts = settings.get("spin_prizes", [10, 50, 100, 200, 500, 1000])
    prob_map = {0: 50, 1: 30, 2: 10, 3: 5, 4: 3, 5: 2}
    pool = []
    for i, amt in enumerate(prizes_amounts):
        prob = prob_map.get(i, 1)
        pool.append({"label": f"₦{amt:,}", "amount": amt, "prob": prob})
    pool.append({"label": "Try Again", "amount": 0, "prob": 2})
    return pool

# ============================================================
# AUTH DECORATORS
# ============================================================
def login_required(f):
    @wraps(f)
    def deco(*args, **kwargs):
        if "user_id" not in session: return redirect(url_for("login"))
        # Check banned
        db = get_db()
        u = db.execute("SELECT banned, is_admin FROM users WHERE id=?", (session["user_id"],)).fetchone()
        db.close()
        if u and u["banned"] and not u["is_admin"]:
            return render_template("banned.html", lang=session.get("lang","en"))
        # Check maintenance (skip for admin)
        if u and not u["is_admin"]:
            s = get_settings()
            if s.get("maintenance"):
                return render_template("maintenance.html", lang=session.get("lang","en"))
        return f(*args, **kwargs)
    return deco

def admin_required(f):
    @wraps(f)
    def deco(*args, **kwargs):
        if "user_id" not in session: return redirect(url_for("login"))
        db = get_db()
        u = db.execute("SELECT is_admin FROM users WHERE id=?", (session["user_id"],)).fetchone()
        db.close()
        if not u or not u["is_admin"]:
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return deco

# ============================================================
# ENSURE ADMIN
# ============================================================
def ensure_admin():
    db = get_db()
    admin = db.execute("SELECT id FROM users WHERE email=? AND is_admin=1",
                       (ADMIN_EMAIL.lower(),)).fetchone()
    if not admin:
        aid = "SP00000001"
        pw_hash = hash_pw(ADMIN_PASSWORD)
        db.execute("""INSERT OR IGNORE INTO users(id,name,email,password,is_admin,role,banned,verified,created,last_login,referral_code,referred_by,lang,signup_reward_given)
                      VALUES(?,?,?,?,1,'super_admin',0,1,?,?,?,NULL,'en',1)""",
                   (aid, ADMIN_NAME, ADMIN_EMAIL.lower(), pw_hash, now_str(), now_str(), aid))
        db.execute("INSERT OR IGNORE INTO wallets(user_id,created) VALUES(?,?)", (aid, now_str()))
        db.commit()
        print(f"[SETUP] Admin created: {ADMIN_EMAIL}")
    db.close()

@app.before_request
def keep_session_alive():
    session.permanent = True
    session.modified = True
    # Auto-generate CSRF token for every session
    generate_csrf_token()

# ============================================================
# ROUTES
# ============================================================
@app.route("/set_lang/<lang>")
def set_lang(lang):
    if lang in ["en", "ar", "ha"]:
        session["lang"] = lang
        if "user_id" in session:
            db = get_db()
            db.execute("UPDATE users SET lang=? WHERE id=?", (lang, session["user_id"]))
            db.commit()
            db.close()
    return redirect(request.referrer or url_for("index"))

@app.route("/r/<refcode>")
def referral_url(refcode):
    return redirect(url_for("register") + f"?ref={refcode}")

@app.route("/")
def index():
    if "user_id" in session:
        if session.get("is_admin"):
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        lang = session.get("lang", "en")
        if not email or not password:
            return jsonify({"success": False, "message": t("fill_all_fields", lang)})
        db = get_db()
        u = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        db.close()
        if not u:
            return jsonify({"success": False, "message": t("wrong_email_or_password", lang)})
        if not verify_pw(password, u["password"]):
            return jsonify({"success": False, "message": t("wrong_email_or_password", lang)})
        if u["banned"]:
            return jsonify({"success": False, "message": t("account_banned", lang)})
        session.permanent = True
        lang = u["lang"] or "en"
        session["lang"] = lang
        session["user_id"] = u["id"]
        session["user_name"] = u["name"]
        session["is_admin"] = bool(u["is_admin"])
        session["role"] = u["role"]
        db = get_db()
        db.execute("UPDATE users SET last_login=? WHERE id=?", (now_str(), u["id"]))
        db.commit()
        db.close()
        log_audit("login", u["id"])
        _check_daily_login(u["id"])
        redir = url_for("admin_dashboard") if u["is_admin"] else url_for("dashboard")
        return jsonify({"success": True, "redirect": redir})
    lang = session.get("lang", "en")
    return render_template("login.html", lang=lang)

def _check_daily_login(uid):
    """Mark user as eligible for daily login reward (does NOT auto-credit)."""
    settings = get_settings()
    if not settings.get("daily_login_enabled"): return
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    dl = db.execute("SELECT * FROM daily_logins WHERE user_id=?", (uid,)).fetchone()
    if dl and dl["last_date"] == today:
        db.close(); return
    # Mark as eligible but don't credit yet - user must manually claim
    total_days = (dl["total_days"] + 1) if dl else 1
    db.execute("INSERT OR REPLACE INTO daily_logins(user_id,last_date,total_days) VALUES(?,?,?)",
               (uid, f"PENDING_{today}", total_days))
    db.commit()
    db.close()

@app.route("/claim_daily", methods=["POST"])
@login_required
def claim_daily():
    uid = session["user_id"]
    lang = session.get("lang","en")
    settings = get_settings()
    if not settings.get("daily_login_enabled"):
        return jsonify({"success": False, "message": "Daily reward is disabled."})
    today = datetime.now().strftime("%Y-%m-%d")
    db = get_db()
    dl = db.execute("SELECT * FROM daily_logins WHERE user_id=?", (uid,)).fetchone()
    db.close()
    if not dl or dl["last_date"] != f"PENDING_{today}":
        return jsonify({"success": False, "message": "No reward to claim today, or already claimed."})
    reward = float(settings.get("daily_login_reward", 10))
    total_days = dl["total_days"]
    db = get_db()
    db.execute("UPDATE daily_logins SET last_date=? WHERE user_id=?", (today, uid))
    db.commit(); db.close()
    upd_wallet(uid, "naira", reward)
    upd_wallet(uid, "total_earned", reward)
    add_transaction(uid, "credit", reward, "naira", f"Daily login reward Day {total_days}")
    add_notif(uid, f"🎁 Daily login reward claimed: +₦{reward:.0f}", "success")
    return jsonify({"success": True, "message": f"🎁 +₦{reward:.0f} Daily Reward Claimed!", "reward": reward})

@app.route("/register", methods=["GET", "POST"])
def register():
    lang = session.get("lang", "en")
    if "user_id" in session:
        if session.get("is_admin"):
            return redirect(url_for("admin_dashboard")) if request.method=="GET" else jsonify({"success":False,"message":"Already logged in"})
        return redirect(url_for("dashboard")) if request.method=="GET" else jsonify({"success":False,"message":"Already logged in"})
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        name = request.form.get("name","").strip()[:100]
        ref_code = request.form.get("ref","").strip()
        if not email or not password or not name:
            return jsonify({"success":False,"message":t("fill_all_fields",lang)})
        if len(password) < 8:
            return jsonify({"success":False,"message":t("password_short",lang)})
        if "@" not in email:
            return jsonify({"success":False,"message":t("fill_all_fields",lang)})
        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            db.close()
            return jsonify({"success":False,"message":t("email_exists",lang)})
        uid = f"SP{short_id()}"
        db.execute("""INSERT INTO users(id,name,email,password,is_admin,role,banned,verified,created,last_login,referral_code,referred_by,lang,signup_reward_given)
                      VALUES(?,?,?,?,0,'user',0,1,?,?,?,NULL,?,0)""",
                   (uid, name, email, hash_pw(password), now_str(), now_str(), uid, lang))
        db.execute("INSERT INTO wallets(user_id,created) VALUES(?,?)", (uid, now_str()))
        # Multi-level referrals
        if ref_code and ref_code != uid:
            referrer = db.execute("SELECT id,referred_by FROM users WHERE referral_code=? OR id=?",
                                  (ref_code, ref_code)).fetchone()
            if referrer:
                ref_uid = referrer["id"]
                db.execute("UPDATE users SET referred_by=? WHERE id=?", (ref_uid, uid))
                db.execute("INSERT INTO referrals(referrer_id,referred_id,level,time,bonus_paid,tasks_done) VALUES(?,?,1,?,0,0)",
                           (ref_uid, uid, now_str()))
                db.execute("UPDATE wallets SET referral_count=referral_count+1 WHERE user_id=?", (ref_uid,))
                # L2
                l2_id = referrer["referred_by"]
                if l2_id:
                    db.execute("INSERT INTO referrals(referrer_id,referred_id,level,time,bonus_paid,tasks_done) VALUES(?,?,2,?,0,0)",
                               (l2_id, uid, now_str()))
                    db.execute("UPDATE wallets SET referral_count_l2=referral_count_l2+1 WHERE user_id=?", (l2_id,))
        db.commit()
        db.close()
        # Sign-up reward
        settings = get_settings()
        if settings.get("signup_reward_enabled"):
            reward = float(settings.get("signup_reward_amount", 50))
            upd_wallet(uid, "naira", reward)
            upd_wallet(uid, "total_earned", reward)
            add_transaction(uid, "credit", reward, "naira", "Sign-up welcome bonus")
            add_notif(uid, f"🎉 Welcome bonus: +₦{reward:.0f}", "success")
        session.permanent = True
        session["user_id"] = uid; session["user_name"] = name
        session["is_admin"] = False; session["role"] = "user"
        add_notif(uid, f"🎉 Welcome to {APP_NAME}! Start earning today.", "success")
        log_audit("register", uid)
        return jsonify({"success":True,"redirect":url_for("dashboard"),"message":f"Account created for {name}"})
    return render_template("login.html", lang=lang, tab="register")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    uid = session["user_id"]
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if user and user["is_admin"]:
        db.close()
        return redirect(url_for("admin_dashboard"))
    wallet = get_wallet(uid)
    unread = db.execute("SELECT COUNT(*) as c FROM notifications WHERE user_id=? AND read=0", (uid,)).fetchone()["c"]
    pending_wd = db.execute("SELECT COUNT(*) as c FROM withdrawals WHERE user_id=? AND status='pending'", (uid,)).fetchone()["c"]
    dl = db.execute("SELECT * FROM daily_logins WHERE user_id=?", (uid,)).fetchone()
    today = datetime.now().strftime("%Y-%m-%d")
    # daily_claimed = fully claimed today; daily_eligible = pending claim available
    daily_claimed = dl and dl["last_date"] == today
    daily_eligible = dl and dl["last_date"] == f"PENDING_{today}"
    daily_days = dl["total_days"] if dl else 0
    # Top earners for display (masked names)
    top_earners = db.execute("""SELECT u.name, w.total_earned FROM wallets w
                                JOIN users u ON w.user_id=u.id
                                WHERE u.is_admin=0 AND w.total_earned>0
                                ORDER BY w.total_earned DESC LIMIT 10""").fetchall()
    db.close()
    settings = get_settings()
    spin_cost = int(settings.get("spin_cost", 50))
    SPIN_PRIZES = get_spin_prizes(settings)
    spin_prizes_js = [{"label": p["label"], "amount": p["amount"]} for p in SPIN_PRIZES]
    lang = session.get("lang", "en")
    app_name = get_app_name()
    # Mask names: show first 3 chars + ***
    def mask_name(n):
        return (n[:3] + "***") if len(n) > 3 else (n[0] + "**")
    earners = [{"name": mask_name(r["name"]), "earned": r["total_earned"]} for r in top_earners]
    return render_template("dashboard.html", user=dict(user), wallet=wallet,
                            unread=unread, pending_wd=pending_wd,
                            announcement=settings.get("announcement",""), lang=lang,
                            daily_claimed=daily_claimed, daily_eligible=daily_eligible,
                            daily_days=daily_days,
                            settings=settings, spin_cost=spin_cost, spin_prizes_js=spin_prizes_js,
                            tg_channel=TG_CHANNEL, tg_group=TG_GROUP, tg_support=TG_SUPPORT,
                            app_name=app_name, earners=earners)

@app.route("/tasks")
@login_required
def tasks_page():
    uid = session["user_id"]
    db = get_db()
    now = now_str()
    rows = db.execute("""SELECT t.*, (SELECT COUNT(*) FROM task_completions WHERE task_id=t.id) as completed_count2
                         FROM tasks t WHERE t.status='active' AND (t.expires_at IS NULL OR t.expires_at > ?)
                         AND t.id NOT IN (SELECT task_id FROM submissions WHERE user_id=? AND status!='rejected')
                         AND (t.max_users > (SELECT COUNT(*) FROM task_completions WHERE task_id=t.id))""",
                      (now, uid)).fetchall()
    db.close()
    available = []
    now_dt = datetime.now()
    for r in rows:
        tc = dict(r)
        if tc.get("expires_at"):
            delta = datetime.fromisoformat(tc["expires_at"]) - now_dt
            tc["time_left"] = int(delta.total_seconds())
            tc["completed_by"] = []
        else:
            tc["time_left"] = None
            tc["completed_by"] = []
        available.append(tc)
    lang = session.get("lang","en")
    return render_template("tasks.html", tasks=available, lang=lang)

@app.route("/upload_screenshot", methods=["POST"])
@login_required
def upload_screenshot():
    """Handle screenshot upload with auto compression."""
    import base64, io
    try:
        data = request.get_json(force=True) or {}
        img_data = data.get("image","")
        if not img_data:
            return jsonify({"success": False, "message": "No image provided"})
        # Strip data URI prefix
        if "," in img_data:
            header, b64 = img_data.split(",", 1)
        else:
            b64 = img_data
        raw = base64.b64decode(b64)
        # Try PIL compression
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(raw))
            # Convert to RGB if needed
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            # Resize if too large (max 1200px wide)
            if img.width > 1200:
                ratio = 1200 / img.width
                new_h = int(img.height * ratio)
                img = img.resize((1200, new_h), Image.LANCZOS)
            # Save compressed
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75, optimize=True)
            compressed = buf.getvalue()
            # Only use compressed if it's smaller
            if len(compressed) < len(raw):
                raw = compressed
                b64 = base64.b64encode(raw).decode()
                img_data = "data:image/jpeg;base64," + b64
        except Exception:
            pass  # PIL not available or error — use original
        # Check final size (max 2MB as data URI)
        if len(img_data) > 2 * 1024 * 1024:
            return jsonify({"success": False, "message": "Image too large even after compression. Please use a smaller screenshot."})
        return jsonify({"success": True, "image": img_data})
    except Exception as e:
        return jsonify({"success": False, "message": f"Upload error: {str(e)}"})

@app.route("/submit_task", methods=["POST"])
@login_required
def submit_task():
    uid = session["user_id"]
    task_id = request.form.get("task_id")
    proof = request.form.get("proof","").strip()
    lang = session.get("lang","en")
    screenshot = request.form.get("screenshot","")
    # Fix #7: only screenshot is valid proof (text proof removed)
    if not task_id or not screenshot:
        return jsonify({"success":False,"message":"Please upload a screenshot as proof."})
    proof = proof or "Screenshot submitted"
    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        db.close()
        return jsonify({"success":False,"message":"Task not found"})
    existing = db.execute("SELECT id FROM submissions WHERE user_id=? AND task_id=? AND status!='rejected'",
                          (uid, task_id)).fetchone()
    if existing:
        db.close()
        return jsonify({"success":False,"message":t("already_submitted",lang)})
    # Fix #15: if max_users==1, only one user can complete it; others blocked unless first is rejected
    if task["max_users"] == 1:
        approved_or_pending = db.execute(
            "SELECT id FROM submissions WHERE task_id=? AND status IN ('pending','approved')", (task_id,)
        ).fetchone()
        if approved_or_pending:
            db.close()
            return jsonify({"success":False,"message":"This task is already taken. You can submit only if the first submission is rejected."})
    sid = f"SUB_{short_id()}"
    ss = screenshot if (screenshot and len(screenshot) <= 2*1024*1024) else ""
    if task["auto_approve"]:
        db.execute("""INSERT INTO submissions(id,user_id,task_id,proof,screenshot,status,reward,currency,submitted_at,reviewed_at,note)
                      VALUES(?,?,?,?,?,'approved',?,?,?,?,?)""",
                   (sid, uid, task_id, proof[:1000], ss, task["reward"], task["currency"], now_str(), now_str(), "Auto approved"))
        db.execute("INSERT OR IGNORE INTO task_completions(task_id,user_id) VALUES(?,?)", (task_id, uid))
        db.execute("UPDATE tasks SET completed_count=completed_count+1 WHERE id=?", (task_id,))
        db.commit()
        db.close()
        upd_wallet(uid, task["currency"], task["reward"])
        upd_wallet(uid, "completed_tasks", 1)
        upd_wallet(uid, "total_earned", task["reward"])
        add_transaction(uid, "credit", task["reward"], task["currency"], f"Task auto-approved: {task['title']}", sid)
        _check_referral_bonus(uid, lang)
        sym = "₦" if task["currency"]=="naira" else "$"
        add_notif(uid, f"✅ Auto approved! +{sym}{task['reward']:,.0f}", "success")
        db2 = get_db()
        db2.execute("UPDATE submissions SET screenshot='' WHERE id=?", (sid,))
        db2.commit()
        db2.close()
        return jsonify({"success":True,"message":f"Task approved! +{sym}{task['reward']:,.0f}"})
    db.execute("""INSERT INTO submissions(id,user_id,task_id,proof,screenshot,status,reward,currency,submitted_at,reviewed_at,note)
                  VALUES(?,?,?,?,?,'pending',?,?,?,NULL,'')""",
               (sid, uid, task_id, proof[:1000], ss, task["reward"], task["currency"], now_str()))
    db.commit()
    db.close()
    upd_wallet(uid, "pending_tasks", 1)
    add_notif(uid, f"✅ {t('task_submitted',lang)}", "info")
    log_audit("task_submitted", uid, task_id, task["reward"])
    return jsonify({"success":True,"message":t("task_submitted",lang)})

def _check_referral_bonus(uid, lang="en"):
    settings = get_settings()
    db = get_db()
    user = db.execute("SELECT referred_by FROM users WHERE id=?", (uid,)).fetchone()
    if not user or not user["referred_by"]:
        db.close(); return
    ref_by = user["referred_by"]
    ref_rec = db.execute("SELECT * FROM referrals WHERE referrer_id=? AND referred_id=? AND level=1 AND bonus_paid=0",
                         (ref_by, uid)).fetchone()
    if ref_rec:
        new_done = ref_rec["tasks_done"] + 1
        db.execute("UPDATE referrals SET tasks_done=? WHERE id=?", (new_done, ref_rec["id"]))
        if new_done >= settings["referral_tasks_needed"]:
            db.execute("UPDATE referrals SET bonus_paid=1 WHERE id=?", (ref_rec["id"],))
            bonus = float(settings["referral_bonus"])
            db.commit()
            db.close()
            upd_wallet(ref_by, "naira", bonus)
            upd_wallet(ref_by, "referral_bonus_earned", bonus)
            upd_wallet(ref_by, "total_earned", bonus)
            add_transaction(ref_by, "credit", bonus, "naira", "L1 referral bonus")
            add_notif(ref_by, f"🎁 L1 Referral bonus! +₦{bonus:.0f}", "success")
        else:
            db.commit()
            db.close()
    else:
        db.close()
    # L2
    db2 = get_db()
    ref_by_user = db2.execute("SELECT referred_by FROM users WHERE id=?", (ref_by,)).fetchone()
    if ref_by_user and ref_by_user["referred_by"]:
        l2_id = ref_by_user["referred_by"]
        ref_rec2 = db2.execute("SELECT * FROM referrals WHERE referrer_id=? AND referred_id=? AND level=2 AND bonus_paid=0",
                               (l2_id, uid)).fetchone()
        if ref_rec2:
            new_done2 = ref_rec2["tasks_done"] + 1
            db2.execute("UPDATE referrals SET tasks_done=? WHERE id=?", (new_done2, ref_rec2["id"]))
            if new_done2 >= settings["referral_tasks_needed"]:
                db2.execute("UPDATE referrals SET bonus_paid=1 WHERE id=?", (ref_rec2["id"],))
                bonus_l2 = float(settings.get("referral_bonus_l2", 15))
                db2.commit()
                db2.close()
                upd_wallet(l2_id, "naira", bonus_l2)
                upd_wallet(l2_id, "referral_bonus_earned", bonus_l2)
                upd_wallet(l2_id, "total_earned", bonus_l2)
                add_transaction(l2_id, "credit", bonus_l2, "naira", "L2 referral bonus")
                add_notif(l2_id, f"🎁 L2 Referral bonus! +₦{bonus_l2:.0f}", "success")
            else:
                db2.commit()
                db2.close()
        else:
            db2.close()
    else:
        db2.close()

@app.route("/balance")
@login_required
def balance_page():
    uid = session["user_id"]
    wallet = get_wallet(uid)
    db = get_db()
    withdrawals = db.execute("SELECT * FROM withdrawals WHERE user_id=? ORDER BY requested_at DESC LIMIT 20", (uid,)).fetchall()
    transfers_sent = db.execute("SELECT t.*,u.name as rname FROM transfers t LEFT JOIN users u ON t.receiver_id=u.id WHERE t.sender_id=? ORDER BY t.time DESC LIMIT 10", (uid,)).fetchall()
    transfers_recv = db.execute("SELECT t.*,u.name as sname FROM transfers t LEFT JOIN users u ON t.sender_id=u.id WHERE t.receiver_id=? ORDER BY t.time DESC LIMIT 10", (uid,)).fetchall()
    transactions = db.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY time DESC LIMIT 50", (uid,)).fetchall()
    db.close()
    settings = get_settings()
    lang = session.get("lang","en")
    return render_template("balance.html", wallet=wallet,
                            withdrawals=[dict(r) for r in withdrawals],
                            transfers_sent=[dict(r) for r in transfers_sent],
                            transfers_recv=[dict(r) for r in transfers_recv],
                            transactions=[dict(r) for r in transactions],
                            settings=settings, lang=lang)

@app.route("/withdraw", methods=["POST"])
@login_required
def withdraw():
    uid = session["user_id"]
    lang = session.get("lang","en")
    try:
        amount = float(request.form.get("amount",0))
    except (ValueError, TypeError):
        return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    currency = request.form.get("currency","naira")
    bank_info = request.form.get("bank_info","").strip()
    pin = request.form.get("pin","")
    settings = get_settings()
    wallet = get_wallet(uid)
    # --- PIN check ---
    db = get_db()
    pin_rec = db.execute("SELECT pin_hash FROM pins WHERE user_id=?", (uid,)).fetchone()
    db.close()
    if not pin_rec:
        return jsonify({"success":False,"message":t("pin_required",lang)})
    if not verify_pw(pin, pin_rec["pin_hash"]):
        return jsonify({"success":False,"message":t("pin_wrong",lang)})
    # --- amount / balance checks ---
    if amount <= 0:
        return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    if amount < settings["min_withdrawal"]:
        return jsonify({"success":False,"message":f"{t('withdraw_min',lang)} ₦{settings['min_withdrawal']:,.0f}"})
    bal_key = "naira" if currency=="naira" else "dollar"
    if amount > wallet[bal_key]:
        return jsonify({"success":False,"message":t("insufficient_balance",lang)})
    if not bank_info:
        return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    fee = amount*(settings["withdrawal_fee_percent"]/100); net = amount-fee
    wid = f"WD_{short_id()}"
    db = get_db()
    db.execute("INSERT INTO withdrawals(id,user_id,amount,fee,net,currency,bank_info,status,requested_at) VALUES(?,?,?,?,?,?,?,'pending',?)",
               (wid, uid, amount, fee, net, currency, bank_info[:500], now_str()))
    db.commit()
    db.close()
    upd_wallet(uid, bal_key, -amount)
    add_transaction(uid, "debit", amount, currency, f"Withdrawal request — Net: ₦{net:,.2f}", wid)
    add_notif(uid, f"💸 {t('withdrawal_request',lang)} ₦{amount:,.2f}", "info")
    log_audit("withdraw_request", uid, wid, amount)
    return jsonify({"success":True,"message":f"{t('withdrawal_request',lang)} Net: ₦{net:,.2f}"})

@app.route("/exchange", methods=["POST"])
@login_required
def exchange():
    uid = session["user_id"]
    lang = session.get("lang","en")
    from_curr = request.form.get("from_currency")
    try:
        amount = float(request.form.get("amount",0))
    except (ValueError, TypeError):
        return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    if amount <= 0:
        return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    settings = get_settings()
    rate = settings["exchange_rate"]
    wallet = get_wallet(uid)
    if from_curr=="naira":
        if amount>wallet["naira"]: return jsonify({"success":False,"message":t("insufficient_balance",lang)})
        to_amount=amount/rate; to_curr="dollar"
    else:
        if amount>wallet["dollar"]: return jsonify({"success":False,"message":t("insufficient_balance",lang)})
        to_amount=amount*rate; to_curr="naira"
    eid = f"EX_{short_id()}"
    db = get_db()
    db.execute("INSERT INTO exchanges(id,user_id,from_currency,from_amount,to_currency,to_amount,rate,time) VALUES(?,?,?,?,?,?,?,?)",
               (eid, uid, from_curr, amount, to_curr, to_amount, rate, now_str()))
    db.commit()
    db.close()
    upd_wallet(uid, from_curr, -amount)
    upd_wallet(uid, to_curr, to_amount)
    sym = "$" if to_curr=="dollar" else "₦"
    add_transaction(uid, "credit", to_amount, to_curr, f"Exchange {from_curr}→{to_curr}", eid)
    return jsonify({"success":True,"message":f"{t('exchanged',lang)} {sym}{to_amount:,.4f}"})

@app.route("/transfer", methods=["POST"])
@login_required
def transfer():
    uid = session["user_id"]
    lang = session.get("lang","en")
    receiver_id = request.form.get("receiver_id","").strip()
    try:
        amount = float(request.form.get("amount",0))
    except (ValueError, TypeError):
        return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    pin = request.form.get("pin","")
    if receiver_id==uid: return jsonify({"success":False,"message":t("cannot_send_self",lang)})
    db = get_db()
    receiver = db.execute("SELECT id,name FROM users WHERE id=?", (receiver_id,)).fetchone()
    if not receiver:
        db.close()
        return jsonify({"success":False,"message":t("user_not_found",lang)})
    pin_rec = db.execute("SELECT pin_hash FROM pins WHERE user_id=?", (uid,)).fetchone()
    if not pin_rec:
        db.close()
        return jsonify({"success":False,"message":t("pin_required",lang)})
    if not verify_pw(pin, pin_rec["pin_hash"]):
        db.close()
        return jsonify({"success":False,"message":t("pin_wrong",lang)})
    sender = db.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()
    db.close()
    wallet = get_wallet(uid)
    if amount>wallet["naira"]: return jsonify({"success":False,"message":t("insufficient_balance",lang)})
    trid = f"TR_{short_id()}"
    db = get_db()
    db.execute("INSERT INTO transfers(id,sender_id,receiver_id,amount,status,time) VALUES(?,?,?,?,'completed',?)",
               (trid, uid, receiver_id, amount, now_str()))
    db.commit()
    db.close()
    upd_wallet(uid, "naira", -amount)
    upd_wallet(receiver_id, "naira", amount)
    sname = sender["name"] if sender else "User"
    rname = receiver["name"]
    add_transaction(uid, "debit", amount, "naira", f"Transfer to {rname}", trid)
    add_transaction(receiver_id, "credit", amount, "naira", f"Transfer from {sname}", trid)
    add_notif(uid, f"💸 {t('money_sent',lang)} → {rname}: ₦{amount:,.2f}", "success")
    add_notif(receiver_id, f"💰 +₦{amount:,.2f} ← {sname}", "success")
    log_audit("transfer", uid, f"to:{receiver_id}", amount)
    return jsonify({"success":True,"message":f"{t('money_sent',lang)} → {rname}"})

@app.route("/set_pin", methods=["POST"])
@login_required
def set_pin():
    uid = session["user_id"]
    lang = session.get("lang","en")
    pin = request.form.get("pin","")
    if len(pin)!=4 or not pin.isdigit(): return jsonify({"success":False,"message":t("pin_4digits",lang)})
    db = get_db()
    db.execute("INSERT OR REPLACE INTO pins(user_id,pin_hash,created) VALUES(?,?,?)",
               (uid, hash_pw(pin), now_str()))
    db.commit()
    db.close()
    return jsonify({"success":True,"message":t("pin_set",lang)})

@app.route("/referrals")
@login_required
def referrals_page():
    uid = session["user_id"]
    db = get_db()
    l1_refs = db.execute("""SELECT r.*,u.name FROM referrals r LEFT JOIN users u ON r.referred_id=u.id
                            WHERE r.referrer_id=? AND r.level=1 ORDER BY r.time DESC""", (uid,)).fetchall()
    l2_refs = db.execute("""SELECT r.*,u.name FROM referrals r LEFT JOIN users u ON r.referred_id=u.id
                            WHERE r.referrer_id=? AND r.level=2 ORDER BY r.time DESC""", (uid,)).fetchall()
    leaderboard = db.execute("""SELECT u.name,u.id, w.referral_count+w.referral_count_l2 as total
                                FROM wallets w JOIN users u ON w.user_id=u.id
                                WHERE u.is_admin=0 AND (w.referral_count+w.referral_count_l2)>0
                                ORDER BY total DESC LIMIT 10""").fetchall()
    db.close()
    wallet = get_wallet(uid)
    settings = get_settings()
    ref_link = f"{request.host_url}r/{uid}"
    lang = session.get("lang","en")
    def enrich(refs):
        return [{"name": r["name"] or "Unknown", "time": r["time"][:10] if r["time"] else "",
                 "tasks_done": r["tasks_done"], "bonus_paid": bool(r["bonus_paid"]),
                 "tasks_needed": settings["referral_tasks_needed"], "level": r["level"]} for r in refs]
    lb_data = [{"name": r["name"], "count": r["total"], "is_me": r["id"]==uid} for r in leaderboard]
    return render_template("referrals.html", ref_link=ref_link,
                            referrals=enrich(l1_refs), referrals_l2=enrich(l2_refs),
                            wallet=wallet, settings=settings, leaderboard=lb_data, lang=lang)

@app.route("/profile", methods=["GET","POST"])
@login_required
def profile():
    uid = session["user_id"]
    lang = session.get("lang","en")
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if request.method=="POST":
        name = request.form.get("name","").strip()[:100]
        old_pw = request.form.get("old_password","")
        new_pw = request.form.get("new_password","")
        if name:
            db.execute("UPDATE users SET name=? WHERE id=?", (name, uid))
            session["user_name"] = name
        if old_pw and new_pw:
            if not verify_pw(old_pw, user["password"]):
                db.close()
                return jsonify({"success":False,"message":t("wrong_email_or_password",lang)})
            if len(new_pw)<8:
                db.close()
                return jsonify({"success":False,"message":t("password_short",lang)})
            db.execute("UPDATE users SET password=? WHERE id=?", (hash_pw(new_pw), uid))
        db.commit()
        db.close()
        return jsonify({"success":True,"message":t("profile_updated",lang)})
    bank = db.execute("SELECT * FROM bank_details WHERE user_id=?", (uid,)).fetchone()
    has_pin = db.execute("SELECT user_id FROM pins WHERE user_id=?", (uid,)).fetchone() is not None
    dl = db.execute("SELECT total_days FROM daily_logins WHERE user_id=?", (uid,)).fetchone()
    db.close()
    wallet = get_wallet(uid)
    daily_days = dl["total_days"] if dl else 0
    return render_template("profile.html", user=dict(user), bank=dict(bank) if bank else {},
                            has_pin=has_pin, wallet=wallet, daily_days=daily_days, lang=lang)

@app.route("/save_bank", methods=["POST"])
@login_required
def save_bank():
    uid = session["user_id"]
    lang = session.get("lang","en")
    db = get_db()
    db.execute("""INSERT OR REPLACE INTO bank_details(user_id,bank_name,account_number,account_name,type,updated)
                  VALUES(?,?,?,?,?,?)""",
               (uid, request.form.get("bank_name","")[:100],
                request.form.get("account_number","")[:20],
                request.form.get("account_name","")[:100],
                request.form.get("type","bank"), now_str()))
    db.commit()
    db.close()
    return jsonify({"success":True,"message":t("bank_saved",lang)})

@app.route("/notifications")
@login_required
def notif_page():
    uid = session["user_id"]
    db = get_db()
    notifs = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY time DESC", (uid,)).fetchall()
    db.execute("UPDATE notifications SET read=1 WHERE user_id=?", (uid,))
    db.commit()
    db.close()
    lang = session.get("lang","en")
    return render_template("notifications.html", notifications=[dict(n) for n in notifs], lang=lang)

@app.route("/my_submissions")
@login_required
def my_submissions():
    uid = session["user_id"]
    db = get_db()
    subs = db.execute("""SELECT s.*,t.title as task_title,t.platform as task_platform
                         FROM submissions s LEFT JOIN tasks t ON s.task_id=t.id
                         WHERE s.user_id=? ORDER BY s.submitted_at DESC""", (uid,)).fetchall()
    db.close()
    lang = session.get("lang","en")
    return render_template("my_submissions.html", submissions=[dict(s) for s in subs], lang=lang)

# ============================================================
# SPIN & WIN
# ============================================================
@app.route("/spin", methods=["POST"])
@login_required
def spin():
    uid = session["user_id"]
    lang = session.get("lang","en")
    settings = get_settings()
    if not settings.get("spin_enabled"):
        return jsonify({"success":False,"message":"Spin is disabled by admin."})
    spin_cost = int(settings.get("spin_cost", 50))
    spin_daily_limit = int(settings.get("spin_daily_limit", 0))
    # Check daily spin limit if set
    if spin_daily_limit > 0:
        db = get_db()
        today = datetime.now().strftime("%Y-%m-%d")
        sp_today = db.execute("SELECT * FROM spins WHERE user_id=?", (uid,)).fetchone()
        db.close()
        if sp_today and sp_today["last_spin"] and sp_today["last_spin"][:10] == today:
            # Count today's spins via transactions
            db2 = get_db()
            today_spins = db2.execute(
                "SELECT COUNT(*) as c FROM transactions WHERE user_id=? AND description LIKE 'Spin%' AND time LIKE ?",
                (uid, f"{today}%")
            ).fetchone()["c"]
            db2.close()
            if today_spins >= spin_daily_limit:
                return jsonify({"success":False,"message":f"Daily spin limit reached ({spin_daily_limit} spins/day). Come back tomorrow!"})
    wallet = get_wallet(uid)
    if wallet.get("naira",0) < spin_cost:
        return jsonify({"success":False,"message":f"Insufficient balance. You need ₦{spin_cost:,} to spin."})
    upd_wallet(uid, "naira", -spin_cost)
    add_transaction(uid, "debit", spin_cost, "naira", "Spin & Win: Entry fee")
    SPIN_PRIZES = get_spin_prizes(settings)
    pool = []
    for i,p in enumerate(SPIN_PRIZES): pool.extend([i]*p["prob"])
    idx = random.choice(pool)
    prize = SPIN_PRIZES[idx]
    db = get_db()
    sp = db.execute("SELECT * FROM spins WHERE user_id=?", (uid,)).fetchone()
    total_spins = (sp["total_spins"]+1) if sp else 1
    total_spent = (sp["total_spent"]+spin_cost) if sp else spin_cost
    db.execute("INSERT OR REPLACE INTO spins(user_id,last_spin,total_spins,total_spent) VALUES(?,?,?,?)",
               (uid, now_str(), total_spins, total_spent))
    db.commit()
    db.close()
    if prize["amount"] > 0:
        upd_wallet(uid, "naira", prize["amount"])
        upd_wallet(uid, "total_earned", prize["amount"])
        add_transaction(uid, "credit", prize["amount"], "naira", f"Spin & Win: {prize['label']}")
        add_notif(uid, f"🎰 You won {prize['label']}! (Cost: ₦{spin_cost:,})", "success")
        log_audit("spin_win", uid, prize["label"], prize["amount"])
    else:
        add_notif(uid, f"🎰 Try Again! You spent ₦{spin_cost:,} on spin.", "info")
        log_audit("spin_try_again", uid, "Try Again", 0)
    prizes_list = [{"label":p["label"],"amount":p["amount"]} for p in SPIN_PRIZES]
    return jsonify({"success":True,"prize":prize["label"],"amount":prize["amount"],"index":idx,"prizes":prizes_list,"spin_cost":spin_cost})

# ============================================================
# SUPPORT
# ============================================================
@app.route("/support", methods=["GET","POST"])
@login_required
def support():
    uid = session["user_id"]
    lang = session.get("lang","en")
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if request.method=="POST":
        subject = request.form.get("subject","").strip()[:200]
        message = request.form.get("message","").strip()[:2000]
        category = request.form.get("category","general")
        if not subject or not message:
            db.close()
            return jsonify({"success":False,"message":t("fill_all_fields",lang)})
        tid = f"TKT_{short_id()}"
        db.execute("""INSERT INTO support_tickets(id,user_id,user_name,user_email,subject,message,category,status,created)
                      VALUES(?,?,?,?,?,?,?,'open',?)""",
                   (tid, uid, user["name"], user["email"], subject, message, category, now_str()))
        db.commit()
        # Fix #12: Notify all admins about new ticket
        admins = db.execute("SELECT id FROM users WHERE is_admin=1").fetchall()
        db.close()
        for adm in admins:
            add_notif(adm["id"], f"🎫 New support ticket from {user['name']}: {subject}", "info")
        add_notif(uid, f"✅ Support ticket submitted: {subject}", "success")
        return jsonify({"success":True,"message":"✅ Ticket submitted! We will reply soon."})
    tickets = db.execute("""SELECT t.*, GROUP_CONCAT(r.from_role||'|'||r.name||'|'||r.message||'|'||r.time, '||SEP||') as replies_raw
                            FROM support_tickets t LEFT JOIN support_replies r ON t.id=r.ticket_id
                            WHERE t.user_id=? GROUP BY t.id ORDER BY t.created DESC""", (uid,)).fetchall()
    db.close()
    parsed_tickets = []
    for tk in tickets:
        td = dict(tk)
        if td.get("replies_raw"):
            replies = []
            for rr in td["replies_raw"].split("||SEP||"):
                parts = rr.split("|")
                if len(parts) >= 4:
                    replies.append({"from": parts[0], "name": parts[1], "message": parts[2], "time": parts[3]})
            td["replies"] = replies
        else:
            td["replies"] = []
        del td["replies_raw"]
        parsed_tickets.append(td)
    return render_template("support.html", tickets=parsed_tickets, user=dict(user), lang=lang, tg_support=TG_SUPPORT)

@app.route("/support/reply/<tid>", methods=["POST"])
@login_required
def support_reply(tid):
    uid = session["user_id"]
    lang = session.get("lang","en")
    message = request.form.get("message","").strip()[:1000]
    if not message: return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    db = get_db()
    tk = db.execute("SELECT user_id FROM support_tickets WHERE id=?", (tid,)).fetchone()
    if not tk or tk["user_id"] != uid:
        db.close()
        return jsonify({"success":False,"message":"Unauthorized"})
    db.execute("INSERT INTO support_replies(ticket_id,from_role,name,message,time) VALUES(?,'user',?,?,?)",
               (tid, session.get("user_name","User"), message, now_str()))
    db.commit()
    db.close()
    return jsonify({"success":True,"message":"Reply sent!"})

# ============================================================
# API
# ============================================================
@app.route("/api/user_lookup", methods=["POST"])
@login_required
def api_user_lookup():
    qid = request.json.get("user_id","").strip()
    db = get_db()
    u = db.execute("SELECT name,is_admin FROM users WHERE id=?", (qid,)).fetchone()
    db.close()
    if u and not u["is_admin"]:
        return jsonify({"found":True,"name":u["name"]})
    return jsonify({"found":False})

@app.route("/api/notif_count")
@login_required
def api_notif_count():
    db = get_db()
    c = db.execute("SELECT COUNT(*) as c FROM notifications WHERE user_id=? AND read=0",
                   (session["user_id"],)).fetchone()["c"]
    db.close()
    return jsonify({"count":c})

@app.route("/api/wallet")
@login_required
def api_wallet():
    w = get_wallet(session["user_id"])
    return jsonify({"naira":w["naira"],"dollar":w["dollar"],"total_earned":w.get("total_earned",0),"completed_tasks":w.get("completed_tasks",0)})

# ============================================================
# ADMIN ROUTES
# ============================================================
@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    total_users = db.execute("SELECT COUNT(*) as c FROM users WHERE is_admin=0").fetchone()["c"]
    active_tasks = db.execute("SELECT COUNT(*) as c FROM tasks WHERE status='active'").fetchone()["c"]
    pending_subs = db.execute("SELECT COUNT(*) as c FROM submissions WHERE status='pending'").fetchone()["c"]
    pending_wds = db.execute("SELECT COUNT(*) as c FROM withdrawals WHERE status='pending'").fetchone()["c"]
    total_naira = db.execute("SELECT COALESCE(SUM(naira),0) as s FROM wallets").fetchone()["s"]
    total_dollar = db.execute("SELECT COALESCE(SUM(dollar),0) as s FROM wallets").fetchone()["s"]
    recent = db.execute("SELECT u.*,w.naira FROM users u LEFT JOIN wallets w ON u.id=w.user_id WHERE u.is_admin=0 ORDER BY u.created DESC LIMIT 5").fetchall()
    my_role = db.execute("SELECT role FROM users WHERE id=?", (session["user_id"],)).fetchone()["role"]
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/dashboard.html",
        total_users=total_users, active_tasks=active_tasks, pending_subs=pending_subs,
        pending_wds=pending_wds, total_naira=total_naira, total_dollar=total_dollar,
        recent_users=[dict(r) for r in recent], settings=get_settings(), lang=lang, my_role=my_role)

@app.route("/admin/users")
@admin_required
def admin_users():
    q = request.args.get("q","").lower()
    db = get_db()
    if q:
        users = db.execute("""SELECT u.*,w.naira,w.completed_tasks FROM users u
                              LEFT JOIN wallets w ON u.id=w.user_id
                              WHERE LOWER(u.name) LIKE ? OR LOWER(u.email) LIKE ? OR LOWER(u.id) LIKE ?
                              ORDER BY u.created DESC""",
                           (f"%{q}%",f"%{q}%",f"%{q}%")).fetchall()
    else:
        users = db.execute("""SELECT u.*,w.naira,w.completed_tasks FROM users u
                              LEFT JOIN wallets w ON u.id=w.user_id ORDER BY u.created DESC""").fetchall()
    my_role = db.execute("SELECT role FROM users WHERE id=?", (session["user_id"],)).fetchone()["role"]
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/users.html", users=[dict(u) for u in users], q=q, lang=lang, my_role=my_role)

@app.route("/admin/user/<uid>")
@admin_required
def admin_user_detail(uid):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        db.close()
        return redirect(url_for("admin_users"))
    wallet = db.execute("SELECT * FROM wallets WHERE user_id=?", (uid,)).fetchone()
    subs = db.execute("SELECT s.*,t.title as task_title FROM submissions s LEFT JOIN tasks t ON s.task_id=t.id WHERE s.user_id=? ORDER BY s.submitted_at DESC LIMIT 10", (uid,)).fetchall()
    wds = db.execute("SELECT * FROM withdrawals WHERE user_id=? ORDER BY requested_at DESC LIMIT 10", (uid,)).fetchall()
    trs = db.execute("SELECT * FROM transfers WHERE sender_id=? OR receiver_id=? ORDER BY time DESC LIMIT 10", (uid, uid)).fetchall()
    txs = db.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY time DESC LIMIT 20", (uid,)).fetchall()
    bank = db.execute("SELECT * FROM bank_details WHERE user_id=?", (uid,)).fetchone()
    has_pin = db.execute("SELECT user_id FROM pins WHERE user_id=?", (uid,)).fetchone() is not None
    my_role = db.execute("SELECT role FROM users WHERE id=?", (session["user_id"],)).fetchone()["role"]
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/user_detail.html", user=dict(user), user_id=uid,
        wallet=dict(wallet) if wallet else {}, submissions=[dict(s) for s in subs],
        withdrawals=[dict(w) for w in wds], transfers=[dict(t) for t in trs],
        transactions=[dict(t) for t in txs], bank=dict(bank) if bank else {},
        has_pin=has_pin, lang=lang, my_role=my_role)

@app.route("/admin/user/action", methods=["POST"])
@admin_required
def admin_user_action():
    action = request.form.get("action")
    uid = request.form.get("user_id")
    admin_id = session["user_id"]
    lang = session.get("lang","en")
    db = get_db()
    my_role = db.execute("SELECT role FROM users WHERE id=?", (admin_id,)).fetchone()["role"]
    user = db.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        db.close()
        return jsonify({"success":False,"message":t("user_not_found",lang)})
    if action=="ban":
        db.execute("UPDATE users SET banned=1 WHERE id=?", (uid,))
        db.commit(); db.close()
        add_notif(uid, f"⛔ {t('account_banned',lang)}", "error")
        log_audit("ban", admin_id, uid)
        return jsonify({"success":True,"message":t("user_banned",lang)})
    elif action=="unban":
        db.execute("UPDATE users SET banned=0 WHERE id=?", (uid,))
        db.commit(); db.close()
        add_notif(uid, "✅ Account restored.", "success")
        log_audit("unban", admin_id, uid)
        return jsonify({"success":True,"message":t("user_unbanned",lang)})
    elif action=="adjust_balance":
        currency = request.form.get("currency","naira")
        amount = float(request.form.get("amount",0))
        mode = request.form.get("mode","add")
        db.commit(); db.close()
        if mode=="add": upd_wallet(uid, currency, amount); add_transaction(uid,"credit",amount,currency,"Admin balance adjustment")
        elif mode=="deduct": upd_wallet(uid, currency, -amount); add_transaction(uid,"debit",amount,currency,"Admin balance deduction")
        else: upd_wallet(uid, currency, amount, absolute=True)
        add_notif(uid, "💰 Balance updated by admin", "info")
        log_audit("adjust_balance", admin_id, f"{uid}:{currency}:{mode}", amount)
        return jsonify({"success":True,"message":t("balance_adjusted",lang)})
    elif action=="message":
        msg = request.form.get("message","").strip()[:500]
        db.commit(); db.close()
        if msg:
            add_notif(uid, f"📩 {t('from_admin',lang)}: {msg}", "info")
            log_audit("message_user", admin_id, uid)
            return jsonify({"success":True,"message":t("message_sent",lang)})
    elif action=="reset_pin":
        db.execute("DELETE FROM pins WHERE user_id=?", (uid,))
        db.commit(); db.close()
        add_notif(uid, f"🔐 {t('pin_reset',lang)}. Please set a new PIN.", "warning")
        log_audit("reset_pin", admin_id, uid)
        return jsonify({"success":True,"message":t("pin_reset",lang)})
    elif action=="make_admin":
        if my_role!="super_admin":
            db.close()
            return jsonify({"success":False,"message":"Only Super Admin can do this"})
        db.execute("UPDATE users SET is_admin=1,role='admin' WHERE id=?", (uid,))
        db.commit(); db.close()
        log_audit("make_admin", admin_id, uid)
        return jsonify({"success":True,"message":"Admin role granted!"})
    elif action=="remove_admin":
        if my_role!="super_admin":
            db.close()
            return jsonify({"success":False,"message":"Only Super Admin can do this"})
        u_role = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
        if u_role and u_role["role"]=="super_admin":
            db.close()
            return jsonify({"success":False,"message":"Cannot remove Super Admin"})
        db.execute("UPDATE users SET is_admin=0,role='user' WHERE id=?", (uid,))
        db.commit(); db.close()
        log_audit("remove_admin", admin_id, uid)
        return jsonify({"success":True,"message":"Admin role removed"})
    elif action=="delete_user":
        if my_role!="super_admin":
            db.close()
            return jsonify({"success":False,"message":"Only Super Admin can delete users"})
        for tbl in ["wallets","pins","bank_details","daily_logins","spins","notifications"]:
            db.execute(f"DELETE FROM {tbl} WHERE user_id=?", (uid,))
        db.execute("DELETE FROM submissions WHERE user_id=?", (uid,))
        db.execute("DELETE FROM withdrawals WHERE user_id=?", (uid,))
        db.execute("DELETE FROM transactions WHERE user_id=?", (uid,))
        db.execute("DELETE FROM referrals WHERE referrer_id=? OR referred_id=?", (uid, uid))
        db.execute("DELETE FROM users WHERE id=?", (uid,))
        db.commit(); db.close()
        log_audit("delete_user", admin_id, uid)
        return jsonify({"success":True,"message":"User deleted!", "redirect":url_for("admin_users")})
    db.close()
    return jsonify({"success":False,"message":"Unknown action"})

@app.route("/admin/tasks")
@admin_required
def admin_tasks():
    db = get_db()
    tasks = db.execute("SELECT * FROM tasks ORDER BY created DESC").fetchall()
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/tasks.html", tasks=[dict(t) for t in tasks], lang=lang)

@app.route("/admin/create_task", methods=["POST"])
@admin_required
def admin_create_task():
    lang = session.get("lang","en")
    title = request.form.get("title","").strip()[:200]
    if not title: return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    tid = f"TASK_{short_id()}"
    expires_hours = request.form.get("expires_hours","")
    expires_at = None
    if expires_hours:
        try: expires_at = (datetime.now()+timedelta(hours=float(expires_hours))).isoformat()
        except: pass
    try:
        reward = float(request.form.get("reward",0))
        max_users = int(request.form.get("max_users",100))
    except (ValueError, TypeError):
        return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    if reward <= 0:
        return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    db = get_db()
    db.execute("""INSERT INTO tasks(id,title,description,platform,task_type,link,reward,currency,max_users,status,auto_approve,completed_count,expires_at,created,created_by)
                  VALUES(?,?,?,?,?,?,?,?,?,'active',?,0,?,?,?)""",
               (tid, title, request.form.get("description","").strip()[:1000],
                request.form.get("platform","other"), request.form.get("task_type","other"),
                request.form.get("link","").strip()[:500], reward,
                request.form.get("currency","naira"), max_users,
                1 if request.form.get("auto_approve")=="1" else 0,
                expires_at, now_str(), session["user_id"]))
    db.commit()
    db.close()
    log_audit("create_task", session["user_id"], tid, reward)
    return jsonify({"success":True,"message":t("task_created",lang)})

@app.route("/admin/delete_task", methods=["POST"])
@admin_required
def admin_delete_task():
    lang = session.get("lang","en")
    tid = request.form.get("task_id")
    db = get_db()
    db.execute("DELETE FROM tasks WHERE id=?", (tid,))
    db.execute("DELETE FROM task_completions WHERE task_id=?", (tid,))
    db.commit()
    db.close()
    log_audit("delete_task", session["user_id"], tid)
    return jsonify({"success":True,"message":t("task_deleted",lang)})

@app.route("/admin/submissions")
@admin_required
def admin_submissions():
    status = request.args.get("status","pending")
    db = get_db()
    subs = db.execute("""SELECT s.*,t.title as task_title,u.name as user_name,u.email as user_email
                         FROM submissions s LEFT JOIN tasks t ON s.task_id=t.id LEFT JOIN users u ON s.user_id=u.id
                         WHERE s.status=? ORDER BY s.submitted_at DESC""", (status,)).fetchall()
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/submissions.html", submissions=[dict(s) for s in subs], status=status, lang=lang)

@app.route("/admin/review_submission", methods=["POST"])
@admin_required
def admin_review_submission():
    sid = request.form.get("sub_id")
    action = request.form.get("action")
    note = request.form.get("note","").strip()[:300]
    admin_id = session["user_id"]
    lang = session.get("lang","en")
    db = get_db()
    sub = db.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
    if not sub:
        db.close()
        return jsonify({"success":False,"message":"Not found"})
    # GUARD: only pending submissions can be reviewed
    if sub["status"] != "pending":
        db.close()
        return jsonify({"success":False,"message":f"This submission is already '{sub['status']}'. Cannot review again."})
    uid = sub["user_id"]
    tid = sub["task_id"]
    if action=="approve":
        reward = sub["reward"]
        curr = sub["currency"]
        db.execute("UPDATE submissions SET status='approved',reviewed_at=?,note=? WHERE id=?",
                   (now_str(), note, sid))
        db.execute("INSERT OR IGNORE INTO task_completions(task_id,user_id) VALUES(?,?)", (tid, uid))
        db.execute("UPDATE tasks SET completed_count=completed_count+1 WHERE id=?", (tid,))
        db.commit()
        db.close()
        upd_wallet(uid, curr, reward)
        upd_wallet(uid, "completed_tasks", 1)
        upd_wallet(uid, "pending_tasks", -1)
        upd_wallet(uid, "total_earned", reward)
        add_transaction(uid, "credit", reward, curr, "Task approved", sid)
        _check_referral_bonus(uid, lang)
        sym = "₦" if curr=="naira" else "$"
        add_notif(uid, f"✅ {t('submission_approved',lang)} +{sym}{reward:,.2f}", "success")
        log_audit("approve_sub", admin_id, sid, reward)
        db2 = get_db()
        db2.execute("UPDATE submissions SET screenshot='' WHERE id=?", (sid,))
        db2.commit()
        db2.close()
        return jsonify({"success":True,"message":t("submission_approved",lang)})
    elif action=="reject":
        db.execute("UPDATE submissions SET status='rejected',reviewed_at=?,note=? WHERE id=?",
                   (now_str(), note, sid))
        db.commit()
        db.close()
        upd_wallet(uid, "pending_tasks", -1)
        add_notif(uid, f"❌ {t('submission_rejected',lang)} — {note or 'Proof invalid'}", "error")
        log_audit("reject_sub", admin_id, sid)
        db2 = get_db()
        db2.execute("UPDATE submissions SET screenshot='' WHERE id=?", (sid,))
        db2.commit()
        db2.close()
        return jsonify({"success":True,"message":t("submission_rejected",lang)})
    db.close()
    return jsonify({"success":False,"message":"Unknown action"})

@app.route("/admin/delete_submission", methods=["POST"])
@admin_required
def admin_delete_submission():
    sid = request.form.get("sub_id")
    lang = session.get("lang","en")
    db = get_db()
    sub = db.execute("SELECT user_id FROM submissions WHERE id=?", (sid,)).fetchone()
    if sub:
        db.execute("DELETE FROM submissions WHERE id=?", (sid,))
        db.commit()
    db.close()
    log_audit("delete_submission", session["user_id"], sid)
    return jsonify({"success":True,"message":"Submission deleted!"})

@app.route("/admin/withdrawals")
@admin_required
def admin_withdrawals():
    status = request.args.get("status","pending")
    db = get_db()
    wds = db.execute("""SELECT w.*,u.name as user_name,u.email as user_email
                        FROM withdrawals w LEFT JOIN users u ON w.user_id=u.id
                        WHERE w.status=? ORDER BY w.requested_at DESC""", (status,)).fetchall()
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/withdrawals.html", withdrawals=[dict(w) for w in wds], status=status, lang=lang)

@app.route("/admin/process_withdrawal", methods=["POST"])
@admin_required
def admin_process_withdrawal():
    wid = request.form.get("wd_id")
    action = request.form.get("action")
    note = request.form.get("note","").strip()
    admin_id = session["user_id"]
    lang = session.get("lang","en")
    db = get_db()
    wd = db.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
    if not wd:
        db.close()
        return jsonify({"success":False,"message":"Not found"})
    # GUARD: only pending withdrawals can be approved or rejected
    if wd["status"] != "pending":
        db.close()
        return jsonify({"success":False,"message":f"This withdrawal is already '{wd['status']}'. Cannot process again."})
    uid = wd["user_id"]
    curr = wd["currency"]
    if action=="approve":
        db.execute("UPDATE withdrawals SET status='approved',processed_at=?,note=? WHERE id=?",
                   (now_str(), note, wid))
        db.commit(); db.close()
        # naira was already deducted when user requested — just record total_withdrawn
        upd_wallet(uid, "total_withdrawn", wd["amount"])
        add_transaction(uid, "debit", wd["net"], curr, f"Withdrawal approved — Net: ₦{wd['net']:,.2f}", wid)
        add_notif(uid, f"✅ {t('withdrawal_approved',lang)} — Net: ₦{wd['net']:,.2f}", "success")
        log_audit("approve_wd", admin_id, wid, wd["amount"])
        return jsonify({"success":True,"message":t("withdrawal_approved",lang)})
    elif action=="reject":
        db.execute("UPDATE withdrawals SET status='rejected',processed_at=?,note=? WHERE id=?",
                   (now_str(), note, wid))
        db.commit(); db.close()
        # Refund full amount back to user balance
        upd_wallet(uid, curr, wd["amount"])
        add_transaction(uid, "credit", wd["amount"], curr, f"Withdrawal rejected — ₦{wd['amount']:,.2f} refunded", wid)
        add_notif(uid, f"❌ {t('withdrawal_rejected',lang)} — ₦{wd['amount']:,.2f} {t('refunded', lang) if lang else 'refunded'}. {note or ''}", "error")
        log_audit("reject_wd", admin_id, wid, wd["amount"])
        return jsonify({"success":True,"message":t("withdrawal_rejected",lang)})
    db.close()
    return jsonify({"success":False,"message":"Unknown action"})

@app.route("/admin/broadcast", methods=["GET","POST"])
@admin_required
def admin_broadcast():
    lang = session.get("lang","en")
    if request.method=="POST":
        msg = request.form.get("message","").strip()[:1000]
        ntype = request.form.get("type","info")
        if not msg: return jsonify({"success":False,"message":t("fill_all_fields",lang)})
        db = get_db()
        users = db.execute("SELECT id FROM users WHERE is_admin=0").fetchall()
        db.close()
        count = 0
        for u in users:
            add_notif(u["id"], f"📢 {t('admin_notice',lang)}: {msg}", ntype)
            count += 1
        log_audit("broadcast", session["user_id"], f"to {count} users")
        return jsonify({"success":True,"message":f"{t('broadcast_sent',lang)} ({count})"})
    return render_template("admin/broadcast.html", lang=lang)

@app.route("/admin/settings", methods=["GET","POST"])
@admin_required
def admin_settings():
    lang = session.get("lang","en")
    if request.method=="POST":
        s = get_settings()
        for k in ["referral_bonus","referral_bonus_l2","referral_tasks_needed","withdrawal_fee_percent",
                  "min_withdrawal","max_withdrawal","exchange_rate","signup_reward_amount","daily_login_reward"]:
            v = request.form.get(k)
            if v:
                try: save_setting(k, float(v))
                except: pass
        save_setting("site_name", request.form.get("site_name", s["site_name"])[:50])
        save_setting("maintenance", "1" if request.form.get("maintenance")=="1" else "0")
        save_setting("announcement", request.form.get("announcement","").strip()[:300])
        save_setting("signup_reward_enabled", "1" if request.form.get("signup_reward_enabled")=="1" else "0")
        save_setting("daily_login_enabled", "1" if request.form.get("daily_login_enabled")=="1" else "0")
        save_setting("spin_enabled", "1" if request.form.get("spin_enabled")=="1" else "0")
        sc = request.form.get("spin_cost")
        if sc:
            try: save_setting("spin_cost", int(float(sc)))
            except: pass
        # Fix #13: spin daily limit
        sdl = request.form.get("spin_daily_limit")
        if sdl:
            try: save_setting("spin_daily_limit", int(float(sdl)))
            except: pass
        raw_prizes = request.form.get("spin_prizes","")
        if raw_prizes.strip():
            try:
                parsed = [int(float(x.strip())) for x in raw_prizes.split(",") if x.strip()]
                if parsed: save_setting("spin_prizes", ",".join(str(p) for p in parsed[:8]))
            except: pass
        return jsonify({"success":True,"message":t("settings_saved",lang)})
    return render_template("admin/settings.html", settings=get_settings(), lang=lang)

@app.route("/admin/logs")
@admin_required
def admin_logs():
    db = get_db()
    logs = db.execute("SELECT * FROM audit_logs ORDER BY time DESC LIMIT 100").fetchall()
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/logs.html", logs=[dict(l) for l in logs], lang=lang)

@app.route("/admin/transfers")
@admin_required
def admin_transfers():
    db = get_db()
    trs = db.execute("""SELECT t.*,s.name as sender_name,r.name as receiver_name
                        FROM transfers t LEFT JOIN users s ON t.sender_id=s.id LEFT JOIN users r ON t.receiver_id=r.id
                        ORDER BY t.time DESC LIMIT 100""").fetchall()
    db.close()
    lang = session.get("lang","en")
    return render_template("admin/transfers.html", transfers=[dict(t) for t in trs], lang=lang)

@app.route("/admin/reverse_transfer", methods=["POST"])
@admin_required
def admin_reverse_transfer():
    trid = request.form.get("tr_id")
    admin_id = session["user_id"]
    lang = session.get("lang","en")
    db = get_db()
    tr = db.execute("SELECT * FROM transfers WHERE id=?", (trid,)).fetchone()
    if not tr:
        db.close()
        return jsonify({"success":False,"message":"Not found"})
    if tr["status"]=="reversed":
        db.close()
        return jsonify({"success":False,"message":"Already reversed"})
    db.execute("UPDATE transfers SET status='reversed',reversed_at=?,reversed_by=? WHERE id=?",
               (now_str(), admin_id, trid))
    db.commit(); db.close()
    upd_wallet(tr["receiver_id"], "naira", -tr["amount"])
    upd_wallet(tr["sender_id"], "naira", tr["amount"])
    add_notif(tr["sender_id"], f"🔄 Transfer ₦{tr['amount']:,.2f} reversed → refunded", "info")
    add_notif(tr["receiver_id"], f"⚠️ Transfer ₦{tr['amount']:,.2f} reversed by admin", "warning")
    log_audit("reverse_transfer", admin_id, trid, tr["amount"])
    return jsonify({"success":True,"message":t("transfer_reversed",lang)})

@app.route("/admin/add_user", methods=["POST"])
@admin_required
def admin_add_user():
    lang = session.get("lang","en")
    email = request.form.get("email","").strip().lower()
    password = request.form.get("password","")
    name = request.form.get("name","").strip()[:100]
    if not email or not password or not name: return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    if len(password)<8: return jsonify({"success":False,"message":t("password_short",lang)})
    if "@" not in email: return jsonify({"success":False,"message":t("fill_all_fields",lang)})
    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    if existing:
        db.close()
        return jsonify({"success":False,"message":t("email_exists",lang)})
    is_admin_account = request.form.get("is_admin")=="1"
    my_role = db.execute("SELECT role FROM users WHERE id=?", (session["user_id"],)).fetchone()["role"]
    if is_admin_account and my_role!="super_admin":
        db.close()
        return jsonify({"success":False,"message":"Only Super Admin can create admin accounts"})
    uid = f"SP{short_id()}"
    db.execute("""INSERT INTO users(id,name,email,password,is_admin,role,banned,verified,created,last_login,referral_code,lang,signup_reward_given)
                  VALUES(?,?,?,?,?,?,0,1,?,?,?,'en',1)""",
               (uid, name, email, hash_pw(password),
                1 if is_admin_account else 0,
                "admin" if is_admin_account else "user",
                now_str(), now_str(), uid))
    db.execute("INSERT INTO wallets(user_id,created) VALUES(?,?)", (uid, now_str()))
    db.commit(); db.close()
    add_notif(uid, f"🎉 Welcome to {APP_NAME}!", "success")
    log_audit("admin_create_user", session["user_id"], uid)
    return jsonify({"success":True,"message":f"✅ Account created: {name} ({uid})","user_id":uid})

@app.route("/admin/support")
@admin_required
def admin_support():
    lang = session.get("lang","en")
    status_filter = request.args.get("status","open")
    db = get_db()
    tickets = db.execute("""SELECT t.*, GROUP_CONCAT(r.from_role||'|'||r.name||'|'||r.message||'|'||r.time, '||SEP||') as replies_raw
                            FROM support_tickets t LEFT JOIN support_replies r ON t.id=r.ticket_id
                            WHERE t.status=? GROUP BY t.id ORDER BY t.created DESC""", (status_filter,)).fetchall()
    db.close()
    parsed = []
    for tk in tickets:
        td = dict(tk)
        if td.get("replies_raw"):
            replies = []
            for rr in td["replies_raw"].split("||SEP||"):
                parts = rr.split("|")
                if len(parts) >= 4:
                    replies.append({"from": parts[0], "name": parts[1], "message": parts[2], "time": parts[3]})
            td["replies"] = replies
        else:
            td["replies"] = []
        del td["replies_raw"]
        parsed.append(td)
    return render_template("admin/support.html", tickets=parsed, status=status_filter, lang=lang)

@app.route("/admin/support/reply/<tid>", methods=["POST"])
@admin_required
def admin_support_reply(tid):
    lang = session.get("lang","en")
    message = request.form.get("message","").strip()[:1000]
    action = request.form.get("action","reply")
    db = get_db()
    tk = db.execute("SELECT * FROM support_tickets WHERE id=?", (tid,)).fetchone()
    if not tk:
        db.close()
        return jsonify({"success":False,"message":"Ticket not found"})
    if message:
        db.execute("INSERT INTO support_replies(ticket_id,from_role,name,message,time) VALUES(?,'admin',?,?,?)",
                   (tid, "SocialPay Support", message, now_str()))
        add_notif(tk["user_id"], f"💬 Admin replied to your ticket: {tk['subject']}", "info")
    if action=="close":
        db.execute("UPDATE support_tickets SET status='closed' WHERE id=?", (tid,))
    elif action=="open":
        db.execute("UPDATE support_tickets SET status='open' WHERE id=?", (tid,))
    db.commit(); db.close()
    return jsonify({"success":True,"message":"Done!"})

# ============================================================
# ERROR HANDLERS
# ============================================================
@app.errorhandler(400)
def bad_request(e):
    return jsonify({"success":False,"message":"Bad request. Please check your input."}), 400

@app.errorhandler(403)
def forbidden(e):
    return jsonify({"success":False,"message":"Access denied."}), 403

@app.errorhandler(404)
def not_found(e):
    return jsonify({"success":False,"message":"Page not found."}), 404

@app.errorhandler(413)
def too_large(e):
    return jsonify({"success":False,"message":"File too large. Max 16MB."}), 413

@app.errorhandler(429)
def too_many_requests(e):
    return jsonify({"success":False,"message":"Too many requests. Please slow down."}), 429

@app.errorhandler(500)
def server_error(e):
    return jsonify({"success":False,"message":"Server error. Please try again."}), 500

# Initialize
init_db()
ensure_admin()

if __name__=="__main__":
    port = int(os.environ.get("PORT",5000))
    print("="*55)
    print(f"  🚀 {APP_NAME} v{VERSION}")
    print(f"  🌐 URL: http://0.0.0.0:{port}")
    print(f"  👑 Admin: {ADMIN_EMAIL}")
    print(f"  🗄️  DB: {DB_PATH}")
    print("="*55)
    app.run(host="0.0.0.0", port=port, debug=False)
