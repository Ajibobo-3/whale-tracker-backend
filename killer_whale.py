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

# --- 2. MAPPINGS & DATA ---
DEX_MAP = {
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter V6",
    "JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB": "Jupiter V4",
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "Raydium V4",
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK": "Raydium CLMM",
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc": "Orca Whirlpool",
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": "Pump.fun",
    "Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EQVn5UaB": "Meteora Pools",
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo": "Meteora DLMM"
}

KNOWN_WALLETS = {
    "H88yS9KmYvM9B6NSpYXzAn8f2g5tY0eD": "Binance Hot Wallet",
    "9WzDXwBsQXds2Wz9C66C3uEt1XUvXn2J": "Binance Cold Storage",
    "JUP6LkbZbjS1jKKccS4n14C9G98zK": "Jupiter Aggregator"
}

# --- 3. STATE INITIALIZATION ---
solana_client = Client(ALCHEMY_URL)
db = SyncPostgrestClient(f"{SUPABASE_URL}/rest/v1", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})

last_scan_time = time.time()
blocks_scanned = 0
last_update_id = 0

# --- 4. UTILITY FUNCTIONS ---

def get_live_prices(mints):
    """Fetches batch pricing from Jupiter API V3."""
    try:
        ids = ",".join(mints)
        url = f"https://api.jup.ag/price/v3?ids={ids}"
        res = requests.get(url, timeout=5).json()
        return {mint: float(data['usdPrice']) for mint, data in res['data'].items() if data}
    except Exception as e:
        print(f"⚠️ Pricing Error: {e}")
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
    """Parses program IDs to identify the swap platform."""
    account_keys = [str(k) for k in tx.transaction.message.account_keys]
    for p_id, name in DEX_MAP.items():
        if p_id in account_keys:
            return name
    return "Private/DEX"

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

# --- 5. THE ALPHA ENGINE ---

def process_whale_move(tx, diff):
    try:
        sig = str(tx.transaction.signatures[0])
        dex_name = identify_dex(tx)
        
        # 1. Price Context
        mints_to_fetch = ["So11111111111111111111111111111111111111112"]
        if hasattr(tx.meta, 'post_token_balances'):
            for b in tx.meta.post_token_balances:
                mints_to_fetch.append(str(b.mint))
        
        prices = get_live_prices(list(set(mints_to_fetch)))
        sol_price = prices.get("So11111111111111111111111111111111111111112", 110.00)
        usd_val = diff * sol_price

        # 2. Alpha Detected Logic
        if diff >= ALPHA_WATCH_THRESHOLD and hasattr(tx.meta, 'post_token_balances'):
            for balance in tx.meta.post_token_balances:
                mint = str(balance.mint)
                if mint != "So11111111111111111111111111111111111111112":
                    token_amount = balance.ui_token_amount.ui_amount or 0
                    token_label = get_token_info(mint)
                    token_usd_price = prices.get(mint)
                    
                    # Store in Supabase
                    db.table("watchlist").upsert({
                        "mint": mint, 
                        "created_at": datetime.datetime.now(timezone.utc).isoformat(),
                        "trigger_vol": diff
                    }).execute()
                    
                    alpha_msg = (f"🏛️ <b>DEX: {dex_name}</b>\n"
                                 f"🌟 <b>ALPHA DETECTED</b>\n"
                                 f"Whale swapped <b>{diff:,.1f} SOL</b> (${usd_val:,.2f})\n"
                                 f"Received: <b>{token_amount:,.2f} {token_label}</b>")
                    
                    if token_usd_price:
                        alpha_msg += f"\nValue: <b>${(token_amount * token_usd_price):,.2f}</b>"
                    
                    alpha_msg += f"\n\n🔗 <a href='https://solscan.io/token/{mint}'>Token View</a>"
                    send_alert(TELEGRAM_CHAT_ID, alpha_msg)
                    break 

        # 3. Standard Whale Alert
        sender = str(tx.transaction.message.account_keys[0])
        receiver = str(tx.transaction.message.account_keys[1]) if len(tx.transaction.message.account_keys) > 1 else "Unknown"
        s_label, s_known = get_label(sender)
        r_label, r_known = get_label(receiver)
        
        icon = "📤" if s_known and not r_known else "📥" if not s_known and r_known else "🔄"
        signal = "🚀 BULLISH OUTFLOW" if icon == "📤" else "🚨 BEARISH INFLOW" if icon == "📥" else "🕵️ NEUTRAL MOVE"

        msg = (f"{icon} <b>{signal}</b>\n💰 <b>{diff:,.0f} SOL</b> (${usd_val:,.2f})\n\n"
               f"📤 <b>From:</b> {s_label}\n📥 <b>To:</b> {r_label}\n\n"
               f"🔗 <a href='https://solscan.io/tx/{sig}'>Solscan</a> | "
               f"<a href='https://bubblemaps.io/solana/token/{sender}'>BubbleMaps</a>")
        
        tweet_text = quote(f"🚨 WHALE ALERT: {diff:,.0f} SOL (${usd_val:,.2f}) moved! #Solana")
        twitter_link = f"https://twitter.com/intent/tweet?text={tweet_text}"
        send_alert_with_button(TELEGRAM_CHAT_ID, msg, twitter_link, is_loud=(diff >= LOUD_THRESHOLD))

    except Exception as e:
        print(f"❌ Error in process_whale_move: {e}", flush=True)

