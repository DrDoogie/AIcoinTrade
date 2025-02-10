import requests
import json
import datetime
from pytz import timezone
import time
import yaml
import pandas as pd  # 이 줄을 추가

with open('config.yaml', encoding='UTF-8') as f:
    _cfg = yaml.load(f, Loader=yaml.FullLoader)
APP_KEY = _cfg['APP_KEY']
APP_SECRET = _cfg['APP_SECRET']
ACCESS_TOKEN = ""
CANO = _cfg['CANO']
ACNT_PRDT_CD = _cfg['ACNT_PRDT_CD']
DISCORD_WEBHOOK_URL = _cfg['DISCORD_WEBHOOK_URL']
URL_BASE = _cfg['URL_BASE']

def send_message(msg):
    """디스코드 메세지 전송"""
    now = datetime.datetime.now()
    message = {"content": f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {str(msg)}"}
    requests.post(DISCORD_WEBHOOK_URL, data=message)
    print(message)

def get_access_token():
    """토큰 발급"""
    headers = {"content-type":"application/json"}
    body = {"grant_type":"client_credentials",
    "appkey":APP_KEY, 
    "appsecret":APP_SECRET}
    PATH = "oauth2/tokenP"
    URL = f"{URL_BASE}/{PATH}"
    res = requests.post(URL, headers=headers, data=json.dumps(body))
    ACCESS_TOKEN = res.json()["access_token"]
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
    """미국 주식 거래 시간인지 확인 (미국 동부시간 기준)"""
    nyse_time = datetime.datetime.now(timezone('America/New_York'))  # 뉴욕 시간
    
    # 주말 체크
    if nyse_time.weekday() >= 5:
        send_message(f"미국 현재 시간: {nyse_time.strftime('%Y-%m-%d %H:%M')} - 주말")
        return False
        
    # 거래 시간 설정 (뉴욕 시간 09:30 ~ 16:00)
    market_start = nyse_time.replace(hour=9, minute=30, second=0, microsecond=0)
    market_end = nyse_time.replace(hour=16, minute=0, second=0, microsecond=0)
    
    # 거래 시간 체크
    if market_start <= nyse_time <= market_end:
        return True
    else:
        kr_time = datetime.datetime.now(timezone('Asia/Seoul'))  # 한국 시간
        send_message(f"미국 현재 시간: {nyse_time.strftime('%Y-%m-%d %H:%M')} - 거래시간 아님 (한국 시간: {kr_time.strftime('%Y-%m-%d %H:%M')})")
        return False

def wait_for_market_open():
    """다음 거래 시작 시간까지 대기 (미국 동부시간 기준)"""
    nyse_time = datetime.datetime.now(timezone('America/New_York'))
    kr_time = datetime.datetime.now(timezone('Asia/Seoul'))
    
    if nyse_time.weekday() >= 5:  # 주말인 경우
        # 다음 월요일 시작시간 계산
        days_until_monday = (7 - nyse_time.weekday())
        next_market = nyse_time + timedelta(days=days_until_monday)
    else:
        # 오늘 또는 다음 날 시작시간 계산
        if nyse_time.hour >= 16:  # 장 마감 후
            next_market = nyse_time + timedelta(days=1)
        else:
            next_market = nyse_time
            
    next_market = next_market.replace(hour=9, minute=30, second=0, microsecond=0)
    
    wait_seconds = (next_market - nyse_time).total_seconds()
    if wait_seconds > 0:
        send_message(f"다음 거래 시작까지 대기합니다.\n"
                    f"미국 현재 시간: {nyse_time.strftime('%Y-%m-%d %H:%M')}\n"
                    f"한국 현재 시간: {kr_time.strftime('%Y-%m-%d %H:%M')}\n"
                    f"다음 거래 시작: {next_market.strftime('%Y-%m-%d %H:%M')} (미국 동부시간)")
        time.sleep(wait_seconds)

def get_current_price(market="NYSE", code="IONQ"):
    """현재가 조회"""
    PATH = "uapi/overseas-price/v1/quotations/price"
    URL = f"{URL_BASE}/{PATH}"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "tr_id": "HHDFS00000300"
    }
    params = {
        "AUTH": "",
        "EXCD": market,
        "SYMB": code,
    }
    try:
        res = requests.get(URL, headers=headers, params=params)
        res_json = res.json()
        
        if res_json['rt_cd'] != '0':
            print(f"API 오류: {res_json['msg1']}")
            return None
            
        if 'output' not in res_json:
            print("API 응답에 output이 없습니다")
            return None
            
        output = res_json['output']
        if not output.get('last'):  # 'last' 값이 비어있는 경우
            print("현재 거래시간이 아니거나 가격 정보를 받아올 수 없습니다.")
            return None
            
        return float(output['last'])
        
    except Exception as e:
        print(f"현재가 조회 중 오류 발생: {e}")
        return None

