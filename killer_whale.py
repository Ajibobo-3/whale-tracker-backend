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

JUPITER_PROGRAM_ID = "JUP6LkbZbjS1jKKccwgwsS1iUCsz3HLbtvNcV6U64V1"
RAYDIUM_PROGRAM_ID = "675k1q2AYp7saS6Y1u4fRPs8yH1uS7S8S7S8S7S8S7S8"

# --- STATE ---
solana_client = Client(ALCHEMY_URL)
db = SyncPostgrestClient(f"{SUPABASE_URL}/rest/v1", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
last_known_price = 108.50 
start_time = time.time()
last_update_id = 0

# --- DATA REGISTRY ---
KNOWN_WALLETS = {
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvu6Gn": "🏢 Binance Hot Wallet",
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM": "🏢 Binance Hot Wallet 2",
    "2QwUbEACJ3ppwfyH19QCSVvNrRzfuK5mNVNDsDMsZKMh": "🏢 Binance Cold Storage",
    "H88yS9KmY89U6pntYkjT9s2S1fDxtw74YAnY8r5x8k": "🏢 Coinbase",
    "AC5RDfQFmDS1deWZos921JfqscXdByf8BKHm5ACWpGsF": "🏢 Bybit Hot Wallet",
    "3QwUbEACJ3ppwfyH19QCSVvNrRzfuK5": "🏢 OKX Wallet",
    "FWznbcNXWQuHTawe9RxvQ2LdCENqHS1Xf9C1d1hSSZKD": "🏢 Kraken Hot Wallet",
}

# --- CORE UTILITY FUNCTIONS ---

def send_alert(msg, is_loud=False):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_notification": not is_loud}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"❌ Telegram Error: {e}")

def get_token_name(mint):
    try:
        res = requests.get(f"https://token.jup.ag/all", timeout=5).json()
        for t in res:
            if t['address'] == mint: return f"${t['symbol']}"
        return f"Token ({mint[:4]})"
    except: return "Meme Coin"

def sync_watchlist():
    try:
        res = db.table("watchlist").select("mint").execute()
        return [item['mint'] for item in res.data]
    except: return []

def get_live_sol_price():
    global last_known_price
    try:
        res = requests.get("https://price.jup.ag/v4/price?ids=SOL", timeout=2).json()
        last_known_price = float(res['data']['SOL']['price'])
        return last_known_price
    except:
        try:
            res = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT", timeout=2).json()
            last_known_price = float(res['price'])
            return last_known_price
        except: return last_known_price

def get_label(addr):
    addr_str = str(addr)
    if addr_str in KNOWN_WALLETS: return KNOWN_WALLETS[addr_str], True
    return f"👤 {addr_str[:4]}...{addr_str[-4:]}", False

# --- COMMANDS ---

def handle_commands():
    global last_update_id
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {"offset": last_update_id + 1, "timeout": 1}
        res = requests.get(url, params=params, timeout=5).json()
        
        for update in res.get("result", []):
            last_update_id = update["update_id"]
            msg = update.get("message", {})
            text = msg.get("text", "")
            
            if text.startswith("/watch "):
                mint = text.replace("/watch ", "").strip()
                if len(mint) > 30:
                    db.table("watchlist").upsert({"mint": mint}).execute()
                    name = get_token_name(mint)
                    send_alert(f"🎯 <b>Watchlist Updated:</b> Monitoring {name}")
            
            elif text.startswith("/unwatch "):
                mint = text.replace("/unwatch ", "").strip()
                db.table("watchlist").delete().eq("mint", mint).execute()
                send_alert(f"❌ <b>Removed:</b> Stopped monitoring {mint[:4]}...")

            elif text == "/list":
                mints = sync_watchlist()
                if not mints:
                    send_alert("📝 <b>Watchlist is empty.</b>")
                else:
                    msg = "🎯 <b>Current Watchlist:</b>\n━━━━━━━━━━━━━━\n"
                    for i, m in enumerate(mints, 1):
                        msg += f"{i}. {get_token_name(m)} (<code>{m[:6]}...</code>)\n"
                    send_alert(msg)

            elif text == "/clear":
                db.table("watchlist").delete().neq("mint", "0").execute()
                send_alert("🧹 <b>Watchlist Cleared:</b> All monitored coins removed.")

            elif text == "/help":
                help_text = (
                    "🛠️ <b>Omni-Tracker Intelligence v6.8</b>\n"
                    "━━━━━━━━━━━━━━\n"
                    "🎯 <code>/watch [mint]</code> - Add coin\n"
                    "❌ <code>/unwatch [mint]</code> - Remove coin\n"
                    "📝 <code>/list</code> - Show active list\n"
                    "🧹 <code>/clear</code> - Wipe all coins\n"
                    "💡 <i>Whale alerts (1k+ SOL) are automatic.</i>"
                )
                send_alert(help_text)
    except: pass

# --- MAIN LOOP ---

def main():
    print("🚀 V6.8 OMNI-TRACKER: FULL INTEL ACTIVE", flush=True)
    last_slot = solana_client.get_slot().value - 1

    while True:
        handle_commands()
        watched_memes = sync_watchlist()
        
        try:
            slot = solana_client.get_slot().value
            if slot <= last_slot:
                time.sleep(1)
                continue
            
            block = solana_client.get_block(slot, encoding="jsonParsed", max_supported_transaction_version=0).value
            if not block or not block.transactions:
                last_slot = slot
                continue

            current_price = get_live_sol_price()

            for tx in block.transactions:
                if not tx.meta or tx.meta.err: continue
                
                diff = abs(tx.meta.pre_balances[0] - tx.meta.post_balances[0]) / 10**9
                usd_val = diff * current_price

                # Scan for Watchlist
                mint = None
                is_watched = False
                if tx.meta.post_token_balances:
                    for b in tx.meta.post_token_balances:
                        if b.mint not in ["So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"]:
                            mint = b.mint
                            if mint in watched_memes: is_watched = True
                            break

                if is_watched:
                    name = get_token_name(mint)
                    msg = (f"🎯 <b>WATCHLIST ALERT: {name}</b>\n"
                           f"━━━━━━━━━━━━━━\n"
                           f"💰 <b>Value:</b> {diff:,.2f} SOL (<b>${usd_val:,.2f}</b>)\n"
                           f"🔗 <a href='https://solscan.io/tx/{tx.transaction.signatures[0]}'>View Tx</a>")
                    send_alert(msg, is_loud=True)
                    continue

                if diff >= WHALE_THRESHOLD:
                    sender = str(tx.transaction.message.account_keys[0])
                    receiver = str(tx.transaction.message.account_keys[1]) if len(tx.transaction.message.account_keys) > 1 else "Unknown"
                    s_label, s_is_known = get_label(sender)
                    r_label, r_is_known = get_label(receiver)

                    if r_is_known and not s_is_known:
                        icon, title = "📥", "EXCHANGE INFLOW"
                    elif s_is_known and not r_is_known:
                        icon, title = "📤", "EXCHANGE OUTFLOW"
                    else:
                        icon, title = "🕵️", "PRIVATE TRANSFER"

                    msg = (f"{icon} <b>{title}</b>\n━━━━━━━━━━━━━━\n"
                           f"💰 <b>{diff:,.0f} SOL</b> (<b>${usd_val:,.2f}</b>)\n"
                           f"📤 <b>From:</b> {s_label}\n"
                           f"📥 <b>To:</b> {r_label}")
                    send_alert(msg, is_loud=(diff >= LOUD_THRESHOLD))

            last_slot = slot
        except Exception as e:
            time.sleep(1)

if __name__ == "__main__":
    main()