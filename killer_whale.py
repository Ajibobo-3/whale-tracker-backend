import time
import requests
import os
from solana.rpc.api import Client
from supabase import create_client, Client as SupabaseClient
from dotenv import load_dotenv

# --- ⚙️ SETTINGS ---
load_dotenv()
WHALE_THRESHOLD = 1000  
# Use a public RPC fallback if Alchemy is being grumpy
ALCHEMY_URL = os.getenv("ALCHEMY_URL", "https://api.mainnet-beta.solana.com")

# --- 🔑 CREDENTIALS ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Initialize Supabase
try:
    supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"FATAL: Supabase Init Failed: {e}")
    exit(1)

def get_sol_price():
    try:
        res = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd", timeout=5).json()
        return float(res['solana']['usd'])
    except:
        return 105.0 # Reliable fallback

def send_alert(msg):
    if not TELEGRAM_BOT_TOKEN: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

def main():
    print(f"🚀 ENGINE STARTING: Threshold {WHALE_THRESHOLD} SOL", flush=True)
    # Using a shorter timeout to prevent hanging
    client = Client(ALCHEMY_URL, timeout=15)
    
    last_processed_slot = 0

    while True:
        try:
            # 1. Get current slot
            slot_resp = client.get_slot()
            current_slot = slot_resp.value

            if current_slot <= last_processed_slot:
                time.sleep(3) # Slow heartbeat
                continue

            # 2. Get block data
            # max_supported_transaction_version is critical for modern Solana blocks
            block_resp = client.get_block(current_slot, max_supported_transaction_version=0)
            block = block_resp.value
            
            if block and block.transactions:
                for tx in block.transactions:
                    try:
                        if not tx.meta or tx.meta.err: continue
                        
                        pre = tx.meta.pre_balances[0]
                        post = tx.meta.post_balances[0]
                        diff = (pre - post) / 10**9 
                        
                        if diff >= WHALE_THRESHOLD:
                            sig = str(tx.transaction.signatures[0])
                            price = get_sol_price()
                            usd_val = diff * price
                            
                            # Log and Notify
                            print(f"🐋 WHALE: {diff:.2f} SOL (${usd_val:,.2f})", flush=True)
                            
                            data = {"sol_amount": diff, "usd_value": usd_val, "signature": sig}
                            supabase.table("whale_alerts").insert(data).execute()
                            
                            msg = f"🚨 <b>WHALE DETECTED</b>\n💰 {diff:,.2f} SOL\n🔗 <a href='https://solscan.io/tx/{sig}'>Solscan</a>"
                            send_alert(msg)
                    except:
                        continue # Skip bad transactions within the block

            last_processed_slot = current_slot
            time.sleep(1) # Small breather between blocks

        except Exception as e:
            print(f"⚠️ System Hiccup: {e}", flush=True)
            time.sleep(10) # Heavy breather if the network is failing
            # Re-initialize client if it keeps failing
            client = Client(ALCHEMY_URL, timeout=15)
            continue

if __name__ == "__main__":
    main()