def get_target_price(market="NYSE", code="IONQ"):
    """변동성 돌파 전략으로 매수 목표가 조회"""
    PATH = "uapi/overseas-price/v1/quotations/dailyprice"
    URL = f"{URL_BASE}/{PATH}"
    headers = {"Content-Type":"application/json", 
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appKey":APP_KEY,
        "appSecret":APP_SECRET,
        "tr_id":"HHDFS76240000"}
    params = {
        "AUTH":"",
        "EXCD":market,
        "SYMB":code,
        "GUBN":"0",
        "BYMD":"",
        "MODP":"0"
    }
    res = requests.get(URL, headers=headers, params=params)
    stck_oprc = float(res.json()['output2'][0]['open']) #오늘 시가
    stck_hgpr = float(res.json()['output2'][1]['high']) #전일 고가
    stck_lwpr = float(res.json()['output2'][1]['low']) #전일 저가
    target_price = stck_oprc + (stck_hgpr - stck_lwpr) * 0.5
    return target_price

def get_stock_balance():
    """주식 잔고조회"""
    PATH = "uapi/overseas-stock/v1/trading/inquire-balance"
    URL = f"{URL_BASE}/{PATH}"
    headers = {"Content-Type":"application/json", 
        "authorization":f"Bearer {ACCESS_TOKEN}",
        "appKey":APP_KEY,
        "appSecret":APP_SECRET,
        "tr_id":"JTTT3012R",
        "custtype":"P"
    }
    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "OVRS_EXCG_CD": "NYSE",
        "TR_CRCY_CD": "USD",
        "CTX_AREA_FK200": "",
        "CTX_AREA_NK200": ""
    }
    res = requests.get(URL, headers=headers, params=params)
    stock_list = res.json()['output1']
    evaluation = res.json()['output2']
    stock_dict = {}
    send_message(f"====주식 보유잔고====")
    for stock in stock_list:
        if int(stock['ovrs_cblc_qty']) > 0:
            stock_dict[stock['ovrs_pdno']] = stock['ovrs_cblc_qty']
            send_message(f"{stock['ovrs_item_name']}({stock['ovrs_pdno']}): {stock['ovrs_cblc_qty']}주")
            time.sleep(0.1)
    send_message(f"주식 평가 금액: ${evaluation['tot_evlu_pfls_amt']}")
    time.sleep(0.1)
    send_message(f"평가 손익 합계: ${evaluation['ovrs_tot_pfls']}")
    time.sleep(0.1)
    send_message(f"=================")
    return stock_dict

def get_balance():
    """현금 잔고조회"""
    PATH = "uapi/domestic-stock/v1/trading/inquire-psbl-order"
    URL = f"{URL_BASE}/{PATH}"
    headers = {"Content-Type":"application/json", 
        "authorization":f"Bearer {ACCESS_TOKEN}",
        "appKey":APP_KEY,
        "appSecret":APP_SECRET,
        "tr_id":"TTTC8908R",
        "custtype":"P",
    }
    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "PDNO": "005930",
        "ORD_UNPR": "65500",
        "ORD_DVSN": "01",
        "CMA_EVLU_AMT_ICLD_YN": "Y",
        "OVRS_ICLD_YN": "Y"
    }
    res = requests.get(URL, headers=headers, params=params)
    cash = res.json()['output']['ord_psbl_cash']
    send_message(f"주문 가능 현금 잔고: {cash}원")
    return int(cash)




