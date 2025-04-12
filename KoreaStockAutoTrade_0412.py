#0404버전에서 
# # 국내 주식 거래  종목 변경

import requests
import json
import datetime
import time
import yaml
import pandas as pd
import numpy as np
from pytz import timezone

# config.yaml 파일 로드
with open('config.yaml', encoding='UTF-8') as f:
    _cfg = yaml.load(f, Loader=yaml.FullLoader)
APP_KEY = _cfg['APP_KEY']
APP_SECRET = _cfg['APP_SECRET']
ACCESS_TOKEN = ""
CANO = _cfg['CANO']
ACNT_PRDT_CD = _cfg['ACNT_PRDT_CD']
DISCORD_WEBHOOK_URL = _cfg['DISCORD_WEBHOOK_URL']
URL_BASE = _cfg['URL_BASE']

# 매매 대상 종목 리스트 (종목코드)
SYMBOLS = ["005930","000660","069500", "371110" ]  # 삼성전자, SK하이닉스, 차이나항생테크, #LGDisplay

# 매수/매도 기준 RSI 값
RSI_OVERSOLD = 28  # RSI가 이 값 이하면 매수 신호
RSI_OVERBOUGHT = 73  # RSI가 이 값 이상이면 매도 신호

# RSI 계산 기간 및 분봉 설정
RSI_PERIOD = 14  # RSI 계산 기간
MINUTE_CANDLE = 30  # 분봉 (30분봉 사용)

# 매매 비율 설정
BUY_RATIO = 0.3  # 계좌 잔고의 30%를 사용

