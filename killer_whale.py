import time
import requests
import os
from solana.rpc.api import Client
from postgrest import SyncPostgrestClient
from dotenv import load_dotenv

load_dotenv()

# --- SETTINGS ---
WHALE_THRESHOLD = 1000  
LOUD_THRESHOLD = 2500  
ALCHEMY_URL = os.getenv("ALCHEMY_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

JUPITER_PROGRAM_ID = "JUP6LkbZbjS1jKKccwgwsS1iUCsz3HLbtvNcV6U64V1"
RAYDIUM_PROGRAM_ID = "675k1q2AYp7saS6Y1u4fRPs8yH1uS7S8S7S8S7S8S7S8"

# --- DATA REGISTRY ---
KNOWN_WALLETS = {
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvu6Gn": "🏢 Binance Hot Wallet",
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM": "🏢 Binance Hot Wallet 2",
    "H88yS9KmY89U6pntYkjT9s2S1fDxtw74YAnY8r5x8k": "🏢 Coinbase",
    "7fFCzxv5Jm6x5rK5L2q8yvK6yV5L2q8yvK6yV5L2": "🔥 SMART MONEY (Penguin Whale)",
    "stupidmoney.sol": "🔥 SMART MONEY (Goat Legend)",
    "9R8cTBpk99JYjG1mGm2iCJeQkUHTu5nUR3h29jCRWSUq": "🔥 SMART MONEY (PNUT Sniper)",
    "6xSRNkqjdy6GSFF74m1oT4nwp1SnDJSyau7CoDz3Y7MC": "🔥 SMART MONEY (WIF God)",
    "TruthTerminal.sol": "🤖 SMART MONEY (AI Agent #1)",
}

# --- STATE ---
last_known_price = 210.0
solana_client = Client(ALCHEMY_URL)
db = SyncPostgrestClient(f"{SUPABASE_URL}/rest/v1", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})

def get_sol_price():
    global last_known_price
    try:
        res = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT", timeout=3).json()
        last_known_price = float(res['price'])
        return last_known_price
    except: return last_known_price

def check_token_safety(mint):
    try:
        res = requests.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary", timeout=5).json()
        score = res.get('score', 9999)
        if score < 600: return "✅ SAFE", "Safe"
        return "🚨 DANGER", "Danger"
    except: return "❓ Unknown", "Unknown"

def get_token_name(mint):
    try:
        res = requests.get(f"https://token.jup.ag/all", timeout=5).json()
        for t in res:
            if t['address'] == mint: return f"${t['symbol']}"
        return f"Token ({mint[:4]})"
    except: return "Meme Coin"

def get_wallet_profile(address):
    if address in KNOWN_WALLETS: return KNOWN_WALLETS[address], True
    return "👤 Active Trader", False

def send_alert(msg, is_loud=False):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_notification": not is_loud})

def main():
    print("🚀 V4.3 STARTING: MEME ALPHA MODE ACTIVE", flush=True)
    last_slot = 0
    while True:
        try:
            slot = solana_client.get_slot().value
            if slot <= last_slot:
                time.sleep(2)
                continue
            
            block = solana_client.get_block(slot, encoding="jsonParsed", max_supported_transaction_version=0).value
            if not block or not block.transactions: continue
            
            for tx in block.transactions:
                if not tx.meta or tx.meta.err: continue
                
                price = get_sol_price()
                diff = abs(tx.meta.pre_balances[0] - tx.meta.post_balances[0]) / 10**9
                usd = diff * price

                # --- THE MEME CHECK ---
                is_meme = False
                for instr in tx.transaction.message.instructions:
                    prog = str(instr.get('programId', ''))
                    if prog in [JUPITER_PROGRAM_ID, RAYDIUM_PROGRAM_ID]:
                        post = tx.meta.post_token_balances
                        if post:
                            mint = post[0]['mint']
                            if mint not in ["So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"]:
                                wallet = tx.transaction.message.account_keys[0]['pubkey']
                                label, is_smart = get_wallet_profile(wallet)
                                safety, status = check_token_safety(mint)
                                title = "🚨 <b>SMART MONEY BUY</b>" if is_smart else "🦄 <b>MEME ALPHA</b>"
                                
                                msg = (f"{title}\n"
                                       f"━━━━━━━━━━━━━━\n"
                                       f"💎 <b>Token:</b> {get_token_name(mint)}\n"
                                       f"🛡️ <b>Safety:</b> {safety}\n"
                                       f"👤 <b>Trader:</b> {label}\n"
                                       f"💰 <b>Size:</b> ${usd:,.2f}\n"
                                       f"━━━━━━━━━━━━━━\n"
                                       f"📊 <a href='https://birdeye.so/token/{mint}?chain=solana'>Trader PnL</a>\n"
                                       f"📈 <a href='https://dexscreener.com/solana/{mint}'>Live Chart</a>")
                                
                                send_alert(msg, is_loud=(is_smart or diff >= LOUD_THRESHOLD))
                                is_meme = True
                                break
                
                # --- THE WHALE FALLBACK ---
                if not is_meme and diff >= WHALE_THRESHOLD:
                    msg = (f"🐋 <b>WHALE SOL MOVE</b>\n"
                           f"━━━━━━━━━━━━━━\n"
                           f"💰 <b>Amount:</b> {diff:,.0f} SOL (${usd:,.2f})\n"
                           f"🔗 <a href='https://solscan.io/tx/{tx.transaction.signatures[0]}'>View Transaction</a>")
                    send_alert(msg, is_loud=(diff >= LOUD_THRESHOLD))

            last_slot = slot
            time.sleep(1)
        except Exception as e:
            time.sleep(5)

if __name__ == "__main__":
    main()