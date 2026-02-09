import time, requests, os, datetime
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
    """Removes commands from the group chat to keep it clean."""
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

def handle_commands():
    global last_update_id
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {"offset": last_update_id + 1, "timeout": 1}
        res = requests.get(url, params=params, timeout=5).json()
        for update in res.get("result", []):
            last_update_id = update["update_id"]
            msg = update.get("message", {})
            chat_id = msg.get("chat", {}).get("id")
            user_id = msg.get("from", {}).get("id")
            message_id = msg.get("message_id")
            text = msg.get("text", "")
            
            if not user_id: continue

            # --- GROUP CLEANUP ---
            # If a command is used in the Group Chat (Negative ID), delete it.
            if text.startswith("/") and str(chat_id).startswith("-"):
                delete_message(chat_id, message_id)
                send_alert(user_id, "💡 <b>Note:</b> Please use commands here in private to keep the group chat focused on Whale Alerts!")

            # --- ONBOARDING & NEW USER NOTIFICATION ---
            if text == "/start":
                user_check = db.table("users").select("user_id").eq("user_id", user_id).execute()
                if not user_check.data:
                    username = msg.get("from", {}).get("username", "Unknown")
                    db.table("users").insert({"user_id": user_id, "username": username}).execute()
                    admin_msg = f"🚀 <b>New User Alert!</b>\n👤 User: @{username}\n🆔 ID: <code>{user_id}</code>"
                    send_alert(ADMIN_USER_ID, admin_msg)

                welcome = (
                    "🚀 <b>Welcome to Omni-Tracker v7.5</b>\n"
                    "━━━━━━━━━━━━━━\n"
                    "🕵️ <b>Private Features:</b>\n"
                    "🎯 <code>/watch [mint]</code> - Track a specific coin\n"
                    "📝 <code>/list</code> - Your personal watchlist\n"
                    "📈 <code>/pnl [mint]</code> - Live price check\n\n"
                    "💡 <i>Whale alerts (1k+ SOL) are in the main group.</i>"
                )
                send_alert(user_id, welcome)

            # --- WATCHLIST CRUD ---
            elif text.startswith("/watch "):
                mint = text.replace("/watch ", "").strip()
                if len(mint) > 30:
                    db.table("watchlist").upsert({"user_id": user_id, "mint": mint}).execute()
                    send_alert(user_id, f"🎯 <b>Monitoring {get_token_name(mint)} for you.</b>")
            
            elif text.startswith("/unwatch "):
                mint = text.replace("/unwatch ", "").strip()
                db.table("watchlist").delete().match({"user_id": user_id, "mint": mint}).execute()
                send_alert(user_id, f"❌ Stopped monitoring {mint[:4]}...")

            elif text == "/list":
                res = db.table("watchlist").select("mint").eq("user_id", user_id).execute()
                mints = [item['mint'] for item in res.data]
                msg = "🎯 <b>Your Watchlist:</b>\n" + "\n".join([f"- {get_token_name(m)}" for m in mints]) if mints else "📝 Empty."
                send_alert(user_id, msg)

            # --- ADMIN ONLY: STATS ---
            elif text == "/stats" and user_id == ADMIN_USER_ID:
                user_count = db.table("users").select("user_id", count="exact").execute()
                watch_count = db.table("watchlist").select("mint", count="exact").execute()
                stats_msg = (
                    f"📊 <b>System Growth Stats:</b>\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"👥 <b>Total Users:</b> {user_count.count}\n"
                    f"🎯 <b>Total Active Watches:</b> {watch_count.count}"
                )
                send_alert(ADMIN_USER_ID, stats_msg)
    except: pass

# --- MAIN LOOP ---

def main():
    global last_heartbeat, blocks_scanned
    print(f"🚀 V7.5 ONLINE | Admin: {ADMIN_USER_ID}", flush=True)
    last_slot = solana_client.get_slot().value - 1

    while True:
        handle_commands()
        
        # --- HOURLY HEARTBEAT ---
        # Checks if the bot is still scanning and alerts the group it's alive.
        if time.time() - last_heartbeat > 3600:
            heartbeat_msg = f"🤖 <b>Omni-Tracker Status:</b> Active\n🧱 <b>Blocks Scanned:</b> {blocks_scanned:,}\n💰 <b>SOL Price:</b> ${get_live_sol_price():.2f}"
            send_alert(TELEGRAM_CHAT_ID, heartbeat_msg)
            last_heartbeat = time.time()
            blocks_scanned = 0

        try:
            slot = solana_client.get_slot().value
            if slot <= last_slot:
                time.sleep(1)
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
                sender = str(tx.transaction.message.account_keys[0])

                # --- 1. PERSONAL WATCHLISTS ---
                if tx.meta.post_token_balances:
                    for b in tx.meta.post_token_balances:
                        if b.mint not in ["So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"]:
                            mint = b.mint
                            res = db.table("watchlist").select("user_id").eq("mint", mint).execute()
                            for row in res.data:
                                msg = (f"🎯 <b>WATCHLIST ALERT: {get_token_name(mint)}</b>\n"
                                       f"💰 <b>Value:</b> {diff:,.2f} SOL (${usd_val:,.2f})\n"
                                       f"🔗 <a href='https://solscan.io/tx/{sig}'>View Tx</a>")
                                send_alert(row['user_id'], msg, is_loud=True)

                # --- 2. GLOBAL WHALES ---
                if diff >= WHALE_THRESHOLD:
                    receiver = str(tx.transaction.message.account_keys[1]) if len(tx.transaction.message.account_keys) > 1 else "Unknown"
                    s_label, _ = get_label(sender)
                    r_label, r_is_known = get_label(receiver)
                    icon = "📥" if r_is_known else "🕵️"
                    msg = (f"{icon} <b>WHALE MOVE</b>\n"
                           f"💰 <b>{diff:,.0f} SOL</b> (${usd_val:,.2f})\n"
                           f"📤 <b>From:</b> {s_label}\n"
                           f"📥 <b>To:</b> {r_label}\n"
                           f"🔗 <a href='https://solscan.io/tx/{sig}'>Solscan</a>")
                    send_alert(TELEGRAM_CHAT_ID, msg, is_loud=(diff >= LOUD_THRESHOLD))

            last_slot = slot
        except: time.sleep(1)

if __name__ == "__main__":
    main()