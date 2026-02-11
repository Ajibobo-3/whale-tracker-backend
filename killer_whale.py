import time, requests, os, threading, datetime, gc
from datetime import timezone
from urllib.parse import quote
from solana.rpc.api import Client
from postgrest import SyncPostgrestClient
from dotenv import load_dotenv

# Railway specific: Ensuring logs are flushed immediately
load_dotenv()

# --- 1. GLOBAL SETTINGS ---
WHALE_THRESHOLD = 1000  
LOUD_THRESHOLD = 2500
ALPHA_WATCH_THRESHOLD = 500 

# RPC Endpoints
ALCHEMY_URL = os.environ.get("ALCHEMY_URL")
# Forcing a high-performance public fallback
FALLBACK_RPC_URL = os.environ.get("FALLBACK_RPC_URL") or "https://api.mainnet-beta.solana.com"

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") 
ADMIN_USER_ID = 7302870957 

# --- 2. MAPPINGS & DATA (KEEP AS IS) ---
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
    "JUP6LkbZbjS1jKKccS4n14C9G98zK": "Jupiter Aggregator",
    "5tz9u7YmG6ncSp1ZAnv4v34Lp2eS": "Coinbase Custody",
    "3uGoRvd6M7SpSpYXAnv4v34Lp2eS": "Kraken Exchange"
}

# --- 3. STATE INITIALIZATION ---
primary_client = Client(ALCHEMY_URL, timeout=30, commitment="confirmed")
fallback_client = Client(FALLBACK_RPC_URL, timeout=30, commitment="confirmed")
db = SyncPostgrestClient(f"{SUPABASE_URL}/rest/v1", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})

last_scan_time = time.time()
blocks_scanned = 0
last_update_id = 0

# --- 4. UTILITY FUNCTIONS (KEEP AS IS) ---
def get_live_prices(mints):
    try:
        clean_mints = [str(m) for m in mints if m]
        ids = ",".join(clean_mints)
        url = f"https://api.jup.ag/price/v2?ids={ids}"
        res = requests.get(url, timeout=5).json()
        return {m: float(d['price']) for m, d in res.get('data', {}).items() if d and 'price' in d}
    except: return {}

def get_label(addr):
    addr_str = str(addr)
    if addr_str in KNOWN_WALLETS:
        return f"🏢 <b>{KNOWN_WALLETS[addr_str]}</b>"
    return f"Unknown Wallet (<code>{addr_str[:4]}...{addr_str[-4:]}</code>)"

def get_token_info(mint):
    mint_str = str(mint)
    if mint_str == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": return "USDC"
    if mint_str == "So11111111111111111111111111111111111111112": return "SOL"
    return f"Token (<code>{mint_str[:4]}...{mint_str[-4:]}</code>)"

def identify_dex(tx):
    account_keys = [str(k) for k in tx.transaction.message.account_keys]
    for p_id, name in DEX_MAP.items():
        if p_id in account_keys: return name
    return "Private/DEX"

# --- 5. THE ALPHA ENGINE ---
def process_whale_move(tx, diff):
    try:
        sig = str(tx.transaction.signatures[0])
        sender = str(tx.transaction.message.account_keys[0])
        receiver = str(tx.transaction.message.account_keys[1]) if len(tx.transaction.message.account_keys) > 1 else "Unknown"
        dex_name = identify_dex(tx)
        
        sol_mint = "So11111111111111111111111111111111111111112"
        prices = get_live_prices([sol_mint])
        sol_price = prices.get(sol_mint, 95.0)
        usd_val = diff * sol_price

        alpha_text = ""
        if diff >= ALPHA_WATCH_THRESHOLD and hasattr(tx.meta, 'post_token_balances'):
            pre_map = {str(b.mint): (b.ui_token_amount.ui_amount or 0) for b in tx.meta.pre_token_balances} if hasattr(tx.meta, 'pre_token_balances') else {}
            for post in tx.meta.post_token_balances:
                mint = str(post.mint)
                if mint == sol_mint: continue 
                received = (post.ui_token_amount.ui_amount or 0) - pre_map.get(mint, 0)
                
                if received > 0.0001:
                    db.table("watchlist").upsert({"mint": mint, "created_at": datetime.datetime.now(timezone.utc).isoformat(), "trigger_vol": diff}).execute()
                    token_label = get_token_info(mint)
                    alpha_text = f"\n🌟 <b>ALPHA: Bought {received:,.1f} {token_label} on {dex_name}</b>"
                    break

        s_label, r_label = get_label(sender), get_label(receiver)
        msg = (
            f"🕵️‍♂️ <b>SOMETHING IS COOKING…</b>{alpha_text}\n\n"
            f"💰 <b>{diff:,.0f} $SOL (~${usd_val:,.0f})</b>\n\n"
            f"📤 <b>From:</b> {s_label}\n"
            f"📥 <b>To:</b> {r_label}\n\n"
            f"🔗 <a href='https://solscan.io/tx/{sig}'>Solscan</a> | "
            f"<a href='https://birdeye.so/token/{sender}?chain=solana'>Birdeye</a> | "
            f"<a href='https://arkhamintelligence.com/explorer/address/{sender}'>Arkham</a> | "
            f"<a href='https://bubblemaps.io/solana/token/{sender}'>BubbleMaps</a>"
        )
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": False}, timeout=8)
    except Exception as e:
        print(f"❌ Alert Error: {e}", flush=True)

