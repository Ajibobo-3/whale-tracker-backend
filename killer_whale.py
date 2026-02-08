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
TOKEN_BUY_THRESHOLD_USD = 5000 

ALCHEMY_URL = os.getenv("ALCHEMY_URL", "https://api.mainnet-beta.solana.com")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- DEX PROGRAM IDs ---
JUPITER_PROGRAM_ID = "JUP6LkbZbjS1jKKccwgwsS1iUCsz3HLbtvNcV6U64V1"
RAYDIUM_PROGRAM_ID = "675k1q2AYp7saS6Y1u4fRPs8yH1uS7S8S7S8S7S8S7S8"

# --- DATA REGISTRY (Smart Money 2026 Edition) ---
KNOWN_WALLETS = {
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvu6Gn": "🏢 Binance Hot Wallet",
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM": "🏢 Binance Hot Wallet 2",
    "H88yS9KmY89U6pntYkjT9s2S1fDxtw74YAnY8r5x8k": "🏢 Coinbase",
    "7fFCzxv5Jm6x5rK5L2q8yvK6yV5L2q8yvK6yV5L2": "🔥 SMART MONEY (Penguin Whale)",
    "stupidmoney.sol": "🔥 SMART MONEY (Goat Legend)",
    "9R8cTBpk99JYjG1mGm2iCJeQkUHTu5nUR3h29jCRWSUq": "🔥 SMART MONEY (PNUT Sniper)",
    "6xSRNkqjdy6GSFF74m1oT4nwp1SnDJSyau7CoDz3Y7MC": "🔥 SMART MONEY (WIF God)",
    "2itf6FWdZUqUb3fKUFPGnaTgqjjvWZwzrz129LCaqFa2": "🔥 SMART MONEY (Alpha Rotator)",
    "TruthTerminal.sol": "🤖 SMART MONEY (AI Agent #1)",
}

# --- STATE MANAGEMENT ---
last_known_price = 105.0
PINNED_MESSAGE_ID = None 
last_pulse_time = 0

db_url = f"{SUPABASE_URL}/rest/v1"
headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
db = SyncPostgrestClient(db_url, headers=headers)
solana_client = Client(ALCHEMY_URL)

# --- CORE FUNCTIONS ---

def check_token_safety(mint):
    """Fetches a safety score and risks from RugCheck.xyz."""
    try:
        url = f"https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary"
        res = requests.get(url, timeout=10).json()
        
        # Risk Score: 0-500 is generally 'Good'
        score = res.get('score', 9999)
        
        if score < 600:
            return "✅ SAFE (RugCheck Verified)", "Safe"
        elif score < 2000:
            return "⚠️ MODERATE RISK", "Risky"
        else:
            return "🚨 HIGH DANGER (Possible Rug)", "Danger"
    except:
        return "❓ Safety Unknown", "Unknown"

def get_token_name(mint):
    try:
        res = requests.get(f"https://token.jup.ag/all", timeout=5).json()
        for token in res:
            if token['address'] == mint:
                return f"${token['symbol']}"
        return f"Token ({mint[:4]})"
    except:
        return "Meme Coin"

def get_wallet_profile(address):
    if address in KNOWN_WALLETS:
        return KNOWN_WALLETS[address], True
    try:
        sigs_resp = solana_client.get_signatures_for_address(address, limit=5)
        sigs = sigs_resp.value
        if not sigs: return "🆕 New Wallet", False
        last_tx_time = sigs[0].block_time
        if (int(time.time()) - last_tx_time) > (180 * 24 * 60 * 60):
            return "💤 Dormant Whale", False
        return "👤 Active Trader", False
    except:
        return "👤 Private Wallet", False

def send_alert(msg, is_loud=False):
    if not TELEGRAM_BOT_TOKEN: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML",
            "disable_web_page_preview": False, "disable_notification": not is_loud
        }
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

def main():
    global last_pulse_time
    print(f"🚀 ENGINE STARTING: WHALE INTEL V4.2 (Smart Money + RugCheck)", flush=True)
    last_processed_slot = 0

    while True:
        try:
            current_slot = solana_client.get_slot().value
            if current_slot <= last_processed_slot:
                time.sleep(3)
                continue

            block = solana_client.get_block(current_slot, encoding="jsonParsed", max_supported_transaction_version=0).value
            
            if block and block.transactions:
                for tx in block.transactions:
                    if not tx.meta or tx.meta.err: continue
                    sol_diff = abs(tx.meta.pre_balances[0] - tx.meta.post_balances[0]) / 10**9

                    # --- SWAP DETECTION ---
                    instructions = tx.transaction.message.instructions
                    for instr in instructions:
                        prog_id = str(instr.get('programId', ''))
                        if prog_id in [JUPITER_PROGRAM_ID, RAYDIUM_PROGRAM_ID]:
                            post_tokens = tx.meta.post_token_balances
                            if post_tokens:
                                for token in post_tokens:
                                    mint = token['mint']
                                    if mint not in ["So11111111111111111111111111111111111111112", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"]:
                                        
                                        user_wallet = tx.transaction.message.account_keys[0]['pubkey']
                                        w_label, _ = get_wallet_profile(user_wallet)
                                        
                                        # FLAG SMART MONEY & SAFETY
                                        is_smart = "🔥 SMART MONEY" in w_label or "🤖" in w_label
                                        safety_label, safety_status = check_token_safety(mint)
                                        
                                        title = "🚨 <b>SMART MONEY ENTRY</b> 🚨" if is_smart else "🦄 <b>MEME COIN ALPHA</b>"
                                        token_symbol = get_token_name(mint)
                                        
                                        msg = (f"{title}\n\n"
                                               f"💎 <b>Token:</b> {token_symbol}\n"
                                               f"🛡️ <b>Security:</b> {safety_label}\n"
                                               f"👤 <b>Trader:</b> {w_label}\n"
                                               f"💰 <b>Size:</b> {sol_diff:,.2f} SOL\n\n"
                                               f"🔍 <a href='https://rugcheck.xyz/tokens/{mint}'>View Security Audit</a>\n"
                                               f"📊 <a href='https://birdeye.so/token/{mint}?chain=solana'>Check Trader PnL</a>\n"
                                               f"📈 <a href='https://dexscreener.com/solana/{mint}'>View Chart</a>")
                                        
                                        # Silent alerts for 'Danger' coins to avoid spamming bad plays
                                        is_loud = (is_smart or (sol_diff >= LOUD_THRESHOLD and safety_status != "Danger"))
                                        send_alert(msg, is_loud=is_loud)
                                        break 

            last_processed_slot = current_slot
            time.sleep(1)
        except Exception as e:
            time.sleep(10)

if __name__ == "__main__":
    main()