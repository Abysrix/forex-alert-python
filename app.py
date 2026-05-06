import os
import re
import time
import json
import email
import imaplib
import threading
import requests
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

imap_thread_active = False
SERVER_START_TIME = datetime.now(timezone.utc)
alerts_sent = 0
alerts_ignored = 0

# --- ENVIRONMENT VARIABLES ---
GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_PASS = os.environ.get("GMAIL_PASS")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
# -----------------------------

DB_FILE = "chat_id_db.json"

def load_chat_ids():
    try:
        with open(DB_FILE, 'r') as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_chat_id_to_db(chat_id):
    chat_ids = load_chat_ids()
    chat_ids.add(chat_id)
    with open(DB_FILE, 'w') as f:
        json.dump(list(chat_ids), f)

@app.route('/api/save-chat-id', methods=['POST'])
def save_chat_id():
    data = request.json
    chat_id = data.get('telegramChatId')

    if not chat_id:
        return jsonify({"error": "Missing Chat ID"}), 400

    save_chat_id_to_db(str(chat_id))
    return jsonify({"message": "Chat ID successfully registered in the database!"})

def send_telegram_alert(bot_token, chat_id, subject, body):
    if not chat_id or not bot_token:
        print("[ALERT] Skipped: Missing bot token or chat ID.")
        return

    text = f"🚨 TradingView Alert 🚨\n{body}"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        resp = requests.post(url, json=payload)
        print(f"[TELEGRAM] Sent to {chat_id} — Status: {resp.status_code}")
    except Exception as e:
        print(f"[TELEGRAM] Failed to send message: {e}")

def monitor_email():
    # FIX: Declare globals at the top of the function so counters & flag can be updated
    global imap_thread_active, alerts_sent, alerts_ignored

    imap_thread_active = True
    print(f"[IMAP] Started Gmail IMAP Listener for {GMAIL_USER}...")

    while True:
        try:
            # Connect to Gmail IMAP securely
            mail = imaplib.IMAP4_SSL('imap.gmail.com')
            mail.login(GMAIL_USER, GMAIL_PASS)

            while True:
                # Refresh the mailbox state to detect new emails
                mail.select('inbox')

                # Search for unread emails
                status, response = mail.search(None, 'UNSEEN')
                unread_msg_nums = response[0].split()

                for num in unread_msg_nums:
                    status, data = mail.fetch(num, '(RFC822)')
                    for response_part in data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])
                            # FIX: renamed to email_subject to avoid shadowing built-in names
                            email_subject = msg['subject']

                            # Extract email body
                            body = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    if part.get_content_type() == "text/plain":
                                        body = part.get_payload(decode=True).decode()
                                        break
                            else:
                                body = msg.get_payload(decode=True).decode()

                            print(f"[IMAP] 🚨 New Alert Received: {email_subject}")

                            # --- SMART ROUTING SYSTEM ---
                            chat_id_to_use = None
                            clean_body = body.strip()
                            clean_subject = "TradingView Alert"

                            # Check if Chat ID is in the Email Subject
                            # Example: "Alert: 1438010651"
                            match_sub = re.search(r'(?i)(?:Alert\s*:\s*)?(-?\d{7,15})', email_subject)
                            if match_sub:
                                chat_id_to_use = match_sub.group(1)

                            # Database Authorization Check
                            authorized_ids = load_chat_ids()

                            if not chat_id_to_use:
                                print("[IMAP] Ignored: No Chat ID found in email Subject.")
                                alerts_ignored += 1
                            elif chat_id_to_use not in authorized_ids:
                                print(f"[IMAP] Ignored: Unregistered Chat ID ({chat_id_to_use}). Not in DB.")
                                alerts_ignored += 1
                            else:
                                send_telegram_alert(TELEGRAM_BOT_TOKEN, chat_id_to_use, clean_subject, clean_body)
                                alerts_sent += 1

                            # Mark email as Read
                            mail.store(num, '+FLAGS', '\\Seen')

                # Check inbox every 3 seconds
                time.sleep(3)

        except Exception as e:
            print(f"[IMAP] Connection lost or Error: {e}. Reconnecting in 10 seconds...")
            imap_thread_active = False
            time.sleep(10)
            imap_thread_active = True

