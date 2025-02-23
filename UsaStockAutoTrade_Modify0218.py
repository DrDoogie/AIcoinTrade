import pandas as pd
import numpy as np
import requests
import json
import time
from datetime import datetime, timedelta
from pytz import timezone
import yaml


# OVRS_EXCG_CD
# # NASD : 나스닥 / NYSE : 뉴욕 / AMEX : 아멕스
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

# 거래소와 종목 전역 변수 설정
MARKET = "NYS" #NAS
SYMBOL = "IONQ"  #TSLA  #AAPL

def send_message(msg):
    """디스코드 메세지 전송"""
    now = datetime.now()
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
    #print(f"새로운 토큰 발급: {ACCESS_TOKEN}")
    print(f"새로운 토큰 발급")
    return ACCESS_TOKEN

def refresh_token():
    """토큰 갱신"""
    global ACCESS_TOKEN
    ACCESS_TOKEN = get_access_token()
    print(f"토큰 갱신 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

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

def get_minute_data(nmin=30, period=5, access_token=""):
    """분봉 데이터 조회 (전역 변수 사용)"""
    print(f"분봉 데이터 조회 시작 - 종목: {SYMBOL}, 시간간격: {nmin}분")
    PATH = "/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
    URL = f"{URL_BASE}/{PATH}"
    
    all_data = []
    next_key = ""
    for _ in range(period):
        params = {
            "AUTH": "",
            "EXCD": MARKET,
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

def calculate_rsi(data, periods=14):
    """RSI 계산 (개선된 버전)"""
    try:
        if "output2" not in data or not data["output2"]:
            print("RSI 계산을 위한 데이터가 부족합니다")
            return 50

        df = pd.DataFrame(data["output2"])
        print(f"RSI 계산을 위한 데이터 프레임 생성 완료: {len(df)} 행")
        
        price_columns = ['stck_prpr', 'ovrs_nmix_prpr', 'close', 'last']
        price_col = next((col for col in price_columns if col in df.columns), None)
        
        if not price_col:
            print("가격 데이터 컬럼을 찾을 수 없습니다:", df.columns)
            return 50
        
        df['price'] = pd.to_numeric(df[price_col], errors='coerce')
        df = df.dropna(subset=['price'])
        
        if 'xymd' in df.columns and 'xhms' in df.columns:
            df['datetime'] = pd.to_datetime(df['xymd'] + df['xhms'], format='%Y%m%d%H%M%S')
        else:
            print("datetime 컬럼 생성 실패")
            return 50
        
        df = df.sort_values(by='datetime').reset_index(drop=True)
        
        if len(df) < periods:
            print(f"데이터 부족 (필요: {periods}, 현재: {len(df)})")
            return 50
        
        delta = df['price'].diff()
        gain = (delta.where(delta > 0, 0)).fillna(0)
        loss = (-delta.where(delta < 0, 0)).fillna(0)
        
        avg_gain = gain.rolling(window=periods, min_periods=periods).mean()
        avg_loss = loss.rolling(window=periods, min_periods=periods).mean()
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        latest_rsi = round(rsi.iloc[-1], 2)
        print(f"RSI 계산 완료: {latest_rsi}")
        return latest_rsi
    except Exception as e:
        print(f"RSI 계산 중 오류 발생: {e}")
        return 50

def get_current_rsi(periods=14, nmin=30):
    """현재 RSI 조회 (전역 변수 사용)"""
    print(f"RSI 조회 시작: {SYMBOL}")
    data = get_minute_data(nmin=nmin, access_token=ACCESS_TOKEN)
    rsi_value = calculate_rsi(data, periods)
    print(f"종목 {SYMBOL}의 RSI 값: {rsi_value}")
    return rsi_value

def get_current_price(market=MARKET, code=SYMBOL):
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

def get_current_price(market="NAS", code="AAPL"):
    """현재가 조회"""
    PATH = "uapi/overseas-price/v1/quotations/price"
    URL = f"{URL_BASE}/{PATH}"
    headers = {"Content-Type":"application/json", 
            "authorization": f"Bearer {ACCESS_TOKEN}",
            "appKey":APP_KEY,
            "appSecret":APP_SECRET,
            "tr_id":"HHDFS00000300"}
    params = {
        "AUTH": "",
        "EXCD":market,
        "SYMB":code,
    }
    res = requests.get(URL, headers=headers, params=params)
    return float(res.json()['output']['last'])

# def buy(market="NAS", code="AAPL", qty="1", price="0"):
#     """미국 주식 지정가 매수"""
#     PATH = "uapi/overseas-stock/v1/trading/order"
#     URL = f"{URL_BASE}/{PATH}"
#     data = {
#         "CANO": CANO,
#         "ACNT_PRDT_CD": ACNT_PRDT_CD,
#         "OVRS_EXCG_CD": market,
#         "PDNO": code,
#         "ORD_DVSN": "00",
#         "ORD_QTY": str(int(qty)),
#         "OVRS_ORD_UNPR": f"{round(price,2)}",
#         "ORD_SVR_DVSN_CD": "0"
#     }
#     headers = {"Content-Type":"application/json", 
#         "authorization":f"Bearer {ACCESS_TOKEN}",
#         "appKey":APP_KEY,
#         "appSecret":APP_SECRET,
#         "tr_id":"JTTT1002U",
#         "custtype":"P",
#         "hashkey" : hashkey(data)
#     }
#     res = requests.post(URL, headers=headers, data=json.dumps(data))
#     if res.json()['rt_cd'] == '0':
#         send_message(f"[매수 성공]{str(res.json())}")
#         return True
#     else:
#         send_message(f"[매수 실패]{str(res.json())}")
#         return False
    


def buy(market=MARKET, code=SYMBOL, qty="1", price="0"):
    """미국 주식 지정가 매수"""
    PATH = "uapi/overseas-stock/v1/trading/order"
    URL = f"{URL_BASE}/{PATH}"
    
    # 📌 거래소 코드 변환 (NYS → NYSE)
    if market == "NYS":
        market = "NYSE"
    elif market == "NAS":
        market = "NASD"

    data = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "OVRS_EXCG_CD": market,  # 🔹 여기를 수정!
        "PDNO": code,
        "ORD_DVSN": "00",  # 지정가 주문
        "ORD_QTY": str(int(qty)),  # 주문 수량 (정수 변환)
        "OVRS_ORD_UNPR": f"{round(float(price), 2)}",  # 가격 변환
        "ORD_SVR_DVSN_CD": "0"
    }
    
    headers = {
        "Content-Type": "application/json", 
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "tr_id": "TTTT1002U",  #TTTT1002U J가 아닌 것 같음
        "custtype": "P",
        "hashkey": hashkey(data)
    }
    
    res = requests.post(URL, headers=headers, data=json.dumps(data))
    res_data = res.json()
    
    if res_data['rt_cd'] == '0':
        send_message(f"[매수 성공] {code} {qty}주 @${price}")
        return True
    else:
        send_message(f"[매수 실패] {res_data['msg1']}")
        if 'msg_cd' in res_data:
            send_message(f"에러 코드: {res_data['msg_cd']}")
        return False



def sell(market=MARKET, code=SYMBOL, qty="1", price="0"):
    """미국 주식 지정가 매도"""
    # 시장 코드 변환
    market = "NASD" if market == "NAS" else market
    
    PATH = "uapi/overseas-stock/v1/trading/order"
    URL = f"{URL_BASE}/{PATH}"
    
    # 수량과 가격 검증
    try:
        qty = str(int(float(qty)))
        price = str(round(float(price), 2))
        
        # 보유 수량 검증
        stock_dict = get_stock_balance()
        if code not in stock_dict:
            send_message(f"{code} 종목을 보유하고 있지 않습니다")
            return False
        
        held_qty = int(stock_dict[code])
        if int(qty) > held_qty:
            send_message(f"매도 수량({qty})이 보유 수량({held_qty})을 초과합니다")
            return False
            
    except ValueError as e:
        send_message(f"수량 또는 가격 변환 오류: {e}")
        return False
    
    data = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "OVRS_EXCG_CD": market,
        "PDNO": code,
        "ORD_DVSN": "00",
        "ORD_QTY": qty,
        "OVRS_ORD_UNPR": price,
        "ORD_SVR_DVSN_CD": "0"
    }
    
    headers = {
        "Content-Type": "application/json", 
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "tr_id": "TTTT1006U",#TTTT1006U J가 아닌 것 같음
        "custtype": "P",
        "hashkey": hashkey(data)
    }
    
    try:
        res = requests.post(URL, headers=headers, data=json.dumps(data))
        res_data = res.json()
        
        if res_data['rt_cd'] == '0':
            send_message(f"[매도 성공] {code} {qty}주 @${price}")
            return True
        else:
            send_message(f"[매도 실패] {res_data['msg1']}")
            if 'msg_cd' in res_data:
                send_message(f"에러 코드: {res_data['msg_cd']}")
            return False
            
    except Exception as e:
        send_message(f"[매도 중 오류 발생] {str(e)}")
        return False