def buy(market="NYSE", code="IONQ", qty="1", price="0"):
    """미국 주식 지정가 매수"""
    PATH = "uapi/overseas-stock/v1/trading/order"
    URL = f"{URL_BASE}/{PATH}"
    data = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "OVRS_EXCG_CD": market,
        "PDNO": code,
        "ORD_DVSN": "00",
        "ORD_QTY": str(int(qty)),
        "OVRS_ORD_UNPR": f"{round(price,2)}",
        "ORD_SVR_DVSN_CD": "0"
    }
    headers = {"Content-Type":"application/json", 
        "authorization":f"Bearer {ACCESS_TOKEN}",
        "appKey":APP_KEY,
        "appSecret":APP_SECRET,
        "tr_id":"JTTT1002U",
        "custtype":"P",
        "hashkey" : hashkey(data)
    }
    res = requests.post(URL, headers=headers, data=json.dumps(data))
    if res.json()['rt_cd'] == '0':
        send_message(f"[매수 성공]{str(res.json())}")
        return True
    else:
        send_message(f"[매수 실패]{str(res.json())}")
        return False

def sell(market="NYSE", code="IONQ", qty="1", price="0"):
    """미국 주식 지정가 매도"""
    PATH = "uapi/overseas-stock/v1/trading/order"
    URL = f"{URL_BASE}/{PATH}"
    data = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "OVRS_EXCG_CD": market,
        "PDNO": code,
        "ORD_DVSN": "00",
        "ORD_QTY": str(int(qty)),
        "OVRS_ORD_UNPR": f"{round(price,2)}",
        "ORD_SVR_DVSN_CD": "0"
    }
    headers = {"Content-Type":"application/json", 
        "authorization":f"Bearer {ACCESS_TOKEN}",
        "appKey":APP_KEY,
        "appSecret":APP_SECRET,
        "tr_id":"JTTT1006U",
        "custtype":"P",
        "hashkey" : hashkey(data)
    }
    res = requests.post(URL, headers=headers, data=json.dumps(data))
    if res.json()['rt_cd'] == '0':
        send_message(f"[매도 성공]{str(res.json())}")
        return True
    else:
        send_message(f"[매도 실패]{str(res.json())}")
        return False

def get_exchange_rate():
    """환율 조회"""
    PATH = "uapi/overseas-stock/v1/trading/inquire-present-balance"
    URL = f"{URL_BASE}/{PATH}"
    headers = {"Content-Type":"application/json", 
            "authorization": f"Bearer {ACCESS_TOKEN}",
            "appKey":APP_KEY,
            "appSecret":APP_SECRET,
            "tr_id":"CTRP6504R"}
    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "OVRS_EXCG_CD": "NYSE",
        "WCRC_FRCR_DVSN_CD": "01",
        "NATN_CD": "840",
        "TR_MKET_CD": "01",
        "INQR_DVSN_CD": "00"
    }
    res = requests.get(URL, headers=headers, params=params)
    exchange_rate = 1270.0
    if len(res.json()['output2']) > 0:
        exchange_rate = float(res.json()['output2'][0]['frst_bltn_exrt'])
    return exchange_rate

def get_minute_data(market="NYSE", code="IONQ"):
    """30분봉 데이터 조회"""
    PATH = "/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
    URL = f"{URL_BASE}/{PATH}"
    
    params = {
        "AUTH": "",
        "EXCD": market,
        "SYMB": code,
        "NMIN": "30",  # 30분봉
        "PINC": "1",
        "NEXT": "",
        "NREC": "120",
        "FILL": "Y"
    }
    
    headers = {
        'content-type': 'application/json',
        'authorization': f'Bearer {ACCESS_TOKEN}',
        'appkey': APP_KEY,
        'appsecret': APP_SECRET,
        'tr_id': 'HHDFS76950200'
    }
    
    res = requests.get(URL, headers=headers, params=params)
    if res.status_code == 200:
        return res.json()
    return None