@app.route('/ping')
def ping():
    uptime_seconds = int((datetime.now(timezone.utc) - SERVER_START_TIME).total_seconds())
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"
    authorized_ids = load_chat_ids()
    listener_status = "🟢 Active" if imap_thread_active else "🔴 Reconnecting..."
    listener_color = "#10b981" if imap_thread_active else "#ef4444"
    server_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Sentinel — Server Status</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Inter', sans-serif;
      background: #050505;
      color: #ffffff;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }}
    .card {{
      background: rgba(15, 15, 20, 0.8);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 20px;
      padding: 40px;
      max-width: 520px;
      width: 100%;
      backdrop-filter: blur(20px);
      box-shadow: 0 25px 50px -12px rgba(0,0,0,0.6), 0 0 60px rgba(56,189,248,0.05);
    }}
    .header {{
      display: flex;
      align-items: center;
      gap: 14px;
      margin-bottom: 32px;
      padding-bottom: 24px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }}
    .pulse-dot {{
      width: 12px; height: 12px;
      background: #10b981;
      border-radius: 50%;
      box-shadow: 0 0 0 0 rgba(16,185,129,0.4);
      animation: pulse 2s infinite;
      flex-shrink: 0;
    }}
    @keyframes pulse {{
      0% {{ box-shadow: 0 0 0 0 rgba(16,185,129,0.5); }}
      70% {{ box-shadow: 0 0 0 10px rgba(16,185,129,0); }}
      100% {{ box-shadow: 0 0 0 0 rgba(16,185,129,0); }}
    }}
    .header h1 {{ font-size: 20px; font-weight: 800; letter-spacing: -0.5px; }}
    .header p {{ font-size: 12px; color: #52525b; margin-top: 2px; font-family: 'JetBrains Mono', monospace; }}
    .grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-bottom: 12px;
    }}
    .stat-card {{
      background: rgba(0,0,0,0.3);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 12px;
      padding: 16px 18px;
    }}
    .stat-card.full {{ grid-column: 1 / -1; }}
    .stat-label {{
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 1.5px;
      color: #52525b;
      margin-bottom: 6px;
    }}
    .stat-value {{
      font-size: 22px;
      font-weight: 800;
      background: linear-gradient(135deg, #fff, #a1a1aa);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      font-family: 'JetBrains Mono', monospace;
    }}
    .stat-value.green {{ background: linear-gradient(135deg, #10b981, #34d399); -webkit-background-clip: text; }}
    .stat-value.blue {{ background: linear-gradient(135deg, #38bdf8, #818cf8); -webkit-background-clip: text; }}
    .stat-value.small {{ font-size: 14px; }}
    .listener-status {{ color: {listener_color}; font-size: 15px; font-weight: 700; -webkit-text-fill-color: {listener_color}; }}
    .footer {{
      margin-top: 24px;
      text-align: center;
      font-size: 11px;
      color: #3f3f46;
      font-family: 'JetBrains Mono', monospace;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <div class="pulse-dot"></div>
      <div>
        <h1>Sentinel — Server Status</h1>
        <p>forex-alert-python.onrender.com</p>
      </div>
    </div>

    <div class="grid">
      <div class="stat-card">
        <div class="stat-label">Uptime</div>
        <div class="stat-value blue">{uptime_str}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">IMAP Listener</div>
        <div class="listener-status">{listener_status}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Alerts Sent</div>
        <div class="stat-value green">{alerts_sent}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Alerts Ignored</div>
        <div class="stat-value">{alerts_ignored}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Registered Users</div>
        <div class="stat-value blue">{len(authorized_ids)}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Gmail Inbox</div>
        <div class="stat-value small">{GMAIL_USER or 'Not Set'}</div>
      </div>
      <div class="stat-card full">
        <div class="stat-label">Server Time (UTC)</div>
        <div class="stat-value small">{server_time}</div>
      </div>
    </div>

    <div class="footer">Sentinel Forex Alert System &nbsp;·&nbsp; Auto-refreshes via UptimeRobot</div>
  </div>
</body>
</html>"""
    return html, 200, {'Content-Type': 'text/html'}

@app.route('/')
def health_check():
    return "IMAP Listener is running securely in the background!", 200

# Start the IMAP listener thread on module load (works with both python app.py AND gunicorn)
_imap_thread = threading.Thread(target=monitor_email)
_imap_thread.daemon = True
_imap_thread.start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
