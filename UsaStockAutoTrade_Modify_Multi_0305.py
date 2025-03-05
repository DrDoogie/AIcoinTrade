import pandas as pd
import numpy as np
import requests
import json
import time
from datetime import datetime, timedelta
from pytz import timezone
import yaml

# 설정 파일 로드
with open('config.yaml', encoding='UTF-8') as f:
    _cfg = yaml.load(f, Loader=yaml.FullLoader)
APP_KEY = _cfg['APP_KEY']
APP_SECRET = _cfg['APP_SECRET']
ACCESS_TOKEN = ""
CANO = _cfg['CANO']
ACNT_PRDT_CD = _cfg['ACNT_PRDT_CD']
DISCORD_WEBHOOK_URL = _cfg['DISCORD_WEBHOOK_URL']
URL_BASE = _cfg['URL_BASE']

# 거래소 및 종목 리스트
MARKET = "NASD"
EXCD_MARKET = "NAS"
SYMBOLS = ["PLTR", "NVDA"]  # ✅ 여러 종목 처리

# 메세지 전송 함수
def send_message(msg):
    now = datetime.now()
    message = {"content": f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {str(msg)}"}
    requests.post(DISCORD_WEBHOOK_URL, data=message)
    print(message)

def get_access_token():
    global ACCESS_TOKEN  #GPT 수정 내용 
    """토큰 발급"""
    headers = {"content-type":"application/json"}
    body = {"grant_type":"client_credentials",
    "appkey":APP_KEY, 
    "appsecret":APP_SECRET}
    PATH = "oauth2/tokenP"
    URL = f"{URL_BASE}/{PATH}"
    res = requests.post(URL, headers=headers, data=json.dumps(body))
    ACCESS_TOKEN = res.json()["access_token"]
    #print(f"새로운 토큰 발급: {ACCESS_TOKEN}")
    print(f"새로운 토큰 발급")
    return ACCESS_TOKEN

def hashkey(datas):
    """암호화"""
    PATH = "uapi/hashkey"
    URL = f"{URL_BASE}/{PATH}"
    headers = {
    'content-Type' : 'application/json',
    'appKey' : APP_KEY,
    'appSecret' : APP_SECRET,
    }
    res = requests.post(URL, headers=headers, data=json.dumps(datas))
    hashkey = res.json()["HASH"]
    return hashkey

def is_market_time():
    """미국 시장 시간 체크 (개선된 버전)"""
    NAS_time = datetime.now(timezone('America/New_York'))
    KST_time = datetime.now(timezone('Asia/Seoul'))
    print(f"현재 미국시간: {NAS_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"현재 한국시간: {KST_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    if NAS_time.weekday() >= 5:
        print("주말 - 시장 닫힘")
        return False
        
    market_start = NAS_time.replace(hour=9, minute=30, second=0, microsecond=0)
    market_end = NAS_time.replace(hour=16, minute=0, second=0, microsecond=0)
    is_market_open = market_start <= NAS_time <= market_end
    
    print(f"시장 개장 상태: {'열림' if is_market_open else '닫힘'}")
    return is_market_open

def wait_for_market_open():
    """시장 개장 대기 (개선된 버전)"""
    send_message("미국 시장이 닫혀 있습니다. 개장까지 대기합니다...")
    
    while not is_market_time():
        nas_time = datetime.now(timezone('America/New_York'))
        next_check = 5 if nas_time.hour >= 9 else 60  # 개장 시간 근처면 더 자주 체크
        send_message(f"다음 확인까지 {next_check}분 대기...")
        time.sleep(next_check * 60)
    send_message("미국 시장이 개장되었습니다!")
    refresh_token()  # 시장 개장 시 토큰 갱신

#분봉 데이터 가져오기기
def get_minute_data(nmin=30, period=2, access_token=""):  #period=5 -> 2
    """분봉 데이터 조회 (전역 변수 사용)"""
    print(f"분봉 데이터 조회 시작 - 종목: {SYMBOL}, 시간간격: {nmin}분")
    PATH = "/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
    URL = f"{URL_BASE}/{PATH}"
    
    all_data = []
    next_key = ""
    for _ in range(period):
        params = {
            "AUTH": "",
            "EXCD": EXCD_MARKET,
            "SYMB": SYMBOL,
            "NMIN": str(nmin),
            "PINC": "1",
            "NEXT": next_key,
            "NREC": "120",
            "FILL": "Y"
        }
     
        headers = {
            'content-type': 'application/json',
            'authorization': f'Bearer {access_token}',
            'appkey': APP_KEY,
            'appsecret': APP_SECRET,
            'tr_id': 'HHDFS76950200'
        }
        
        res = requests.get(URL, headers=headers, params=params)
        if res.status_code == 200:
            data = res.json()
            if "output2" in data and data["output2"]:
                all_data.extend(data["output2"])
                next_key = data.get("output1", {}).get("next", "")
                if not next_key:
                    break
            else:
                print(f"데이터 없음 - 요청 코드: {SYMBOL}, 거래소: {MARKET}")
                break
        else:
            print(f"API 호출 실패. 상태 코드: {res.status_code}, 응답 내용: {res.text}")
            break
        time.sleep(0.5)
    
    print(f"조회된 데이터 수: {len(all_data)}")
    return {"output2": all_data} if all_data else None


# RSI 조회 함수 (심볼을 받아서 개별 계산)
def get_current_rsi(symbol, periods=14, nmin=30):
    print(f"RSI 조회 시작: {symbol}")
    data = get_minute_data(symbol, nmin=nmin, access_token=ACCESS_TOKEN)
    rsi_value = calculate_rsi(data, periods)
    print(f"종목 {symbol}의 RSI 값: {rsi_value}")
    return rsi_value

# 현재가 조회 함수 (심볼 기반으로 조회)
def get_current_price(symbol):
    PATH = "uapi/overseas-price/v1/quotations/price"
    URL = f"{URL_BASE}/{PATH}"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "tr_id": "HHDFS00000300"
    }
    params = {"AUTH": "", "EXCD": EXCD_MARKET, "SYMB": symbol}
    res = requests.get(URL, headers=headers, params=params)
    res_json = res.json()
    return float(res_json['output']['last']) if 'output' in res_json else None

# 현금 잔고 조회 (잔고 반반 분배 가능하도록 수정)
def get_balance():
    PATH = "/uapi/overseas-stock/v1/trading/inquire-psamount"
    URL = f"{URL_BASE}/{PATH}"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "tr_id": "TTTS3007R",
        "custtype": "P",
    }
    params = {"CANO": CANO, "ACNT_PRDT_CD": ACNT_PRDT_CD, "OVRS_EXCG_CD": MARKET}
    res = requests.get(URL, headers=headers, params=params)
    res_data = res.json()
    cash = float(res_data['output'].get('ovrs_ord_psbl_amt', '0'))
    return cash

# 매수 함수 (종목별 매수 가능하도록 수정)
def buy(symbol, qty, price):
    PATH = "uapi/overseas-stock/v1/trading/order"
    URL = f"{URL_BASE}/{PATH}"
    data = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "OVRS_EXCG_CD": MARKET,
        "PDNO": symbol,
        "ORD_QTY": str(qty),
        "OVRS_ORD_UNPR": f"{price:.2f}",
        "ORD_SVR_DVSN_CD": "0",
        "ORD_DVSN": "00"
    }
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "tr_id": "TTTT1002U",
        "custtype": "P",
        "hashkey": hashkey(data)
    }
    res = requests.post(URL, headers=headers, data=json.dumps(data))
    return res.json()