def calculate_rsi(data, periods=14):
    """RSI 계산"""
    try:
        if 'output2' not in data:
            print("데이터 구조 확인:", data)
            return 50

        df = pd.DataFrame(data['output2'])
        if len(df) == 0:
            return 50

        # 종가(Close) 필드 확인 및 설정
        price_columns = ['stck_prpr', 'ovrs_nmix_prpr', 'close', 'last']
        price_col = None
        for col in price_columns:
            if col in df.columns:
                price_col = col
                break

        if price_col is None:
            print("가격 데이터 컬럼을 찾을 수 없습니다:", df.columns)
            return 50

        # 가격 데이터 변환
        df['price'] = pd.to_numeric(df[price_col], errors='coerce')
        df = df.sort_values('xymd').reset_index(drop=True)
        
        # 결측치 제거
        df = df.dropna(subset=['price'])
        
        if len(df) < periods:
            print(f"충분한 데이터가 없습니다. (필요: {periods}, 현재: {len(df)})")
            return 50
            
        # 가격 변화 계산
        delta = df['price'].diff()
        gain = (delta.where(delta > 0, 0))
        loss = (-delta.where(delta < 0, 0))
        
        # 평균 계산
        avg_gain = gain.rolling(window=periods).mean()
        avg_loss = loss.rolling(window=periods).mean()
        
        # RSI 계산
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        final_rsi = rsi.iloc[-1] if not rsi.empty else 50
        
        return final_rsi

    except Exception as e:
        print(f"RSI 계산 중 오류 발생: {e}")
        return 50
    





    

def debug_api_response(market="NYSE", code="IONQ"):
    """API 응답 데이터 출력"""
    response = get_minute_data(market, code)
    print("API 응답 데이터:", json.dumps(response, indent=4, ensure_ascii=False))
    return response

## 클러드내용 추가

def get_minute_data(market="NYSE", code="IONQ"):
    """30분봉 데이터 조회"""
    PATH = "/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
    URL = f"{URL_BASE}/{PATH}"
    
    params = {
        "AUTH": "",
        "EXCD": market,
        "SYMB": code,
        "NMIN": "30",  # 30분봉
        "PINC": "1",
        "NEXT": "",
        "NREC": "120",
        "FILL": "Y"
    }
    
    headers = {
        'content-type': 'application/json',
        'authorization': f'Bearer {ACCESS_TOKEN}',
        'appkey': APP_KEY,
        'appsecret': APP_SECRET,
        'tr_id': 'HHDFS76950200'
    }
    
    res = requests.get(URL, headers=headers, params=params)
    if res.status_code == 200:
        return res.json()
    return None


def get_current_rsi(market="NYSE", code="IONQ", periods=14):
    """현재 RSI 값 조회"""
    data = get_minute_data(market, code)
    if data is not None:
        return calculate_rsi(data, periods)
    return 50  # 데이터 조회 실패시 중립값 반환

def get_current_profit_loss():
    """현재 수익률 계산"""
    try:
        PATH = "uapi/overseas-stock/v1/trading/inquire-balance"
        URL = f"{URL_BASE}/{PATH}"
        headers = {"Content-Type":"application/json", 
            "authorization":f"Bearer {ACCESS_TOKEN}",
            "appKey":APP_KEY,
            "appSecret":APP_SECRET,
            "tr_id":"JTTT3012R",
            "custtype":"P"
        }
        params = {
            "CANO": CANO,
            "ACNT_PRDT_CD": ACNT_PRDT_CD,
            "OVRS_EXCG_CD": "NYSE",
            "TR_CRCY_CD": "USD",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": ""
        }
        res = requests.get(URL, headers=headers, params=params)
        evaluation = res.json()['output2']
        profit_loss = float(evaluation['ovrs_tot_pfls'])
        total_amount = float(evaluation['tot_evlu_pfls_amt'])
        if total_amount != 0:
            profit_loss_rate = (profit_loss / total_amount) * 100
            return profit_loss_rate
        return 0
    except Exception as e:
        print(f"수익률 계산 중 오류: {e}")
        return 0


