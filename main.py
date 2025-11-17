from flask import Flask, request
import requests
from bs4 import BeautifulSoup
import pytz
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = "93ahsc44ZtZ9fOhGe9aLLDmJblRjteWAmX9uMHv2nHNyV7ZeCaKGdhKVCDYv78vujiNsmBk0Q5MM8QBEbqUAPIqLzaByFsqccmu6lG5kdAXowh/yl15hwfTBewnDGopDcjBY0On7fSQcN9gID/9YbgdB04t89/1O/w1cDnyilFU="
TO_USER_ID = "Ca65d5b8ecf7b309a655207945ca5afee"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ExchangeBot/1.0; +https://github.com/)"
}
REQUEST_TIMEOUT = 10
TZ = pytz.timezone("Asia/Taipei")

# -------- 抓取工具與匯率函式 -------- #

def safe_request(url: str):
    try:
        res = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        res.raise_for_status()
        return BeautifulSoup(res.text, "html.parser")
    except Exception as e:
        print(f"[safe_request] 讀取 {url} 失敗: {e}")
        return None

def get_usd_max():
    soup = safe_request("https://www.twrates.com/bankrate/bot/usd/selltt.html")
    if not soup:
        return None
    for row in soup.select("table tr"):
        tds = row.find_all("td")
        if len(tds) >= 2 and "最高" in tds[0].text:
            return float(tds[1].text.strip().split()[0])

def get_usd_min():
    soup = safe_request("https://www.twrates.com/bankrate/bot/usd/selltt.html")
    if not soup:
        return None
    for row in soup.select("table tr"):
        tds = row.find_all("td")
        if len(tds) >= 2 and "最低" in tds[0].text:
            return float(tds[1].text.strip().split()[0])

def get_eur_max():
    soup = safe_request("https://www.twrates.com/bankrate/bot/eur/selltt.html")
    if not soup:
        return None
    for row in soup.select("table tr"):
        tds = row.find_all("td")
        if len(tds) >= 2 and "最高" in tds[0].text:
            return float(tds[1].text.strip().split()[0])

def get_eur_min():
    soup = safe_request("https://www.twrates.com/bankrate/bot/eur/selltt.html")
    if not soup:
        return None
    for row in soup.select("table tr"):
        tds = row.find_all("td")
        if len(tds) >= 2 and "最低" in tds[0].text:
            return float(tds[1].text.strip().split()[0])

def get_bot_exchange_rates():
    soup = safe_request("https://www.twrates.com/bankrate/bot.html")
    if not soup:
        return None, None
    eur = usd = None
    for row in soup.select("table tr"):
        tds = row.find_all("td")
        if len(tds) >= 5:
            label = tds[0].text.strip().lower()
            if "usd" in label:
                usd = {
                    "rate": float(tds[1].text),
                    "max": get_usd_max(),
                    "min": get_usd_min(),
                }
            elif "eur" in label:
                eur = {
                    "rate": float(tds[1].text),
                    "max": get_eur_max(),
                    "min": get_eur_min(),
                }
    return eur, usd

def get_esun_jpy_sell():
    soup = safe_request("https://www.twrates.com/bankrate/twesun.html")
    if not soup:
        return None
    for row in soup.select("table tr"):
        tds = row.find_all("td")
        if len(tds) >= 3 and "日圓" in tds[0].text:
            return float(tds[2].text.strip())

def get_esun_jpy_max():
    soup = safe_request("https://www.twrates.com/bankrate/twesun/jpy/selltt.html")
    if not soup:
        return None
    for row in soup.select("table tr"):
        tds = row.find_all("td")
        if len(tds) >= 2 and "最高" in tds[0].text:
            return float(tds[1].text.strip().split()[0])

def get_esun_jpy_min():
    soup = safe_request("https://www.twrates.com/bankrate/twesun/jpy/selltt.html")
    if not soup:
        return None
    for row in soup.select("table tr"):
        tds = row.find_all("td")
        if len(tds) >= 2 and "最低" in tds[0].text:
            return float(tds[1].text.strip().split()[0])

def get_twdbs_exchange_rates():
    soup = safe_request("https://www.twrates.com/bankrate/twdbs.html")
    if not soup:
        return None, None
    for row in soup.select("table tr"):
        tds = row.find_all("td")
        if len(tds) >= 5 and "jpy" in tds[0].text.lower():
            return {"rate": float(tds[1].text)}, float(tds[1].text)

# -------- 推播主流程 -------- #

def push_message():
    try:
        print(f"⏰ [push_message] 執行時間：{datetime.now(TZ)}")
        eur, usd = get_bot_exchange_rates()
        jpy, jpy_ntd = get_twdbs_exchange_rates()
        esun_jpy = get_esun_jpy_sell()
        esun_jpy_max = get_esun_jpy_max()
        esun_jpy_min = get_esun_jpy_min()

        now = datetime.now(TZ)
        if now.weekday() >= 5 or not (8 <= now.hour <= 17):
            print("⏱ 不在推播時間內，跳過。")
            return

        message = ""

        if usd:
            message += f"USD匯率（台灣銀行）：{usd['rate']:.4f}\n"
            message += f"📉 最高：{usd['max']:.4f} 最低：{usd['min']:.4f}\n\n"
        if eur:
            message += f"EUR匯率（台灣銀行）：{eur['rate']:.4f}\n"
            message += f"📉 最高：{eur['max']:.4f} 最低：{eur['min']:.4f}\n\n"
        if esun_jpy:
            message += f"JPY匯率（玉山賣出）：{esun_jpy:.4f}\n"
            message += f"📉 最高：{esun_jpy_max:.4f} 最低：{esun_jpy_min:.4f}\n"
            jpy_total = round(esun_jpy * 22_000_000)
            message += f"🌐 試算：22,000,000 日圓 ➜ 約 {jpy_total:,} 元（銀行賣出）\n\n"
        if jpy:
            message += f"JPY匯率（星展銀行）：{jpy['rate']:.4f}\n"
        if jpy_ntd:
            ntd = round(jpy_ntd * 1_779_442)
            message += f"🌐 試算：1,779,442 日圓 ➜ 約 {ntd:,} 元（銀行買入）"

        headers = {
            "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "to": TO_USER_ID,
            "messages": [{"type": "text", "text": message.strip()}]
        }
        response = requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
        print(f"✅ 推播成功: {response.status_code} | {response.text}")

    except Exception as e:
        err_msg = f"⚠️ 無法取得匯率資訊：{str(e)}"
        headers = {
            "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "to": TO_USER_ID,
            "messages": [{"type": "text", "text": err_msg}]
        }
        response = requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
        print(f"❌ 推播錯誤回報: {response.status_code} | {response.text}")

# -------- 自動排程設定（週一至週五 09:00 / 14:00） -------- #

scheduler = BackgroundScheduler(timezone=TZ)
scheduler.add_job(push_message, 'cron', day_of_week='mon-fri', hour='9,14', minute=0)
scheduler.start()
push_message()  # ➕ 加這行，首次啟動時就推播一次
atexit.register(lambda: scheduler.shutdown())

# -------- 手動觸發用路由 -------- #

@app.route("/trigger_push", methods=["GET"])
def trigger_push():
    print(f"🟢 [trigger_push] 手動觸發 at {datetime.now(TZ)}")
    push_message()
    return "Trigger pushed successfully"

@app.route('/')
def home():
    return "LINE BOT2 is alive.", 200

@app.route("/ping")
def ping():
    return "pong", 200

if __name__ == "__main__":
    app.run(debug=False, use_reloader=False)
