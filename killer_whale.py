import time, requests, os, threading, datetime
from solana.rpc.api import Client
from postgrest import SyncPostgrestClient
from dotenv import load_dotenv

load_dotenv()

# --- SETUP ---
WHALE_THRESHOLD = 0.1 # Very low for testing
LOUD_THRESHOLD = 2500
ALCHEMY_URL = os.getenv("ALCHEMY_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ADMIN_USER_ID = 7302870957 

# --- GLOBAL HEALTH STATE ---
last_scan_time = time.time()
start_time = time.time()
blocks_scanned = 0
last_known_price = 108.50 
last_update_id = 0

# --- STATE INITIALIZATION ---
solana_client = Client(ALCHEMY_URL)
db = SyncPostgrestClient(f"{SUPABASE_URL}/rest/v1", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})

# --- UPDATED UTILITY WITH LOGGING ---

def send_alert(chat_id, msg, is_loud=False):
    """Sends a message and prints any errors to Railway Logs."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": msg, "parse_mode": "HTML", "disable_notification": not is_loud}
    try: 
        res = requests.post(url, json=payload, timeout=8)
        if res.status_code != 200:
            print(f"❌ Telegram Error for {chat_id}: {res.status_code} - {res.text}", flush=True)
        return res
    except Exception as e: 
        print(f"❌ Connection Error: {e}", flush=True)
        return None

def delete_message(chat_id, message_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteMessage"
    payload = {"chat_id": chat_id, "message_id": message_id}
    try: requests.post(url, json=payload, timeout=5)
    except: pass

def get_token_name(mint):
    try:
        res = requests.get(f"https://token.jup.ag/all", timeout=5).json()
        for t in res:
            if t['address'] == mint: return f"${t['symbol']}"
        return f"Token ({mint[:4]})"
    except: return "Meme Coin"

def get_live_sol_price():
    global last_known_price
    try:
        res = requests.get("https://price.jup.ag/v4/price?ids=SOL", timeout=2).json()
        last_known_price = float(res['data']['SOL']['price'])
    except: pass
    return last_known_price

# --- THREAD 1: THE LISTENER ---
def handle_commands_loop():
    global last_update_id, last_scan_time, blocks_scanned
    print("👂 Command Listener Thread Started", flush=True)
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            params = {"offset": last_update_id + 1, "timeout": 10}
            res = requests.get(url, params=params, timeout=15).json()
            
            for update in res.get("result", []):
                last_update_id = update["update_id"]
                msg = update.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                user_id = msg.get("from", {}).get("id")
                message_id = msg.get("message_id")
                text = msg.get("text", "")
                
                if not user_id or not text: continue

                # CLEANUP: Delete group commands
                if text.startswith("/") and str(chat_id).startswith("-"):
                    delete_message(chat_id, message_id)
                    send_alert(user_id, "💡 Please use commands here in private!")

                if text == "/start":
                    send_alert(user_id, "🚀 <b>Omni-Tracker V7.8: Live Debugging Active.</b>")

                # --- NEW ID DISCOVERY COMMAND ---
                elif text == "/id":
                    # Type /id in the GROUP to see what the bot thinks the ID is
                    send_alert(chat_id, f"📍 <b>Chat ID:</b> <code>{chat_id}</code>\n(Paste this into Railway!)")

                elif text == "/health" and user_id == ADMIN_USER_ID:
                    scanner_lag = time.time() - last_scan_time
                    scanner_status = "✅ Active" if scanner_lag < 120 else "⚠️ Stalled"
                    health_msg = f"🛡️ <b>Scanner:</b> {scanner_status} ({int(scanner_lag)}s lag)\n🧱 <b>Blocks:</b> {blocks_scanned:,}"
                    send_alert(ADMIN_USER_ID, health_msg)

                elif text.startswith("/watch "):
                    mint = text.replace("/watch ", "").strip()
                    if len(mint) > 30:
                        db.table("watchlist").upsert({"user_id": user_id, "mint": mint}).execute()
                        send_alert(user_id, f"🎯 Monitoring {get_token_name(mint)}")

        except Exception as e:
            time.sleep(2)

# --- THREAD 2: THE SCANNER ---
def main():
    global last_scan_time, blocks_scanned
    print(f"🚀 V7.8 ONLINE | Admin: {ADMIN_USER_ID}", flush=True)
    
    cmd_thread = threading.Thread(target=handle_commands_loop, daemon=True)
    cmd_thread.start()

    last_slot = solana_client.get_slot().value - 1
    last_heartbeat = time.time()

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
                usd_val = diff * current_price
                sig = str(tx.transaction.signatures[0])

                if diff >= WHALE_THRESHOLD:
                    msg = (f"🕵️ <b>TEST WHALE MOVE</b>\n💰 <b>{diff:,.2f} SOL</b>\n"
                           f"🔗 <a href='https://solscan.io/tx/{sig}'>Solscan</a>")
                    # SEND TO GROUP
                    send_alert(TELEGRAM_CHAT_ID, msg)

            last_slot = slot
        except: time.sleep(0.5)

if __name__ == "__main__":
    main()