# 메인 실행 로직
def main():
    global ACCESS_TOKEN
    ACCESS_TOKEN = get_access_token()
    while True:
        if not is_market_time():
            wait_for_market_open()
            continue

        # 두 종목의 RSI 조회
        rsi_values = {symbol: get_current_rsi(symbol) for symbol in SYMBOLS}
        current_prices = {symbol: get_current_price(symbol) for symbol in SYMBOLS}
        cash_balance = get_balance()
        buy_candidates = [s for s in SYMBOLS if rsi_values[s] <= 30]
        sell_candidates = [s for s in SYMBOLS if rsi_values[s] >= 70]
        
        if buy_candidates:
            cash_per_stock = cash_balance / len(buy_candidates)
            for symbol in buy_candidates:
                price = current_prices[symbol]
                qty = max(1, int(cash_per_stock / price))
                buy_result = buy(symbol, qty, price)
                send_message(f"✅ {symbol} {qty}주 매수 결과: {buy_result}")

        if sell_candidates:
            for symbol in sell_candidates:
                qty = get_stock_balance().get(symbol, 0)
                if qty > 0:
                    sell_result = sell(symbol, qty, current_prices[symbol])
                    send_message(f"✅ {symbol} {qty}주 매도 결과: {sell_result}")

        time.sleep(60)  # 1분 간격 실행

if __name__ == "__main__":
    main()