def get_balance():
    """API에서 직접 주문 가능 금액 조회"""
    PATH = "uapi/domestic-stock/v1/trading/inquire-psbl-order"
    URL = f"{URL_BASE}/{PATH}"
    
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "tr_id": "TTTC8908R",
        "custtype": "P",
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
    if res.status_code == 200:
        response_json = res.json()
        cash_available = int(response_json['output']['ord_psbl_cash'])  # 🔹 API 제공 주문 가능 금액 사용
        send_message(f"🔹 API에서 조회한 주문 가능 금액 (KRW): {cash_available}원")
        return cash_available
    else:
        send_message(f"🚨 주문 가능 금액 조회 실패: {res.text}")
        return 0
    


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
        "OVRS_EXCG_CD": market,
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
        "OVRS_EXCG_CD": market,
        "WCRC_FRCR_DVSN_CD": "01",
        "NATN_CD": "840",
        "TR_MKET_CD": "01",
        "INQR_DVSN_CD": "00"
    }
    res = requests.get(URL, headers=headers, params=params)
    exchange_rate = 1300.0  #1450
    if len(res.json()['output2']) > 0:
        exchange_rate = float(res.json()['output2'][0]['frst_bltn_exrt'])
    return exchange_rate

# 소숫점 단위 매수방법법
# def main():
#     global ACCESS_TOKEN
    
