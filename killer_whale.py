import time
import requests
import os
from solana.rpc.api import Client
from supabase import create_client, Client as SupabaseClient
from dotenv import load_dotenv

# --- ⚙️ GROWTH ENGINE SETTINGS ---
load_dotenv()

WHALE_THRESHOLD = 1000  
# Use the environment variable or fallback to Alchemy
ALCHEMY_URL = os.getenv("ALCHEMY_URL", "https://solana-mainnet.g.alchemy.com/v2/gV3Ws30jlt4osFOdMJCKD")

# --- 🔑 NOTIFICATION & DB CHANNELS (SECURED) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Initialize Supabase Safely
if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ ERROR: Supabase credentials missing!")
    exit(1)

supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)
SOL_MINT = "So11111111111111111111111111111111111111112"

KNOWN_WALLETS = {
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvu6Gn": "Binance Hot 1",
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM": "Binance Hot 2",
    "HuDxqF2acC6f8T7Ea8K3P6qK4WjH4Z3h4z6f5e7h8j9k": "Kraken Cold",
}

# --- 📊 FAIL-PROOF PRICE ORACLE ---
def get_sol_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
        res = requests.get(url, timeout=5).json()
        return float(res['solana']['usd'])
    except Exception:
        try:
            url = "https://min-api.cryptocompare.com/data/price?fsym=SOL&tsyms=USD"
            res = requests.get(url, timeout=5).json()
            return float(res['USD'])
        except Exception as e:
            print(f"⚠️ Price Oracles Failed. Using fallback. Error: {e}")
            return 105.0 # Fallback price

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
        print(f"📁 [DB] Entry Synced: {sol_amount} SOL (${usd_val:,.2f})", flush=True)
    except Exception as e:
        print(f"⚠️ Supabase Sync Error: {e}")

def send_alert(msg):
    if not TELEGRAM_BOT_TOKEN: return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=10)
        return True
    except Exception as e:
        print(f"❌ Telegram Error: {e}")
        return False

def main():
    print(f"🌊 MONITORING FOR MOVES > {WHALE_THRESHOLD} SOL...", flush=True)
    client = Client(ALCHEMY_URL)
    
    send_alert("🚀 <b>GROWTH ENGINE ACTIVATED</b>\n📊 Status: Stabilized Loop (2.0s sleep)")
    
    last_processed_slot = 0

    while True:
        try:
            current_slot = client.get_slot().value
            
            # If we haven't moved to a new block, wait 2 seconds
            if current_slot <= last_processed_slot:
                time.sleep(2.0) 
                continue

            block = client.get_block(current_slot, max_supported_transaction_version=0).value
            
            if block and block.transactions:
                for tx in block.transactions:
                    if not tx.meta or tx.meta.err: continue
                    
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
                        
                        msg = (f"🚨 <b>WHALE MOVEMENT DETECTED</b>\n\n"
                               f"💰 <b>Amount:</b> {diff:,.2f} SOL (<b>${usd_value:,.2f} USD</b>)\n"
                               f"📤 <b>From:</b> {s_name}\n"
                               f"📥 <b>To:</b> {r_name}\n\n"
                               f"🔗 <a href='https://solscan.io/tx/{sig}'>Solscan Explorer</a>")
                        
                        if send_alert(msg):
                            log_to_supabase(diff, usd_value, sender, receiver, sig)
                            # Small rest after processing a whale to keep the connection cool
                            time.sleep(0.5)

            last_processed_slot = current_slot
            
        except Exception as e:
            print(f"⚠️ Loop Warning: {e}")
            time.sleep(5) # Longer sleep if we hit a serious error (like rate limit)
            continue

if __name__ == "__main__":
    main()