import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import telegram
from telegram import Bot

# Environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# LBank futures API endpoint (public market data)
API_URL = "https://api.lbank.info/api/v1/future_ticker_all"

# Telegram bot init
bot = Bot(token=TELEGRAM_BOT_TOKEN)

def send_telegram_message(message: str):
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='HTML')
    except Exception as e:
        print(f"Telegram send error: {e}")

def fetch_futures_data():
    try:
        response = requests.get(API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data['data']  # List of dicts for each symbol
    except Exception as e:
        print(f"Error fetching LBank data: {e}")
        return []

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def analyze_symbol(symbol_data):
    symbol = symbol_data['symbol']  # e.g., BTC_USDT
    last_price = float(symbol_data['last'])
    vol = float(symbol_data['vol'])
    change = float(symbol_data['change'])  # 24h change in %
    high = float(symbol_data['high'])
    low = float(symbol_data['low'])
    open_price = float(symbol_data['open'])
    
    # We want to detect large surge in short timeframe — we use 1h candles
    
    # Since LBank API doesn't provide historical candles here, we'll fetch 1h candles for the symbol:
    # Use: https://api.lbank.info/api/v1/future_kline?symbol=BTC_USDT&type=1hour&size=20
    try:
        kline_resp = requests.get(f"https://api.lbank.info/api/v1/future_kline?symbol={symbol}&type=1hour&size=20", timeout=10)
        kline_resp.raise_for_status()
        klines = kline_resp.json()['data']
    except Exception as e:
        print(f"Error fetching klines for {symbol}: {e}")
        return None
    
    # Convert klines to DataFrame
    # Kline format: [timestamp, open, close, high, low, volume]
    df = pd.DataFrame(klines, columns=['timestamp','open','close','high','low','volume'])
    df[['open','close','high','low','volume']] = df[['open','close','high','low','volume']].astype(float)
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

    # Calculate 1h return = (last close - previous close) / previous close * 100
    df['return_1h'] = df['close'].pct_change() * 100

    # Calculate RSI (14 periods)
    df['rsi'] = calculate_rsi(df['close'], 14)

    # Calculate volume spike = current volume / average volume (last 14)
    avg_volume = df['volume'].rolling(window=14).mean().iloc[-2]  # exclude current candle for avg
    current_vol = df['volume'].iloc[-1]
    volume_spike = current_vol / avg_volume if avg_volume > 0 else 0

    # Check conditions:
    # - Last 1h return >= 80%
    # - RSI > 85
    # - Volume spike >= 3
    if df['return_1h'].iloc[-1] >= 80 and df['rsi'].iloc[-1] > 85 and volume_spike >= 3:
        return {
            'symbol': symbol,
            'last_price': last_price,
            'return_1h': round(df['return_1h'].iloc[-1], 2),
            'rsi': round(df['rsi'].iloc[-1], 2),
            'volume_spike': round(volume_spike, 2)
        }
    return None

def main_loop():
    print(f"[{datetime.utcnow()}] Bot started, scanning LBank futures every minute...")
    while True:
        try:
            futures_data = fetch_futures_data()
            alerts = []
            for symbol_data in futures_data:
                result = analyze_symbol(symbol_data)
                if result:
                    msg = (
                        f"🚨 <b>SHORT ALERT</b> 🚨\n"
                        f"Symbol: <b>{result['symbol']}</b>\n"
                        f"Price surged: <b>{result['return_1h']}%</b> in last hour\n"
                        f"RSI: <b>{result['rsi']}</b>\n"
                        f"Volume spike: <b>{result['volume_spike']}x</b>\n"
                        f"Potential short opportunity!\n"
                        f"<a href='https://www.lbank.info/futures/exchange/{result['symbol']}'>Chart Link</a>"
                    )
                    alerts.append(msg)

            for alert in alerts:
                print(f"Sending alert:\n{alert}\n")
                send_telegram_message(alert)

            time.sleep(60)  # Wait 1 minute before next scan

        except Exception as e:
            print(f"Unexpected error in main loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main_loop()