# 메인 로직
try:
    ACCESS_TOKEN = get_access_token()
    nyse_symbol_list = ["IONQ"]
    bought_list = []
    total_cash = get_balance()
    stock_dict = get_stock_balance()
    
    for sym in stock_dict.keys():
        bought_list.append(sym)

    send_message("===RSI 기반 해외 주식 자동매매 프로그램을 시작합니다===")
    
    while True:
        # 거래 시간 체크
        if not is_market_time():
            wait_for_market_open()
            # 새로운 거래일 시작 시 토큰 재발급
            ACCESS_TOKEN = get_access_token()
            continue

        # 현재 수익률 확인
        current_profit = get_current_profit_loss()
        if current_profit >= 5.0:
            send_message(f"목표 수익률 달성! (현재 수익률: {current_profit:.2f}%)")
            stock_dict = get_stock_balance()
            for sym, qty in stock_dict.items():
                sell(market="NYSE", code=sym, qty=qty, price=get_current_price("NYSE", sym))
            # 거래일 종료 후 다음 거래일까지 대기
            wait_for_market_open()
            continue
            
        elif current_profit <= -5.0:
            send_message(f"손절 수익률 도달! (현재 수익률: {current_profit:.2f}%)")
            stock_dict = get_stock_balance()
            for sym, qty in stock_dict.items():
                sell(market="NYSE", code=sym, qty=qty, price=get_current_price("NYSE", sym))
            # 거래일 종료 후 다음 거래일까지 대기
            wait_for_market_open()
            continue

        # 30분마다 RSI 체크 및 매매
        t_now = datetime.datetime.now(timezone('America/New_York'))
        if t_now.minute % 30 == 0 and t_now.second <= 5:
            for sym in nyse_symbol_list:
                current_rsi = get_current_rsi("NYSE", sym)
                if current_rsi is None:
                    continue
                    
                current_price = get_current_price("NYSE", sym)
                if current_price is None:
                    continue
                
                send_message(f"{sym} 현재 RSI: {current_rsi:.2f}")
                
                # 매수 조건: RSI 30 이하 (과매도)
                if current_rsi <= 30 and sym not in bought_list:
                    buy_amount = total_cash * 0.33
                    buy_qty = int(buy_amount / current_price)
                    if buy_qty > 0:
                        send_message(f"{sym} 매수 시도 (RSI: {current_rsi:.2f})")
                        result = buy(market="NYSE", code=sym, qty=buy_qty, price=current_price)
                        if result:
                            bought_list.append(sym)
                
                # 매도 조건: RSI 70 이상 (과매수)
                elif current_rsi >= 70 and sym in bought_list:
                    stock_dict = get_stock_balance()
                    if sym in stock_dict:
                        send_message(f"{sym} 매도 시도 (RSI: {current_rsi:.2f})")
                        sell(market="NYSE", code=sym, qty=stock_dict[sym], price=current_price)
                        bought_list.remove(sym)

        time.sleep(1)

except Exception as e:
    send_message(f"[오류 발생]{str(e)}")
    time.sleep(1)

