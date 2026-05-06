


from SmartApi import SmartConnect
import pyotp, requests, time
from datetime import datetime
import traceback

# ========= CONFIG =========
API_KEY = "x2dxUBP6"
CLIENT_ID = "A58372607"
PASSWORD = "7777"
TOTP_SECRET = "B5PEOYQHVMQGHVIKMLRBLH7WUE"

LOT_SIZE = 65
AUTO_TRADE = True

# ========= SAFE LOGIN =========
def login():
    try:
        obj = SmartConnect(API_KEY)
        totp = pyotp.TOTP(TOTP_SECRET).now()
        obj.generateSession(CLIENT_ID, PASSWORD, totp)
        print("✅ Logged in")
        return obj
    except Exception as e:
        print("❌ LOGIN ERROR:", e)
        return None

obj = login()

# ========= LOAD MASTER (RETRY SAFE) =========
def load_master():
    for _ in range(3):
        try:
            data = requests.get(
                "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json",
                timeout=10
            ).json()
            print("✅ Master Loaded")
            return data
        except:
            print("Retrying master...")
            time.sleep(2)
    raise Exception("Master load failed")

master = load_master()

# ========= GET EXPIRY =========
from datetime import datetime as dt

def get_expiry():
    expiries = {
        x['expiry'] for x in master
        if x['name']=="NIFTY"
        and x['instrumenttype']=="OPTIDX"
        and x['expiry']
    }

    parsed = []
    for e in expiries:
        try:
            parsed.append((dt.strptime(e, "%d%b%Y"), e))
        except:
            pass

    parsed.sort()
    today = dt.now()

    for d, e in parsed:
        if d.date() >= today.date():
            return e

    return parsed[0][1]

expiry = get_expiry()
print("📅 Expiry:", expiry)

# ========= GET ATM =========
def get_atm_ce():
    try:
        ltp = obj.ltpData("NSE", "NIFTY", "26000")['data']['ltp']
        strike = round(ltp/50)*50

        for s in master:
            if (s['name']=="NIFTY"
                and s['expiry']==expiry
                and s['symbol'].endswith("CE")
                and str(strike) in s['symbol']):
                return s

    except Exception as e:
        print("ATM ERROR:", e)

    return None

# ========= ORDER =========
last_order_time = None

def place_order(opt):
    global last_order_time

    # prevent duplicate orders
    if last_order_time and (time.time() - last_order_time < 120):
        print("⛔ Skipping duplicate order")
        return

    print("📈 BUY:", opt['symbol'])

    if not AUTO_TRADE:
        print("⚠️ AUTO OFF")
        return

    try:
        res = obj.placeOrder({
            "variety":"NORMAL",
            "tradingsymbol":opt['symbol'],
            "symboltoken":opt['token'],
            "transactiontype":"BUY",
            "exchange":"NFO",
            "ordertype":"MARKET",
            "producttype":"INTRADAY",
            "duration":"DAY",
            "quantity":LOT_SIZE
        })

        last_order_time = time.time()
        print("✅ ORDER:", res)

    except Exception as e:
        print("❌ ORDER ERROR:", e)

last_run_minute = -1

while True:
    try:
        now = datetime.now()

        # ========= STRICT MARKET TIME =========
        if not (now.hour == 9 and now.minute >= 15) and not (9 < now.hour < 15) and not (now.hour == 15 and now.minute <= 30):
            time.sleep(5)
            continue

        # ========= RUN EXACTLY AT CANDLE START =========
        if now.second != 0:
            time.sleep(0.5)
            continue

        # ========= PREVENT DUPLICATE RUN =========
        if now.minute == last_run_minute:
            time.sleep(1)
            continue

        last_run_minute = now.minute

        print("\n⏱ RUN:", now.strftime("%H:%M:%S"))

        # ========= GET ATM =========
        ce = get_atm_ce()

        if ce is None:
            print("❌ CE not found")
            continue

        # ========= PLACE ORDER =========
        place_order(ce)

        # ========= SMALL SLEEP =========
        time.sleep(1)

    except Exception as e:
        print("🔥 LOOP ERROR:", e)
        traceback.print_exc()

        # auto re-login
        obj = login()

        time.sleep(5)
