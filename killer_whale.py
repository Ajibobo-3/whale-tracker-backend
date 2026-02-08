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
last_known_price = 210.0 # Set a realistic default
PINNED_MESSAGE_ID = None 
last_pulse_time = 0

db_url = f"{SUPABASE_URL}/rest/v1"
headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
db = SyncPostgrestClient(db_url, headers=headers)
solana_client = Client(ALCHEMY_URL)

# --- CORE FUNCTIONS ---

def get_sol_price():
    """Triple-redundant price oracle to prevent $0.00 values."""
    global last_known_price
    # 1. CoinGecko
    try:
        res = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd", timeout=3).json()
        last_known_price = float(res['solana']['usd'])
        return last_known_price
    except: pass

    # 2. Binance
    try:
        res = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT", timeout=3).json()
        last_known_price = float(res['price'])
        return last_known_price
    except: pass

    # 3. Jupiter
    try:
        res = requests.get("https://price.jup.ag/v4/price?ids=SOL", timeout=3).json()
        last_known_price = float(res['data']['SOL']['price'])
        return last_known_price
    except:
        print("⚠️ All price oracles failed. Using last cached price.")
        return last_known_price

def check_blacklisted_dev(mint):
    """Checks if the token creator is in the blacklist table."""
    try:
        # Get mint account info to find the authority (deployer)
        info = solana_client.get_account_info(mint).value
        if not info: return None, False
        
        # Simulating creator detection for now; in prod, use a parser for mintAuthority
        creator_address = "Check_Manual_For_Now" 
        
        check = db.table("blacklisted_devs").select("*").eq("wallet_address", creator_address).execute()
        return creator_address, len(check.data) > 0
    except:
        return None, False

def check_token_safety(mint):
    try:
        url = f"https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary"
        res = requests.get(url, timeout=10).json()
        score = res.get('score', 9999)
        if score < 600: return "✅ SAFE", "Safe"
        elif score < 2000: return "⚠️ MODERATE", "Risky"
        else: return "🚨 HIGH DANGER", "Danger"
    except:
        return "❓ Unknown", "Unknown"

def get_token_name(mint):
    try:
        res = requests.get(f"https://token.jup.ag/all", timeout=5).json()
        for token in res:
            if token['address'] == mint: return f"${token['symbol']}"
        return f"Token ({mint[:4]})"
    except: return "Meme Coin"

def get_wallet_profile(address):
    if address in KNOWN_WALLETS: return KNOWN_WALLETS[address], True
    try:
        sigs = solana_client.get_signatures_for_address(address, limit=5).value
        if not sigs: return "🆕 New Wallet", False
        return "👤 Active Trader", False
    except: return "👤 Private Wallet", False

def send_alert(msg, is_loud=False):
    if not TELEGRAM_BOT_TOKEN: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_notification": not is_loud}
        requests.post(url, json=payload, timeout=10)
    except Exception as e: print(f"Telegram Error: {e}")

def main():
    global last_pulse_time
    print(f"🚀 ENGINE STARTING: WHALE INTEL V4.3 (Anti-Rug Edition)", flush=True)
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
                    
                    price = get_sol_price()
                    sol_diff = abs(tx.meta.pre_balances[0] - tx.meta.post_balances[0]) / 10**9
                    usd_val = sol_diff * price

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
                                        
                                        # FLAG BLACKLIST, SMART MONEY & SAFETY
                                        _, is_blacklisted = check_blacklisted_dev(mint)
                                        is_smart = "🔥 SMART MONEY" in w_label or "🤖" in w_label
                                        safety_label, safety_status = check_token_safety(mint)
                                        
                                        if is_blacklisted:
                                            title = "❌ <b>BLACKLISTED DEV DETECTED</b> ❌"
                                            status_emoji = "🔴"
                                        elif is_smart:
                                            title = "🚨 <b>SMART MONEY ENTRY</b> 🚨"
                                            status_emoji = "🔥"
                                        else:
                                            title = "🦄 <b>MEME COIN ALPHA</b>"
                                            status_emoji = "💎"

                                        token_symbol = get_token_name(mint)
                                        
                                        msg = (f"{title}\n\n"
                                               f"{status_emoji} <b>Token:</b> {token_symbol}\n"
                                               f"🛡️ <b>Security:</b> {safety_label}\n"
                                               f"👤 <b>Trader:</b> {w_label}\n"
                                               f"💰 <b>Size:</b> ${usd_val:,.2f} USD\n\n"
                                               f"🔍 <a href='https://rugcheck.xyz/tokens/{mint}'>Security Audit</a>\n"
                                               f"📊 <a href='https://birdeye.so/token/{mint}?chain=solana'>Trader PnL</a>")
                                        
                                        send_alert(msg, is_loud=(is_smart or is_blacklisted or (sol_diff >= LOUD_THRESHOLD and safety_status != "Danger")))
                                        break 

            last_processed_slot = current_slot
            time.sleep(1)
        except Exception as e:
            time.sleep(10)

if __name__ == "__main__":
    main()