try:
    ACCESS_TOKEN = get_access_token()

    nyse_symbol_list = ["IONQ"] # 매수 희망 종목 리스트
    bought_list = [] # 매수 완료된 종목 리스트
    total_cash = get_balance() # 보유 현금 조회
    stock_dict = get_stock_balance() # 보유 주식 조회
    for sym in stock_dict.keys():
        bought_list.append(sym)

    send_message("===RSI 기반 해외 주식 자동매매 프로그램을 시작합니다===")
    
    while True:
        # 거래 시간 체크
        if not is_market_time():
            wait_for_market_open()
            # 새로운 거래일 시작 시 토큰 재발급
            ACCESS_TOKEN = get_access_token()
            continue

        nyse_time = datetime.datetime.now(timezone('America/New_York'))
        if nyse_time.weekday() == 5 or nyse_time.weekday() == 6:
            send_message("미국 주말이므로 프로그램을 종료합니다.")
            break

        # 현재 수익률 확인
        current_profit = get_current_profit_loss()
        if current_profit >= 5.0:
            send_message(f"목표 수익률 달성! (현재 수익률: {current_profit:.2f}%)")
            stock_dict = get_stock_balance()
            for sym, qty in stock_dict.items():
                sell(market="NYSE", code=sym, qty=qty, price=get_current_price("NYSE", sym))
            wait_for_market_open()
            continue
        elif current_profit <= -5.0:
            send_message(f"손절 수익률 도달! (현재 수익률: {current_profit:.2f}%)")
            stock_dict = get_stock_balance()
            for sym, qty in stock_dict.items():
                sell(market="NYSE", code=sym, qty=qty, price=get_current_price("NYSE", sym))
            wait_for_market_open()
            continue

        # 30분마다 RSI 체크 및 매매
        if nyse_time.minute % 30 == 0 and nyse_time.second <= 5:
            for sym in nyse_symbol_list:
                current_rsi = get_current_rsi("NYSE", sym)
                if current_rsi is None:
                    continue
                    
                current_price = get_current_price("NYSE", sym)
                if current_price is None:
                    continue
                
                kr_time = datetime.datetime.now(timezone('Asia/Seoul'))
                send_message(f"[미국 시간 {nyse_time.strftime('%H:%M')} / 한국 시간 {kr_time.strftime('%H:%M')}]")
                send_message(f"{sym} 현재 RSI: {current_rsi:.2f}")
                
                # 매수 조건: RSI 30 이하 (과매도)
                if current_rsi <= 30 and sym not in bought_list:
                    buy_amount = total_cash * 0.33  # 보유 현금의 33%
                    buy_qty = int(buy_amount / current_price)
                    if buy_qty > 0:
                        send_message(f"{sym} 매수 시도 (RSI: {current_rsi:.2f})")
                        result = buy(market="NYSE", code=sym, qty=buy_qty, price=current_price)
                        if result:
                            bought_list.append(sym)
                            get_stock_balance()
                
                # 매도 조건: RSI 70 이상 (과매수)
                elif current_rsi >= 70 and sym in bought_list:
                    stock_dict = get_stock_balance()
                    if sym in stock_dict:
                        send_message(f"{sym} 매도 시도 (RSI: {current_rsi:.2f})")
                        result = sell(market="NYSE", code=sym, qty=stock_dict[sym], price=current_price)
                        if result:
                            bought_list.remove(sym)
                            get_stock_balance()

        # 프로그램 종료 시간 체크 (미국 동부시간 16:00)
        if nyse_time.hour >= 16:
            send_message("미국 장 마감으로 프로그램을 종료합니다.")
            wait_for_market_open()
            continue

        time.sleep(1)

except Exception as e:
    send_message(f"[오류 발생]{str(e)}")
    time.sleep(1)
    
# try:
#     ACCESS_TOKEN = get_access_token()

#     #NYSEd_symbol_list = ["IONQ"] # 매수 희망 종목 리스트 (NYSE)
#     nyse_symbol_list = ["IONQ"] # 매수 희망 종목 리스트 (NYSE)
#     #amex_symbol_list = ["LIT"] # 매수 희망 종목 리스트 (AMEX)



#     bought_list = [] # 매수 완료된 종목 리스트
#     total_cash = get_balance() # 보유 현금 조회
#     stock_dict = get_stock_balance() # 보유 주식 조회
#     for sym in stock_dict.keys():
#         bought_list.append(sym)

