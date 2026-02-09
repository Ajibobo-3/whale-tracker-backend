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
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") # Used for GLOBAL Whale alerts

JUPITER_PROGRAM_ID = "JUP6LkbZbjS1jKKccwgwsS1iUCsz3HLbtvNcV6U64V1"
RAYDIUM_PROGRAM_ID = "675k1q2AYp7saS6Y1u4fRPs8yH1uS7S8S7S8S7S8S7S8"

# --- STATE ---
solana_client = Client(ALCHEMY_URL)
db = SyncPostgrestClient(f"{SUPABASE_URL}/rest/v1", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
last_known_price = 108.50 
last_update_id = 0

# --- DATA REGISTRY ---
KNOWN_WALLETS = {
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvu6Gn": "🏢 Binance Hot Wallet",
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM": "🏢 Binance Hot Wallet 2",
    "2QwUbEACJ3ppwfyH19QCSVvNrRzfuK5mNVNDsDMsZKMh": "🏢 Binance Cold Storage",
    "H88yS9KmY89U6pntYkjT9s2S1fDxtw74YAnY8r5x8k": "🏢 Coinbase",
    "AC5RDfQFmDS1deWZos921JfqscXdByf8BKHm5ACWpGsF": "🏢 Bybit Hot Wallet",
    "3QwUbEACJ3ppwfyH19QCSVvNrRzfuK5": "🏢 OKX Wallet",
}

# --- CORE UTILITY FUNCTIONS ---

def send_alert(chat_id, msg, is_loud=False):
    """Sends a message to a specific Chat/User ID."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": msg, "parse_mode": "HTML", "disable_notification": not is_loud}
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
    if addr_str in KNOWN_WALLETS: return KNOWN_WALLETS[addr_str], True
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
            user_id = msg.get("from", {}).get("id")
            text = msg.get("text", "")
            
            if not user_id: continue

            if text.startswith("/watch "):
                mint = text.replace("/watch ", "").strip()
                if len(mint) > 30:
                    db.table("watchlist").upsert({"user_id": user_id, "mint": mint}).execute()
                    send_alert(user_id, f"🎯 <b>Watchlist Updated:</b> Now monitoring {get_token_name(mint)} for you.")
            
            elif text.startswith("/unwatch "):
                mint = text.replace("/unwatch ", "").strip()
                db.table("watchlist").delete().match({"user_id": user_id, "mint": mint}).execute()
                send_alert(user_id, f"❌ Stopped monitoring {mint[:4]}...")

            elif text == "/list":
                res = db.table("watchlist").select("mint").eq("user_id", user_id).execute()
                mints = [item['mint'] for item in res.data]
                msg = "🎯 <b>Your Personal Watchlist:</b>\n" + "\n".join([f"- {get_token_name(m)}" for m in mints]) if mints else "📝 Your list is empty."
                send_alert(user_id, msg)
            
            elif text == "/help":
                send_alert(user_id, "🛠️ <b>Personal Intelligence v7.0</b>\n- /watch [mint]\n- /unwatch [mint]\n- /list\n\n<i>Note: Whale alerts are still global.</i>")
    except: pass

# --- MAIN LOOP ---

def main():
    print("🚀 V7.0 MULTI-USER ENGINE ONLINE", flush=True)
    last_slot = solana_client.get_slot().value - 1

    while True:
        handle_commands()
        
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
                sig = str(tx.transaction.signatures[0])
                sender = str(tx.transaction.message.account_keys[0])

                # --- SCAN FOR INDIVIDUAL WATCHLISTS ---
                if tx.meta.post_token_balances:
                    for b in tx.meta.post_token_balances:
                        if b.mint not in ["So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"]:
                            mint = b.mint
                            # Find all users watching THIS mint
                            res = db.table("watchlist").select("user_id").eq("mint", mint).execute()
                            watchers = [item['user_id'] for item in res.data]
                            
                            if watchers:
                                msg = (f"🎯 <b>WATCHLIST ALERT: {get_token_name(mint)}</b>\n"
                                       f"━━━━━━━━━━━━━━\n"
                                       f"💰 <b>Value:</b> {diff:,.2f} SOL (<b>${usd_val:,.2f}</b>)\n"
                                       f"🔗 <a href='https://solscan.io/tx/{sig}'>View Tx</a>")
                                for uid in watchers:
                                    send_alert(uid, msg, is_loud=True)
                                break # Found the mint, move to next transaction

                # --- SCAN FOR GLOBAL WHALES (>= 1000 SOL) ---
                if diff >= WHALE_THRESHOLD:
                    receiver = str(tx.transaction.message.account_keys[1]) if len(tx.transaction.message.account_keys) > 1 else "Unknown"
                    s_label, s_is_known = get_label(sender)
                    r_label, r_is_known = get_label(receiver)
                    icon = "📥" if r_is_known else ("📤" if s_is_known else "🕵️")
                    title = "EXCHANGE INFLOW" if r_is_known else ("EXCHANGE OUTFLOW" if s_is_known else "PRIVATE TRANSFER")

                    msg = (f"{icon} <b>{title}</b>\n"
                           f"━━━━━━━━━━━━━━\n"
                           f"💰 <b>{diff:,.0f} SOL</b> (<b>${usd_val:,.2f}</b>)\n"
                           f"📤 <b>From:</b> {s_label}\n"
                           f"📥 <b>To:</b> {r_label}\n"
                           f"━━━━━━━━━━━━━━\n"
                           f"🔗 <a href='https://solscan.io/tx/{sig}'>Solscan</a> | "
                           f"<a href='https://app.bubblemaps.io/sol/address/{sender}'>Maps</a>")
                    send_alert(TELEGRAM_CHAT_ID, msg, is_loud=(diff >= LOUD_THRESHOLD))

            last_slot = slot
        except: time.sleep(1)

if __name__ == "__main__":
    main()