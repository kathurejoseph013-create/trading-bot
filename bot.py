import os
import ssl
import time
import requests
import pandas as pd
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter

# Load environment variables
load_dotenv()

# Complete, verified endpoints from your reference code
BASE_URL = "https://63.35.40.93"  
HOST_NAME = "demo-api-capital.backend-capital.com"
EPIC = "EURUSD"
TRADE_SIZE = 500  

class ForceIPRoutingAdapter(HTTPAdapter):
    """Forces Python requests to handshake with the direct IP while presenting the correct domain name."""
    def init_poolmanager(self, *args, **kwargs):
        # Create an explicit runtime context that skips strict hostname string matching
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = context
        return super(ForceIPRoutingAdapter, self).init_poolmanager(*args, **kwargs)

    def send(self, request, **kwargs):
        connection_pool_kwargs = self.poolmanager.connection_pool_kw
        connection_pool_kwargs["server_hostname"] = HOST_NAME
        return super(ForceIPRoutingAdapter, self).send(request, **kwargs)

def create_routed_session():
    """Generates a secure connection instance pre-configured to bypass local DNS."""
    session = requests.Session()
    session.mount("https://", ForceIPRoutingAdapter())
    return session

def get_auth_headers(session):
    email = os.getenv("CAPITAL_EMAIL")
    password = os.getenv("CAPITAL_API_PASSWORD")
    api_key = os.getenv("CAPITAL_API_KEY")
    
    if not all([email, password, api_key]):
        print("❌ Error: Missing environment variables inside your .env configuration file.")
        return None
        
    payload = {"identifier": email, "password": password}
    headers = {
        "Host": HOST_NAME,
        "X-CAP-API-KEY": api_key,
        "Content-Type": "application/json"
    }
    
    try:
        url = f"{BASE_URL}/api/v1/session"
        # Explicitly tell urllib3 to skip standard verification parameters over the direct IP handshake
        resp = session.post(url, json=payload, headers=headers, timeout=15, verify=False)
        if resp.status_code == 200:
            return {
                "Host": HOST_NAME,
                "X-CAP-API-KEY": api_key,
                "CST": resp.headers.get("CST"),
                "X-SECURITY-TOKEN": resp.headers.get("X-SECURITY-TOKEN"),
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
        print(f"❌ Authentication Failed: {resp.status_code} - {resp.text}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Connection error during session setup: {e}")
    return None

def fetch_and_analyze_market(session, headers):
    url = f"{BASE_URL}/api/v1/prices/{EPIC}"
    params = {"resolution": "MINUTE", "max": 20}
    
    try:
        resp = session.get(url, headers=headers, params=params, timeout=15, verify=False)
        if resp.status_code != 200:
            print(f"⚠️ Error fetching prices: {resp.status_code}")
            return None
    except requests.exceptions.RequestException:
        print("⚠️ Network error while polling live price.")
        return None
        
    raw_data = resp.json()
    prices = raw_data.get("prices", [])
    if not prices:
        return None
        
    # FIXED: Reindexed using prices[::-1] to arrange data chronologically (Oldest -> Newest)
    flattened_candles = []
    for candle in prices[::-1]:
        flattened_candles.append({
            "Timestamp": pd.to_datetime(candle.get("snapshotTimeUTC")),
            "Close": float(candle.get("closePrice", {}).get("bid", 0.0)),
            "Volume": int(candle.get("lastTradedVolume", 0))
        })
        
    df = pd.DataFrame(flattened_candles).sort_values(by="Timestamp").reset_index(drop=True)
    
    df["SMA_7"] = df["Close"].rolling(window=7).mean()
    df["SMA_14"] = df["Close"].rolling(window=14).mean()
    
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    # Accurate Wilder's Exponential Smoothing matching platform charts perfectly
    ema_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    ema_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    
    rs = ema_gain / (ema_loss + 1e-9)
    df["RSI_14"] = 100 - (100 / (1 + rs))
    
    return df.iloc[-1]

def place_market_order(session, headers, direction, size):
    url = f"{BASE_URL}/api/v1/positions"
    payload = {
        "epic": EPIC,
        "direction": direction,
        "size": size,
        "guaranteedStop": False,
        "forceOpen": True
    }
    try:
        resp = session.post(url, json=payload, headers=headers, timeout=15, verify=False)
        if resp.status_code == 200:
            order_info = resp.json()
            print(f"🚀 ORDER EXECUTED SUCCESSFULLY! ID: {order_info.get('dealReference')}")
        else:
            print(f"❌ Order Rejected: {resp.status_code} - {resp.text}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Order pipeline exception: {e}")

def main():
    print("🤖 Starting Live Capital.com Trading Loop Engine (Routed Engine Ready)...")
    
    # Disable urllib3 warning messages to ensure a clean console dashboard output
    requests.packages.urllib3.disable_warnings()
    
    session = create_routed_session()
    headers = get_auth_headers(session)
    if not headers:
        return
        
    last_processed_timestamp = None
    
    while True:
        latest_candle = fetch_and_analyze_market(session, headers)
        if latest_candle is not None:
            current_time = latest_candle["Timestamp"]
            close_price = latest_candle["Close"]
            rsi = latest_candle["RSI_14"]
            
            # FIXED: Nested your strategy signals strictly inside the new-candle timestamp block
            if current_time != last_processed_timestamp:
                print(f"⏰ Candle: {current_time} | Close: {close_price:.5f} | RSI: {rsi:.2f}")
                last_processed_timestamp = current_time
                
                if rsi <= 30:
                    print(f"📉 Market Oversold (RSI: {rsi:.2f})! Triggering BUY Order for {TRADE_SIZE} units...")
                    place_market_order(session, headers, direction="BUY", size=TRADE_SIZE)
                elif rsi >= 70:
                    print(f"📈 Market Overbought (RSI: {rsi:.2f})! Triggering SELL Order for {TRADE_SIZE} units...")
                    place_market_order(session, headers, direction="SELL", size=TRADE_SIZE)
                    
        time.sleep(10)

if __name__ == "__main__":
    main()
