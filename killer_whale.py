import time, requests, os, threading, datetime, gc
from datetime import timezone
from urllib.parse import quote
from solana.rpc.api import Client
from postgrest import SyncPostgrestClient
from dotenv import load_dotenv

load_dotenv()

# --- 1. SETTINGS ---
WHALE_THRESHOLD = 1000  
LOUD_THRESHOLD = 2500
ALPHA_WATCH_THRESHOLD = 500 
ALCHEMY_URL = os.getenv("ALCHEMY_URL")
FALLBACK_RPC_URL = os.getenv("FALLBACK_RPC_URL") 
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") 
ADMIN_USER_ID = 7302870957 

# --- 2. STATE ---
# 'processed' for tip (fastest), 'confirmed' for block (stable)
primary_client = Client(ALCHEMY_URL, timeout=12)
fallback_client = Client(FALLBACK_RPC_URL, timeout=12) if FALLBACK_RPC_URL else None
db = SyncPostgrestClient(f"{SUPABASE_URL}/rest/v1", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})

last_scan_time = time.time()
blocks_scanned = 0
last_update_id = 0

# --- 4. UTILITIES ---
def get_live_prices(mints):
    try:
        ids = ",".join([str(m) for m in mints if m])
        res = requests.get(f"https://api.jup.ag/price/v2?ids={ids}", timeout=5).json()
        return {m: float(d['price']) for m, d in res.get('data', {}).items() if d and 'price' in d}
    except: return {}

def get_label(addr):
    addr_str = str(addr)
    return f"Unknown Wallet (<code>{addr_str[:4]}...{addr_str[-4:]}</code>)"

def get_token_info(mint):
    m = str(mint)
    if m == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": return "USDC"
    if m == "So11111111111111111111111111111111111111112": return "SOL"
    return f"Token (<code>{m[:4]}...{m[-4:]}</code>)"

# --- 5. THE ENGINE ---
def process_whale_move(tx, diff):
    try:
        sig = str(tx.transaction.signatures[0])
        sender = str(tx.transaction.message.account_keys[0])
        receiver = str(tx.transaction.message.account_keys[1]) if len(tx.transaction.message.account_keys) > 1 else "Unknown"
        sol_mint = "So11111111111111111111111111111111111111112"
        prices = get_live_prices([sol_mint])
        sol_price = prices.get(sol_mint, 90.0)
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
                    alpha_text = f"\n🌟 <b>ALPHA: Bought {received:,.1f} {get_token_info(mint)}</b>"
                    break

        msg = (
            f"🕵️‍♂️ <b>SOMETHING IS COOKING…</b>{alpha_text}\n\n"
            f"💰 <b>{diff:,.0f} $SOL (~${usd_val:,.0f})</b>\n\n"
            f"📤 <b>From:</b> {get_label(sender)}\n"
            f"📥 <b>To:</b> {get_label(receiver)}\n\n"
            f"🔗 <a href='https://solscan.io/tx/{sig}'>Solscan</a> | "
            f"<a href='https://birdeye.so/token/{sender}?chain=solana'>Birdeye</a> | "
            f"<a href='https://arkhamintelligence.com/explorer/address/{sender}'>Arkham</a> | "
            f"<a href='https://bubblemaps.io/solana/token/{sender}'>BubbleMaps</a>"
        )
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": False}, timeout=8)
    except Exception as e: print(f"❌ Alert Error: {e}", flush=True)

# --- 6. COMMANDS ---
def handle_commands_loop():
    global last_update_id, last_scan_time, blocks_scanned
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            res = requests.get(url, params={"offset": last_update_id+1, "timeout": 10}, timeout=15).json()
            for update in res.get("result", []):
                last_update_id = update["update_id"]
                m = update.get("message", {})
                if m.get("text") == "/health" and m.get("from", {}).get("id") == ADMIN_USER_ID:
                    lag = int(time.time() - last_scan_time)
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                                  json={"chat_id": ADMIN_USER_ID, "text": f"🛡️ WhaleMatrix: Overdrive Active\n🧱 Blocks: {blocks_scanned}\n⏳ Lag: {lag}s"})
        except: time.sleep(5)

# --- 7. MAIN ENGINE (OVERDRIVE) ---
def main():
    global last_scan_time, blocks_scanned
    print("🚀 WhaleMatrix V11.2 OVERDRIVE ONLINE", flush=True)
    try: 
        last_slot = primary_client.get_slot(commitment="confirmed").value - 1
    except: return
    threading.Thread(target=handle_commands_loop, daemon=True).start()

    while True:
        try:
            if blocks_scanned % 10 == 0: gc.collect()
            
            # Tip check using fastest commitment
            current_tip = primary_client.get_slot(commitment="processed").value
            
            # OVERDRIVE JUMP: If lag > 15 slots, JUMP immediately
            if (current_tip - last_slot) > 15:
                print(f"⚠️ Overdrive Jump: Lag was {current_tip - last_slot}. Warping to tip.", flush=True)
                last_slot = current_tip - 1
            
            if current_tip <= last_slot:
                time.sleep(0.3); continue
            
            target_slot = last_slot + 1
            block = None
            
            # Dual-Engine Fetch
            try:
                block_res = primary_client.get_block(target_slot, encoding="jsonParsed", max_supported_transaction_version=0, rewards=False)
                block = block_res.value
            except Exception:
                if fallback_client:
                    try:
                        block_res = fallback_client.get_block(target_slot, encoding="jsonParsed", max_supported_transaction_version=0, rewards=False)
                        block = block_res.value
                    except: pass
            
            if block and block.transactions:
                last_scan_time = time.time()
                blocks_scanned += 1
                for tx in block.transactions:
                    if not tx.meta or tx.meta.err: continue
                    diff = abs(tx.meta.pre_balances[0] - tx.meta.post_balances[0]) / 10**9
                    if diff >= WHALE_THRESHOLD: process_whale_move(tx, diff)
                    del tx
                if blocks_scanned % 5 == 0: print(f"🧱 Block {target_slot} OK. Total: {blocks_scanned}", flush=True)
            
            # Force increment so we never freeze
            last_slot += 1
        except Exception as e:
            print(f"🚨 Engine Error: {e}", flush=True)
            time.sleep(1)

if __name__ == "__main__": main()