
# 1파트

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

# 거래소와 종목 전역 변수 설정
MARKET = "NASD"  # 나스닥
EXCD_MARKET = "NAS"
SYMBOLS = ["PLTR", "NVDA","TSLA"]  # 여러 심볼 추가

def send_message(msg, symbol=None):
    """디스코드 메세지 전송 (심볼 정보 추가)"""
    now = datetime.now()
    symbol_info = f"[{symbol}] " if symbol else ""
    message = {"content": f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {symbol_info}{str(msg)}"}
    requests.post(DISCORD_WEBHOOK_URL, data=message)
    print(message)


def get_access_token():
    """토큰 발급"""
    global ACCESS_TOKEN
    headers = {"content-type":"application/json"}
    body = {"grant_type":"client_credentials",
    "appkey":APP_KEY, 
    "appsecret":APP_SECRET}
    PATH = "oauth2/tokenP"
    URL = f"{URL_BASE}/{PATH}"
    res = requests.post(URL, headers=headers, data=json.dumps(body))
    ACCESS_TOKEN = res.json()["access_token"]
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

def is_market_time():
    """미국 시장 시간 체크"""
    NAS_time = datetime.now(timezone('America/New_York'))
    print(f"현재 미국시간: {NAS_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    if NAS_time.weekday() >= 5:
        print("주말 - 시장 닫힘")
        return False
        
    market_start = NAS_time.replace(hour=9, minute=30, second=0, microsecond=0)
    market_end = NAS_time.replace(hour=16, minute=0, second=0, microsecond=0)
    is_market_open = market_start <= NAS_time <= market_end
    
    print(f"시장 개장 상태: {'열림' if is_market_open else '닫힘'}")
    return is_market_open

def wait_for_market_open():
    """시장 개장 대기"""
    send_message("미국 시장이 닫혀 있습니다. 개장까지 대기합니다...")
    
    while not is_market_time():
        # 16시 이후 또는 00시~08시까지는 60분 단위 대기
        nas_time = datetime.now(timezone('America/New_York'))
        if nas_time.hour >= 16 or nas_time.hour < 9:
            next_check = 60
        else:
            next_check = 5  # 09시 이후부터 개장 전(09:30 전)까지는 5분 단위 대기
        send_message(f"다음 확인까지 {next_check}분 대기...")
        time.sleep(next_check * 60)
    
    send_message("미국 시장이 개장되었습니다!")
    refresh_token()  # 시장 개장 시 토큰 갱신


#2파트

def get_minute_data(symbol, nmin=30, period=2, access_token=""):
    """분봉 데이터 조회 (다중 심볼 대응)"""
    print(f"분봉 데이터 조회 시작 - 종목: {symbol}, 시간간격: {nmin}분")
    PATH = "/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
    URL = f"{URL_BASE}/{PATH}"
    
    # 각 종목별 시장 정보 매핑
    MARKET_MAP = {
        "PLTR": {"EXCD": "NAS", "MARKET": "NASD"},
        "NVDA": {"EXCD": "NAS", "MARKET": "NASD"},
        "TSLA": {"EXCD": "NAS", "MARKET": "NASD"}
    }
    
    # 해당 심볼의 거래소 정보 가져오기
    market_info = MARKET_MAP.get(symbol, {"EXCD": EXCD_MARKET, "MARKET": MARKET})
    
    all_data = []
    next_key = ""
    for _ in range(period):
        params = {
            "AUTH": "",
            "EXCD": market_info["EXCD"],
            "SYMB": symbol,
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
                print(f"데이터 없음 - 요청 코드: {symbol}, 거래소: {market_info['MARKET']}")
                break
        else:
            print(f"API 호출 실패. 상태 코드: {res.status_code}, 응답 내용: {res.text}")
            break
        time.sleep(0.5)
    
    print(f"{symbol} 조회된 데이터 수: {len(all_data)}")
    return {"output2": all_data} if all_data else None

def calculate_rsi(data, periods=14):
    """RSI 계산 (다중 심볼 대응 개선 버전)"""
    try:
        # 데이터 유효성 확인
        if "output2" not in data or not data["output2"]:
            print("RSI 계산을 위한 데이터가 부족합니다")
            return 50

        # 데이터프레임 생성
        df = pd.DataFrame(data["output2"])
        print(f"RSI 계산을 위한 데이터 프레임 생성 완료: {len(df)} 행")
        
        # 가격 컬럼 동적 탐색
        price_columns = ['stck_prpr', 'ovrs_nmix_prpr', 'close', 'last']
        price_col = next((col for col in price_columns if col in df.columns), None)
        
        if not price_col:
            print("가격 데이터 컬럼을 찾을 수 없습니다:", df.columns)
            return 50
        
        # 가격 데이터 숫자 변환 및 결측값 처리
        df['price'] = pd.to_numeric(df[price_col], errors='coerce')
        df = df.dropna(subset=['price'])
        
        # 날짜/시간 컬럼 처리
        if 'xymd' in df.columns and 'xhms' in df.columns:
            df['datetime'] = pd.to_datetime(df['xymd'] + df['xhms'], format='%Y%m%d%H%M%S')
        else:
            print("datetime 컬럼 생성 실패")
            return 50
        
        # 데이터 정렬
        df = df.sort_values(by='datetime').reset_index(drop=True)
        
        # 데이터 충분성 확인
        if len(df) < periods:
            print(f"데이터 부족 (필요: {periods}, 현재: {len(df)})")
            return 50
        
        # RSI 계산 로직
        delta = df['price'].diff()
        gain = (delta.where(delta > 0, 0)).fillna(0)
        loss = (-delta.where(delta < 0, 0)).fillna(0)
        
        avg_gain = gain.rolling(window=periods, min_periods=periods).mean()
        avg_loss = loss.rolling(window=periods, min_periods=periods).mean()
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        # 최신 RSI 값 추출 및 반올림
        latest_rsi = round(rsi.iloc[-1], 2)
        print(f"RSI 계산 완료: {latest_rsi}")
        return latest_rsi
    
    except Exception as e:
        print(f"RSI 계산 중 오류 발생: {e}")
        return 50

# 다중 심볼 RSI 조회 헬퍼 함수 (선택사항)
def get_current_rsi(symbol, periods=14, nmin=30):
    """현재 RSI 조회 (다중 심볼 대응)"""
    print(f"RSI 조회 시작: {symbol}")
    try:
        # 액세스 토큰 확인 및 갱신
        global ACCESS_TOKEN
        if not ACCESS_TOKEN:
            ACCESS_TOKEN = get_access_token()
        
        # 분봉 데이터 조회
        data = get_minute_data(
            symbol=symbol, 
            nmin=nmin, 
            access_token=ACCESS_TOKEN
        )
        
        # RSI 계산
        rsi_value = calculate_rsi(data, periods)
        
        print(f"종목 {symbol}의 RSI 값: {rsi_value}")
        return rsi_value
    
    except Exception as e:
        print(f"{symbol} RSI 조회 중 오류: {e}")
        return 50


def get_current_price(symbol, market=MARKET):
    """현재가 조회 (심볼 인자 추가)"""
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
        "EXCD": EXCD_MARKET,
        "SYMB": symbol,
    }
    res = requests.get(URL, headers=headers, params=params)
    return float(res.json()['output']['last'])

def get_balance(symbol):
    """현금 잔고조회 (심볼 인자 추가)"""
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

    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "ITEM_CD": symbol,
        "OVRS_EXCG_CD": MARKET,
        "OVRS_ORD_UNPR": str(get_current_price(symbol))
    }

    res = requests.get(URL, headers=headers, params=params)
    res_data = res.json()
    if 'output' not in res_data:
        send_message(f"🚨 API 응답 오류: {res_data}", symbol)
        return 0

    cash = res_data['output'].get('ovrs_ord_psbl_amt', '0')
    send_message(f"주문 가능 현금 잔고: {cash}$", symbol)
    
    return float(cash)

def get_stock_balance(symbol):
    """주식 잔고조회 (심볼 인자 추가)"""
    PATH = "uapi/overseas-stock/v1/trading/inquire-balance"
    URL = f"{URL_BASE}/{PATH}"
    headers = {
        "Content-Type": "application/json", 
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "tr_id": "JTTT3012R",
        "custtype": "P"
    }
    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "OVRS_EXCG_CD": MARKET,
        "TR_CRCY_CD": "USD",
        "CTX_AREA_FK200": "",
        "CTX_AREA_NK200": ""
    }
    res = requests.get(URL, headers=headers, params=params)
    stock_list = res.json()['output1']
    evaluation = res.json()['output2']
    stock_dict = {}
    
    send_message(f"====주식 보유잔고====", symbol)
    for stock in stock_list:
        if int(stock['ovrs_cblc_qty']) > 0:
            stock_dict[stock['ovrs_pdno']] = stock['ovrs_cblc_qty']
            send_message(f"{stock['ovrs_item_name']}({stock['ovrs_pdno']}): {stock['ovrs_cblc_qty']}주", symbol)
            time.sleep(0.1)
    
    send_message(f"주식 평가 금액: ${evaluation['tot_evlu_pfls_amt']}", symbol)
    time.sleep(0.1)
    send_message(f"평가 손익 합계: ${evaluation['ovrs_tot_pfls']}", symbol)
    time.sleep(0.1)
    send_message(f"=================", symbol)
    
    return stock_dict



