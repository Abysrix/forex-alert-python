import time
import requests
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

def get_current_price(pair):
      # pair is like "EUR/USD"
      base, target = pair.split('/')
      url = f"https://api.exchangerate-api.com/v4/latest/{base}"
      try:
                response = requests.get(url)
                data = response.json()
                return data['rates'].get(target)
except Exception as e:
        print(f"Error fetching price: {e}")
        return None

def telegram_alert(token, chat_id, message):
      url = f"https://api.telegram.org/bot{token}/sendMessage"
      payload = {"chat_id": chat_id, "text": message}
      requests.post(url, json=payload)

def monitor_price(config):
      pair = config['pair']
      zone_min = float(config['zoneMin'])
      zone_max = float(config['zoneMax'])
      token = config['telegramBotToken']
      chat_id = config['telegramChatId']

    print(f"[{pair}] Started background monitoring loop...")

    while True:
              price = get_current_price(pair)
              if price is not None:
                            print(f"[{pair}] Current Price: {price}")
                            if zone_min <= price <= zone_max:
                                              message = f"Alert! {pair} price {price} entered zone ({zone_min}-{zone_max})."
                                              telegram_alert(token, chat_id, message)
                                              break
                                      time.sleep(60)

      @app.route('/api/save-config', methods=['POST'])
def save_config():
      data = request.json
      thread = threading.Thread(target=monitor_price, args=(data,))
      thread.daemon = True
      thread.start()
      return jsonify({"status": "success", "message": "Monitoring started."})

if __name__ == '__main__':
      app.run(host='0.0.0.0', port=5000)
  
