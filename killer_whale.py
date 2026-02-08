import time
import requests
import os
from solana.rpc.api import Client
from supabase import create_client, Client as SupabaseClient
from dotenv import load_dotenv

# --- ⚙️ GROWTH ENGINE SETTINGS ---
# We load .env only for local testing. Railway uses its "Variables" tab.
load_dotenv()

WHALE_THRESHOLD = 1000  
# Fallback to your Alchemy URL if the environment variable isn't set
ALCHEMY_URL = os.getenv("ALCHEMY_URL", "https://solana-mainnet.g.alchemy.com/v2/gV3Ws30jlt4osFOdMJCKD")

# --- 🔑 NOTIFICATION & DB CHANNELS (SECURED) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Supabase Credentials
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Initialize Supabase Safely
if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ ERROR: Supabase credentials missing!")
    exit(1)

supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)

# Wrapped SOL Mint Address
SOL_MINT = "So11111111111111111111111111111111111111112"

KNOWN_WALLETS = {
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvu6Gn": "Binance Hot 1",
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM": "Binance Hot 2",
    "HuDxqF2acC6f8T7Ea8K3P6qK4WjH4Z3h4z6f5e7h8j9k": "Kraken Cold",
}

# --- 📊 FAIL-PROOF PRICE FETCHING ---
def get_sol_price():
    # Attempt 1: Jupiter V2
    try:
        url = f"https://api.jup.ag/price/v2?ids={SOL_MINT}"
        response = requests.get(url, timeout=5).json()
        price = float(response['data'][SOL_MINT]['price'])
        if price > 0: return price
    except Exception:
        pass

    # Attempt 2: CoinGecko
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
        res = requests.get(url, timeout=5).json()
        price = float(res['solana']['usd'])
        if price > 0: return price
    except Exception:
        pass

    # Attempt 3: Binance
    try:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT"
        res = requests.get(url, timeout=5).json()
        return float(res['price'])
    except Exception as e:
        print(f"⚠️ Price Oracles Failed: {e}")
        return 0

# --- ☁️ SUPABASE LOGGING ---
def log_to_supabase(sol_amount, usd_val, sender, receiver, sig):
    try:
        data = {
            "sol_amount": sol_amount,
            "usd_value": usd_val,
            "sender": sender,
            "receiver": receiver,
            "signature": sig
        }
        supabase.table("whale_alerts").insert(data).execute()
        print(f"📁 [DB] Entry Synced: {sol_amount} SOL", flush=True)
    except Exception as e:
        print(f"⚠️ Supabase Sync Error: {e}")

def send_alert(msg):
    if not TELEGRAM_BOT_TOKEN:
        print("⚠️ Telegram token missing, skipping alert.")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID, 
            "text": msg, 
            "parse_mode": "HTML", 
            "disable_web_page_preview": False 
        }
        requests.post(url, json=payload, timeout=10)
        return True
    except Exception as e:
        print(f"❌ Telegram Error: {e}")
        return False

def main():
    print(f"🌊 MONITORING FOR MOVES > {WHALE_THRESHOLD} SOL...", flush=True)
    client = Client(ALCHEMY_URL)
    
    send_alert(f"🚀 <b>GROWTH ENGINE ACTIVATED</b>\n🎯 Filtering: >{WHALE_THRESHOLD} SOL\n📊 Status: Redundant Price Oracles Active")
    
    last_processed_slot = 0

    while True:
        try:
            current_slot = client.get_slot().value
            if current_slot <= last_processed_slot:
                time.sleep(0.5)
                continue

            block = client.get_block(current_slot, max_supported_transaction_version=0).value
            
            if block and block.transactions:
                for tx in block.transactions:
                    if not tx.meta or tx.meta.err:
                        continue
                    
                    pre = tx.meta.pre_balances[0]
                    post = tx.meta.post_balances[0]
                    diff = (pre - post) / 10**9 
                    
                    if diff >= WHALE_THRESHOLD:
                        sender = str(tx.transaction.message.account_keys[0])
                        receiver = str(tx.transaction.message.account_keys[1])
                        sig = str(tx.transaction.signatures[0])
                        
                        current_price = get_sol_price()
                        usd_value = diff * current_price
                        
                        print(f"🔍 [DEBUG] Move: {diff:.2f} SOL | Total: ${usd_value:,.2f}")
                        
                        s_name = KNOWN_WALLETS.get(sender, f"<code>{sender[:4]}...{sender[-4:]}</code>")
                        r_name = KNOWN_WALLETS.get(receiver, f"<code>{receiver[:4]}...{receiver[-4:]}</code>")
                        
                        solscan = f"https://solscan.io/tx/{sig}"
                        bubble = f"https://app.bubblemaps.io/sol/address/{sender}"
                        
                        msg = (f"🚨 <b>WHALE MOVEMENT DETECTED</b>\n\n"
                               f"💰 <b>Amount:</b> {diff:,.2f} SOL (<b>${usd_value:,.2f} USD</b>)\n"
                               f"📤 <b>From:</b> {s_name}\n"
                               f"📥 <b>To:</b> {r_name}\n\n"
                               f"🔗 <b>Intelligence:</b>\n"
                               f"• <a href='{solscan}'>Solscan Explorer</a>\n"
                               f"• <a href='{bubble}'>BubbleMaps</a>")
                        
                        if send_alert(msg):
                            log_to_supabase(diff, usd_value, sender, receiver, sig)

            last_processed_slot = current_slot
            
        except Exception as e:
            time.sleep(1)
            continue

if __name__ == "__main__":
    main()