def send_message(msg, symbol=None):
    """디스코드 메세지 전송"""
    now = datetime.datetime.now()
    symbol_info = f"[{symbol}] " if symbol else ""
    message = {"content": f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {symbol_info}{str(msg)}"}
    requests.post(DISCORD_WEBHOOK_URL, data=message)
    print(message)

def get_access_token():
    """토큰 발급"""
    try:
        headers = {"content-type":"application/json"}
        body = {"grant_type":"client_credentials",
        "appkey":APP_KEY, 
        "appsecret":APP_SECRET}
        PATH = "oauth2/tokenP"
        URL = f"{URL_BASE}/{PATH}"
        res = requests.post(URL, headers=headers, data=json.dumps(body))
        
        # 응답 확인
        if res.status_code != 200:
            send_message(f"토큰 발급 실패: 상태 코드 {res.status_code}")
            return None
            
        access_token = res.json()["access_token"]
        print(f"새로운 토큰 발급")
        return access_token
    except Exception as e:
        send_message(f"🚨 토큰 발급 중 오류 발생: {str(e)}")
        return None

def refresh_token():
    """토큰 갱신"""
    global ACCESS_TOKEN
    try:
        ACCESS_TOKEN = get_access_token()
        if ACCESS_TOKEN:
            print(f"토큰 갱신 완료: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            return True
        else:
            print("토큰 갱신 실패")
            return False
    except Exception as e:
        send_message(f"🚨 토큰 갱신 중 오류 발생: {str(e)}")
        return False

def hashkey(datas):
    """암호화"""
    try:
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
    except Exception as e:
        send_message(f"🚨 해시키 생성 중 오류 발생: {str(e)}")
        return None

def is_market_open():
    """국내 시장 시간 체크"""
    try:
        KST_time = datetime.datetime.now(timezone('Asia/Seoul'))
        print(f"현재 한국시간: {KST_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        if KST_time.weekday() >= 5:
            print("주말 - 시장 닫힘")
            return False
            
        market_start = KST_time.replace(hour=9, minute=0, second=0, microsecond=0)
        market_end = KST_time.replace(hour=15, minute=30, second=0, microsecond=0)
        is_market_open = market_start <= KST_time <= market_end
        
        print(f"시장 개장 상태: {'열림' if is_market_open else '닫힘'}")
        return is_market_open
    except Exception as e:
        send_message(f"🚨 시장 시간 확인 중 오류: {str(e)}")
        # 오류 발생 시 기본적으로 닫힘으로 처리
        return False

def wait_for_market_open():
    """시장 개장 대기 (주말 처리 개선)"""
    try:
        send_message("한국 시장이 닫혀 있습니다. 개장까지 대기합니다...")
        
        while not is_market_open():
            # 현재 한국 시간 확인
            kst_time = datetime.datetime.now(timezone('Asia/Seoul'))
            
            # 다음 체크 시간 결정
            next_check = 60  # 기본 대기 시간 60분
            
            # 개장일(월~금) 확인
            weekday = kst_time.weekday()  # 0=월요일, 6=일요일
            is_weekend = weekday >= 5  # 주말 여부
            
            if is_weekend:
                # 일요일 && 15시 이후 - 개장 임박
                if weekday == 6 and kst_time.hour >= 15:
                    next_check = 180
                # 토요일 또는 일요일 오전 - 여전히 많은 시간 남음
                else:
                    next_check = 240  # 주말에는 4시간 간격으로 체크
            else:
                # 평일
                # 15시 이후 또는 00시~08시까지는 240분 단위 대기
                if kst_time.hour >= 15 or kst_time.hour < 8:
                    next_check = 240
                # 08시~09시 - 개장 준비 시간
                elif kst_time.hour == 8:
                    next_check = 15  # 15분 간격으로 체크
                # 09시 이후부터 개장 전(09:00 전)까지는 5분 단위 대기
                elif kst_time.hour == 8 and kst_time.minute >= 45:
                    next_check = 5
                else:
                    next_check = 30  # 다른 평일 시간대
            
            send_message(f"다음 확인까지 {next_check}분 대기... (한국시간: {kst_time.strftime('%Y-%m-%d %H:%M')} {['월','화','수','목','금','토','일'][weekday]}요일)")
            time.sleep(next_check * 60)
        
        send_message("한국 시장이 개장되었습니다!")
        if not refresh_token():  # 시장 개장 시 토큰 갱신
            send_message("토큰 갱신에 실패했습니다. 1분 후 다시 시도합니다.")
            time.sleep(60)
            refresh_token()
    except Exception as e:
        send_message(f"🚨 시장 개장 대기 중 오류: {str(e)}")
        time.sleep(60)  # 오류 발생 시 1분 대기 후 재시도

def get_minute_data(code, time_unit=MINUTE_CANDLE, period=20):
    """분봉 데이터 조회"""
    global ACCESS_TOKEN
    
    print(f"분봉 데이터 조회 시작 - 종목: {code}, 시간간격: {time_unit}분")
    PATH = "uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
    URL = f"{URL_BASE}/{PATH}"
    
    all_data = []
    next_key = ""
    
    # 토큰 체크
    if not ACCESS_TOKEN:
        ACCESS_TOKEN = get_access_token()
        if not ACCESS_TOKEN:
            print("토큰 발급 실패, 1분 후 재시도...")
            time.sleep(60)
            ACCESS_TOKEN = get_access_token()
            if not ACCESS_TOKEN:
                return None
    
    for _ in range(period):
        headers = {
            "Content-Type": "application/json", 
            "authorization": f"Bearer {ACCESS_TOKEN}",
            "appKey": APP_KEY,
            "appSecret": APP_SECRET,
            "tr_id": "FHKST03010200",
            "custtype": "P"
        }
        
        params = {
            "FID_ETC_CLS_CODE": "",
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_HOUR_1": time_unit,
            "FID_PW_DATA_INCU_YN": "Y",
            "FID_ETC_CLS_CODE": "",
            "CTX_AREA_FK100": next_key,
            "CTX_AREA_NK100": ""
        }
        
        try:
            res = requests.get(URL, headers=headers, params=params)
            
            # 응답 코드가 만료된 토큰 오류인 경우
            if res.status_code == 401 or (res.status_code == 200 and 'access_token' in res.text.lower()):
                print("토큰이 만료되었습니다. 새 토큰을 발급합니다.")
                ACCESS_TOKEN = get_access_token()
                if ACCESS_TOKEN:
                    # 새 토큰으로 다시 시도
                    headers['authorization'] = f"Bearer {ACCESS_TOKEN}"
                    res = requests.get(URL, headers=headers, params=params)
                else:
                    print("토큰 재발급 실패, 1분 후 다시 시도합니다.")
                    time.sleep(60)
                    continue
            
            if res.status_code == 200:
                data = res.json()
                if "output2" in data and data["output2"]:
                    all_data.extend(data["output2"])
                    next_key = data.get("ctx_area_fk100", "")
                    if not next_key:
                        break
                else:
                    print(f"요청 코드: {code}, 추가 데이터 없음")
                    break
            else:
                print(f"API 호출 실패. 상태 코드: {res.status_code}, 응답 내용: {res.text}")
                break
        except Exception as e:
            print(f"데이터 요청 중 오류 발생: {e}")
            time.sleep(1)
            break
            
        time.sleep(0.5)
    
    print(f"{code} 조회된 데이터 수: {len(all_data)}")
    return {"output2": all_data} if all_data else None


def calculate_rsi(data, periods=RSI_PERIOD):
    """RSI 계산"""
    try:
        # 데이터 유효성 확인
        if "output2" not in data or not data["output2"]:
            print("RSI 계산을 위한 데이터가 부족합니다")
            return 50

        # 데이터프레임 생성
        df = pd.DataFrame(data["output2"])
        print(f"RSI 계산을 위한 데이터 프레임 생성 완료: {len(df)} 행")
        
        # 가격 컬럼 확인
        if 'stck_prpr' in df.columns:
            df['price'] = pd.to_numeric(df['stck_prpr'], errors='coerce')
        else:
            print("가격 데이터 컬럼을 찾을 수 없습니다:", df.columns)
            return 50
        
        # 결측값 처리
        df = df.dropna(subset=['price'])
        
        # 날짜/시간 컬럼 처리
        if 'stck_bsop_date' in df.columns and 'stck_cntg_hour' in df.columns:
            df['datetime'] = pd.to_datetime(df['stck_bsop_date'] + df['stck_cntg_hour'], format='%Y%m%d%H%M%S')
        else:
            print("datetime 컬럼 생성 실패")
            # 인덱스를 datetime으로 사용
            df['datetime'] = pd.date_range(end=pd.Timestamp.now(), periods=len(df))
        
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


def get_current_rsi(code, periods=RSI_PERIOD, time_unit=MINUTE_CANDLE):
    """현재 RSI 조회"""
    global ACCESS_TOKEN
    print(f"RSI 조회 시작: {code}")
    try:
        # 액세스 토큰 확인 및 갱신
        if not ACCESS_TOKEN:
            ACCESS_TOKEN = get_access_token()
            if not ACCESS_TOKEN:
                print("토큰 발급 실패, 1분 후 재시도...")
                time.sleep(60)
                ACCESS_TOKEN = get_access_token()
                if not ACCESS_TOKEN:
                    return 50  # 기본값 반환
        
        # 분봉 데이터 조회
        data = get_minute_data(
            code=code, 
            time_unit=time_unit
        )
        
        if not data:
            send_message(f"{code} 데이터 조회 실패, RSI 계산 불가", code)
            return 50
            
        # RSI 계산
        rsi_value = calculate_rsi(data, periods)
        
        print(f"종목 {code}의 RSI 값: {rsi_value}")
        return rsi_value
    
    except Exception as e:
        error_msg = str(e).lower()
        if 'access_token' in error_msg:
            send_message(f"{code} RSI 조회 중 토큰 오류 발생. 토큰 갱신 시도 중...", code)
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                send_message("토큰 갱신 성공. 다시 시도합니다.", code)
                # 재귀적으로 다시 시도 (단, 무한 루프 방지를 위한 조치 필요)
                return get_current_rsi(code, periods, time_unit)
        else:
            send_message(f"{code} RSI 조회 중 오류: {e}", code)
        return 50


def get_current_price(code):
    """현재가 조회"""
    global ACCESS_TOKEN
    
    PATH = "uapi/domestic-stock/v1/quotations/inquire-price"
    URL = f"{URL_BASE}/{PATH}"
    
    # 토큰 확인
    if not ACCESS_TOKEN:
        ACCESS_TOKEN = get_access_token()
        if not ACCESS_TOKEN:
            send_message(f"{code} 현재가 조회 실패: 토큰 없음", code)
            return None
    
    headers = {
        "Content-Type": "application/json", 
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "tr_id": "FHKST01010100"
    }
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": code,
    }
    
    try:
        res = requests.get(URL, headers=headers, params=params)
        
        # 토큰 오류 처리
        if res.status_code == 401 or (res.status_code == 200 and 'access_token' in res.text.lower()):
            send_message(f"{code} 현재가 조회 중 토큰 오류. 토큰 갱신 중...", code)
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                # 새 토큰으로 다시 시도
                headers["authorization"] = f"Bearer {ACCESS_TOKEN}"
                res = requests.get(URL, headers=headers, params=params)
            else:
                send_message(f"{code} 토큰 갱신 실패", code)
                return None
        
        if res.status_code != 200:
            send_message(f"{code} 현재가 조회 실패: 상태 코드 {res.status_code}", code)
            return None
            
        data = res.json()
        if 'output' not in data or 'stck_prpr' not in data['output']:
            send_message(f"{code} 현재가 데이터 없음: {data}", code)
            return None
            
        return int(data['output']['stck_prpr'])
        
    except Exception as e:
        error_msg = str(e).lower()
        if 'access_token' in error_msg:
            send_message(f"{code} 현재가 조회 중 토큰 오류: {e}", code)
            # 토큰 갱신 시도
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                # 재귀적으로 다시 시도
                return get_current_price(code)
        else:
            send_message(f"{code} 현재가 조회 중 오류: {e}", code)
        return None


def get_balance():
    """현금 잔고조회"""
    global ACCESS_TOKEN
    
    PATH = "uapi/domestic-stock/v1/trading/inquire-psbl-order"
    URL = f"{URL_BASE}/{PATH}"
    
    # 토큰 확인
    if not ACCESS_TOKEN:
        ACCESS_TOKEN = get_access_token()
        if not ACCESS_TOKEN:
            send_message("주문가능현금 조회 실패: 토큰 없음")
            return 0
    
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
    
    try:
        res = requests.get(URL, headers=headers, params=params)
        
        # 토큰 오류 처리
        if res.status_code == 401 or (res.status_code == 200 and 'access_token' in res.text.lower()):
            send_message("주문가능현금 조회 중 토큰 오류. 토큰 갱신 중...")
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                # 새 토큰으로 다시 시도
                headers["authorization"] = f"Bearer {ACCESS_TOKEN}"
                res = requests.get(URL, headers=headers, params=params)
            else:
                send_message("토큰 갱신 실패")
                return 0
        
        if res.status_code != 200:
            send_message(f"주문가능현금 조회 실패: 상태 코드 {res.status_code}")
            return 0
            
        cash = res.json()['output']['ord_psbl_cash']
        send_message(f"주문 가능 현금 잔고: {cash}원")
        
        return int(cash)
        
    except Exception as e:
        error_msg = str(e).lower()
        if 'access_token' in error_msg:
            send_message(f"주문가능현금 조회 중 토큰 오류: {e}")
            # 토큰 갱신 시도
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                # 재귀적으로 다시 시도
                return get_balance()
        else:
            send_message(f"주문가능현금 조회 중 오류: {e}")
        return 0



# 파트2

def get_stock_balance():
    """주식 잔고조회"""
    global ACCESS_TOKEN
    
    PATH = "uapi/domestic-stock/v1/trading/inquire-balance"
    URL = f"{URL_BASE}/{PATH}"
    
    # 토큰 확인
    if not ACCESS_TOKEN:
        ACCESS_TOKEN = get_access_token()
        if not ACCESS_TOKEN:
            send_message("주식 잔고 조회 실패: 토큰 없음")
            return {}
    
    headers = {
        "Content-Type": "application/json", 
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "tr_id": "TTTC8434R",
        "custtype": "P"
    }
    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "01",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }
    
    try:
        res = requests.get(URL, headers=headers, params=params)
        
        # 토큰 오류 처리
        if res.status_code == 401 or (res.status_code == 200 and 'access_token' in res.text.lower()):
            send_message("주식 잔고 조회 중 토큰 오류. 토큰 갱신 중...")
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                # 새 토큰으로 다시 시도
                headers["authorization"] = f"Bearer {ACCESS_TOKEN}"
                res = requests.get(URL, headers=headers, params=params)
            else:
                send_message("토큰 갱신 실패")
                return {}
                
        if res.status_code != 200:
            send_message(f"주식 잔고 조회 실패: 상태 코드 {res.status_code}")
            return {}
            
        stock_list = res.json()['output1']
        evaluation = res.json()['output2']
        stock_dict = {}
        
        send_message(f"====주식 보유잔고====")
        for stock in stock_list:
            if int(stock['hldg_qty']) > 0:
                stock_dict[stock['pdno']] = stock['hldg_qty']
                send_message(f"{stock['prdt_name']}({stock['pdno']}): {stock['hldg_qty']}주")
                time.sleep(0.1)
        
        send_message(f"주식 평가 금액: {evaluation[0]['scts_evlu_amt']}원")
        time.sleep(0.1)
        send_message(f"평가 손익 합계: {evaluation[0]['evlu_pfls_smtl_amt']}원")
        time.sleep(0.1)
        send_message(f"=================")
        
        return stock_dict
        
    except Exception as e:
        error_msg = str(e).lower()
        if 'access_token' in error_msg:
            send_message(f"주식 잔고 조회 중 토큰 오류: {e}")
            # 토큰 갱신 시도
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                # 재귀적으로 다시 시도
                return get_stock_balance()
        else:
            send_message(f"주식 잔고 조회 중 오류: {e}")
        return {}

def buy(code, qty, price=0):
    """주식 시장가/지정가 매수"""
    global ACCESS_TOKEN
    
    PATH = "uapi/domestic-stock/v1/trading/order-cash"
    URL = f"{URL_BASE}/{PATH}"
    
    # 지정가인지 시장가인지 확인
    if price == 0:
        ord_dvsn = "01"  # 시장가
    else:
        ord_dvsn = "00"  # 지정가
        price = str(price)
    
    # 토큰 확인
    if not ACCESS_TOKEN:
        ACCESS_TOKEN = get_access_token()
        if not ACCESS_TOKEN:
            send_message(f"{code} 매수 실패: 토큰 없음", code)
            return False
    
    data = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "PDNO": code,
        "ORD_DVSN": ord_dvsn,
        "ORD_QTY": str(int(qty)),
        "ORD_UNPR": "0" if ord_dvsn == "01" else price,
    }
    
    # 해시키 생성
    hash_key = hashkey(data)
    if not hash_key:
        send_message(f"{code} 매수 실패: 해시키 생성 오류", code)
        return False
    
    headers = {
        "Content-Type": "application/json", 
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "tr_id": "TTTC0802U",
        "custtype": "P",
        "hashkey": hash_key
    }
    
    try:
        res = requests.post(URL, headers=headers, data=json.dumps(data))
        
        # 토큰 오류 처리
        if res.status_code == 401 or (res.status_code == 200 and 'access_token' in res.text.lower()):
            send_message(f"{code} 매수 중 토큰 오류. 토큰 갱신 중...", code)
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                # 새 토큰으로 다시 시도
                headers["authorization"] = f"Bearer {ACCESS_TOKEN}"
                hash_key = hashkey(data)  # 해시키 재생성
                if hash_key:
                    headers["hashkey"] = hash_key
                    res = requests.post(URL, headers=headers, data=json.dumps(data))
                else:
                    send_message(f"{code} 매수 실패: 해시키 재생성 오류", code)
                    return False
            else:
                send_message(f"{code} 매수 실패: 토큰 갱신 실패", code)
                return False
                
        if res.status_code != 200:
            send_message(f"{code} 매수 실패: 상태 코드 {res.status_code}", code)
            return False
            
        res_data = res.json()
        if res_data['rt_cd'] == '0':
            price_type = "시장가" if ord_dvsn == "01" else f"{price}원"
            send_message(f"✅ {code} {qty}주 {price_type} 매수 주문 성공", code)
            return True
        else:
            send_message(f"❌ {code} 매수 실패: {res_data['msg1']}", code)
            return False
            
    except Exception as e:
        error_msg = str(e).lower()
        if 'access_token' in error_msg:
            send_message(f"{code} 매수 중 토큰 오류: {e}", code)
            # 토큰 갱신 시도
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                # 재귀적으로 다시 시도
                return buy(code, qty, price)
        else:
            send_message(f"{code} 매수 중 오류: {e}", code)
        return False

