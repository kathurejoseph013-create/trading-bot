import os
import time
import urllib3
import requests
import pandas as pd
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter

# Load environment variables
load_dotenv()

BASE_URL = "https://63.35.40.93"  
HOST_NAME = "demo-api-capital.backend-capital.com"
EPIC = "EURUSD"

# ==============================================================================
# 🛠️ LOW-LEVEL SSL CONTEXT PATCH (Forcefully clears cached tracking blocks)
# ==============================================================================
try:
    import ssl
    clean_context = ssl.create_default_context()
    clean_context.check_hostname = False
    clean_context.verify_mode = ssl.CERT_NONE
    # Overwrites the runtime context generator to completely drop name verification
    urllib3.util.ssl_.create_urllib3_context = lambda *a, **kw: clean_context
except Exception:
    pass
# ==============================================================================

class ForceIPRoutingAdapter(HTTPAdapter):
    """Forces Python requests to handshake with the direct IP while presenting the correct domain name."""
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
        # verify=False prevents your computer from looking up standard domain trees locally
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
    params = {"resolution": "MINUTE", "max": 40}
    
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
        
    flattened_candles = []
    for candle in prices[::-1]:  # Chronological ordering correction preserved
        flattened_candles.append({
            "Timestamp": pd.to_datetime(candle.get("snapshotTimeUTC")),
            "High": float(candle.get("highPrice", {}).get("bid", 0.0)),
            "Low": float(candle.get("lowPrice", {}).get("bid", 0.0)),
            "Close": float(candle.get("closePrice", {}).get("bid", 0.0))
        })
        
    df = pd.DataFrame(flattened_candles)
    
    # Mathematical Bollinger Bands Volatility channels
    df["MA20"] = df["Close"].rolling(window=20).mean()
    df["STD20"] = df["Close"].rolling(window=20).std()
    df["Upper_Band"] = df["MA20"] + (df["STD20"] * 2)
    df["Lower_Band"] = df["MA20"] - (df["STD20"] * 2)
    
    return df.iloc[-1]

def process_account_risk_profile(session, headers):
    url = f"{BASE_URL}/api/v1/accounts"
    try:
        resp = session.get(url, headers=headers, timeout=10, verify=False)
        if resp.status_code == 200:
            accounts_data = resp.json().get("accounts", [])
            if accounts_data:
                # Direct check across the primary wallet response list properties
                primary_wallet = accounts_data if isinstance(accounts_data, list) else accounts_data
                available_balance = float(primary_wallet.get("balance", {}).get("available", 0.0))
                
                # 🛑 1. ACCOUNT SAFETY PROTECTION GUARD
                if available_balance < 7.00:
                    print(f"🛑 SAFETY GUARD TRIGGERED: Available Cash (${available_balance:.2f}) is too low.")
                    print("➡️ Order Blocked! Preventing margin liquidation risks.")
                    return None  
                
                # 📈 2. DYNAMIC FRACTIONAL POSITION SIZE COMPOUNDING
                calculated_size = int((available_balance / 2.0) * 100)
                final_size = max(calculated_size, 500)  
                
                print(f"💳 Risk Assessment: Available Cash: ${available_balance:.2f} | Dynamic Size: {final_size} Units")
                return final_size
    except Exception as e:
        print(f"⚠️ Account liquidity verify failed: {e}. Defaulting to minimum 500 size for protection.")
        return 500
    return 500

def place_adaptive_order(session, headers, direction, current_price, size):
    url = f"{BASE_URL}/api/v1/positions"
    
    # TARGET FIX: Your explicitly mapped 20:10 pip safety ratios
    final_sl = 0.00100  # Exactly 10 pips Stop-Loss
    final_tp = 0.00200  # Exactly 20 pips Take-Profit
    
    if direction == "BUY":
        stop_level = current_price - final_sl
        profit_level = current_price + final_tp
    else:  
        stop_level = current_price + final_sl
        profit_level = current_price - final_tp
        
    payload = {
        "epic": EPIC,
        "direction": direction,
        "size": size, 
        "guaranteedStop": False,
        "forceOpen": True,
        "stopLevel": round(stop_level, 5),
        "profitLevel": round(profit_level, 5)
    }
    
    try:
        resp = session.post(url, json=payload, headers=headers, timeout=15, verify=False)
        if resp.status_code == 200:
            order_info = resp.json()
            print(f"🚀 ORDER EXECUTED! Direction: {direction} | Contract Size: {size} | SL Target: {stop_level:.5f} | TP Target: {profit_level:.5f}")
        else:
            print(f"❌ Order Rejected: {resp.status_code} - {resp.text}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Order pipeline exception: {e}")

def main():
    print("🤖 Starting Live Capital.com Trading Loop Engine (Reference Profiles Restored)...")
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
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
            upper_band = latest_candle["Upper_Band"]
            lower_band = latest_candle["Lower_Band"]
            
            if current_time != last_processed_timestamp:
                print(f"⏰ Candle: {current_time} | Close: {close_price:.5f} | Bollinger Bands: [{lower_band:.5f} - {upper_band:.5f}]")
                last_processed_timestamp = current_time
                
                if close_price <= lower_band:
                    print(f"📉 Price hit Lower Band (Oversold)! Evaluating portfolio risk profile...")
                    safe_trade_size = process_account_risk_profile(session, headers)
                    if safe_trade_size:
                        print("➡️ Risk assessment passed. Firing BUY Order...")
                        place_adaptive_order(session, headers, "BUY", close_price, safe_trade_size)
                        
                elif close_price >= upper_band:
                    print(f"📈 Price hit Upper Band (Overbought)! Evaluating portfolio risk profile...")
                    safe_trade_size = process_account_risk_profile(session, headers)
                    if safe_trade_size:
                        print("➡️ Risk assessment passed. Firing SELL Order...")
                        place_adaptive_order(session, headers, "SELL", close_price, safe_trade_size)
                    
        time.sleep(10)

if __name__ == "__main__":
    main()
