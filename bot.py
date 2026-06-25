import os
import logging
import requests
import pandas as pd
from dotenv import load_dotenv
from ratelimit import limits, sleep_and_retry

# 1. Initialization
load_dotenv() 
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('TradingBot')

# 2. Configuration
BASE_URL = "https://api-capital.backend-capital.com"
STARTING_BALANCE = 1000.0
LOSS_LIMIT = 0.02

def get_auth_headers():
    """Authenticates and returns session headers."""
    url = f"{BASE_URL}/api/v1/session"
    payload = {
        "identifier": os.getenv("CAPITAL_EMAIL"), 
        "password": os.getenv("CAPITAL_API_PASSWORD")
    }
    headers = {"X-CAP-API-KEY": os.getenv("CAPITAL_API_KEY"), "Content-Type": "application/json"}
    resp = requests.post(url, json=payload, headers=headers)
    
    if resp.status_code != 200:
        logger.error(f"Auth failed: {resp.text}")
        raise Exception("Authentication failed")
        
    return {
        "X-CAP-API-KEY": os.getenv("CAPITAL_API_KEY"), 
        "CST": resp.headers["CST"], 
        "X-SECURITY-TOKEN": resp.headers["X-SECURITY-TOKEN"],
        "Content-Type": "application/json"
    }

@sleep_and_retry
@limits(calls=5, period=1)
def get_rsi(epic, headers, period=14):
    """Calculates RSI to determine market momentum."""
    resp = requests.get(f"{BASE_URL}/api/v1/marketdata/{epic}", headers=headers).json()
    prices = pd.Series([item['closePrice']['bid'] for item in resp['prices']])
    
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs.iloc[-1]))

def run_trading_strategy():
    logger.info("--- Starting Strategy Cycle ---")
    try:
        headers = get_auth_headers()
        
        # 1. Account Check (Circuit Breaker)
        acc_resp = requests.get(f"{BASE_URL}/api/v1/accounts", headers=headers)
        acc_data = acc_resp.json()
        
        # Safely extract account balance
        account_info = acc_data[0] if isinstance(acc_data, list) else acc_data['accounts'][0]
        balance_info = account_info.get('balance', {})
        current_equity = balance_info.get('balance', 0.0) 
        
        if (STARTING_BALANCE - current_equity) / STARTING_BALANCE >= LOSS_LIMIT:
            logger.critical(f"LOSS LIMIT REACHED: Equity is {current_equity}. Safety stop activated.")
            return 

        # 2. Strategy Execution
        epic = "EURUSD"
        rsi = get_rsi(epic, headers)
        
        if pd.isna(rsi):
            logger.warning("RSI calculation inconclusive. Waiting for more data.")
            return

        logger.info(f"Current {epic} RSI: {rsi:.2f}")

        if rsi < 30:
            logger.info("Signal: RSI < 30 (Oversold). Preparing Buy Order.")
        elif rsi > 70:
            logger.info("Signal: RSI > 70 (Overbought). Preparing Sell Order.")
        else:
            logger.info("Signal: Neutral market. No trade executed.")
            
    except Exception as e:
        logger.error(f"Strategy execution error: {e}")

if __name__ == "__main__":
    run_trading_strategy()
