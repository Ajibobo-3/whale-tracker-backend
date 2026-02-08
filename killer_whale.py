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

# --- STATE MANAGEMENT ---
last_known_price = 105.0
PINNED_MESSAGE_ID = None 
last_pulse_time = 0

# --- DATA REGISTRY ---
KNOWN_WALLETS = {
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvu6Gn": "Binance Hot Wallet",
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM": "Binance Hot Wallet 2",
    "2QwUbEACJ3ppwfyH19QCSVvNrRzfuK5mNVNDsDMsZKMh": "Binance Cold Storage",
    "H88yS9KmY89U6pntYkjT9s2S1fDxtw74YAnY8r5x8k": "Coinbase",
    "AC59pU9r6p4jAiof6MvS6G68p8G6MvS6G68p8G6MvS6": "Bybit",
    "5VC89L2q8yvK6yV5L2q8yvK6yV5L2q8yvK6yV5L2q8y": "OKX",
    "HuDxqF2acC6f8T7Ea8K3P6qK4WjH4Z3h4z6f5e7h8j9k": "Kraken",
    "6686pSGYmZpL9pS5v9K9pS5v9K9pS5v9K9pS5v9K9pS": "FixedFloat (Bridge)"
}

db_url = f"{SUPABASE_URL}/rest/v1"
headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
db = SyncPostgrestClient(db_url, headers=headers)
solana_client = Client(ALCHEMY_URL)

# --- CORE FUNCTIONS ---

def get_wallet_profile(address):
    if address in KNOWN_WALLETS:
        return f"🏢 {KNOWN_WALLETS[address]}", True
    try:
        sigs_resp = solana_client.get_signatures_for_address(address, limit=10)
        sigs = sigs_resp.value
        if not sigs: return "🆕 New Wallet", False
        last_tx_time = sigs[0].block_time
        if (int(time.time()) - last_tx_time) > (180 * 24 * 60 * 60):
            return "💤 Idle Wallet (6mo+)", False
        if len(sigs) < 5: return "🐣 Fresh Wallet", False
        return "👤 Active Private Wallet", False
    except:
        return "👤 Private Wallet", False

def get_sol_price():
    global last_known_price
    try:
        res = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd", timeout=5).json()
        last_known_price = float(res['solana']['usd'])
        return last_known_price
    except:
        return last_known_price

def send_alert(msg, is_loud=False):
    if not TELEGRAM_BOT_TOKEN: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
            "disable_notification": not is_loud
        }
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

def update_pulse_report():
    """Calculates 24h flows and updates the pinned Telegram message."""
    global PINNED_MESSAGE_ID
    try:
        # 1. Fetch alerts from Supabase
        res = db.table("whale_alerts").select("*").execute()
        
        # 2. THE FIX: Filter out rows where created_at_unix is None (old data)
        day_ago = time.time() - (24 * 60 * 60)
        alerts = [
            a for a in res.data 
            if a.get('created_at_unix') is not None and float(a['created_at_unix']) > day_ago
        ]
        
        if not alerts:
            print("🕒 Pulse Report: No valid whale data found for the last 24h yet.")
            return

        inflow = sum(a['sol_amount'] for a in alerts if "BEARISH" in a.get('sentiment', ''))
        outflow = sum(a['sol_amount'] for a in alerts if "BULLISH" in a.get('sentiment', ''))
        net_flow = outflow - inflow
        
        status_emoji = "🟢" if net_flow > 0 else "🔴"
        report = (f"📊 <b>24H WHALE PULSE REPORT</b>\n"
                  f"━━━━━━━━━━━━━━━━━━\n"
                  f"📥 <b>Total Inflow (to CEX):</b> {inflow:,.0f} SOL\n"
                  f"📤 <b>Total Outflow (to Cold):</b> {outflow:,.0f} SOL\n\n"
                  f"⚖️ <b>Net Market Movement:</b> {net_flow:,.0f} SOL {status_emoji}\n"
                  f"<i>Last Updated: {time.strftime('%H:%M')} UTC</i>\n"
                  f"━━━━━━━━━━━━━━━━━━\n"
                  f"📌 <i>This report updates every 6 hours.</i>")

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"
        if PINNED_MESSAGE_ID is None:
            resp = requests.post(url + "sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": report, "parse_mode": "HTML"}).json()
            if resp.get('ok'):
                PINNED_MESSAGE_ID = resp['result']['message_id']
                requests.post(url + "pinChatMessage", json={"chat_id": TELEGRAM_CHAT_ID, "message_id": PINNED_MESSAGE_ID})
        else:
            requests.post(url + "editMessageText", json={
                "chat_id": TELEGRAM_CHAT_ID, "message_id": PINNED_MESSAGE_ID, "text": report, "parse_mode": "HTML"
            })
    except Exception as e:
        print(f"Pulse Error: {e}")

def main():
    global last_pulse_time
    print(f"🚀 ENGINE STARTING: WHALE INTEL V3 (Pulse + Silent Notifications)", flush=True)
    last_processed_slot = 0

    while True:
        try:
            # Check for Pulse Report update (Every 6 hours)
            if time.time() - last_pulse_time > 21600:
                update_pulse_report()
                last_pulse_time = time.time()

            current_slot = solana_client.get_slot().value
            if current_slot <= last_processed_slot:
                time.sleep(3)
                continue

            block = solana_client.get_block(current_slot, max_supported_transaction_version=0).value
            if block and block.transactions:
                for tx in block.transactions:
                    if not tx.meta or tx.meta.err: continue
                    pre, post = tx.meta.pre_balances[0], tx.meta.post_balances[0]
                    diff = (pre - post) / 10**9 
                    
                    if diff >= WHALE_THRESHOLD:
                        sender = str(tx.transaction.message.account_keys[0])
                        receiver = str(tx.transaction.message.account_keys[1])
                        sig = str(tx.transaction.signatures[0])
                        
                        s_label, s_is_cex = get_wallet_profile(sender)
                        r_label, r_is_cex = get_wallet_profile(receiver)
                        
                        sentiment = "🔄 Wallet Transfer"
                        if s_is_cex and not r_is_cex: sentiment = "🟢 BULLISH (Exchange Outflow)"
                        elif not s_is_cex and r_is_cex: sentiment = "🔴 BEARISH (Exchange Inflow)"
                        
                        price = get_sol_price()
                        usd_val = diff * price
                        
                        msg = (f"🚨 <b>WHALE MOVEMENT DETECTED</b>\n\n"
                               f"📊 <b>Sentiment:</b> {sentiment}\n"
                               f"💰 <b>Amount:</b> {diff:,.2f} SOL (<b>${usd_val:,.2f} USD</b>)\n\n"
                               f"📤 <b>From:</b> {s_label}\n"
                               f"📥 <b>To:</b> {r_label}\n\n"
                               f"🧼 <a href='https://bubblemaps.io/eth/address/{sender}'>Analyze Clusters (Bubblemaps)</a>\n"
                               f"🔗 <a href='https://solscan.io/tx/{sig}'>View Transaction</a>")
                        
                        send_alert(msg, is_loud=(diff >= LOUD_THRESHOLD))
                        db.table("whale_alerts").insert({
                            "sol_amount": diff, "usd_value": usd_val, "signature": sig,
                            "sender": sender, "receiver": receiver, "sentiment": sentiment,
                            "created_at_unix": time.time()
                        }).execute()

            last_processed_slot = current_slot
            time.sleep(1)

        except Exception as e:
            time.sleep(10)
            continue

if __name__ == "__main__":
    main()