


from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
import pyotp, pandas as pd, pytz, time, requests
from datetime import datetime

# ================= CONFIG =================
API_KEY = "x2dxUBP6"
CLIENT_ID = "A58372607"
PASSWORD = "7777"
TOTP_SECRET = "B5PEOYQHVMQGHVIKMLRBLH7WUE"

LOT_SIZE = 50
TARGET = 8
SL = 8
MAX_TRADES = 2
AUTO_TRADE = False   # 🔴 KEEP FALSE FIRST

# =========================================

# LOGIN
obj = SmartConnect(api_key=API_KEY)
totp = pyotp.TOTP(TOTP_SECRET).now()
data = obj.generateSession(CLIENT_ID, PASSWORD, totp)

AUTH_TOKEN = data['data']['jwtToken']
FEED_TOKEN = obj.getfeedToken()

# LOAD INSTRUMENT
url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
df = pd.DataFrame(requests.get(url).json())
df['strike'] = df['strike'].astype(float)

# ================= GLOBAL =================
candles = []
position = None
entry_price = 0
trade_count = 0
ce_data = None
pe_data = None

# ================= ATM =================
def get_atm_options():
    global ce_data, pe_data

    ltp = obj.ltpData("NSE", "NIFTY", "26000")['data']['ltp']
    strike = round(ltp / 50) * 50

    nifty = df[df['symbol'].str.startswith("NIFTY")]
    nifty = nifty[nifty['instrumenttype'] == "OPTIDX"]

    expiry = sorted(nifty['expiry'].dropna().unique())[0]
    nifty['strike_val'] = nifty['strike'] / 100

    ce = nifty[(nifty['expiry']==expiry) & (nifty['symbol'].str.endswith("CE"))].copy()
    pe = nifty[(nifty['expiry']==expiry) & (nifty['symbol'].str.endswith("PE"))].copy()

    ce = ce.iloc[(ce['strike_val']-strike).abs().argsort()[:1]]
    pe = pe.iloc[(pe['strike_val']-strike).abs().argsort()[:1]]

    ce_data = ce.iloc[0]
    pe_data = pe.iloc[0]

    print(f"ATM: {strike} {ce_data['symbol']} {pe_data['symbol']}")

# ================= ORDER =================
def place_order(opt):
    global entry_price, position, trade_count

    if trade_count >= MAX_TRADES:
        return

    print("📈 ORDER:", opt['symbol'])

    if not AUTO_TRADE:
        print("⚠️ AUTO TRADE OFF")
        return

    res = obj.placeOrder({
        "variety": "NORMAL",
        "tradingsymbol": opt['symbol'],
        "symboltoken": opt['token'],
        "transactiontype": "BUY",
        "exchange": "NFO",
        "ordertype": "MARKET",
        "producttype": "INTRADAY",
        "duration": "DAY",
        "quantity": LOT_SIZE
    })

    print("Order Response:", res)

    ltp = obj.ltpData("NFO", opt['symbol'], opt['token'])['data']['ltp']
    entry_price = ltp
    position = opt
    trade_count += 1

def exit_order():
    global position

    if position is None:
        return

    print("❌ EXIT:", position['symbol'])

    obj.placeOrder({
        "variety": "NORMAL",
        "tradingsymbol": position['symbol'],
        "symboltoken": position['token'],
        "transactiontype": "SELL",
        "exchange": "NFO",
        "ordertype": "MARKET",
        "producttype": "INTRADAY",
        "duration": "DAY",
        "quantity": LOT_SIZE
    })

    position = None

# ================= CANDLE =================
def build_candle(price):
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist).replace(second=0, microsecond=0)

    if not candles:
        candles.append({"time": now, "open": price, "high": price, "low": price, "close": price})
        return

    last = candles[-1]

    if now == last["time"]:
        last["high"] = max(last["high"], price)
        last["low"] = min(last["low"], price)
        last["close"] = price
    else:
        candles.append({"time": now, "open": price, "high": price, "low": price, "close": price})

        if len(candles) > 50:
            candles.pop(0)

        check_signal()

# ================= EMA =================
def check_signal():
    global position

    if len(candles) < 20:
        return

    df_c = pd.DataFrame(candles)
    df_c['ema9'] = df_c['close'].ewm(span=9).mean()
    df_c['ema15'] = df_c['close'].ewm(span=15).mean()

    if position is None:

        if df_c.iloc[-2]['ema9'] < df_c.iloc[-2]['ema15'] and df_c.iloc[-1]['ema9'] > df_c.iloc[-1]['ema15']:
            print("🚀 CALL SIGNAL")
            place_order(ce_data)

        elif df_c.iloc[-2]['ema9'] > df_c.iloc[-2]['ema15'] and df_c.iloc[-1]['ema9'] < df_c.iloc[-1]['ema15']:
            print("🔻 PUT SIGNAL")
            place_order(pe_data)

# ================= MONITOR =================
def monitor(price):
    global position, entry_price

    if position is None:
        return

    if price >= entry_price + TARGET:
        print("🎯 TARGET HIT")
        exit_order()

    elif price <= entry_price - SL:
        print("🛑 SL HIT")
        exit_order()

# ================= WEBSOCKET =================
sws = SmartWebSocketV2(AUTH_TOKEN, API_KEY, CLIENT_ID, FEED_TOKEN)

def on_open(ws):
    print("Connected")
    get_atm_options()

    tokens = [{"exchangeType": 1, "tokens": ["26000"]}]
    sws.subscribe("1", 1, tokens)

def on_data(ws, message):
    try:
        if 'data' not in message:
            return

        data = message['data']

        if 'last_traded_price' not in data:
            return

        price = data['last_traded_price'] / 100

        print("LTP:", price)

        build_candle(price)
        monitor(price)

    except Exception as e:
        print("WS ERROR:", e)

def on_error(ws, error):
    print("Error:", error)

def on_close(ws):
    print("Closed")

sws.on_open = on_open
sws.on_data = on_data
sws.on_error = on_error
sws.on_close = on_close

sws.connect()