#     try:
#         ACCESS_TOKEN = get_access_token()
#         bought_list = []  # 매수 완료된 종목 리스트
        
#         # 매수 비율 설정 (30% ~ 100% 사이)
#         BUY_RATIO = 0.3  # 30%로 설정
        
#         send_message(f"=== RSI 기반 자동매매 프로그램 시작 ({MARKET}:{SYMBOL}) ===")
#         send_message(f"매수 비율: 보유 금액의 {BUY_RATIO*100}%")
        
#         # 시간대 설정 (모든 datetime 객체에 일관되게 적용)
#         tz = timezone('America/New_York')
#         last_token_refresh = datetime.now(tz)
        
#         # 초기 실행을 위한 설정
#         force_first_check = True
#         last_check_time = datetime.now(tz) - timedelta(minutes=31)
        
#         # 초기 시장 체크
#         market_open = is_market_time()
#         if not market_open:
#             wait_for_market_open()
        
#         while True:
#             current_time = datetime.now(tz)
#             NAS_time = datetime.now(timezone('America/New_York'))
            
#             # 토큰 갱신 (2시간마다)
#             if (current_time - last_token_refresh).total_seconds() >= 7200:
#                 refresh_token()
#                 last_token_refresh = current_time
            
#             # RSI 체크 조건
#             minutes_elapsed = (current_time - last_check_time).total_seconds() / 60
#             time_to_check = (NAS_time.minute % 30 == 0 or (NAS_time.minute % 30 == 1 and NAS_time.second <= 30))
            
#             if force_first_check or (minutes_elapsed >= 29 and time_to_check):
#                 # 시장 상태 확인
#                 market_open = is_market_time()
#                 if not market_open:
#                     wait_for_market_open()
#                     last_check_time = current_time
#                     force_first_check = False
#                     continue
                
#                 # RSI 체크 및 매매 로직
#                 KST_time = datetime.now(timezone('Asia/Seoul'))
#                 send_message(f"=== RSI 체크 시작 (미국: {NAS_time.strftime('%H:%M')}, 한국: {KST_time.strftime('%H:%M')}) ===")
                
#                 current_rsi = get_current_rsi()
#                 send_message(f"{SYMBOL} 현재 RSI: {current_rsi:.2f}")
                
