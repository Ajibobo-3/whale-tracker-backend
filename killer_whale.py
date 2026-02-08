import time
import requests
import os
from solana.rpc.api import Client
from postgrest import SyncPostgrestClient
from dotenv import load_dotenv

load_dotenv()

# --- SETTINGS ---
WHALE_THRESHOLD = 1000  
ALCHEMY_URL = os.getenv("ALCHEMY_URL", "https://api.mainnet-beta.solana.com")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- GLOBAL PRICE MEMORY ---
last_known_price = 105.0 # Starting default

db_url = f"{SUPABASE_URL}/rest/v1"
headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
db = SyncPostgrestClient(db_url, headers=headers)

def get_sol_price():
    global last_known_price
    try:
        res = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd", timeout=5).json()
        price = float(res['solana']['usd'])
        last_known_price = price # Update memory
        return price
    except:
        print(f"⚠️ Price Oracle busy. Using memory: ${last_known_price}")
        return last_known_price # Return the last good price we saw

def send_alert(msg):
    if not TELEGRAM_BOT_TOKEN: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

def main():
    print(f"🚀 ENGINE STARTING: Threshold {WHALE_THRESHOLD} SOL", flush=True)
    client = Client(ALCHEMY_URL, timeout=15)
    last_processed_slot = 0

    while True:
        try:
            slot_resp = client.get_slot()
            current_slot = slot_resp.value

            if current_slot <= last_processed_slot:
                time.sleep(3) 
                continue

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
                            
                            # Now always returns a valid number (Live or Memory)
                            price = get_sol_price()
                            usd_val = diff * price
                            
                            print(f"🐋 WHALE: {diff:.2f} SOL (${usd_val:,.2f})", flush=True)
                            
                            # Sync to DB
                            data = {"sol_amount": diff, "usd_value": usd_val, "signature": sig}
                            db.table("whale_alerts").insert(data).execute()
                            
                            # Telegram Alert
                            msg = (f"🚨 <b>WHALE DETECTED</b>\n\n"
                                   f"💰 <b>Amount:</b> {diff:,.2f} SOL\n"
                                   f"💵 <b>Est. Value:</b> ${usd_val:,.2f} USD\n"
                                   f"🔗 <a href='https://solscan.io/tx/{sig}'>Solscan Explorer</a>")
                            send_alert(msg)
                    except:
                        continue 

            last_processed_slot = current_slot
            time.sleep(1) 

        except Exception as e:
            print(f"⚠️ System Hiccup: {e}", flush=True)
            time.sleep(10) 
            client = Client(ALCHEMY_URL, timeout=15)
            continue

if __name__ == "__main__":
    main()