def sell(code, qty="all", price=0):
    """주식 시장가/지정가 매도"""
    global ACCESS_TOKEN
    
    PATH = "uapi/domestic-stock/v1/trading/order-cash"
    URL = f"{URL_BASE}/{PATH}"
    
    # 보유 주식 확인
    try:
        stock_dict = get_stock_balance()
        if code not in stock_dict:
            send_message(f"❌ {code} 종목을 보유하고 있지 않습니다", code)
            return False

        held_qty = int(stock_dict[code])

        # "all" 입력 시 보유 수량 전량 매도
        if qty == "all":
            qty = held_qty
        else:
            qty = int(qty)

        # 보유 수량보다 많은 수량을 매도하려는 경우 방지
        if qty > held_qty:
            send_message(f"❌ 매도 수량({qty})이 보유 수량({held_qty})을 초과합니다", code)
            return False
            
        # 지정가인지 시장가인지 확인
        if price == 0:
            ord_dvsn = "01"  # 시장가
        else:
            ord_dvsn = "00"  # 지정가
            price = str(price)
        
        # 토큰 확인
        if not ACCESS_TOKEN:
            ACCESS_TOKEN = get_access_token()
            if not ACCESS_TOKEN:
                send_message(f"{code} 매도 실패: 토큰 없음", code)
                return False
        
        price_type = "시장가" if ord_dvsn == "01" else f"{price}원"
        send_message(f"매도 주문 시작: {code} {qty}주 {price_type}", code)
        
        data = {
            "CANO": CANO,
            "ACNT_PRDT_CD": ACNT_PRDT_CD,
            "PDNO": code,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(int(qty)),
            "ORD_UNPR": "0" if ord_dvsn == "01" else price,
        }
        
        # 해시키 생성
        hash_key = hashkey(data)
        if not hash_key:
            send_message(f"{code} 매도 실패: 해시키 생성 오류", code)
            return False
        
        headers = {
            "Content-Type": "application/json", 
            "authorization": f"Bearer {ACCESS_TOKEN}",
            "appKey": APP_KEY,
            "appSecret": APP_SECRET,
            "tr_id": "TTTC0801U",
            "custtype": "P",
            "hashkey": hash_key
        }
        
        try:
            res = requests.post(URL, headers=headers, data=json.dumps(data))
            
            # 토큰 오류 처리
            if res.status_code == 401 or (res.status_code == 200 and 'access_token' in res.text.lower()):
                send_message(f"{code} 매도 중 토큰 오류. 토큰 갱신 중...", code)
                ACCESS_TOKEN = get_access_token()
                if ACCESS_TOKEN:
                    # 새 토큰으로 다시 시도
                    headers["authorization"] = f"Bearer {ACCESS_TOKEN}"
                    hash_key = hashkey(data)  # 해시키 재생성
                    if hash_key:
                        headers["hashkey"] = hash_key
                        res = requests.post(URL, headers=headers, data=json.dumps(data))
                    else:
                        send_message(f"{code} 매도 실패: 해시키 재생성 오류", code)
                        return False
                else:
                    send_message(f"{code} 매도 실패: 토큰 갱신 실패", code)
                    return False
            
            # 주문 결과 확인
            if res.status_code != 200:
                send_message(f"{code} 매도 실패: 상태 코드 {res.status_code}", code)
                return False
                
            res_data = res.json()
            if res_data['rt_cd'] == '0':
                send_message(f"✅ {code} {qty}주 {price_type} 매도 주문 성공", code)
                return True
            else:
                send_message(f"❌ {code} 매도 실패: {res_data['msg1']}", code)
                return False
                
        except Exception as e:
            error_msg = str(e).lower()
            if 'access_token' in error_msg:
                send_message(f"{code} 매도 중 토큰 오류: {e}", code)
                # 토큰 갱신 시도
                ACCESS_TOKEN = get_access_token()
                if ACCESS_TOKEN:
                    # 재귀적으로 다시 시도
                    return sell(code, qty, price)
            else:
                send_message(f"{code} 매도 중 오류: {e}", code)
            return False
            
    except Exception as e:
        send_message(f"{code} 매도 준비 중 오류: {str(e)}", code)
        return False

