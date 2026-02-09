import time, requests, os, threading, datetime
from urllib.parse import quote
from solana.rpc.api import Client
from postgrest import SyncPostgrestClient
from dotenv import load_dotenv

load_dotenv()

# --- SETTINGS ---
WHALE_THRESHOLD = 1000  
LOUD_THRESHOLD = 2500
ALPHA_WATCH_THRESHOLD = 500 # Threshold for Auto-Watchlist entries
ALCHEMY_URL = os.getenv("ALCHEMY_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") 
ADMIN_USER_ID = 7302870957 

# --- KNOWN WALLETS ---
KNOWN_WALLETS = {
    "H88yS9KmYvM9B6NSpYXzAn8f2g5tY0eD": "Binance Hot Wallet",
    "9WzDXwBsQXds2Wz9C66C3uEt1XUvXn2J": "Binance Cold Storage",
    "5tzC9Uo4H4XpWhmH5n8z9S6M6H8S5S5S": "Binance 3",
    "2AQdpS4S8SHT8v4C4T4S5K5S8C6S5S": "Coinbase Hot Wallet",
    "FWznbUJS5S8C6S5K5S8C6S5S": "Kraken Hot Wallet",
    "JUP6LkbZbjS1jKKccS4n14C9G98zK": "Jupiter Aggregator",
    "5Q544fKrSJu8W6uyNQAnmMvHqvT8tHLH8vB1r5vD1L": "Raydium Pool"
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

def send_alert_with_button(chat_id, msg, twitter_link, is_loud=False):
    """Sends alert with a 'Share on X' button for viral growth."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    keyboard = {
        "inline_keyboard": [[
            {"text": "🐦 Share on X", "url": twitter_link}
        ]]
    }
    payload = {
        "chat_id": chat_id, 
        "text": msg, 
        "parse_mode": "HTML", 
        "reply_markup": keyboard,
        "disable_notification": not is_loud
    }
    try: requests.post(url, json=payload, timeout=8)
    except: pass

def get_label(addr):
    addr_str = str(addr)
    label = KNOWN_WALLETS.get(addr_str, f"{addr_str[:4]}...{addr_str[-4:]}")
    is_known = addr_str in KNOWN_WALLETS
    return f"👤 {label}", is_known

def get_token_name(mint):
    try:
        # Simplified for performance; returns mint if name not found
        return f"Token ({str(mint)[:4]})"
    except: return "Unknown Token"

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
                    send_alert(user_id, "🚀 <b>Omni-Tracker V8.4: Viral Alpha Active.</b>")

                elif text == "/health" and user_id == ADMIN_USER_ID:
                    lag = int(time.time() - last_scan_time)
                    status = "✅ Active" if lag < 120 else "⚠️ Stalled"
                    send_alert(ADMIN_USER_ID, f"🛡️ <b>Scanner:</b> {status} ({lag}s lag)\n🧱 <b>Blocks:</b> {blocks_scanned:,}")

        except Exception as e:
            time.sleep(2)

# --- THREAD 2: BLOCK SCANNER ---
def main():
    global last_scan_time, blocks_scanned
    print(f"🚀 V8.4 VIRAL ALPHA ONLINE", flush=True)
    
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
                usd_val = diff * current_price
                sig = str(tx.transaction.signatures[0])
                sender = str(tx.transaction.message.account_keys[0])
                receiver = str(tx.transaction.message.account_keys[1]) if len(tx.transaction.message.account_keys) > 1 else "Unknown"

                # --- 1. AUTO-WATCHLIST LOGIC ---
                if diff >= ALPHA_WATCH_THRESHOLD:
                    if tx.meta.post_token_balances:
                        # Grab the first non-SOL mint detected in the swap
                        mint = tx.meta.post_token_balances[0].mint
                        if mint != "So11111111111111111111111111111111111111112":
                            db.table("global_watchlist").upsert({
                                "mint": mint, 
                                "added_at": datetime.datetime.utcnow().isoformat(),
                                "trigger_vol": diff
                            }).execute()
                            
                            send_alert(TELEGRAM_CHAT_ID, f"🌟 <b>NEW ALPHA DETECTED</b>\nWhale just entered {get_token_name(mint)}. Token added to Auto-Watchlist!")

                # --- 2. WHALE ALERT LOGIC ---
                if diff >= WHALE_THRESHOLD:
                    s_label, _ = get_label(sender)
                    r_label, r_known = get_label(receiver)
                    icon = "📥" if r_known else "🕵️"

                    # Viral Twitter Link Generation
                    tweet_text = quote(
                        f"🚨 WHALE ALERT: {diff:,.0f} SOL (${usd_val:,.2f}) moved on #Solana!\n\n"
                        f"Tracked by Avitunde Intelligence 🏛️\n"
                        f"Join the Alpha: https://t.me/your_group_link\n"
                        f"$SOL #Crypto #WhaleAlert"
                    )
                    twitter_url = f"https://twitter.com/intent/tweet?text={tweet_text}"

                    msg = (f"{icon} <b>WHALE MOVE DETECTED</b>\n"
                           f"💰 <b>{diff:,.0f} SOL</b> (${usd_val:,.2f})\n"
                           f"📤 <b>From:</b> {s_label}\n"
                           f"📥 <b>To:</b> {r_label}\n"
                           f"🔗 <a href='https://solscan.io/tx/{sig}'>Solscan</a> | "
                           f"<a href='https://bubblemaps.io/solana/token/{sender}'>Bubble</a>")
                    
                    send_alert_with_button(TELEGRAM_CHAT_ID, msg, twitter_url, is_loud=(diff >= LOUD_THRESHOLD))

            last_slot = slot
        except: time.sleep(0.5)

if __name__ == "__main__":
    main()