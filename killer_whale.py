import time, requests, os, threading, datetime
from datetime import timezone
from urllib.parse import quote
from solana.rpc.api import Client
from postgrest import SyncPostgrestClient
from dotenv import load_dotenv

load_dotenv()

# --- 1. GLOBAL SETTINGS ---
WHALE_THRESHOLD = 1000  
LOUD_THRESHOLD = 2500  # <--- FIXED: RESTORED FOR ALERTS
ALPHA_WATCH_THRESHOLD = 500 
ALCHEMY_URL = os.getenv("ALCHEMY_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") 
ADMIN_USER_ID = 7302870957 

# --- 2. DEX & WALLET MAPPING ---
DEX_MAP = {
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter V6",
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
    try:
        ids = ",".join(mints)
        url = f"https://api.jup.ag/price/v3?ids={ids}"
        res = requests.get(url, timeout=5).json()
        return {mint: float(data['usdPrice']) for mint, data in res['data'].items() if data}
    except: return {}

def get_label(addr):
    """FIXED: Restored for V9.6.1"""
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
        "chat_id": chat_id, "text": msg, "parse_mode": "HTML", "reply_markup": keyboard, "disable_notification": not is_loud
    }
    try: requests.post(url, json=payload, timeout=8)
    except: pass

# --- 5. THE ALPHA ENGINE ---

def process_whale_move(tx, diff):
    try:
        sig = str(tx.transaction.signatures[0])
        dex_name = identify_dex(tx)
        
        mints_to_fetch = ["So11111111111111111111111111111111111111112"]
        if hasattr(tx.meta, 'post_token_balances'):
            for b in tx.meta.post_token_balances:
                mints_to_fetch.append(str(b.mint))
        
        prices = get_live_prices(list(set(mints_to_fetch)))
        sol_price = prices.get("So11111111111111111111111111111111111111112", 110.00)
        usd_val = diff * sol_price

        # 1. Alpha Watchlist Logic
        if diff >= ALPHA_WATCH_THRESHOLD and hasattr(tx.meta, 'post_token_balances'):
            for balance in tx.meta.post_token_balances:
                mint = str(balance.mint)
                if mint != "So11111111111111111111111111111111111111112":
                    token_amount = balance.ui_token_amount.ui_amount or 0
                    token_label = get_token_info(mint)
                    token_usd_price = prices.get(mint)
                    
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
                    
                    alpha_msg += f"\n🔗 <a href='https://solscan.io/token/{mint}'>Token View</a>"
                    send_alert(TELEGRAM_CHAT_ID, alpha_msg)
                    break 

        # 2. FIXED: get_label and LOUD_THRESHOLD restored
        sender = str(tx.transaction.message.account_keys[0])
        receiver = str(tx.transaction.message.account_keys[1]) if len(tx.transaction.message.account_keys) > 1 else "Unknown"
        s_label, s_known = get_label(sender)
        r_label, r_known = get_label(receiver)
        
        icon = "📤" if s_known and not r_known else "📥" if not s_known and r_known else "🔄"
        signal = "🚀 BULLISH OUTFLOW" if icon == "📤" else "🚨 BEARISH INFLOW" if icon == "📥" else "🕵️ NEUTRAL MOVE"

        msg = (f"{icon} <b>{signal}</b>\n💰 <b>{diff:,.0f} SOL</b> (${usd_val:,.2f})\n\n"
               f"📤 <b>From:</b> {s_label}\n📥 <b>To:</b> {r_label}\n\n"
               f"🔗 <a href='https://solscan.io/tx/{sig}'>Solscan</a>")
        
        twitter_link = f"https://twitter.com/intent/tweet?text={quote(f'🚨 WHALE ALERT: {diff:,.0f} SOL (${usd_val:,.2f}) moved! #Solana')}"
        send_alert_with_button(TELEGRAM_CHAT_ID, msg, twitter_link, is_loud=(diff >= LOUD_THRESHOLD))

    except Exception as e:
        print(f"❌ Error in process_whale_move: {e}", flush=True)

# ... (main and handle_commands_loop remains same as V9.6)