#     send_message("===RSI 기반 해외 주식 자동매매 프로그램을 시작합니다===")
    
#     while True:
#         t_now = datetime.datetime.now(timezone('America/New_York'))
#         if t_now.weekday() == 5 or t_now.weekday() == 6:
#             send_message("주말이므로 프로그램을 종료합니다.")
#             break

#         # 현재 수익률 확인
#         current_profit = get_current_profit_loss()
#         if current_profit >= 5.0:
#             send_message(f"목표 수익률 달성! (현재 수익률: {current_profit:.2f}%)")
#             stock_dict = get_stock_balance()
#             for sym, qty in stock_dict.items():
#                 sell(market="NYSE", code=sym, qty=qty, price=get_current_price("NYSE", sym))
#             break
#         elif current_profit <= -5.0:
#             send_message(f"손절 수익률 도달! (현재 수익률: {current_profit:.2f}%)")
#             stock_dict = get_stock_balance()
#             for sym, qty in stock_dict.items():
#                 sell(market="NYSE", code=sym, qty=qty, price=get_current_price("NYSE", sym))
#             break

#         # 30분마다 RSI 체크 및 매매
#         if t_now.minute % 1 == 0 and t_now.second <= 5:
#             for sym in nyse_symbol_list:
#                 current_rsi = get_current_rsi("NYSE", sym)
#                 current_price = get_current_price("NYSE", sym)
                
#                 send_message(f"{sym} 현재 RSI: {current_rsi:.2f}")
                
#                 # 매수 조건: RSI 30 이하 (과매도)
#                 if current_rsi <= 30 and sym not in bought_list:
#                     buy_amount = total_cash * 0.33  # 보유 현금의 33%
#                     buy_qty = int(buy_amount / current_price)
#                     if buy_qty > 0:
#                         send_message(f"{sym} 매수 시도 (RSI: {current_rsi:.2f})")
#                         result = buy(market="NYSE", code=sym, qty=buy_qty, price=current_price)
#                         if result:
#                             bought_list.append(sym)
                
#                 # 매도 조건: RSI 70 이상 (과매수)
#                 elif current_rsi >= 70 and sym in bought_list:
#                     stock_dict = get_stock_balance()
#                     if sym in stock_dict:
#                         send_message(f"{sym} 매도 시도 (RSI: {current_rsi:.2f})")
#                         sell(market="NYSE", code=sym, qty=stock_dict[sym], price=current_price)
#                         bought_list.remove(sym)

#             time.sleep(1)

#         # 프로그램 종료 시간
#         if t_now.hour >= 15 and t_now.minute >= 45:
#             send_message("장 마감 임박으로 프로그램을 종료합니다.")
#             break

#         time.sleep(1)

# except Exception as e:
#     send_message(f"[오류 발생]{str(e)}")
#     time.sleep(1)



# # 자동매매 시작
# try:
#     ACCESS_TOKEN = get_access_token()

#     NYSEd_symbol_list = ["IONQ"] # 매수 희망 종목 리스트 (NYSE)
#     nyse_symbol_list = ["KO"] # 매수 희망 종목 리스트 (NYSE)
#     amex_symbol_list = ["LIT"] # 매수 희망 종목 리스트 (AMEX)
#     symbol_list = NYSEd_symbol_list + nyse_symbol_list + amex_symbol_list
#     bought_list = [] # 매수 완료된 종목 리스트
#     total_cash = get_balance() # 보유 현금 조회
#     exchange_rate = get_exchange_rate() # 환율 조회
#     stock_dict = get_stock_balance() # 보유 주식 조회
#     for sym in stock_dict.keys():
#         bought_list.append(sym)
#     target_buy_count = 3 # 매수할 종목 수
#     buy_percent = 0.33 # 종목당 매수 금액 비율
#     buy_amount = total_cash * buy_percent / exchange_rate # 종목별 주문 금액 계산 (달러)
#     soldout = False

