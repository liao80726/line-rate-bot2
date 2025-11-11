import os
from time import time
from threading import Lock
from flask import Flask, request
import requests
from bs4 import BeautifulSoup
import pytz
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

# ---- 基本設定 ----
TZ = pytz.timezone("Asia/Taipei")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExchangeBot/1.0)"}
REQUEST_TIMEOUT = 10

# ---- 重要：請用環境變數，別把金鑰丟 GitHub ----
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
TO_USER_ID = os.getenv("LINE_TO_USER_ID", "")
TRIGGER_SECRET = os.getenv("TRIGGER_SECRET", "liao80726")
STARTUP_PUSH = os.getenv("STARTUP_PUSH", "false").lower() == "true"

# ---- 全域去重 + 互斥鎖（手動/排程同一個閘門）----
_LAST_PUSH_TS = 0
DEDUP_WINDOW_SEC = 180
_PUSH_LOCK = Lock()

def _allow_push_now():
    global _LAST_PUSH_TS
    now = time()
    if now - _LAST_PUSH_TS < DEDUP_WINDOW_SEC:
        return False
    _LAST_PUSH_TS = now
    return True

app = Flask(__name__)

# ----------- 抓取工具與匯率函式 ------------
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
    if not soup: return None
    for row in soup.select("table tr"):
        tds = row.find_all("td")
        if len(tds) >= 2 and "最高" in tds[0].text:
            return float(tds[1].text.strip().split()[0])

def get_usd_min():
    soup = safe_request("https://www.twrates.com/bankrate/bot/usd/selltt.html")
    if not soup: return None
    for row in soup.select("table tr"):
        tds = row.find_all("td")
        if len(tds) >= 2 and "最低" in tds[0].text:
            return float(tds[1].text.strip().split()[0])

def get_eur_max():
    soup = safe_request("https://www.twrates.com/bankrate/bot/eur/selltt.html")
    if not soup: return None
    for row in soup.select("table tr"):
        tds = row.find_all("td")
        if len(tds) >= 2 and "最高" in tds[0].text:
            return float(tds[1].text.strip().split()[0])

def get_eur_min():
    soup = safe_request("https://www.twrates.com/bankrate/bot/eur/selltt.html")
    if not soup: return None
    for row in soup.select("table tr"):
        tds = row.find_all("td")
        if len(tds) >= 2 and "最低" in tds[0].text:
            return float(tds[1].text.strip().split()[0])

def get_bot_exchange_rates():
    soup = safe_request("https://www.twrates.com/bankrate/bot.html")
    if not soup: return None, None
    eur = usd = None
    for row in soup.select("table tr"):
        tds = row.find_all("td")
        if len(tds) >= 5:
            label = tds[0].text.strip().lower()
            if "usd" in label:
                usd = {"rate": float(tds[1].text), "max": get_usd_max(), "min": get_usd_min()}
            elif "eur" in label:
                eur = {"rate": float(tds[1].text), "max": get_eur_max(), "min": get_eur_min()}
    return eur, usd

def get_esun_jpy_sell():
    soup = safe_request("https://www.twrates.com/bankrate/twesun.html")
    if not soup: return None
    for row in soup.select("table tr"):
        tds = row.find_all("td")
        if len(tds) >= 3 and "日圓" in tds[0].text:
            return float(tds[2].text.strip())

def get_esun_jpy_max():
    soup = safe_request("https://www.twrates.com/bankrate/twesun/jpy/selltt.html")
    if not soup: return None
    for row in soup.select("table tr"):
        tds = row.find_all("td")
        if len(tds) >= 2 and "最高" in tds[0].text:
            return float(tds[1].text.strip().split()[0])

def get_esun_jpy_min():
    soup = safe_request("https://www.twrates.com/bankrate/twesun/jpy/selltt.html")
    if not soup: return None
    for row in soup.select("table tr"):
        tds = row.find_all("td")
        if len(tds) >= 2 and "最低" in tds[0].text:
            return float(tds[1].text.strip().split()[0])

def get_twdbs_exchange_rates():
    soup = safe_request("https://www.twrates.com/bankrate/twdbs.html")
    if not soup: return None, None
    for row in soup.select("table tr"):
        tds = row.find_all("td")
        if len(tds) >= 5 and "jpy" in tds[0].text.lower():
            return {"rate": float(tds[1].text)}, float(tds[1].text)