def main():
    """메인 함수"""
    global ACCESS_TOKEN
    
    token_retry_count = 0
    max_token_retries = 5
    
    while True:  # 메인 무한 루프
        try:
            # 토큰이 없거나 토큰 오류 후 재시작한 경우
            if not ACCESS_TOKEN:
                ACCESS_TOKEN = get_access_token()
                if not ACCESS_TOKEN:
                    send_message("토큰 발급 실패, 1분 후 재시도...")
                    time.sleep(60)
                    token_retry_count += 1
                    if token_retry_count > max_token_retries:
                        send_message(f"토큰 발급 {max_token_retries}회 실패, 10분 후 다시 시도합니다.")
                        time.sleep(600)
                        token_retry_count = 0
                    continue
                token_retry_count = 0
                
            bought_list = []  # 매수 완료된 종목 리스트
            
            # 초기 시장 체크
            market_open = is_market_open()
            if not market_open:
                wait_for_market_open()
                continue
            
            # 매매 대상 종목 수와 매수 비율 설정
            target_buy_count = min(3, len(SYMBOLS))  # 최대 3개 종목 매수
            
            # 프로그램 시작 메시지
            send_message(f"=== RSI 기반 국내 주식 자동매매 프로그램 시작 ===")
            send_message(f"매수 대상 종목: {SYMBOLS}")
            send_message(f"매수 비율: 보유 금액의 {BUY_RATIO*100}%")
            
            # 시간대 설정
            tz = timezone('Asia/Seoul')
            last_token_refresh = datetime.datetime.now(tz)
            
            # 초기 실행 설정
            force_first_check = True
            last_check_time = datetime.datetime.now(tz) - datetime.timedelta(minutes=31)
            
            # 이미 보유 중인 종목 확인
            stock_dict = get_stock_balance()
            for code in stock_dict.keys():
                if code not in bought_list:
                    bought_list.append(code)
            
            # 내부 루프 - 정상 실행
            while True:
                current_time = datetime.datetime.now(tz)
                
                # 토큰 갱신 (3시간마다)
                if (current_time - last_token_refresh).total_seconds() >= 10800:
                    refresh_token()
                    last_token_refresh = current_time
                
                # 시장 상태 확인
                market_open = is_market_open()
                if not market_open:
                    send_message("장이 마감되었습니다. 다음 개장일까지 대기합니다...")
                    wait_for_market_open()
                    continue
                
                # RSI 체크 조건 (매 30분마다 또는 첫 실행 시)
                minutes_elapsed = (current_time - last_check_time).total_seconds() / 60
                time_to_check = current_time.minute % 30 == 0 and current_time.second < 30
                
                if force_first_check or (minutes_elapsed >= 29 and time_to_check):
                    # 현금 잔고 확인
                    total_cash = get_balance()
                    if total_cash <= 0:
                        send_message("💰 주문 가능 현금이 없습니다. 다음 체크까지 대기...")
                        time.sleep(60)
                        continue
                        
                    # 종목별 매수 금액 계산
                    buy_amount = total_cash * BUY_RATIO
                    
                    # 현재 보유 종목 확인
                    stock_dict = get_stock_balance()
                    for code in stock_dict.keys():
                        if code not in bought_list:
                            bought_list.append(code)
                    
                    # 종목별 처리
                    for code in SYMBOLS:
                        try:
                            # RSI 조회
                            current_rsi = get_current_rsi(code)
                            if current_rsi is None:
                                send_message(f"RSI 계산 실패, 다음 종목으로 넘어갑니다", code)
                                continue
                            send_message(f"현재 RSI: {current_rsi:.2f}", code)
                            
                            # 현재가 조회
                            current_price = get_current_price(code)
                            if current_price is None:
                                send_message(f"현재가 조회 실패", code)
                                continue
                            send_message(f"현재가: {current_price}원", code)
                            
                            # 매수 조건 (RSI가 30 이하이고 매수 리스트에 없는 경우)
                            if current_rsi <= RSI_OVERSOLD:
                                if len(bought_list) < target_buy_count and code not in bought_list:
                                    send_message(f"매수 신호 감지 (RSI: {current_rsi:.2f})", code)
                                    
                                    # 매수 수량 계산
                                    qty = int(buy_amount // current_price)
                                    
                                    if qty > 0:
                                        total_cost = qty * current_price
                                        
                                        send_message(f"- 매수 가능 금액: {buy_amount:.0f}원", code)
                                        send_message(f"- 주문 수량: {qty}주", code)
                                        send_message(f"- 주문 가격: {current_price}원", code)
                                        send_message(f"- 총 주문 금액: {total_cost:.0f}원", code)
                                        
                                        # 매수 실행
                                        buy_result = buy(code, qty)
                                        if buy_result:
                                            bought_list.append(code)
                                            send_message(f"✅ {code} {qty}주 매수 완료", code)
                                    else:
                                        send_message(f"❌ 계산된 매수 수량이 0입니다", code)
                                else:
                                    if code in bought_list:
                                        send_message(f"이미 보유 중인 종목입니다", code)
                                    else:
                                        send_message(f"최대 매수 종목 수({target_buy_count})에 도달했습니다", code)
                            
                            # 매도 조건 (RSI가 70 이상이고 해당 종목 보유 중인 경우)
                            elif current_rsi >= RSI_OVERBOUGHT:
                                if code in stock_dict:
                                    send_message(f"매도 신호 감지 (RSI: {current_rsi:.2f})", code)
                                    sell_result = sell(code, "all")
                                    if sell_result:
                                        if code in bought_list:
                                            bought_list.remove(code)
                                        send_message(f"✅ {code} 매도 완료", code)
                            
                            # 그 외 상태 메시지
                            else:
                                send_message(f"현재 RSI {current_rsi:.2f}는 매수/매도 구간이 아닙니다", code)
                                
                        except Exception as e:
                            send_message(f"🚨 {code} 처리 중 오류: {str(e)}", code)
                            continue
                    
                    # 다음 체크를 위한 설정 업데이트
                    last_check_time = current_time
                    force_first_check = False
                    
                    # 다음 체크 시간 계산
                    next_check_minutes = 30 - (current_time.minute % 30)
                    if next_check_minutes == 0:
                        next_check_minutes = 30
                    send_message(f"⏳ 다음 RSI 체크까지 약 {next_check_minutes}분 남았습니다")
                    
                # 장 마감 체크 (15:20 이후)
                if current_time.hour >= 15 and current_time.minute >= 20:
                    # 보유 종목 매도
                    send_message("장 마감 시간이 다가옵니다. 보유 종목을 매도합니다.")
                    stock_dict = get_stock_balance()
                    for code, qty in stock_dict.items():
                        sell(code, qty)
                    
                    send_message("📉 장 마감으로 프로그램을 종료합니다. 다음 개장일까지 대기합니다.")
                    wait_for_market_open()
                    break
                
                # 짧은 대기 후 루프 계속
                time.sleep(1)
                
        except Exception as main_error:
            error_msg = str(main_error).lower()
            send_message(f"🚨 [메인 루프 오류 발생] {error_msg}")
            
            # 토큰 관련 오류인 경우
            if 'access_token' in error_msg:
                send_message("토큰 오류로 인한 재시작, 1분 후 토큰 재발급을 시도합니다.")
                ACCESS_TOKEN = None  # 토큰 초기화
                time.sleep(60)
            else:
                # 그 외 오류는 3분 대기 후 재시작
                send_message("3분 후 프로그램을 재시작합니다...")
                time.sleep(180)

if __name__ == "__main__":
    main()
