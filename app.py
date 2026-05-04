import os
import time
import requests
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS
from tradingview_ta import TA_Handler, Interval

app = Flask(__name__)
CORS(app)

configs = {}

def get_price(pair):
    try:
        pair_upper = pair.upper()
        symbol = pair_upper.replace('/', '').replace('-', '')
        exchange = 'OANDA'
        screener = 'forex'
        
        # Crypto handling
        if 'BTC' in symbol or 'ETH' in symbol:
            screener = 'crypto'
            exchange = 'BINANCE'
            # Convert BTC/USD to BTCUSDT for Binance if needed, but Binance supports BTCUSD for perps
            # Actually, the test above showed BTCUSD works on Binance!
            
        # Gold/CFD handling
        elif 'XAU' in symbol or 'GOLD' in symbol:
            screener = 'cfd'
            exchange = 'OANDA'
            symbol = 'XAUUSD'

        handler = TA_Handler(
            symbol=symbol,
            screener=screener,
            exchange=exchange,
            interval=Interval.INTERVAL_1_MINUTE
        )
        
        analysis = handler.get_analysis()
        if analysis and analysis.indicators and 'close' in analysis.indicators:
            return float(analysis.indicators['close'])
            
    except Exception as e:
        print(f"[{pair}] Error fetching price from TradingView: {e}")
        
    return None

def send_telegram_alert(bot_token, chat_id, pair, price, zone_min, zone_max):
    text = f"🚨 *ZONE ALERT*\nPair: {pair}\nCurrent Price: {price}\nZone: {zone_min} - {zone_max}\n\nPrice has *ENTERED* your area of interest."
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

def monitor_price(pair):
    config = configs.get(pair)
    if not config:
        return
    
    print(f"[{pair}] Started background monitoring loop...")
    
    # Recursive / While loop logic
    while True:
        if pair not in configs:
            print(f"[{pair}] Stopped monitoring.")
            break
            
        config = configs[pair]
        current_price = get_price(pair)
        
        if current_price is not None:
            print(f"[{pair}] Current Price: {current_price}")
            
            # Check if price entered the zone
            if config['zoneMin'] <= current_price <= config['zoneMax']:
                print(f"[{pair}] 🚨 Price entered zone! Triggering Telegram Alert & Exiting Loop.")
                send_telegram_alert(
                    config['telegramBotToken'], 
                    config['telegramChatId'], 
                    pair, 
                    current_price, 
                    config['zoneMin'], 
                    config['zoneMax']
                )
                
                # As requested: exit the loop once it reaches the target
                del configs[pair]
                break
        
        # Sleep for 1 minute before checking again
        time.sleep(5)

@app.route('/api/save-config', methods=['POST'])
def save_config():
    data = request.json
    pair = data.get('pair')
    
    if not pair:
        return jsonify({"error": "Missing pair"}), 400
        
    configs[pair] = data
    
    # Start a background thread (acts as our recursive loop without freezing the server)
    thread = threading.Thread(target=monitor_price, args=(pair,))
    thread.daemon = True
    thread.start()
        
    return jsonify({"message": "Configuration saved and monitoring loop started."})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