#3파트

def main():
    global ACCESS_TOKEN
    
    try:
        ACCESS_TOKEN = get_access_token()
        bought_list = []  # 매수 완료된 종목 리스트
        
        # 매수 비율 설정 (100% 활용 가능)
        BUY_RATIO = 0.1  # 100% 사용

        send_message(f"=== RSI 기반 다중 자동매매 프로그램 시작 ({MARKET}) ===")
        send_message(f"매수 대상 종목: {SYMBOLS}")
        send_message(f"매수 비율: 보유 금액의 {BUY_RATIO*100}%")
        
        # 시간대 설정
        tz = timezone('America/New_York')
        last_token_refresh = datetime.now(tz)
        
        # 초기 실행 설정
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
            time_to_check = (NAS_time.minute % 20 == 0 or (NAS_time.minute % 20 == 1 and NAS_time.second <= 30))
            
            if force_first_check or (minutes_elapsed >= 19 and time_to_check):
                # 시장 상태 확인
                market_open = is_market_time()
                if not market_open:
                    wait_for_market_open()
                    last_check_time = current_time
                    force_first_check = False
                    continue
                
                # 각 심볼에 대해 반복 처리
                for symbol in SYMBOLS:
                    KST_time = datetime.now(timezone('Asia/Seoul'))
                    send_message(f"=== RSI 체크 시작 ({symbol}) (미국: {NAS_time.strftime('%H:%M')}, 한국: {KST_time.strftime('%H:%M')}) ===", symbol)
                    
                    current_rsi = get_current_rsi(symbol)
                    send_message(f"현재 RSI: {current_rsi:.2f}", symbol)
                    
                    # 현재가 조회
                    current_price = get_current_price(symbol)
                    if current_price is None:
                        send_message(f"현재가 조회 실패", symbol)
                        continue
                    
                    send_message(f"현재가: ${current_price}", symbol)
                    
                    # 매수 조건
                    if current_rsi <= 30:
                        send_message(f"매수 신호 감지 (RSI: {current_rsi:.2f})", symbol)
                        
                        # 현재 잔고 조회
                        cash_balance = get_balance(symbol)
                        if cash_balance > 0:
                            # 환율 조회
                            exchange_rate = get_exchange_rate()
                            usd_balance = cash_balance
                            
                            # 매수 가능 금액 계산
                            available_usd = usd_balance * BUY_RATIO
                            
                            # 매수 수량 계산
                            share_price_with_margin = current_price * 1.01
                            qty = max(1, int(available_usd / share_price_with_margin))
                            
                            if qty > 0:
                                total_cost = qty * current_price
                                
                                send_message(f"- 매수 가능 금액: ${available_usd:.2f}", symbol)
                                send_message(f"- 주문 수량: {qty}주", symbol)
                                send_message(f"- 주문 가격: ${current_price:.2f}", symbol)
                                send_message(f"- 총 주문 금액: ${total_cost:.2f}", symbol)
                                
                                # 최종 검증 후 매수
                                if total_cost <= (available_usd * 0.99):
                                    buy_result = buy(code=symbol, qty=str(qty), price=str(current_price))
                                    if buy_result:
                                        bought_list.append(symbol)
                                        send_message(f"✅ {symbol} {qty}주 매수 완료", symbol)
                                else:
                                    send_message(f"❌ 안전 마진 적용 후 주문 불가", symbol)
                            else:
                                send_message(f"❌ 계산된 매수 수량이 0입니다", symbol)
                        else:
                            send_message("🚨 현재 잔고를 조회할 수 없습니다", symbol)
                    
                    # 매도 조건
                    elif current_rsi >= 70:
                        send_message(f"매도 신호 감지 (RSI: {current_rsi:.2f})", symbol)
                        stock_dict = get_stock_balance(symbol)
                        if symbol in stock_dict:
                            qty = stock_dict[symbol]
                            sell_result = sell(code=symbol, qty=str(qty), price=str(current_price))
                            if sell_result:
                                send_message(f"✅ {symbol} 매도 완료", symbol)
                        else:
                            send_message(f"❌ {symbol}을 보유하고 있지 않습니다", symbol)
                
                last_check_time = current_time
                force_first_check = False
                
                # 다음 체크 시간 계산
                next_check_minutes = 30 - (NAS_time.minute % 30)
                if next_check_minutes == 0:
                    next_check_minutes = 30
                send_message(f"⏳ 다음 RSI 체크까지 약 {next_check_minutes}분 남았습니다")
                
                # 정확히 다음 RSI 체크까지 대기
                time.sleep(next_check_minutes * 60)

            # 장 마감 체크
            if NAS_time.hour >= 16:
                send_message("📉 미국 장 마감으로 프로그램을 종료합니다.")
                wait_for_market_open()
                continue
    
    except Exception as e:
        send_message(f"🚨 [오류 발생]{str(e)}")
        time.sleep(1)

if __name__ == "__main__":
    main()

    