#                 # 현재가 조회
#                 current_price = get_current_price(MARKET, SYMBOL)
#                 if current_price is None:
#                     send_message(f"{SYMBOL} 현재가 조회 실패")
#                 else:
#                     send_message(f"{SYMBOL} 현재가: ${current_price}")
                    
#                     # 매수 조건
#                     if current_rsi <= 30 and SYMBOL not in bought_list:
#                         send_message(f"{SYMBOL} 매수 신호 감지 (RSI: {current_rsi:.2f})")
                        
#                         # 현재 잔고 조회
#                         cash_balance = get_balance()
#                         if cash_balance > 0:
#                             # 환율 조회
#                             exchange_rate = get_exchange_rate()
#                             usd_balance = cash_balance / exchange_rate
                            
#                             # 수수료 고려 (0.05%)
#                             available_usd = usd_balance * 0.9995
                            
#                             # 설정된 비율만큼만 사용
#                             trade_amount = available_usd * BUY_RATIO
                            
#                             # 매수 가능 수량 계산 (소수점 포함)
#                             qty = trade_amount / current_price
                            
#                             # 최소 수량 로직 추가
#                             min_qty = 0.01  # 0.01주부터 매수 가능한지 테스트
#                             if qty < min_qty and trade_amount > 0:
#                                 qty = min_qty
#                                 send_message(f"최소 수량으로 매수 시도: {min_qty}주")
                            
#                             # 소수점 둘째 자리까지 반올림
#                             qty = round(qty, 2)
                            
#                             if qty > 0:
#                                 send_message(f"매수 금액: ${trade_amount:.2f} (전체 가용 금액의 {BUY_RATIO*100}%)")
#                                 send_message(f"매수 수량: {qty}주")
                                
#                                 buy_result = buy(market=MARKET, code=SYMBOL, qty=str(qty), price=str(current_price))
#                                 if buy_result:
#                                     bought_list.append(SYMBOL)
#                                     send_message(f"{SYMBOL} {qty}주 매수 주문 완료")
#                             else:
#                                 send_message(f"잔고 부족으로 매수 불가 (현재 잔고: ${available_usd:.2f}, 필요 금액: ${current_price:.2f})")
#                         else:
#                             send_message("현재 잔고를 조회할 수 없습니다")
                    
#                     # 매도 조건
#                     elif current_rsi >= 70 and SYMBOL in bought_list:
#                         send_message(f"{SYMBOL} 매도 신호 감지 (RSI: {current_rsi:.2f})")
#                         # 현재 보유 수량 확인
#                         stock_dict = get_stock_balance()
#                         if SYMBOL in stock_dict:
#                             qty = stock_dict[SYMBOL]
#                             sell_result = sell(market=MARKET, code=SYMBOL, qty=qty, price=str(current_price))
#                             if sell_result:
#                                 bought_list.remove(SYMBOL)
#                                 send_message(f"{SYMBOL} {qty}주 매도 주문 완료")
#                         else:
#                             send_message(f"{SYMBOL}은 보유하고 있지 않습니다")
                
#                 last_check_time = current_time
#                 force_first_check = False
                
#                 # 다음 체크 시간 계산
#                 next_check_minutes = 30 - (NAS_time.minute % 30)
#                 if next_check_minutes == 0:
#                     next_check_minutes = 30
#                 send_message(f"다음 RSI 체크까지 약 {next_check_minutes}분 남았습니다")
            
#             # 장 마감 체크
#             if NAS_time.hour >= 16:
#                 send_message("미국 장 마감으로 프로그램을 종료합니다.")
#                 break
            
#             time.sleep(30)  # 30초마다 한 번만 체크
    
#     except Exception as e:
#         send_message(f"[오류 발생]{str(e)}")
#         time.sleep(1)


# 아래 적용시 돈 부족 발생

