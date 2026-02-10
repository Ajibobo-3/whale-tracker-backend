import time, requests, os, threading, datetime, gc
from datetime import timezone
from urllib.parse import quote
from solana.rpc.api import Client
from postgrest import SyncPostgrestClient
from dotenv import load_dotenv

load_dotenv()

# --- 1. GLOBAL SETTINGS ---
WHALE_THRESHOLD = 0.1  # Keeping your test threshold
LOUD_THRESHOLD = 2500
ALPHA_WATCH_THRESHOLD = 500 
ALCHEMY_URL = os.getenv("ALCHEMY_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") 
ADMIN_USER_ID = 7302870957 

# --- 3. STATE INITIALIZATION ---
# Add a timeout to prevent the bot from hanging on slow blocks
solana_client = Client(ALCHEMY_URL, timeout=15)
db = SyncPostgrestClient(f"{SUPABASE_URL}/rest/v1", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})

last_scan_time = time.time()
blocks_scanned = 0
last_update_id = 0

# --- 4. UTILITY FUNCTIONS ---

def get_live_prices(mints):
    """V10.4: Direct Jupiter V2 pricing with timeout protection."""
    try:
        clean_mints = [str(m) for m in mints if m]
        ids = ",".join(clean_mints)
        url = f"https://api.jup.ag/price/v2?ids={ids}"
        res = requests.get(url, timeout=5).json()
        
        prices = {}
        if 'data' in res:
            for mint, data in res['data'].items():
                if data and 'price' in data:
                    prices[mint] = float(data['price'])
        return prices
    except:
        return {}

def get_label(addr):
    addr_str = str(addr)
    label = KNOWN_WALLETS.get(addr_str, f"{addr_str[:4]}...{addr_str[-4:]}")
    is_known = addr_str in KNOWN_WALLETS
    return f"👤 {label}", is_known

def get_token_info(mint):
    mint_str = str(mint)
    if mint_str == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": return "USDC"
    if mint_str == "So11111111111111111111111111111111111111112": return "SOL"
    return f"Token ({mint_str[:4]}...{mint_str[-4:]})"

def identify_dex(tx):
    # Using 'jsonParsed' or 'json' accounts
    account_keys = []
    if hasattr(tx.transaction, 'message') and hasattr(tx.transaction.message, 'account_keys'):
        account_keys = [str(k) for k in tx.transaction.message.account_keys]
    
    for p_id, name in DEX_MAP.items():
        if p_id in account_keys:
            return name
    return "Private/DEX"

