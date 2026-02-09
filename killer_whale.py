import time, requests, os, threading
from solana.rpc.api import Client
from postgrest import SyncPostgrestClient
from dotenv import load_dotenv

load_dotenv()

# --- SETUP ---
WHALE_THRESHOLD = 1000
LOUD_THRESHOLD = 2500
ALCHEMY_URL = os.getenv("ALCHEMY_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ADMIN_USER_ID = 7302870957 

# --- STATE ---
solana_client = Client(ALCHEMY_URL)
db = SyncPostgrestClient(f"{SUPABASE_URL}/rest/v1", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
last_known_price = 108.50 
last_update_id = 0
last_heartbeat = time.time()
blocks_scanned = 0

# --- CORE UTILITY FUNCTIONS ---

def send_alert(chat_id, msg, is_loud=False):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": msg, "parse_mode": "HTML", "disable_notification": not is_loud}
    try: requests.post(url, json=payload, timeout=5)
    except: pass

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

def get_label(addr):
    addr_str = str(addr)
    return f"👤 {addr_str[:4]}...{addr_str[-4:]}", False

# --- THREAD 1: THE LISTENER ---
def handle_commands_loop():
    global last_update_id
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

                # Command Logic (Cleaned for speed)
                if text.startswith("/") and str(chat_id).startswith("-"):
                    delete_message(chat_id, message_id)
                    send_alert(user_id, "💡 Please use commands here in private!")

                if text == "/start":
                    send_alert(user_id, "🚀 <b>Omni-Tracker V7.6: Instant Response Active.</b>")
                
                elif text.startswith("/watch "):
                    mint = text.replace("/watch ", "").strip()
                    if len(mint) > 30:
                        db.table("watchlist").upsert({"user_id": user_id, "mint": mint}).execute()
                        send_alert(user_id, f"🎯 Monitoring {get_token_name(mint)}")

                elif text == "/list":
                    res_db = db.table("watchlist").select("mint").eq("user_id", user_id).execute()
                    mints = [item['mint'] for item in res_db.data]
                    send_alert(user_id, "🎯 Watchlist:\n" + "\n".join([f"- {get_token_name(m)}" for m in mints]) if mints else "Empty.")

                elif text == "/stats" and user_id == ADMIN_USER_ID:
                    u_count = db.table("users").select("user_id", count="exact").execute()
                    w_count = db.table("watchlist").select("mint", count="exact").execute()
                    send_alert(ADMIN_USER_ID, f"📊 Total Users: {u_count.count}\n🎯 Total Watches: {w_count.count}")

        except Exception as e:
            time.sleep(2)

# --- THREAD 2: THE SCANNER ---
def main():
    global last_heartbeat, blocks_scanned
    print(f"🚀 V7.6 ONLINE | Admin: {ADMIN_USER_ID}", flush=True)
    
    # Start the Command Listener in the background
    cmd_thread = threading.Thread(target=handle_commands_loop, daemon=True)
    cmd_thread.start()

    last_slot = solana_client.get_slot().value - 1

    while True:
        # HOURLY HEARTBEAT
        if time.time() - last_heartbeat > 3600:
            heartbeat_msg = f"🤖 <b>Status:</b> Active\n🧱 <b>Blocks:</b> {blocks_scanned:,}\n💰 <b>SOL:</b> ${get_live_sol_price():.2f}"
            send_alert(TELEGRAM_CHAT_ID, heartbeat_msg)
            last_heartbeat = time.time()
            blocks_scanned = 0

        try:
            slot = solana_client.get_slot().value
            if slot <= last_slot:
                time.sleep(0.5)
                continue
            
            block = solana_client.get_block(slot, encoding="jsonParsed", max_supported_transaction_version=0).value
            if not block or not block.transactions:
                last_slot = slot
                continue
            
            blocks_scanned += 1
            current_price = get_live_sol_price()

            for tx in block.transactions:
                if not tx.meta or tx.meta.err: continue
                diff = abs(tx.meta.pre_balances[0] - tx.meta.post_balances[0]) / 10**9
                usd_val = diff * current_price
                sig = str(tx.transaction.signatures[0])

                # WHALE CHECK (>= 1000 SOL)
                if diff >= WHALE_THRESHOLD:
                    msg = (f"🕵️ <b>WHALE MOVE</b>\n💰 <b>{diff:,.0f} SOL</b> (${usd_val:,.2f})\n"
                           f"🔗 <a href='https://solscan.io/tx/{sig}'>Solscan</a>")
                    send_alert(TELEGRAM_CHAT_ID, msg, is_loud=(diff >= LOUD_THRESHOLD))

            last_slot = slot
        except: time.sleep(0.5)

if __name__ == "__main__":
    main()