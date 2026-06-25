import os
import logging
import requests
from ratelimit import limits, sleep_and_retry

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('TradingBot')

# Configuration from Environment Variables (injected by GitHub Secrets)
BASE_URL = "https://api-capital.backend-capital.com"
HEADERS = {
    "X-CAP-API-KEY": os.getenv("CAPITAL_API_KEY"),
    "Content-Type": "application/json",
    "CST": None,
    "X-SECURITY-TOKEN": None
}

def authenticate():
    """Authenticates and sets session tokens in HEADERS."""
    url = f"{BASE_URL}/api/v1/session"
    payload = {
        "identifier": os.getenv("CAPITAL_EMAIL"),
        "password": os.getenv("CAPITAL_API_PASSWORD")
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        HEADERS["CST"] = response.headers["CST"]
        HEADERS["X-SECURITY-TOKEN"] = response.headers["X-SECURITY-TOKEN"]
        logger.info("Authentication successful.")
    else:
        logger.error(f"Auth failed: {response.status_code} {response.text}")
        exit(1)

@sleep_and_retry
@limits(calls=5, period=1)
def get_account_data():
    """Fetch real-time equity directly from API."""
    url = f"{BASE_URL}/api/v1/accounts"
    return requests.get(url, headers=HEADERS).json()

def run_trading_strategy():
    authenticate()
    
    # 1. Circuit Breaker: Always verify safety first
    account = get_account_data()
    # Logic to compare balance vs starting_balance
    logger.info("Bot execution cycle started.")
    
    # 2. Strategy: Check positions and market prices here
    # Since this is stateless, you do not need active_deals.json.
    # Just fetch /positions to see what is currently open.
    
    logger.info("Cycle complete. Shutting down until next trigger.")

if __name__ == "__main__":
    run_trading_strategy()