def main():
    global ACCESS_TOKEN
    
    try:
        ACCESS_TOKEN = get_access_token()
        bought_list = []  # 매수 완료된 종목 리스트
        
        # 매수 비율 설정 (30% ~ 100% 사이)
        BUY_RATIO = 1.0  # 30%로 설정
        
        send_message(f"=== RSI 기반 자동매매 프로그램 시작 ({MARKET}:{SYMBOL}) ===")
        send_message(f"매수 비율: 보유 금액의 {BUY_RATIO*100}%")
        
        # 시간대 설정 (모든 datetime 객체에 일관되게 적용)
        tz = timezone('America/New_York')
        last_token_refresh = datetime.now(tz)
        
        # 초기 실행을 위한 설정
        force_first_check = True
        last_check_time = datetime.now(tz) - timedelta(minutes=31)
        
        # 초기 시장 체크
        market_open = is_market_time()
        if not market_open:
            wait_for_market_open()
        
        while True:
            current_time = datetime.now(tz)
            NAS_time = datetime.now(timezone('America/New_York'))
            
            # 토큰 갱신 (2시간마다)
            if (current_time - last_token_refresh).total_seconds() >= 7200:
                refresh_token()
                last_token_refresh = current_time
            
            # RSI 체크 조건
            minutes_elapsed = (current_time - last_check_time).total_seconds() / 60
            time_to_check = (NAS_time.minute % 30 == 0 or (NAS_time.minute % 30 == 1 and NAS_time.second <= 30))
            
            if force_first_check or (minutes_elapsed >= 29 and time_to_check):
                # 시장 상태 확인
                market_open = is_market_time()
                if not market_open:
                    wait_for_market_open()
                    last_check_time = current_time
                    force_first_check = False
                    continue
                
                # RSI 체크 및 매매 로직
                KST_time = datetime.now(timezone('Asia/Seoul'))
                send_message(f"=== RSI 체크 시작 (미국: {NAS_time.strftime('%H:%M')}, 한국: {KST_time.strftime('%H:%M')}) ===")
                
                current_rsi = get_current_rsi()
                send_message(f"{SYMBOL} 현재 RSI: {current_rsi:.2f}")
                
                # 현재가 조회
                current_price = get_current_price(MARKET, SYMBOL)
                if current_price is None:
                    send_message(f"{SYMBOL} 현재가 조회 실패")
                else:
                    send_message(f"{SYMBOL} 현재가: ${current_price}")
                    
                    # 매수 조건
                    if current_rsi <= 30 and SYMBOL not in bought_list: #30
                        send_message(f"{SYMBOL} 매수 신호 감지 (RSI: {current_rsi:.2f})")
                        
                        # 현재 잔고 조회
                        cash_balance = get_balance()
                        if cash_balance > 0:
                            # 환율 조회
                            exchange_rate = get_exchange_rate()
                            usd_balance = cash_balance / exchange_rate
                            
                            # 더 보수적인 매수 가능 금액 계산 (증거금, 수수료, 환율 변동 리스크 고려)
                            available_usd = (usd_balance * 0.50) * BUY_RATIO  # 10% 마진으로 증가 + 설정된 매수 비율
                            # main 함수 내 매수 금액 계산 부분
                            # 매수 수량 계산 (보수적으로)
                            share_price_with_margin = current_price * 1.02  # 2% 가격 버퍼로 증가
                            qty = int(available_usd / share_price_with_margin)
                            
                            if qty > 0:
                                total_cost = qty * current_price
                                
                                # 상세 정보 출력
                                send_message(f"매수 시도 정보:")
                                send_message(f"- 원화 잔고: ₩{cash_balance:,.0f}")
                                send_message(f"- 적용 환율: ₩{exchange_rate:,.2f}")
                                send_message(f"- 달러 환산 잔고: ${usd_balance:.2f}")
                                send_message(f"- 매수 가능 금액(마진 적용): ${available_usd:.2f}")
                                send_message(f"- 주문 수량: {qty}주")
                                send_message(f"- 주문 가격: ${current_price:.2f}")
                                send_message(f"- 총 주문 금액: ${total_cost:.2f}")
                                
                                # 최종 검증 후 매수
                                if total_cost <= (available_usd * 0.98):  # 추가 2% 안전 마진
                                    buy_result = buy(qty=str(qty), price=str(current_price))
                                    if buy_result:
                                        bought_list.append(SYMBOL)
                                        send_message(f"{SYMBOL} 매수 완료")
                                else:
                                    send_message(f"안전 마진 적용 후 주문 불가 (필요금액: ${total_cost:.2f}, 가용금액: ${available_usd:.2f})")
                            else:
                                send_message(f"계산된 매수 수량이 0입니다 (가용금액: ${available_usd:.2f}, 필요금액/주: ${share_price_with_margin:.2f})")
                        else:
                            send_message("현재 잔고를 조회할 수 없습니다")
                    
                    # 매도 조건
                    elif current_rsi >= 70 and SYMBOL in bought_list:
                        send_message(f"{SYMBOL} 매도 신호 감지 (RSI: {current_rsi:.2f})")
                        # 현재 보유 수량 확인
                        stock_dict = get_stock_balance()
                        if SYMBOL in stock_dict:
                            qty = stock_dict[SYMBOL]
                            sell_result = sell(qty=str(qty), price=str(current_price))
                            if sell_result:
                                bought_list.remove(SYMBOL)
                                send_message(f"{SYMBOL} 매도 완료")
                        else:
                            send_message(f"{SYMBOL}은 보유하고 있지 않습니다")
                
                last_check_time = current_time
                force_first_check = False
                
                # 다음 체크 시간 계산
                next_check_minutes = 30 - (NAS_time.minute % 30)
                if next_check_minutes == 0:
                    next_check_minutes = 30
                send_message(f"다음 RSI 체크까지 약 {next_check_minutes}분 남았습니다")
            
            # 장 마감 체크
            if NAS_time.hour >= 16:
                send_message("미국 장 마감으로 프로그램을 종료합니다.")
                break
            
            time.sleep(30)  # 30초마다 체크
    
    except Exception as e:
        send_message(f"[오류 발생]{str(e)}")
        time.sleep(1)