def send_alert(chat_id, msg, is_loud=False):
    """Rate-limit friendly alert sender."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": msg, "parse_mode": "HTML", "disable_notification": not is_loud}
    try: 
        res = requests.post(url, json=payload, timeout=8)
        if res.status_code == 429:
            print("⏳ Telegram Rate Limit. Sleeping 5s...", flush=True)
            time.sleep(5)
    except: pass

def send_alert_with_button(chat_id, msg, twitter_link, is_loud=False):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    keyboard = {"inline_keyboard": [[{"text": "🐦 Share on X", "url": twitter_link}]]}
    payload = {
        "chat_id": chat_id, "text": msg, "parse_mode": "HTML", "reply_markup": keyboard, "disable_notification": not is_loud
    }
    try: requests.post(url, json=payload, timeout=8)
    except: pass

# --- 5. THE ALPHA ENGINE ---

def process_whale_move(tx, diff):
    try:
        sig = str(tx.transaction.signatures[0])
        dex_name = identify_dex(tx)
        sender = str(tx.transaction.message.account_keys[0])
        
        # 1. Price Context
        sol_mint = "So11111111111111111111111111111111111111112"
        mints_to_fetch = [sol_mint]
        if hasattr(tx.meta, 'post_token_balances') and tx.meta.post_token_balances:
            for b in tx.meta.post_token_balances:
                mints_to_fetch.append(str(b.mint))
        
        prices = get_live_prices(list(set(mints_to_fetch)))
        sol_price = prices.get(sol_mint, 87.84) 
        usd_val = diff * sol_price

        # 2. Alpha Detected Logic (Only for swaps > 500 SOL)
        if diff >= ALPHA_WATCH_THRESHOLD and hasattr(tx.meta, 'post_token_balances'):
            pre_map = {str(b.mint): (b.ui_token_amount.ui_amount or 0) for b in tx.meta.pre_token_balances} if hasattr(tx.meta, 'pre_token_balances') else {}
            
            for post in tx.meta.post_token_balances:
                mint = str(post.mint)
                if mint == sol_mint: continue 
                
                post_amount = post.ui_token_amount.ui_amount or 0
                pre_amount = pre_map.get(mint, 0)
                received = post_amount - pre_amount
                
                if received > 0.0001: 
                    token_label = get_token_info(mint)
                    token_price = prices.get(mint)
                    
                    db.table("watchlist").upsert({
                        "mint": mint, 
                        "created_at": datetime.datetime.now(timezone.utc).isoformat(),
                        "trigger_vol": diff
                    }).execute()
                    
                    alpha_msg = (f"🏛️ <b>DEX: {dex_name}</b>\n"
                                 f"🌟 <b>ALPHA DETECTED</b>\n\n"
                                 f"Whale sent: <b>{diff:,.1f} SOL</b>\n"
                                 f"Received: <b>{received:,.2f} {token_label}</b>")
                    
                    if token_price:
                        alpha_msg += f"\nValue: <b>${(received * token_price):,.2f}</b>"
                    
                    alpha_msg += f"\n\n🔗 <a href='https://solscan.io/token/{mint}'>View</a>"
                    send_alert(TELEGRAM_CHAT_ID, alpha_msg)
                    return # Exit after one alpha found per tx

        # 3. Standard Alert (If no alpha found, send standard)
        s_label, _ = get_label(sender)
        msg = (f"🔄 <b>WHALE MOVE</b>\n💰 <b>{diff:,.2f} SOL</b> (${usd_val:,.2f})\n\n"
               f"📤 <b>From:</b> {s_label}\n"
               f"🔗 <a href='https://solscan.io/tx/{sig}'>Solscan</a>")
        
        tweet_text = quote(f"🚨 {diff:,.0f} SOL moved! #WhaleMatrix")
        twitter_link = f"https://twitter.com/intent/tweet?text={tweet_text}"
        send_alert_with_button(TELEGRAM_CHAT_ID, msg, twitter_link)

    except Exception as e:
        print(f"❌ Alert Error: {e}", flush=True)

# --- 6. COMMANDS ---
def handle_commands_loop():
    global last_update_id, last_scan_time, blocks_scanned
    print("👂 Command Listener Active", flush=True)
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            params = {"offset": last_update_id + 1, "timeout": 10}
            res = requests.get(url, params=params, timeout=15).json()
            for update in res.get("result", []):
                last_update_id = update["update_id"]
                msg = update.get("message", {})
                if msg.get("text") == "/health" and msg.get("from", {}).get("id") == ADMIN_USER_ID:
                    lag = int(time.time() - last_scan_time)
                    send_alert(ADMIN_USER_ID, f"🛡️ Scanner: Active ({lag}s lag)\n🧱 Blocks: {blocks_scanned}")
        except: time.sleep(5)

# --- 7. MAIN SCANNER ---
def main():
    global last_scan_time, blocks_scanned
    print(f"🚀 WhaleMatrix V10.4 TURBO ONLINE", flush=True)
    
    # 1. Start behind the tip to ensure data is available
    try:
        last_slot = solana_client.get_slot().value - 5 
    except:
        return

    threading.Thread(target=handle_commands_loop, daemon=True).start()

    while True:
        try:
            current_slot = solana_client.get_slot().value
            if current_slot <= last_slot:
                time.sleep(0.5); continue
            
            # Fetch with 'jsonParsed' but wrap in timeout
            try:
                block_res = solana_client.get_block(last_slot + 1, encoding="jsonParsed", max_supported_transaction_version=0)
                block = block_res.value
            except:
                print(f"⏩ Timeout Slot {last_slot + 1}", flush=True)
                last_slot += 1; continue

            if block and block.transactions:
                last_scan_time = time.time()
                blocks_scanned += 1
                for tx in block.transactions:
                    if not tx.meta or tx.meta.err: continue
                    diff = abs(tx.meta.pre_balances[0] - tx.meta.post_balances[0]) / 10**9
                    if diff >= WHALE_THRESHOLD:
                        process_whale_move(tx, diff)
                
                if blocks_scanned % 10 == 0:
                    print(f"🧱 Block {last_slot + 1} Done. (Total: {blocks_scanned})", flush=True)
            
            last_slot += 1
            if blocks_scanned % 50 == 0: gc.collect()

        except Exception as e:
            print(f"🚨 Main Loop Error: {e}", flush=True)
            time.sleep(2)

if __name__ == "__main__":
    main()