# --- 6. COMMANDS ---
def handle_commands_loop():
    global last_update_id, last_scan_time, blocks_scanned
    print("👂 Command Listener Active", flush=True)
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            res = requests.get(url, params={"offset": last_update_id+1, "timeout": 10}, timeout=15).json()
            for update in res.get("result", []):
                last_update_id = update["update_id"]
                m = update.get("message", {})
                if m.get("text") == "/health" and m.get("from", {}).get("id") == ADMIN_USER_ID:
                    lag = int(time.time() - last_scan_time)
                    status = "Railway V11.9.8 (Triple-Fetch)"
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                                  json={"chat_id": ADMIN_USER_ID, "text": f"🛡️ WhaleMatrix: {status}\n🧱 Blocks: {blocks_scanned}\n⏳ Lag: {lag}s"})
        except: time.sleep(5)

# --- 7. MAIN ENGINE (STABILIZED TRIPLE-FETCH) ---
def main():
    global last_scan_time, blocks_scanned
    print("🚀 WhaleMatrix V11.9.8 TRIPLE-FETCH ONLINE", flush=True)
    
    try:
        current_tip = primary_client.get_slot().value
        # Start exactly at Tip-30 for maximum indexing stability
        last_slot = current_tip - 30 
        last_scan_time = time.time()
        print(f"🔗 Syncing from: {last_slot}", flush=True)
    except Exception as e:
        print(f"🚨 Connection Failed: {e}")
        return

    threading.Thread(target=handle_commands_loop, daemon=True).start()

    while True:
        try:
            if blocks_scanned > 0 and blocks_scanned % 15 == 0: gc.collect()
            
            try:
                current_tip = primary_client.get_slot().value
            except:
                current_tip = fallback_client.get_slot().value

            # Anti-Warp Cushion
            if (current_tip - last_slot) > 100: 
                print(f"⚠️ Heavy Lag detected ({current_tip - last_slot}). Warping to Tip-30...", flush=True)
                last_slot = current_tip - 31
                continue

            # Buffer Check
            if current_tip <= (last_slot + 25):
                time.sleep(1); continue 
            
            target_slot = last_slot + 1
            block = None

            # --- TRIPLE-FETCH LOGIC ---
            # Attempt 1: Chainstack
            try:
                res = primary_client.get_block(target_slot, encoding="jsonParsed", max_supported_transaction_version=0, rewards=False)
                block = res.value
            except: pass

            # Attempt 2: Public Fallback (Only if Chainstack failed)
            if not block:
                try:
                    res = fallback_client.get_block(target_slot, encoding="jsonParsed", max_supported_transaction_version=0, rewards=False)
                    block = res.value
                    if block: print(f"✅ Fallback Saved Slot {target_slot}", flush=True)
                except: pass

            if block and block.transactions:
                last_scan_time = time.time() 
                blocks_scanned += 1
                for tx in block.transactions:
                    if not tx.meta or tx.meta.err: continue
                    diff = abs(tx.meta.pre_balances[0] - tx.meta.post_balances[0]) / 10**9
                    if diff >= WHALE_THRESHOLD:
                        process_whale_move(tx, diff)
                
                print(f"🧱 Block {target_slot} Scanned. Total: {blocks_scanned} | Lag: {int(time.time()-last_scan_time)}s", flush=True)
                last_slot += 1 
            else:
                print(f"⏩ Slot {target_slot} confirmed empty. Moving on...", flush=True)
                last_slot += 1
            
        except Exception as e:
            print(f"🚨 Engine Error: {e}", flush=True)
            time.sleep(1)

if __name__ == "__main__":
    main()