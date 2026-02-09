import time, requests, os, threading, datetime
from datetime import timezone
from urllib.parse import quote
from solana.rpc.api import Client
from postgrest import SyncPostgrestClient
from dotenv import load_dotenv

load_dotenv()

# --- 1. GLOBAL SETTINGS ---
WHALE_THRESHOLD = 1000  
LOUD_THRESHOLD = 2500
ALPHA_WATCH_THRESHOLD = 500 
ALCHEMY_URL = os.getenv("ALCHEMY_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") 
ADMIN_USER_ID = 7302870957 

# --- 2. STATE INITIALIZATION ---
solana_client = Client(ALCHEMY_URL)
db = SyncPostgrestClient(f"{SUPABASE_URL}/rest/v1", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})

last_scan_time = time.time()
blocks_scanned = 0
last_known_price = 110.00 
last_update_id = 0

KNOWN_WALLETS = {
    "H88yS9KmYvM9B6NSpYXzAn8f2g5tY0eD": "Binance Hot Wallet",
    "9WzDXwBsQXds2Wz9C66C3uEt1XUvXn2J": "Binance Cold Storage",
    "JUP6LkbZbjS1jKKccS4n14C9G98zK": "Jupiter Aggregator"
}

# --- 3. UTILITY FUNCTIONS ---

def get_live_sol_price():
    global last_known_price
    try:
        res = requests.get("https://price.jup.ag/v4/price?ids=SOL", timeout=2).json()
        last_known_price = float(res['data']['SOL']['price'])
    except: pass
    return last_known_price

def get_label(addr):
    addr_str = str(addr)
    label = KNOWN_WALLETS.get(addr_str, f"{addr_str[:4]}...{addr_str[-4:]}")
    is_known = addr_str in KNOWN_WALLETS
    return f"👤 {label}", is_known

def get_token_name(mint):
    # Shorten mint for cleaner UI
    return f"Token ({str(mint)[:4]}...{str(mint)[-4:]})"

def send_alert(chat_id, msg, is_loud=False):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": msg, "parse_mode": "HTML", "disable_notification": not is_loud}
    try: requests.post(url, json=payload, timeout=8)
    except: pass

def send_alert_with_button(chat_id, msg, twitter_link, is_loud=False):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    keyboard = {"inline_keyboard": [[{"text": "🐦 Share on X", "url": twitter_link}]]}
    payload = {
        "chat_id": chat_id, 
        "text": msg, 
        "parse_mode": "HTML", 
        "reply_markup": keyboard,
        "disable_notification": not is_loud
    }
    try: requests.post(url, json=payload, timeout=8)
    except: pass

# --- 4. THE ALPHA ENGINE ---

def process_whale_move(tx, diff):
    """
    Unified logic for Signal Intelligence, Viral Sharing, and Auto-Watchlist.
    """
    try:
        current_price = last_known_price
        usd_val = diff * current_price
        sig = str(tx.transaction.signatures[0])
        sender = str(tx.transaction.message.account_keys[0])
        receiver = str(tx.transaction.message.account_keys[1]) if len(tx.transaction.message.account_keys) > 1 else "Unknown"

        # --- 1. AUTO-WATCHLIST (Alpha Detection) ---
        if diff >= ALPHA_WATCH_THRESHOLD and hasattr(tx.meta, 'post_token_balances') and tx.meta.post_token_balances:
            mint = tx.meta.post_token_balances[0].mint
            if mint != "So11111111111111111111111111111111111111112":
                db.table("global_watchlist").upsert({
                    "mint": mint, 
                    "added_at": datetime.datetime.now(timezone.utc).isoformat(),
                    "trigger_vol": diff
                }).execute()
                send_alert(TELEGRAM_CHAT_ID, f"🌟 <b>ALPHA DETECTED</b>\nWhale entered {get_token_name(mint)}.\n🔗 <a href='https://solscan.io/token/{mint}'>Token View</a>")

        # --- 2. SIGNAL INTELLIGENCE (Labels) ---
        s_label, s_known = get_label(sender)
        r_label, r_known = get_label(receiver)
        
        if s_known and not r_known:
            signal, icon = "🚀 <b>BULLISH OUTFLOW</b>", "📤"
            note = "<i>(Accumulation: Moving to cold storage)</i>"
        elif not s_known and r_known:
            signal, icon = "🚨 <b>BEARISH INFLOW</b>", "📥"
            note = "<i>(Potential Sell: Moving to exchange)</i>"
        else:
            signal, icon = "🕵️ <b>NEUTRAL MOVE</b>", "🔄"
            note = "<i>(Private wallet transfer)</i>"

        # --- 3. VIRAL SHARING (Twitter/X) ---
        tweet_text = quote(
            f"🚨 WHALE ALERT: {diff:,.0f} SOL (${usd_val:,.2f}) moved! #Solana\n\n"
            f"Tracked by Avitunde Intelligence 🏛️\n"
            f"Join the Alpha: https://t.me/your_group_link"
        )
        twitter_url = f"https://twitter.com/intent/tweet?text={tweet_text}"

        # --- 4. TELEGRAM ALERT ---
        msg = (f"{icon} {signal}\n"
               f"💰 <b>{diff:,.0f} SOL</b> (${usd_val:,.2f})\n\n"
               f"📤 <b>From:</b> {s_label}\n"
               f"📥 <b>To:</b> {r_label}\n"
               f"📝 {note}\n\n"
               f"🔗 <a href='https://solscan.io/tx/{sig}'>Solscan</a> | "
               f"<a href='https://bubblemaps.io/solana/token/{sender}'>BubbleMaps</a>")
        
        send_alert_with_button(TELEGRAM_CHAT_ID, msg, twitter_url, is_loud=(diff >= LOUD_THRESHOLD))

    except Exception as e:
        print(f"❌ Error in process_whale_move: {e}", flush=True)