# --- 6. THE COMMAND LISTENER THREAD ---

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
                
                if text == "/health" and user_id == ADMIN_USER_ID:
                    lag = int(time.time() - last_scan_time)
                    send_alert(ADMIN_USER_ID, f"🛡️ Scanner: Active ({lag}s lag)\n🧱 Blocks: {blocks_scanned}")

                elif text == "/topbuy":
                    time_threshold = (datetime.datetime.now(timezone.utc) - datetime.timedelta(hours=24)).isoformat()
                    response = db.table("watchlist").select("mint, trigger_vol").gt("created_at", time_threshold).execute()
                    
                    if not response.data:
                        send_alert(TELEGRAM_CHAT_ID, "📉 No whale entries in 24H.")
                        continue

                    rankings = {}
                    for entry in response.data:
                        m, v = entry['mint'], entry['trigger_vol']
                        rankings[m] = rankings.get(m, 0) + v
                    
                    sorted_list = sorted(rankings.items(), key=lambda x: x[1], reverse=True)[:5]
                    summary = "🏛️ <b>TOP WHALE ENTRIES (24H)</b>\n\n"
                    for i, (mint, total_vol) in enumerate(sorted_list, 1):
                        summary += f"{i}. <code>{mint[:4]}...</code>\n💰 Total Vol: <b>{total_vol:,.0f} SOL</b>\n\n"
                    
                    send_alert(TELEGRAM_CHAT_ID, summary)
        except: time.sleep(2)

# --- 7. THE MAIN SCANNER LOOP ---

def main():
    global last_scan_time, blocks_scanned
    print(f"🚀 V9.7 FULL KRAKEN PRODUCTION ONLINE", flush=True)
    threading.Thread(target=handle_commands_loop, daemon=True).start()
    
    last_slot = solana_client.get_slot().value 

    while True:
        try:
            current_slot = solana_client.get_slot().value
            if current_slot <= last_slot:
                time.sleep(0.2); continue
            
            # Use jsonParsed for detailed token balance extraction
            block_data = solana_client.get_block(current_slot, encoding="jsonParsed", max_supported_transaction_version=0)
            block = block_data.value
            if not block or not block.transactions:
                last_slot = current_slot; continue
            
            last_scan_time = time.time()
            blocks_scanned += 1

            for tx in block.transactions:
                try:
                    if not tx.meta or tx.meta.err: continue
                    # Absolute SOL difference
                    diff = abs(tx.meta.pre_balances[0] - tx.meta.post_balances[0]) / 10**9
                    if diff >= WHALE_THRESHOLD:
                        process_whale_move(tx, diff)
                except: continue 

            last_slot = current_slot
        except Exception as e:
            print(f"⚠️ Scanner Restart: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()