#     send_message("===해외 주식 자동매매 프로그램을 시작합니다===")
#     while True:
#         t_now = datetime.datetime.now(timezone('America/New_York')) # 뉴욕 기준 현재 시간
#         t_9 = t_now.replace(hour=9, minute=30, second=0, microsecond=0)
#         t_start = t_now.replace(hour=9, minute=35, second=0, microsecond=0)
#         t_sell = t_now.replace(hour=15, minute=45, second=0, microsecond=0)
#         t_exit = t_now.replace(hour=15, minute=50, second=0,microsecond=0)
#         today = t_now.weekday()
#         if today == 5 or today == 6:  # 토요일이나 일요일이면 자동 종료
#             send_message("주말이므로 프로그램을 종료합니다.")
#             break
#         if t_9 < t_now < t_start and soldout == False: # 잔여 수량 매도
#             for sym, qty in stock_dict.items():
#                 market1 = "NYSE"
#                 market2 = "NYSE"
#                 if sym in nyse_symbol_list:
#                     market1 = "NYSE"
#                     market2 = "NYS"
#                 if sym in amex_symbol_list:
#                     market1 = "AMEX"
#                     market2 = "AMS"
#                 sell(market=market1, code=sym, qty=qty, price=get_current_price(market=market2, code=sym))
#             soldout == True
#             bought_list = []
#             time.sleep(1)
#             stock_dict = get_stock_balance()
#         if t_start < t_now < t_sell :  # AM 09:35 ~ PM 03:45 : 매수
#             for sym in symbol_list:
#                 if len(bought_list) < target_buy_count:
#                     if sym in bought_list:
#                         continue
#                     market1 = "NYSE"
#                     market2 = "NYSE"
#                     if sym in nyse_symbol_list:
#                         market1 = "NYSE"
#                         market2 = "NYS"
#                     if sym in amex_symbol_list:
#                         market1 = "AMEX"
#                         market2 = "AMS"
#                     target_price = get_target_price(market2, sym)
#                     current_price = get_current_price(market2, sym)
#                     if target_price < current_price:
#                         buy_qty = 0  # 매수할 수량 초기화
#                         buy_qty = int(buy_amount // current_price)
#                         if buy_qty > 0:
#                             send_message(f"{sym} 목표가 달성({target_price} < {current_price}) 매수를 시도합니다.")
#                             market = "NYSE"
#                             if sym in nyse_symbol_list:
#                                 market = "NYSE"
#                             if sym in amex_symbol_list:
#                                 market = "AMEX"
#                             result = buy(market=market1, code=sym, qty=buy_qty, price=get_current_price(market=market2, code=sym))
#                             time.sleep(1)
#                             if result:
#                                 soldout = False
#                                 bought_list.append(sym)
#                                 get_stock_balance()
#                     time.sleep(1)
#             time.sleep(1)
#             if t_now.minute == 30 and t_now.second <= 5: 
#                 get_stock_balance()
#                 time.sleep(5)
#         if t_sell < t_now < t_exit:  # PM 03:45 ~ PM 03:50 : 일괄 매도
#             if soldout == False:
#                 stock_dict = get_stock_balance()
#                 for sym, qty in stock_dict.items():
#                     market1 = "NYSE"
#                     market2 = "NYSE"
#                     if sym in nyse_symbol_list:
#                         market1 = "NYSE"
#                         market2 = "NYS"
#                     if sym in amex_symbol_list:
#                         market1 = "AMEX"
#                         market2 = "AMS"
#                     sell(market=market1, code=sym, qty=qty, price=get_current_price(market=market2, code=sym))
#                 soldout = True
#                 bought_list = []
#                 time.sleep(1)
#         if t_exit < t_now:  # PM 03:50 ~ :프로그램 종료
#             send_message("프로그램을 종료합니다.")
#             break
# except Exception as e:
#     send_message(f"[오류 발생]{e}")
#     time.sleep(1)