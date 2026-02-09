import time, requests, os, threading, datetime
from solana.rpc.api import Client
from postgrest import SyncPostgrestClient
from dotenv import load_dotenv

load_dotenv()

# --- SETTINGS ---
WHALE_THRESHOLD = 1000  # Restored to 1k SOL
LOUD_THRESHOLD = 2500
ALCHEMY_URL = os.getenv("ALCHEMY_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") # Must be -1005254570403 in Railway
ADMIN_USER_ID = 7302870957 

# --- KNOWN WALLETS ---
KNOWN_WALLETS = {
    "H88yS9KmYvM9B6NSpYXzAn8f2g5tY0eD": "Binance Hot Wallet",
    "5tzC9Uo4H4XpWhmH5n8z9S6M6H8S5S5S": "Coinbase Cold",
    "ASTRL": "ASTRAL Whale"
}

# --- GLOBAL STATE ---
last_scan_time = time.time()
start_time = time.time()
blocks_scanned = 0
last_known_price = 110.00 
last_update_id = 0

# --- INITIALIZATION ---
solana_client = Client(ALCHEMY_URL)
db = SyncPostgrestClient(f"{SUPABASE_URL}/rest/v1", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})

# --- UTILITIES ---

def send_alert(chat_id, msg, is_loud=False):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": msg, "parse_mode": "HTML", "disable_notification": not is_loud}
    try: 
        res = requests.post(url, json=payload, timeout=8)
        if res.status_code != 200:
            print(f"❌ Telegram Error: {res.text}", flush=True)
    except: pass

def get_label(addr):
    addr_str = str(addr)
    label = KNOWN_WALLETS.get(addr_str, f"{addr_str[:4]}...{addr_str[-4:]}")
    is_known = addr_str in KNOWN_WALLETS
    return f"👤 {label}", is_known

def get_live_sol_price():
    global last_known_price
    try:
        res = requests.get("https://price.jup.ag/v4/price?ids=SOL", timeout=2).json()
        last_known_price = float(res['data']['SOL']['price'])
    except: pass
    return last_known_price

# --- THREAD 1: INSTANT COMMANDS ---
def handle_commands_loop():
    global last_update_id, last_scan_time
    print("👂 Listener Thread Active", flush=True)
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            params = {"offset": last_update_id + 1, "timeout": 10}
            res = requests.get(url, params=params, timeout=15).json()
            
            for update in res.get("result", []):
                last_update_id = update["update_id"]
                msg = update.get("message", {})
                user_id = msg.get("from", {}).get("id")
                text = msg.get("text", "")
                
                if not user_id or not text: continue

                if text == "/start":
                    send_alert(user_id, "🚀 <b>Omni-Tracker V8.0: Active & Optimized.</b>")

                elif text == "/health" and user_id == ADMIN_USER_ID:
                    lag = int(time.time() - last_scan_time)
                    status = "✅ Active" if lag < 120 else "⚠️ Stalled"
                    send_alert(ADMIN_USER_ID, f"🛡️ <b>Scanner:</b> {status} ({lag}s lag)\n🧱 <b>Blocks:</b> {blocks_scanned:,}")

        except Exception as e:
            time.sleep(2)

# --- THREAD 2: BLOCK SCANNER ---
def main():
    global last_scan_time, blocks_scanned
    print(f"🚀 V8.0 PRODUCTION ONLINE", flush=True)
    
    threading.Thread(target=handle_commands_loop, daemon=True).start()
    last_slot = solana_client.get_slot().value - 1

    while True:
        try:
            slot = solana_client.get_slot().value
            if slot <= last_slot:
                time.sleep(0.5)
                continue
            
            block = solana_client.get_block(slot, encoding="jsonParsed", max_supported_transaction_version=0).value
            if not block or not block.transactions:
                last_slot = slot
                continue
            
            last_scan_time = time.time()
            blocks_scanned += 1
            current_price = get_live_sol_price()

            for tx in block.transactions:
                if not tx.meta or tx.meta.err: continue
                diff = abs(tx.meta.pre_balances[0] - tx.meta.post_balances[0]) / 10**9
                
                if diff >= WHALE_THRESHOLD:
                    usd_val = diff * current_price
                    sig = str(tx.transaction.signatures[0])
                    sender = str(tx.transaction.message.account_keys[0])
                    receiver = str(tx.transaction.message.account_keys[1]) if len(tx.transaction.message.account_keys) > 1 else "Unknown"
                    
                    s_label, _ = get_label(sender)
                    r_label, r_known = get_label(receiver)
                    icon = "📥" if r_known else "🕵️"

                    msg = (f"{icon} <b>WHALE MOVE DETECTED</b>\n"
                           f"💰 <b>{diff:,.0f} SOL</b> (${usd_val:,.2f})\n"
                           f"📤 <b>From:</b> {s_label}\n"
                           f"📥 <b>To:</b> {r_label}\n"
                           f"🔗 <a href='https://solscan.io/tx/{sig}'>Solscan</a> | "
                           f"<a href='https://bubblemaps.io/solana/token/{sender}'>Bubble</a>")
                    
                    send_alert(TELEGRAM_CHAT_ID, msg, is_loud=(diff >= LOUD_THRESHOLD))

            last_slot = slot
        except: time.sleep(0.5)

if __name__ == "__main__":
    main()