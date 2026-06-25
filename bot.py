import os
import ssl
import asyncio
import aiohttp
import pandas as pd
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BASE_URL = "https://63.35.40.93"
HOST_NAME = "demo-api-capital.backend-capital.com"
EPIC = "EURUSD"
TRADE_SIZE = 500  

# FIXED: Create an encrypted SSL context that skips strict hostname string matching
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False  
ssl_context.verify_mode = ssl.CERT_NONE  

class FastIPResolver(aiohttp.DefaultResolver):
    """Bypasses DNS resolution delays by forcing connection tracking straight to the IP."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
    async def resolve(self, host, port=0, family=0):
        if host == HOST_NAME:
            return [{"hostname": HOST_NAME, "host": "63.35.40.93", "port": port, "family": family, "proto": 0, "flags": 0}]
        return await super().resolve(host, port, family)

async def get_auth_headers(session: aiohttp.ClientSession):
    email = os.getenv("CAPITAL_EMAIL")
    password = os.getenv("CAPITAL_API_PASSWORD")
    api_key = os.getenv("CAPITAL_API_KEY")
    
    if not all([email, password, api_key]):
        print("❌ Error: Missing environment variables inside .env file.")
        return None
        
    payload = {"identifier": email, "password": password}
    headers = {
        "Host": HOST_NAME,
        "X-CAP-API-KEY": api_key,
        "Content-Type": "application/json"
    }
    
    try:
        url = f"{BASE_URL}/api/v1/session"
        # Using the tailored ssl_context to handle the handshake smoothly
        async with session.post(url, json=payload, headers=headers, timeout=10, ssl=ssl_context) as resp:
            if resp.status == 200:
                return {
                    "Host": HOST_NAME,
                    "X-CAP-API-KEY": api_key,
                    "CST": resp.headers.get("CST"),
                    "X-SECURITY-TOKEN": resp.headers.get("X-SECURITY-TOKEN"),
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }
            print(f"❌ Auth Failed: {resp.status}")
    except Exception as e:
        print(f"❌ Connection error during setup: {e}")
    return None

async def fetch_and_analyze_market(session: aiohttp.ClientSession, headers: dict):
    url = f"{BASE_URL}/api/v1/prices/{EPIC}"
    params = {"resolution": "MINUTE", "max": "20"}
    
    try:
        async with session.get(url, headers=headers, params=params, timeout=5, ssl=ssl_context) as resp:
            if resp.status != 200:
                return None
            raw_data = await resp.json()
    except Exception:
        return None
        
    prices = raw_data.get("prices", [])
    if not prices:
        return None
        
    df = pd.DataFrame([{
        "Close": float(c.get("closePrice", {}).get("bid", 0.0)),
        "Time": c.get("snapshotTimeUTC")
    } for c in prices])
    
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    ema_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    ema_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    
    df["RSI_14"] = 100 - (100 / (1 + (ema_gain / (ema_loss + 1e-9))))
    
    return df.iloc[-1]["Time"], df.iloc[-1]["Close"], df.iloc[-1]["RSI_14"]

async def place_market_order(session: aiohttp.ClientSession, headers: dict, direction: str, size: int):
    url = f"{BASE_URL}/api/v1/positions"
    payload = {
        "epic": EPIC, 
        "direction": direction, 
        "size": size, 
        "guaranteedStop": False, 
        "forceOpen": True
    }
    
    try:
        async with session.post(url, json=payload, headers=headers, timeout=5, ssl=ssl_context) as resp:
            resp_data = await resp.json()
            if resp.status == 200:
                print(f"🚀 ORDER EXECUTED! Ref: {resp_data.get('dealReference')}")
            else:
                print(f"❌ Order Rejected: {resp.status} - {resp_data}")
    except Exception as e:
        print(f"❌ Pipeline exception: {e}")

async def main():
    print("⚡ Starting High-Speed Asynchronous Trading Engine...")
    
    connector = aiohttp.TCPConnector(resolver=FastIPResolver(), ttl_dns_cache=300, limit=10)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        headers = await get_auth_headers(session)
        if not headers:
            return
            
        last_processed_timestamp = None
        
        while True:
            market_data = await fetch_and_analyze_market(session, headers)
            
            if market_data:
                current_time, close_price, rsi = market_data
                
                if current_time != last_processed_timestamp:
                    print(f"⏰ Candle: {current_time} | Close: {close_price:.5f} | RSI: {rsi:.2f}")
                    last_processed_timestamp = current_time
                    
                    if rsi <= 30:
                        print(f"📉 Market Oversold! Triggering BUY Order for {TRADE_SIZE} units...")
                        asyncio.create_task(place_market_order(session, headers, "BUY", TRADE_SIZE))
                    elif rsi >= 70:
                        print(f"📈 Market Overbought! Triggering SELL Order for {TRADE_SIZE} units...")
                        asyncio.create_task(place_market_order(session, headers, "SELL", TRADE_SIZE))
            
            await asyncio.sleep(2) 

if __name__ == "__main__":
    asyncio.run(main())
