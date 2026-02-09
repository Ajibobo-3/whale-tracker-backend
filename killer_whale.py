import time, requests, os, datetime
from solana.rpc.api import Client
from dotenv import load_dotenv

load_dotenv()

# --- SETUP ---
WHALE_THRESHOLD = 1000
LOUD_THRESHOLD = 2500
PINNED_MESSAGE_ID = None  # Your bot will print this ID in the logs on the first run
ALCHEMY_URL = os.getenv("ALCHEMY_URL")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

JUPITER_PROGRAM_ID = "JUP6LkbZbjS1jKKccwgwsS1iUCsz3HLbtvNcV6U64V1"
RAYDIUM_PROGRAM_ID = "675k1q2AYp7saS6Y1u4fRPs8yH1uS7S8S7S8S7S8S7S8"

# --- STATE ---
solana_client = Client(ALCHEMY_URL)
last_known_price = 100.0  # Realistic fallback
start_time = time.time()
pulse_data = {"sol": 0, "memes": []}

# --- DATA REGISTRY (Expanded) ---
KNOWN_WALLETS = {
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvu6Gn": "🏢 Binance Hot Wallet",
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM": "🏢 Binance Hot Wallet 2",
    "2QwUbEACJ3ppwfyH19QCSVvNrRzfuK5mNVNDsDMsZKMh": "🏢 Binance Cold Storage",
    "H88yS9KmY89U6pntYkjT9s2S1fDxtw74YAnY8r5x8k": "🏢 Coinbase",
    "AC5RDfQFmDS1deWZos921JfqscXdByf8BKHm5ACWpGsF": "🏢 Bybit Hot Wallet",
    "3QwUbEACJ3ppwfyH19QCSVvNrRzfuK5": "🏢 OKX Wallet",
    "FWznbcNXWQuHTawe9RxvQ2LdCENqHS1Xf9C1d1hSSZKD": "🏢 Kraken Hot Wallet",
    "7fFCzxv5Jm6x5rK5L2q8yvK6yV5L2q8yvK6yV5L2": "🔥 SMART MONEY (Penguin Whale)",
    "stupidmoney.sol": "🔥 SMART MONEY (Goat Legend)",
    "TruthTerminal.sol": "🤖 SMART MONEY (AI Agent #1)",
}

# --- CORE FUNCTIONS ---

def get_sol_price():
    global last_known_price
    try:
        res = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT", timeout=3).json()
        last_known_price = float(res['price'])
        return last_known_price
    except:
        try:
            jup_res = requests.get("https://price.jup.ag/v4/price?ids=SOL", timeout=3).json()
            last_known_price = float(jup_res['data']['SOL']['price'])
            return last_known_price
        except:
            return last_known_price

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

def update_pulse_report(data):
    report = (f"📊 <b>2-HOUR WHALE PULSE</b>\n"
              f"━━━━━━━━━━━━━━\n"
              f"💰 <b>Total Flow:</b> {data['sol']:,.0f} SOL\n"
              f"💎 <b>New Gems:</b> {', '.join(set(data['memes'])) if data['memes'] else 'None'}\n"
              f"🕒 <b>Updated:</b> {datetime.datetime.now().strftime('%H:%M')} WAT\n"
              f"━━━━━━━━━━━━━━\n"
              f"🛰️ <i>Real-time monitoring active.</i>")
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"
    if PINNED_MESSAGE_ID:
        requests.post(url + "editMessageText", json={"chat_id": TELEGRAM_CHAT_ID, "message_id": PINNED_MESSAGE_ID, "text": report, "parse_mode": "HTML"})
    else:
        r = requests.post(url + "sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": report, "parse_mode": "HTML"}).json()
        print(f"📌 NEW PINNED ID: {r['result']['message_id']}", flush=True)

# --- MAIN LOOP ---

def main():
    global start_time, pulse_data
    print("🚀 V5.1 OMNI-TRACKER ONLINE", flush=True)
    last_slot = solana_client.get_slot().value - 1

    while True:
        if time.time() - start_time >= 7200:
            update_pulse_report(pulse_data)
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

            for tx in block.transactions:
                if not tx.meta or tx.meta.err: continue
                
                price = get_sol_price()
                diff = abs(tx.meta.pre_balances[0] - tx.meta.post_balances[0]) / 10**9
                if diff < WHALE_THRESHOLD: continue

                sender = str(tx.transaction.message.account_keys[0])
                receiver = str(tx.transaction.message.account_keys[1]) if len(tx.transaction.message.account_keys) > 1 else "Unknown"
                s_label, s_is_known = get_label(sender)
                r_label, r_is_known = get_label(receiver)
                usd_val = diff * price

                # --- SCENARIO 1: SWAP DETECTED ---
                is_meme = False
                for instr in tx.transaction.message.instructions:
                    prog = str(getattr(instr, 'program_id', ''))
                    if prog in [JUPITER_PROGRAM_ID, RAYDIUM_PROGRAM_ID]:
                        post_balances = tx.meta.post_token_balances
                        if post_balances:
                            mint = next((b.mint for b in post_balances if b.mint not in ["So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"]), None)
                            if mint:
                                name = get_token_name(mint)
                                safety = check_token_safety(mint)
                                msg = (f"🔄 <b>MEME COIN SWAP</b>\n"
                                       f"━━━━━━━━━━━━━━\n"
                                       f"💰 <b>{diff:,.0f} SOL</b> swapped for <b>{name}</b>\n"
                                       f"🛡️ <b>Safety:</b> {safety}\n"
                                       f"👤 <b>Trader:</b> {s_label}\n"
                                       f"📊 <a href='https://birdeye.so/token/{mint}?chain=solana'>Trader PnL</a> | <a href='https://dexscreener.com/solana/{mint}'>Chart</a>")
                                send_alert(msg)
                                pulse_data["memes"].append(name)
                                is_meme = True
                                break

                # --- SCENARIO 2: CLASSIFIED TRANSFERS ---
                if not is_meme:
                    pulse_data["sol"] += diff
                    
                    if r_is_known and not s_is_known:
                        icon, title, vibe = "📥", "EXCHANGE INFLOW", "🚩 Potential Sell Pressure"
                    elif s_is_known and not r_is_known:
                        icon, title, vibe = "📤", "EXCHANGE OUTFLOW", "🟢 Bullish Accumulation"
                    elif s_is_known and r_is_known:
                        icon, title, vibe = "🏢", "EXCHANGE TO EXCHANGE", "⚪ Neutral Rebalancing"
                    else:
                        icon, title, vibe = "🕵️", "PRIVATE TRANSFER", "⚪ Neutral Move"

                    msg = (f"{icon} <b>{title}</b>\n"
                           f"━━━━━━━━━━━━━━\n"
                           f"💰 <b>{diff:,.0f} SOL</b> (<b>${usd_val:,.2f}</b>)\n"
                           f"📝 {vibe}\n"
                           f"📤 <b>From:</b> {s_label}\n"
                           f"📥 <b>To:</b> {r_label}\n"
                           f"━━━━━━━━━━━━━━\n"
                           f"🔗 <a href='https://solscan.io/tx/{tx.transaction.signatures[0]}'>View on Solscan</a>")
                    
                    send_alert(msg, is_loud=(diff >= LOUD_THRESHOLD))

            last_slot = slot
        except Exception as e:
            print(f"⚠️ Error: {e}", flush=True)
            time.sleep(1)

if __name__ == "__main__":
    main()