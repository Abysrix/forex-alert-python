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

import json

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
    if not chat_id:
        return
        
    text = f"🚨 *TRADINGVIEW ALERT*\n*{subject}*\n\n{body}"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Failed to send telegram message: {e}")

def monitor_email():
    print(f"[IMAP] Started Gmail IMAP Listener for {GMAIL_USER}...")
    
    while True:
        try:
            # Connect to Gmail IMAP securely
            mail = imaplib.IMAP4_SSL('imap.gmail.com')
            mail.login(GMAIL_USER, GMAIL_PASS)
            
            while True:
                # Refresh the mailbox state to detect new emails
                mail.select('inbox')
                
                # Quickly search for unread emails
                status, response = mail.search(None, 'UNSEEN')
                unread_msg_nums = response[0].split()
                
                for num in unread_msg_nums:
                    status, data = mail.fetch(num, '(RFC822)')
                    for response_part in data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])
                            subject = msg['subject']
                            
                            # Extract email body
                            body = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    if part.get_content_type() == "text/plain":
                                        body = part.get_payload(decode=True).decode()
                                        break
                            else:
                                body = msg.get_payload(decode=True).decode()
                                
                            print(f"[IMAP] 🚨 New Alert Received: {subject}")
                            
                            # --- SMART ROUTING SYSTEM ---
                            chat_id_to_use = None
                            clean_body = body.strip()
                            clean_subject = subject
                            
                            import re
                            
                            # 1. Check if Chat ID is hidden in the Email Subject
                            # Example: "Alert: 1438010651"
                            match_sub = re.search(r'(?i)(?:Alert\s*:\s*)?(-?\d{7,15})', subject)
                            if match_sub:
                                chat_id_to_use = match_sub.group(1)
                                clean_subject = "TradingView Alert" # Hide the ID from the final Telegram message

                            # 2. Database Authorization Check
                            authorized_ids = load_chat_ids()

                            if not chat_id_to_use:
                                print("[IMAP] Ignored: No Telegram Chat ID found in Subject.")
                                alerts_ignored += 1
                            elif chat_id_to_use not in authorized_ids:
                                print(f"[IMAP] Ignored: Unregistered Chat ID ({chat_id_to_use}). User must save it in the Extension first.")
                                alerts_ignored += 1
                            else:
                                # Forward the cleaned message to Telegram
                                send_telegram_alert(TELEGRAM_BOT_TOKEN, chat_id_to_use, clean_subject, clean_body)
                                alerts_sent += 1
                                
                            # Mark email as Read
                            mail.store(num, '+FLAGS', '\\Seen')
                
                # Check inbox every 3 seconds
                time.sleep(3)
                
        except Exception as e:
            print(f"[IMAP] Connection lost or Error: {e}. Reconnecting in 10 seconds...")
            time.sleep(10)

@app.route('/ping')
def ping():
    uptime_seconds = int((datetime.now(timezone.utc) - SERVER_START_TIME).total_seconds())
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"

    authorized_ids = load_chat_ids()

    return jsonify({
        "status": "🟢 Online",
        "uptime": uptime_str,
        "imap_listener": "Active" if imap_thread_active else "Inactive",
        "registered_users": len(authorized_ids),
        "alerts_sent": alerts_sent,
        "alerts_ignored": alerts_ignored,
        "server_time_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    })

@app.route('/')
def health_check():
    return "IMAP Listener is running securely in the background!", 200

if __name__ == '__main__':
    # Start the IMAP listener in the background immediately
    thread = threading.Thread(target=monitor_email)
    thread.daemon = True
    thread.start()
    
    # Run the dummy web server so Render doesn't crash from port timeout
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