# --- 5. THE LISTENER & SCANNER THREADS ---

def handle_commands_loop():
    global last_update_id, last_scan_time
    print("👂 Command Listener Active", flush=True)
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
                
                if text == "/start":
                    send_alert(user_id, "🚀 <b>Avitunde Intelligence V9.0 Active.</b>")

                elif text == "/health" and user_id == ADMIN_USER_ID:
                    lag = int(time.time() - last_scan_time)
                    send_alert(ADMIN_USER_ID, f"🛡️ Scanner active ({lag}s lag)\n🧱 Blocks: {blocks_scanned}")

                elif text == "/topbuy":
                    time_threshold = (datetime.datetime.now(timezone.utc) - datetime.timedelta(hours=24)).isoformat()
                    response = db.table("global_watchlist").select("mint, trigger_vol").gt("added_at", time_threshold).execute()
                    
                    if not response.data:
                        send_alert(TELEGRAM_CHAT_ID, "📉 <b>No whale entries in 24H.</b>")
                        continue

                    # Group and Rank
                    rankings = {}
                    for entry in response.data:
                        m, v = entry['mint'], entry['trigger_vol']
                        rankings[m] = rankings.get(m, 0) + v
                    
                    sorted_list = sorted(rankings.items(), key=lambda x: x[1], reverse=True)[:5]
                    summary = "🏛️ <b>TOP WHALE ENTRIES (24H)</b>\n\n"
                    for i, (mint, total_vol) in enumerate(sorted_list, 1):
                        summary += f"{i}. <code>{mint[:4]}...{mint[-4:]}</code>\n💰 Total: <b>{total_vol:,.0f} SOL</b>\n\n"
                    
                    send_alert(TELEGRAM_CHAT_ID, summary)

        except: time.sleep(2)

def main():
    global last_scan_time, blocks_scanned
    print(f"🚀 V9.0 PRODUCTION READY ONLINE", flush=True)
    threading.Thread(target=handle_commands_loop, daemon=True).start()
    
    last_slot = solana_client.get_slot().value 

    while True:
        try:
            current_slot = solana_client.get_slot().value
            if current_slot - last_slot > 10:
                last_slot = current_slot
            if current_slot <= last_slot:
                time.sleep(0.2); continue
            
            block_data = solana_client.get_block(current_slot, encoding="jsonParsed", max_supported_transaction_version=0)
            block = block_data.value
            if not block or not block.transactions:
                last_slot = current_slot; continue
            
            last_scan_time = time.time()
            blocks_scanned += 1
            if blocks_scanned % 100 == 0: get_live_sol_price()

            for tx in block.transactions:
                try:
                    if not tx.meta or tx.meta.err: continue
                    diff = abs(tx.meta.pre_balances[0] - tx.meta.post_balances[0]) / 10**9
                    if diff >= WHALE_THRESHOLD:
                        process_whale_move(tx, diff)
                except: continue 

            last_slot = current_slot
        except Exception as e:
            print(f"⚠️ Scanner Error: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()