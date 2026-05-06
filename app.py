import os
import time
import email
import imaplib
import threading
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

imap_thread_active = False

# --- ENVIRONMENT VARIABLES ---
GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_PASS = os.environ.get("GMAIL_PASS")  
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")  
# -----------------------------

# Global variable to store the Chat ID from the extension
active_chat_id = None

@app.route('/api/save-chat-id', methods=['POST'])
def save_chat_id():
    global active_chat_id
    data = request.json
    chat_id = data.get('telegramChatId')
    
    if not chat_id:
        return jsonify({"error": "Missing Chat ID"}), 400
        
    active_chat_id = chat_id
    return jsonify({"message": "Chat ID securely saved to server!"})

def send_telegram_alert(bot_token, chat_id, subject, body):
    if not chat_id:
        print("Alert skipped: No Chat ID provided by Extension yet.")
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
                            
                            # Forward exactly what TradingView sent to Telegram
                            send_telegram_alert(TELEGRAM_BOT_TOKEN, active_chat_id, subject, body)
                            
                            # Mark email as Read
                            mail.store(num, '+FLAGS', '\\Seen')
                
                # Check inbox every 3 seconds
                time.sleep(3)
                
        except Exception as e:
            print(f"[IMAP] Connection lost or Error: {e}. Reconnecting in 10 seconds...")
            time.sleep(10)

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