# ----------- 推播主流程 ------------
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

        parts = []
        if usd:
            parts += [f"USD匯率（台灣銀行）：{usd['rate']:.4f}",
                      f"📉 最高：{usd['max']:.4f} 最低：{usd['min']:.4f}", ""]
        if eur:
            parts += [f"EUR匯率（台灣銀行）：{eur['rate']:.4f}",
                      f"📉 最高：{eur['max']:.4f} 最低：{eur['min']:.4f}", ""]
        if esun_jpy:
            parts += [f"JPY匯率（玉山賣出）：{esun_jpy:.4f}",
                      f"📉 最高：{esun_jpy_max:.4f} 最低：{esun_jpy_min:.4f}"]
            jpy_total = round(esun_jpy * 22_000_000)
            parts += [f"🌐 試算：22,000,000 日圓 ➜ 約 {jpy_total:,} 元（銀行賣出）", ""]
        if jpy:
            parts += [f"JPY匯率（星展銀行）：{jpy['rate']:.4f}"]
        if jpy_ntd:
            ntd = round(jpy_ntd * 1_779_442)
            parts += [f"🌐 試算：1,779,442 日圓 ➜ 約 {ntd:,} 元（銀行買入）"]

        message = "\n".join([p for p in parts if p is not None]).strip() or "⚠️ 無資料"

        if not CHANNEL_ACCESS_TOKEN or not TO_USER_ID:
            print("⚠️ 未設定 LINE 環境變數，跳過推播。")
            return

        headers = {"Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}", "Content-Type": "application/json"}
        payload = {"to": TO_USER_ID, "messages": [{"type": "text", "text": message}]}
        resp = requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
        print(f"✅ 推播成功: {resp.status_code} | {resp.text}")

    except Exception as e:
        err_msg = f"⚠️ 無法取得匯率資訊：{str(e)}"
        if CHANNEL_ACCESS_TOKEN and TO_USER_ID:
            headers = {"Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}", "Content-Type": "application/json"}
            payload = {"to": TO_USER_ID, "messages": [{"type": "text", "text": err_msg}]}
            resp = requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
            print(f"❌ 推播錯誤回報: {resp.status_code} | {resp.text}")
        else:
            print(err_msg)

def push_message_guarded():
    # 3 分鐘去重 + 互斥，擋掉手動/排程同時進入
    if not _allow_push_now():
        print("[guard] skipped: duplicate within 3min")
        return
    with _PUSH_LOCK:
        push_message()

# ----------- 排程（週一至週五 09:00 / 14:00） ------------
scheduler = BackgroundScheduler(
    timezone=TZ,
    job_defaults={
        "coalesce": True,          # 冷啟錯過多個只補一次
        "max_instances": 1,        # 不重疊
        "misfire_grace_time": 3600 # 補發窗拉到 1 小時
    }
)
scheduler.add_job(push_message_guarded, 'cron', day_of_week='mon-fri', hour='9,14', minute=0)
scheduler.start()

# 啟動即推（可選；僅在 STARTUP_PUSH=true）
if STARTUP_PUSH:
    push_message_guarded()

atexit.register(lambda: scheduler.shutdown())

# ----------- 路由（UptimeRobot 打 /healthz） ------------
@app.get("/healthz")
def healthz():
    return "ok", 200

@app.get("/diag")
def diag():
    jobs = scheduler.get_jobs()
    nxt = jobs[0].next_run_time.isoformat() if jobs else "no-jobs"
    now = datetime.now(TZ).isoformat()
    return {"now": now, "jobs": len(jobs), "next_run": nxt}, 200

# 只接受 POST 並驗證 Token（別再用瀏覽器 GET）
@app.post("/trigger_push")
def trigger_push():
    if request.headers.get("X-Trigger-Token") != TRIGGER_SECRET:
        return "unauthorized", 401
    push_message_guarded()
    return "queued", 202

@app.get("/")
def home():
    return "LINE 匯率推播機器人：ALIVE", 200

@app.get("/ping")
def ping():
    return "pong", 200

# ---- 本地啟動（Render 用 gunicorn）----
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False, use_reloader=False)
