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

# --- DATA REGISTRY ---
last_known_price = 105.0
KNOWN_EXCHANGES = {
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvu6Gn": "Binance",
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM": "Binance",
    "ASTyfSdyv7moByo1Zi9yG3S86W9U68KshY9Pdu6FfH8B": "Coinbase",
    "6686pSGYmZpL9pS5v9K9pS5v9K9pS5v9K9pS5v9K9pS": "Kraken"
}

db_url = f"{SUPABASE_URL}/rest/v1"
headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
db = SyncPostgrestClient(db_url, headers=headers)
solana_client = Client(ALCHEMY_URL)

def get_wallet_profile(address):
    """Analyzes a wallet to see if it's an Exchange, New, or Idle account."""
    if address in KNOWN_EXCHANGES:
        return f"🏢 {KNOWN_EXCHANGES[address]} (Exchange)"
    
    try:
        # Get transaction signatures for this address
        sigs = solana_client.get_signatures_for_address(address, limit=5).value
        
        if not sigs:
            return "🆕 New Account"
        
        # Check for Idleness (Last tx > 30 days ago)
        last_tx_time = sigs[0].block_time
        current_time = int(time.time())
        if (current_time - last_tx_time) > (30 * 24 * 60 * 60):
            return "💤 Idle Account (30d+)"
            
        if len(sigs) < 5:
            return "🐣 Fresh Account"
            
        return "👤 Private Wallet"
    except:
        return "👤 Private Wallet"

def get_sol_price():
    global last_known_price
    try:
        res = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd", timeout=5).json()
        price = float(res['solana']['usd'])
        last_known_price = price
        return price
    except:
        return last_known_price

def send_alert(msg):
    if not TELEGRAM_BOT_TOKEN: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

def main():
    print(f"🚀 ENGINE STARTING WITH WALLET PROFILER...", flush=True)
    last_processed_slot = 0

    while True:
        try:
            current_slot = solana_client.get_slot().value
            if current_slot <= last_processed_slot:
                time.sleep(3) 
                continue

            block = solana_client.get_block(current_slot, max_supported_transaction_version=0).value
            
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
                        
                        # --- NEW INTELLIGENCE ---
                        sender_profile = get_wallet_profile(sender)
                        receiver_profile = get_wallet_profile(receiver)
                        
                        price = get_sol_price()
                        usd_val = diff * price
                        
                        msg = (f"🚨 <b>WHALE MOVEMENT DETECTED</b>\n\n"
                               f"💰 <b>Amount:</b> {diff:,.2f} SOL\n"
                               f"💵 <b>Value:</b> ${usd_val:,.2f} USD\n\n"
                               f"📤 <b>From:</b> {sender_profile}\n"
                               f"<code>{sender[:4]}...{sender[-4:]}</code>\n"
                               f"📥 <b>To:</b> {receiver_profile}\n"
                               f"<code>{receiver[:4]}...{receiver[-4:]}</code>\n\n"
                               f"🔗 <a href='https://solscan.io/tx/{sig}'>View on Solscan</a>")
                        
                        send_alert(msg)
                        
                        # Sync to DB
                        db.table("whale_alerts").insert({
                            "sol_amount": diff, 
                            "usd_value": usd_val, 
                            "signature": sig,
                            "sender": sender,
                            "receiver": receiver
                        }).execute()

            last_processed_slot = current_slot
            time.sleep(1) 

        except Exception as e:
            time.sleep(10) 
            continue

if __name__ == "__main__":
    main()