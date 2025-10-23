import requests
import sqlite3
import time
import threading
from bs4 import BeautifulSoup
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# === KONFIGURASI ===
BOT_TOKEN = "8386389319:AAHebkfIydioJ4tqXZtPZZrtq-jGMmnYNco"
CHAT_ID = "5979117432"
BASE_URL = "https://trustpositif.komdigi.go.id"
PROXY = None  # contoh: "http://103.150.120.5:8080"
INTERVAL = 300  # detik (5 menit)
DB_FILE = "database.db"
LOG_FILE = "logs.txt"

# === INIT DATABASE ===
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS domains (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT UNIQUE,
            last_status TEXT,
            last_checked TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT,
            status TEXT,
            checked_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def db_connect():
    return sqlite3.connect(DB_FILE)

def add_domain(domain):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO domains (domain, last_status, last_checked) VALUES (?, ?, ?)",
              (domain, "Belum dicek", datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return True

def remove_domain(domain):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM domains WHERE domain=?", (domain,))
    conn.commit()
    conn.close()

def get_all_domains():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT domain FROM domains")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows

def update_status(domain, status):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE domains SET last_status=?, last_checked=? WHERE domain=?",
              (status, datetime.now().isoformat(), domain))
    conn.commit()
    conn.close()

def get_status(domain):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT last_status FROM domains WHERE domain=?", (domain,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def save_log(domain, status):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO logs (domain, status, checked_at) VALUES (?, ?, ?)",
              (domain, status, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def log_message(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")

# === CEK TRUSTPOSITIF ===
def check_trustpositif(domain):
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    if PROXY:
        session.proxies.update({"http": PROXY, "https": PROXY})

    try:
        r = session.get(BASE_URL, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        token_input = soup.find("input", {"name": "csrf_token"})
        token = token_input["value"] if token_input else None

        payload = {"search": domain}
        if token:
            payload["csrf_token"] = token

        r2 = session.post(BASE_URL, data=payload, timeout=30)
        text = r2.text.lower()

        if "tidak ditemukan" in text:
            return "✅ Aman"
        elif "ditemukan" in text or "diblokir" in text:
            return "🚫 Diblokir"
        else:
            return "⚠️ Tidak jelas"
    except Exception as e:
        log_message(f"Error cek {domain}: {e}")
        return "❌ Error"

# === TELEGRAM COMMANDS ===
async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("Gunakan: /add <domain>")
        return
    domain = context.args[0].lower()
    add_domain(domain)
    await update.message.reply_text(f"✅ {domain} ditambahkan ke daftar pantauan.")

async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("Gunakan: /remove <domain>")
        return
    domain = context.args[0].lower()
    remove_domain(domain)
    await update.message.reply_text(f"🗑️ {domain} dihapus dari daftar pantauan.")

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    domains = get_all_domains()
    if not domains:
        await update.message.reply_text("📭 Belum ada domain yang dipantau.")
    else:
        msg = "📋 Daftar domain yang dipantau:\n" + "\n".join([f"- {d}" for d in domains])
        await update.message.reply_text(msg)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("Gunakan: /status <domain>")
        return
    domain = context.args[0].lower()
    await update.message.reply_text(f"🔍 Mengecek status {domain} di TrustPositif...")
    status = check_trustpositif(domain)
    save_log(domain, status)
    update_status(domain, status)
    msg = f"📡 Hasil cek untuk <b>{domain}</b>:\nStatus: {status}"
    await update.message.reply_text(msg, parse_mode="HTML")

# === AUTO CHECKER ===
def auto_check(app):
    while True:
        domains = get_all_domains()
        for d in domains:
            new_status = check_trustpositif(d)
            old_status = get_status(d)
            save_log(d, new_status)

            if new_status != old_status:
                update_status(d, new_status)
                log_message(f"{d} berubah: {old_status} → {new_status}")
                text = f"🔔 <b>Status berubah</b>\nDomain: <code>{d}</code>\nDari: {old_status}\nKe: {new_status}"
                app.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML")
            else:
                log_message(f"{d}: {new_status}")
        time.sleep(INTERVAL)

# === MAIN ===
if __name__ == "__main__":
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler("remove", remove_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("status", status_command))
    t = threading.Thread(target=auto_check, args=(app,), daemon=True)
    t.start()
    print("🚀 Bot TrustPositif berjalan...")
    app.run_polling()
