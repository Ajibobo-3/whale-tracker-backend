import time, requests, os, datetime
from solana.rpc.api import Client
from dotenv import load_dotenv

load_dotenv()

# --- SETUP ---
WHALE_THRESHOLD = 1000
LOUD_THRESHOLD = 2500
PINNED_MESSAGE_ID = None 
ALCHEMY_URL = os.getenv("ALCHEMY_URL")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

JUPITER_PROGRAM_ID = "JUP6LkbZbjS1jKKccwgwsS1iUCsz3HLbtvNcV6U64V1"
RAYDIUM_PROGRAM_ID = "675k1q2AYp7saS6Y1u4fRPs8yH1uS7S8S7S8S7S8S7S8"

# --- WATCHLIST ---
# Add mint addresses here to monitor EVERY transaction for specific coins
WATCHED_MEMES = [
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", # Example: USDC
    # Paste your meme mints here
]

# --- STATE ---
solana_client = Client(ALCHEMY_URL)
last_known_price = 87.30 # Current market fallback for Feb 9, 2026
start_time = time.time()
pulse_data = {"sol": 0, "memes": []}

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

# --- CORE FUNCTIONS ---

def get_sol_price():
    global last_known_price
    try:
        # Layer 1: Binance
        res = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT", timeout=2).json()
        last_known_price = float(res['price'])
        return last_known_price
    except:
        try:
            # Layer 2: Jupiter (Native Solana Price)
            jup_res = requests.get("https://price.jup.ag/v4/price?ids=SOL", timeout=2).json()
            last_known_price = float(jup_res['data']['SOL']['price'])
            return last_known_price
        except: return last_known_price

def get_token_name(mint):
    try:
        res = requests.get(f"https://token.jup.ag/all", timeout=5).json()
        for t in res:
            if t['address'] == mint: return f"${t['symbol']}"
        return f"Token ({mint[:4]})"
    except: return "Meme Coin"

def check_token_safety(mint):
    try:
        res = requests.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary", timeout=5).json()
        score = res.get('score', 9999)
        return ("✅ SAFE" if score < 600 else "🚨 DANGER")
    except: return "❓ Unknown"

def get_label(addr):
    addr_str = str(addr)
    if addr_str in KNOWN_WALLETS: return KNOWN_WALLETS[addr_str], True
    return f"👤 {addr_str[:4]}...{addr_str[-4:]}", False

def send_alert(msg, is_loud=False):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_notification": not is_loud}
    requests.post(url, json=payload)

# --- MAIN LOOP ---

def main():
    global start_time, pulse_data
    print("🚀 V6.0 WATCHLIST MODE ONLINE", flush=True)
    last_slot = solana_client.get_slot().value - 1

    while True:
        if time.time() - start_time >= 7200:
            # Update Pulse Report logic here...
            start_time, pulse_data = time.time(), {"sol": 0, "memes": []}

        try:
            slot = solana_client.get_slot().value
            if slot <= last_slot:
                time.sleep(1)
                continue
            
            block = solana_client.get_block(slot, encoding="jsonParsed", max_supported_transaction_version=0).value
            if not block or not block.transactions:
                last_slot = slot
                continue

            # FETCH LIVE PRICE ONCE PER BLOCK
            current_sol_price = get_sol_price()

            for tx in block.transactions:
                if not tx.meta or tx.meta.err: continue
                
                diff = abs(tx.meta.pre_balances[0] - tx.meta.post_balances[0]) / 10**9
                usd_val = diff * current_sol_price

                # --- SCAN FOR MINT & WATCHLIST ---
                mint = None
                is_watched = False
                post_balances = tx.meta.post_token_balances
                if post_balances:
                    for b in post_balances:
                        if b.mint not in ["So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"]:
                            mint = b.mint
                            if mint in WATCHED_MEMES: is_watched = True
                            break

                # --- 1. WATCHED MEME ALERT (ANY SIZE) ---
                if is_watched:
                    name = get_token_name(mint)
                    safety = check_token_safety(mint)
                    msg = (f"🎯 <b>WATCHLIST ALERT: {name}</b>\n"
                           f"━━━━━━━━━━━━━━\n"
                           f"📦 <b>Activity:</b> Transfer Detected\n"
                           f"💰 <b>Value:</b> {diff:,.2f} SOL (${usd_val:,.2f})\n"
                           f"🛡️ <b>Safety:</b> {safety}\n"
                           f"🔗 <a href='https://solscan.io/tx/{tx.transaction.signatures[0]}'>View Tx</a>")
                    send_alert(msg, is_loud=True)
                    continue

                # --- 2. STANDARD WHALE / SWAP LOGIC (>= 1000 SOL) ---
                if diff >= WHALE_THRESHOLD:
                    sender = str(tx.transaction.message.account_keys[0])
                    receiver = str(tx.transaction.message.account_keys[1]) if len(tx.transaction.message.account_keys) > 1 else "Unknown"
                    s_label, s_is_known = get_label(sender)
                    r_label, r_is_known = get_label(receiver)
                    
                    is_swap = False
                    for instr in tx.transaction.message.instructions:
                        prog = str(getattr(instr, 'program_id', ''))
                        if prog in [JUPITER_PROGRAM_ID, RAYDIUM_PROGRAM_ID] and mint:
                            name = get_token_name(mint)
                            msg = (f"🔄 <b>MEME COIN SWAP</b>\n━━━━━━━━━━━━━━\n"
                                   f"💰 <b>{diff:,.0f} SOL</b> swapped for <b>{name}</b>\n"
                                   f"👤 <b>Trader:</b> {s_label}")
                            send_alert(msg)
                            is_swap = True
                            break

                    if not is_swap:
                        # Logic for Inflow / Outflow classification...
                        icon = "📥" if r_is_known else ("📤" if s_is_known else "🕵️")
                        msg = (f"{icon} <b>WHALE MOVE</b>\n━━━━━━━━━━━━━━\n"
                               f"💰 <b>{diff:,.0f} SOL</b> (<b>${usd_val:,.2f}</b>)\n"
                               f"📤 <b>From:</b> {s_label}\n"
                               f"📥 <b>To:</b> {r_label}")
                        send_alert(msg, is_loud=(diff >= LOUD_THRESHOLD))

            last_slot = slot
        except Exception as e:
            print(f"⚠️ Error: {e}", flush=True)
            time.sleep(1)

if __name__ == "__main__":
    main()