def check_rsi_and_trade(bought_list, buy_ratio):
    """RSI 체크 및 매매 로직을 분리한 함수"""
    KST_time = datetime.now(timezone('Asia/Seoul'))
    NAS_time = datetime.now(timezone('America/New_York'))
    send_message(f"=== RSI 체크 시작 (미국: {NAS_time.strftime('%H:%M')}, 한국: {KST_time.strftime('%H:%M')}) ===")
    
    current_rsi = get_current_rsi()
    send_message(f"{SYMBOL} 현재 RSI: {current_rsi:.2f}")
    
    # 현재가 조회
    current_price = get_current_price(MARKET, SYMBOL)
    if current_price is None:
        send_message(f"{SYMBOL} 현재가 조회 실패")
        return
    
    send_message(f"{SYMBOL} 현재가: ${current_price}")
    
    # 매수 조건
    if current_rsi <= 80 and SYMBOL not in bought_list: #30
        send_message(f"{SYMBOL} 매수 신호 감지 (RSI: {current_rsi:.2f})")
        
        # 현재 잔고 조회
        cash_balance = get_balance()
        if cash_balance > 0:
            # 환율 조회
            exchange_rate = get_exchange_rate()
            usd_balance = cash_balance / exchange_rate
            
            # 수수료 고려 (0.05%)
            available_usd = usd_balance * 0.9995
            
            # 설정된 비율만큼만 사용
            trade_amount = available_usd * buy_ratio
            
            # 매수 가능 수량 계산 (정수로 변환)
            qty = int(trade_amount / current_price)
            
            if qty > 0:
                send_message(f"매수 금액: ${trade_amount:.2f} (전체 가용 금액의 {buy_ratio*100}%)")
                send_message(f"매수 수량: {qty}주")
                
                buy_result = buy(market=MARKET, code=SYMBOL, qty=str(qty), price=str(current_price))
                if buy_result:
                    bought_list.append(SYMBOL)
                    send_message(f"{SYMBOL} {qty}주 매수 주문 완료")
            else:
                send_message(f"잔고 부족으로 매수 불가 (현재 잔고: ${available_usd:.2f}, 필요 금액: ${current_price:.2f})")
        else:
            send_message("현재 잔고를 조회할 수 없습니다")
    
    # 매도 조건
    elif current_rsi >= 70 and SYMBOL in bought_list:
        send_message(f"{SYMBOL} 매도 신호 감지 (RSI: {current_rsi:.2f})")
        stock_dict = get_stock_balance()
        if SYMBOL in stock_dict:
            qty = stock_dict[SYMBOL]
            sell_result = sell(market=MARKET, code=SYMBOL, qty=qty, price=str(current_price))
            if sell_result:
                bought_list.remove(SYMBOL)
                send_message(f"{SYMBOL} {qty}주 매도 주문 완료")
        else:
            send_message(f"{SYMBOL}은 보유하고 있지 않습니다")




if __name__ == "__main__":
    main()