#0308버전에서 Access Token 오류 수정 버전

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
SYMBOLS = ["PLTR", "NVDA","IONQ","TSLA"]  # 여러 심볼 추가 "IONQ" 제외외 "TSLA"

def send_message(msg, symbol=None):
    """디스코드 메세지 전송 (심볼 정보 추가)"""
    now = datetime.now()
    symbol_info = f"[{symbol}] " if symbol else ""
    message = {"content": f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {symbol_info}{str(msg)}"}
    requests.post(DISCORD_WEBHOOK_URL, data=message)
    print(message)


def get_access_token():
    """토큰 발급 (오류 처리 추가)"""
    global ACCESS_TOKEN
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
            
        ACCESS_TOKEN = res.json()["access_token"]
        print(f"새로운 토큰 발급")
        return ACCESS_TOKEN
    except Exception as e:
        send_message(f"🚨 토큰 발급 중 오류 발생: {str(e)}")
        return None

def refresh_token():
    """토큰 갱신"""
    global ACCESS_TOKEN
    try:
        ACCESS_TOKEN = get_access_token()
        if ACCESS_TOKEN:
            print(f"토큰 갱신 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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

def is_market_time():
    """미국 시장 시간 체크"""
    try:
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
    except Exception as e:
        send_message(f"🚨 시장 시간 확인 중 오류: {str(e)}")
        # 오류 발생 시 기본적으로 닫힘으로 처리
        return False


def wait_for_market_open():
    """시장 개장 대기 (주말 처리 개선)"""
    try:
        send_message("미국 시장이 닫혀 있습니다. 개장까지 대기합니다...")
        
        while not is_market_time():
            # 현재 미국 시간 확인
            nas_time = datetime.now(timezone('America/New_York'))
            
            # 다음 체크 시간 결정
            next_check = 60  # 기본 대기 시간 60분
            
            # 개장일(월~금) 확인
            weekday = nas_time.weekday()  # 0=월요일, 6=일요일
            is_weekend = weekday >= 5  # 주말 여부
            
            if is_weekend:
                # 일요일 && 15시 이후 - 개장 임박
                if weekday == 6 and nas_time.hour >= 15:
                    next_check = 180
                # 토요일 또는 일요일 오전 - 여전히 많은 시간 남음칟ㅁㄱㄱ
                else:
                    next_check = 240  # 주말에는 4시간 간격으로 체크
            else:
                # 평일
                # 16시 이후 또는 00시~08시까지는 240분 단위 대기 120
                if nas_time.hour >= 16 or nas_time.hour < 8:
                    next_check = 240
                # 08시~09시 - 개장 준비 시간
                elif nas_time.hour == 8:
                    next_check = 15  # 15분 간격으로 체크
                # 09시 이후부터 개장 전(09:30 전)까지는 5분 단위 대기
                elif nas_time.hour == 9 and nas_time.minute < 30:
                    next_check = 5
                else:
                    next_check = 30  # 다른 평일 시간대
            
            send_message(f"다음 확인까지 {next_check}분 대기... (미국시간: {nas_time.strftime('%Y-%m-%d %H:%M')} {['월','화','수','목','금','토','일'][weekday]}요일)")
            time.sleep(next_check * 60)
        
        send_message("미국 시장이 개장되었습니다!")
        if not refresh_token():  # 시장 개장 시 토큰 갱신
            send_message("토큰 갱신에 실패했습니다. 1분 후 다시 시도합니다.")
            time.sleep(60)
            refresh_token()
    except Exception as e:
        send_message(f"🚨 시장 개장 대기 중 오류: {str(e)}")
        time.sleep(60)  # 오류 발생 시 1분 대기 후 재시도


# 평일과 주말을 구분하여 더 효율적인 대기 시간 설정
# 주말(토, 일)에는 기본적으로 3시간 단위로 체크하여 리소스 절약
# 일요일 오후(15시 이후)부터는 개장이 가까워져 5분 단위로 더 자주 체크
# 평일 오전에도 시간대별로 체크 주기 차등화:

# 개장 직전(9시~9시30분): 5분 간격
# 개장 준비 시간(8시~9시): 15분 간격
# 새벽/야간(16시 이후, 8시 이전): 60분 간격

# 메시지에 요일 정보 추가로 더 명확한 상태 안내

#2파트

def get_minute_data(symbol, nmin=30, period=2, access_token=""):
    """분봉 데이터 조회 (다중 심볼 대응 + 토큰 오류 처리)"""
    global ACCESS_TOKEN
    
    print(f"분봉 데이터 조회 시작 - 종목: {symbol}, 시간간격: {nmin}분")
    PATH = "/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
    URL = f"{URL_BASE}/{PATH}"
    
    # 각 종목별 시장 정보 매핑
    MARKET_MAP = {
        "PLTR": {"EXCD": "NAS", "MARKET": "NASD"},
        "NVDA": {"EXCD": "NAS", "MARKET": "NASD"},
        "TSLA": {"EXCD": "NAS", "MARKET": "NASD"},
        "IONQ": {"EXCD": "NYS", "MARKET": "NYSE"}
    }
    
    # 해당 심볼의 거래소 정보 가져오기
    market_info = MARKET_MAP.get(symbol, {"EXCD": EXCD_MARKET, "MARKET": MARKET})
    
    all_data = []
    next_key = ""
    
    # 토큰 체크
    if not access_token:
        ACCESS_TOKEN = get_access_token()
        if not ACCESS_TOKEN:
            print("토큰 발급 실패, 1분 후 재시도...")
            time.sleep(60)
            ACCESS_TOKEN = get_access_token()
            if not ACCESS_TOKEN:
                return None
        access_token = ACCESS_TOKEN
        
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
        
        try:
            res = requests.get(URL, headers=headers, params=params)
            
            # 응답 코드가 만료된 토큰 오류인 경우
            if res.status_code == 401 or (res.status_code == 200 and 'access_token' in res.text.lower()):
                print("토큰이 만료되었습니다. 새 토큰을 발급합니다.")
                ACCESS_TOKEN = get_access_token()
                if ACCESS_TOKEN:
                    # 새 토큰으로 다시 시도
                    headers['authorization'] = f'Bearer {ACCESS_TOKEN}'
                    res = requests.get(URL, headers=headers, params=params)
                else:
                    print("토큰 재발급 실패, 1분 후 다시 시도합니다.")
                    time.sleep(60)
                    continue
            
            if res.status_code == 200:
                data = res.json()
                if "output2" in data and data["output2"]:
                    all_data.extend(data["output2"])
                    next_key = data.get("output1", {}).get("next", "")
                    if not next_key:
                        break
                else:
                    print(f" 요청 코드: {symbol}, 거래소: {market_info['MARKET']}")
                    break
            else:
                print(f"API 호출 실패. 상태 코드: {res.status_code}, 응답 내용: {res.text}")
                break
        except Exception as e:
            print(f"데이터 요청 중 오류 발생: {e}")
            time.sleep(1)
            break
            
        time.sleep(0.5)
    
    print(f"{symbol} 조회된 데이터 수: {len(all_data)}")
    return {"output2": all_data} if all_data else None

def calculate_rsi(data, periods=14):
    """RSI 계산 (강화된 다중 심볼 대응 버전)"""
    try:
        # 데이터 유효성 확인
        if "output2" not in data or not data["output2"]:
            print("RSI 계산을 위한 데이터가 부족합니다")
            return 50

        # 데이터프레임 생성
        df = pd.DataFrame(data["output2"])
        print(f"RSI 계산을 위한 데이터 프레임 생성 완료: {len(df)} 행")
        
        # 가격 컬럼 동적 탐색 및 처리
        price_columns = ['stck_prpr', 'ovrs_nmix_prpr', 'close', 'last', 'stck_clpr']
        
        # 가격 컬럼 찾기 및 데이터 정제
        price_col = None
        for col in price_columns:
            if col in df.columns:
                # 숫자가 아닌 값 제거, 빈 문자열 처리
                df[col] = pd.to_numeric(df[col].replace('', np.nan), errors='coerce')
                if not df[col].isnull().all():
                    price_col = col
                    break
        
        if not price_col:
            print("가격 데이터 컬럼을 찾을 수 없습니다:", df.columns)
            return 50
        
        # 가격 데이터 숫자 변환 및 결측값 처리
        df['price'] = df[price_col]
        df = df.dropna(subset=['price'])
        
        # 날짜/시간 컬럼 처리
        datetime_cols = [
            ('xymd', 'xhms', '%Y%m%d%H%M%S'),
            ('date', 'time', '%Y-%m-%d %H:%M:%S')
        ]
        
        datetime_col_found = False
        for date_col, time_col, date_format in datetime_cols:
            if date_col in df.columns and time_col in df.columns:
                try:
                    df['datetime'] = pd.to_datetime(df[date_col] + df[time_col], format=date_format)
                    datetime_col_found = True
                    break
                except:
                    continue
        
        if not datetime_col_found:
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

# def calculate_rsi(data, periods=14):
#     """RSI 계산 (다중 심볼 대응 개선 버전)"""
#     try:
#         # 데이터 유효성 확인
#         if "output2" not in data or not data["output2"]:
#             print("RSI 계산을 위한 데이터가 부족합니다")
#             return 50

#         # 데이터프레임 생성
#         df = pd.DataFrame(data["output2"])
#         print(f"RSI 계산을 위한 데이터 프레임 생성 완료: {len(df)} 행")
        
#         # 가격 컬럼 동적 탐색
#         price_columns = ['stck_prpr', 'ovrs_nmix_prpr', 'close', 'last']
#         price_col = next((col for col in price_columns if col in df.columns), None)
        
#         if not price_col:
#             print("가격 데이터 컬럼을 찾을 수 없습니다:", df.columns)
#             return 50
        
#         # 가격 데이터 숫자 변환 및 결측값 처리
#         df['price'] = pd.to_numeric(df[price_col], errors='coerce')
#         df = df.dropna(subset=['price'])
        
#         # 날짜/시간 컬럼 처리
#         if 'xymd' in df.columns and 'xhms' in df.columns:
#             df['datetime'] = pd.to_datetime(df['xymd'] + df['xhms'], format='%Y%m%d%H%M%S')
#         else:
#             print("datetime 컬럼 생성 실패")
#             return 50
        
#         # 데이터 정렬
#         df = df.sort_values(by='datetime').reset_index(drop=True)
        
#         # 데이터 충분성 확인
#         if len(df) < periods:
#             print(f"데이터 부족 (필요: {periods}, 현재: {len(df)})")
#             return 50
        
#         # RSI 계산 로직
#         delta = df['price'].diff()
#         gain = (delta.where(delta > 0, 0)).fillna(0)
#         loss = (-delta.where(delta < 0, 0)).fillna(0)
        
#         avg_gain = gain.rolling(window=periods, min_periods=periods).mean()
#         avg_loss = loss.rolling(window=periods, min_periods=periods).mean()
        
#         rs = avg_gain / avg_loss
#         rsi = 100 - (100 / (1 + rs))
        
#         # 최신 RSI 값 추출 및 반올림
#         latest_rsi = round(rsi.iloc[-1], 2)
#         print(f"RSI 계산 완료: {latest_rsi}")
#         return latest_rsi
    
#     except Exception as e:
#         print(f"RSI 계산 중 오류 발생: {e}")
#         return 50

# 다중 심볼 RSI 조회 헬퍼 함수 (선택사항)
def get_current_rsi(symbol, periods=14, nmin=30):
    """현재 RSI 조회 (다중 심볼 대응 + 토큰 오류 처리)"""
    global ACCESS_TOKEN
    print(f"RSI 조회 시작: {symbol}")
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
            symbol=symbol, 
            nmin=nmin, 
            access_token=ACCESS_TOKEN
        )
        
        if not data:
            send_message(f"{symbol} 데이터 조회 실패, RSI 계산 불가", symbol)
            return 50
            
        # RSI 계산
        rsi_value = calculate_rsi(data, periods)
        
        print(f"종목 {symbol}의 RSI 값: {rsi_value}")
        return rsi_value
    
    except Exception as e:
        error_msg = str(e).lower()
        if 'access_token' in error_msg:
            send_message(f"{symbol} RSI 조회 중 토큰 오류 발생. 토큰 갱신 시도 중...", symbol)
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                send_message("토큰 갱신 성공. 다시 시도합니다.", symbol)
                # 재귀적으로 다시 시도 (단, 무한 루프 방지를 위한 조치 필요)
                return get_current_rsi(symbol, periods, nmin)
        else:
            send_message(f"{symbol} RSI 조회 중 오류: {e}", symbol)
        return 50


def get_current_price(symbol, market=MARKET):
    """현재가 조회 (심볼 인자 추가 + 토큰 오류 처리)"""
    global ACCESS_TOKEN
    
    #여기부터 수정 
    MARKET_MAP = {
        "PLTR": {"EXCD": "NAS", "MARKET": "NASD"},
        "NVDA": {"EXCD": "NAS", "MARKET": "NASD"},
        "TSLA": {"EXCD": "NAS", "MARKET": "NASD"},
        "IONQ": {"EXCD": "NYS", "MARKET": "NYSE"}
    }
    
    # 해당 심볼의 거래소 정보 가져오기
    market_info = MARKET_MAP.get(symbol, {"EXCD": EXCD_MARKET, "MARKET": MARKET})

    PATH = "uapi/overseas-price/v1/quotations/price"
    URL = f"{URL_BASE}/{PATH}"
    
    # 토큰 확인
    if not ACCESS_TOKEN:
        ACCESS_TOKEN = get_access_token()
        if not ACCESS_TOKEN:
            send_message(f"{symbol} 현재가 조회 실패: 토큰 없음", symbol)
            return None
    
    headers = {
        "Content-Type": "application/json", 
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "tr_id": "HHDFS00000300"
    }
    params = {
        "AUTH": "",
        "EXCD": market_info["EXCD"],  #market_info["EXCD"] EXCD_MARKET
        "SYMB": symbol,
    }
    
    try:
        res = requests.get(URL, headers=headers, params=params)
        
        # 토큰 오류 처리
        if res.status_code == 401 or (res.status_code == 200 and 'access_token' in res.text.lower()):
            send_message(f"{symbol} 현재가 조회 중 토큰 오류. 토큰 갱신 중...", symbol)
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                # 새 토큰으로 다시 시도
                headers["authorization"] = f"Bearer {ACCESS_TOKEN}"
                res = requests.get(URL, headers=headers, params=params)
            else:
                send_message(f"{symbol} 토큰 갱신 실패", symbol)
                return None
        
        if res.status_code != 200:
            send_message(f"{symbol} 현재가 조회 실패: 상태 코드 {res.status_code}", symbol)
            return None
            
        data = res.json()
        if 'output' not in data or 'last' not in data['output']:
            send_message(f"{symbol} 현재가 데이터 없음: {data}", symbol)
            return None
            
        return float(data['output']['last'])
        
    except Exception as e:
        error_msg = str(e).lower()
        if 'access_token' in error_msg:
            send_message(f"{symbol} 현재가 조회 중 토큰 오류: {e}", symbol)
            # 토큰 갱신 시도
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                # 재귀적으로 다시 시도
                return get_current_price(symbol, market)
        else:
            send_message(f"{symbol} 현재가 조회 중 오류: {e}", symbol)
        return None
    


# 각 API 함수에서 오류 처리 강화

def get_balance(symbol):
    """현금 잔고조회 (심볼 인자 추가 + 토큰 오류 처리)"""
    global ACCESS_TOKEN
    
    # 각 종목별 시장 정보 매핑
    MARKET_MAP = {
        "PLTR": {"EXCD": "NAS", "MARKET": "NASD"},
        "NVDA": {"EXCD": "NAS", "MARKET": "NASD"},
        "TSLA": {"EXCD": "NAS", "MARKET": "NASD"},
        "IONQ": {"EXCD": "NYS", "MARKET": "NYSE"}
    }
    
    # 해당 심볼의 거래소 정보 가져오기
    market_info = MARKET_MAP.get(symbol, {"EXCD": EXCD_MARKET, "MARKET": MARKET})

    PATH = "/uapi/overseas-stock/v1/trading/inquire-psamount"
    URL = f"{URL_BASE}/{PATH}"
    
    # 토큰 확인
    if not ACCESS_TOKEN:
        ACCESS_TOKEN = get_access_token()
        if not ACCESS_TOKEN:
            send_message(f"{symbol} 잔고 조회 실패: 토큰 없음", symbol)
            return 0
    
    headers = {
        "Content-Type": "application/json", 
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "tr_id": "TTTS3007R",
        "custtype": "P",
    }

    # 현재가 조회
    current_price = get_current_price(symbol)
    if current_price is None:
        send_message(f"{symbol} 잔고 조회를 위한 현재가 조회 실패", symbol)
        return 0

    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "ITEM_CD": symbol,
        "OVRS_EXCG_CD": market_info["MARKET"], # MARKET
        "OVRS_ORD_UNPR": str(current_price)
    }

    try:
        res = requests.get(URL, headers=headers, params=params)
        
        # 토큰 오류 처리
        if res.status_code == 401 or (res.status_code == 200 and 'access_token' in res.text.lower()):
            send_message(f"{symbol} 잔고 조회 중 토큰 오류. 토큰 갱신 중...", symbol)
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                # 새 토큰으로 다시 시도
                headers["authorization"] = f"Bearer {ACCESS_TOKEN}"
                res = requests.get(URL, headers=headers, params=params)
            else:
                send_message(f"{symbol} 토큰 갱신 실패", symbol)
                return 0
                
        if res.status_code != 200:
            send_message(f"{symbol} 잔고 조회 실패: 상태 코드 {res.status_code}", symbol)
            return 0
            
        res_data = res.json()
        if 'output' not in res_data:
            send_message(f"🚨 API 응답 오류: {res_data}", symbol)
            return 0

        cash = res_data['output'].get('ovrs_ord_psbl_amt', '0')
        send_message(f"주문 가능 현금 잔고: {cash}$", symbol)
        
        return float(cash)
        
    except Exception as e:
        error_msg = str(e).lower()
        if 'access_token' in error_msg:
            send_message(f"{symbol} 잔고 조회 중 토큰 오류: {e}", symbol)
            # 토큰 갱신 시도
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                # 재귀적으로 다시 시도
                return get_balance(symbol)
        else:
            send_message(f"{symbol} 잔고 조회 중 오류: {e}", symbol)
        return 0

def get_stock_balance(symbol):
    """주식 잔고조회 (심볼 인자 추가 + 토큰 오류 처리)"""
    global ACCESS_TOKEN
    
    # 각 종목별 시장 정보 매핑
    MARKET_MAP = {
        "PLTR": {"EXCD": "NAS", "MARKET": "NASD"},
        "NVDA": {"EXCD": "NAS", "MARKET": "NASD"},
        "TSLA": {"EXCD": "NAS", "MARKET": "NASD"},
        "IONQ": {"EXCD": "NYS", "MARKET": "NYSE"}
    }
    
    # 해당 심볼의 거래소 정보 가져오기
    market_info = MARKET_MAP.get(symbol, {"EXCD": EXCD_MARKET, "MARKET": MARKET})

    PATH = "uapi/overseas-stock/v1/trading/inquire-balance"
    URL = f"{URL_BASE}/{PATH}"
    
    # 토큰 확인
    if not ACCESS_TOKEN:
        ACCESS_TOKEN = get_access_token()
        if not ACCESS_TOKEN:
            send_message(f"{symbol} 주식 잔고 조회 실패: 토큰 없음", symbol)
            return {}
    
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
        "OVRS_EXCG_CD": market_info["MARKET"],   # MARKET
        "TR_CRCY_CD": "USD",
        "CTX_AREA_FK200": "",
        "CTX_AREA_NK200": ""
    }
    
    try:
        res = requests.get(URL, headers=headers, params=params)
        
        # 토큰 오류 처리
        if res.status_code == 401 or (res.status_code == 200 and 'access_token' in res.text.lower()):
            send_message(f"{symbol} 주식 잔고 조회 중 토큰 오류. 토큰 갱신 중...", symbol)
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                # 새 토큰으로 다시 시도
                headers["authorization"] = f"Bearer {ACCESS_TOKEN}"
                res = requests.get(URL, headers=headers, params=params)
            else:
                send_message(f"{symbol} 토큰 갱신 실패", symbol)
                return {}
                
        if res.status_code != 200:
            send_message(f"{symbol} 주식 잔고 조회 실패: 상태 코드 {res.status_code}", symbol)
            return {}
            
        res_data = res.json()
        if 'output1' not in res_data or 'output2' not in res_data:
            send_message(f"🚨 API 응답 오류: {res_data}", symbol)
            return {}
        
        stock_list = res_data['output1']
        evaluation = res_data['output2']
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
        
    except Exception as e:
        error_msg = str(e).lower()
        if 'access_token' in error_msg:
            send_message(f"{symbol} 주식 잔고 조회 중 토큰 오류: {e}", symbol)
            # 토큰 갱신 시도
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                # 재귀적으로 다시 시도
                return get_stock_balance(symbol)
        else:
            send_message(f"{symbol} 주식 잔고 조회 중 오류: {e}", symbol)
        return {}

def buy(market=MARKET, code=SYMBOLS, qty="1", price="0"): 
    """미국 주식 지정가 매수 (토큰 오류 처리 추가)"""
    global ACCESS_TOKEN
    PATH = "uapi/overseas-stock/v1/trading/order"
    URL = f"{URL_BASE}/{PATH}"

    # 각 종목별 시장 정보 매핑
    MARKET_MAP = {
        "PLTR": {"EXCD": "NAS", "MARKET": "NASD"},
        "NVDA": {"EXCD": "NAS", "MARKET": "NASD"},
        "TSLA": {"EXCD": "NAS", "MARKET": "NASD"},
        "IONQ": {"EXCD": "NYS", "MARKET": "NYSE"}
    }
    
    # 해당 심볼의 거래소 정보 가져오기
    market_info = MARKET_MAP.get(code, {"EXCD": EXCD_MARKET, "MARKET": MARKET})

    try:
        # 🔹 주문 가격을 float으로 변환 후 소수점 2자리까지 제한
        price = round(float(price), 2)

        # 🔹 API 규칙: 주문 가격은 1$ 이상이어야 함
        if price < 1.00:
            send_message(f"🚨 [매수 실패] 주문 가격이 너무 낮습니다 (${price}). 1$ 이상이어야 합니다.", code)
            return False

        # 🔹 주문 수량을 정수로 변환
        qty = str(int(float(qty)))  

    except ValueError:
        send_message(f"🚨 [매수 실패] 주문 가격 또는 수량이 잘못된 형식입니다. (price={price}, qty={qty})", code)
        return False

    # 토큰 확인
    if not ACCESS_TOKEN:
        ACCESS_TOKEN = get_access_token()
        if not ACCESS_TOKEN:
            send_message(f"🚨 [매수 실패] 토큰이 없습니다.", code)
            return False

    # 🔹 주문 데이터 구성
    data = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "OVRS_EXCG_CD": market_info["MARKET"], # market_info["MARKET"] market
        "PDNO": code,
        "ORD_QTY": qty,  
        "OVRS_ORD_UNPR": f"{price:.2f}",  # 🔹 가격을 소수점 2자리까지 변환
        "ORD_SVR_DVSN_CD": "0",
        "ORD_DVSN": "00"  # 지정가 주문
    }

    # 해시키 생성
    hash_key = hashkey(data)
    if not hash_key:
        send_message(f"🚨 [매수 실패] 해시키 생성 오류", code)
        return False

    headers = {
        "Content-Type": "application/json", 
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "tr_id": "TTTT1002U",  # 미국 매수 주문
        "custtype": "P",
        "hashkey": hash_key
    }

    # 🔹 API 요청 실행
    try:
        res = requests.post(URL, headers=headers, data=json.dumps(data))
        
        # 토큰 오류 처리
        if res.status_code == 401 or (res.status_code == 200 and 'access_token' in res.text.lower()):
            send_message(f"🚨 [매수 중 토큰 오류] 토큰 갱신 중...", code)
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                # 새 토큰으로 다시 시도
                headers["authorization"] = f"Bearer {ACCESS_TOKEN}"
                hash_key = hashkey(data)  # 해시키 재생성
                if hash_key:
                    headers["hashkey"] = hash_key
                    res = requests.post(URL, headers=headers, data=json.dumps(data))
                else:
                    send_message(f"🚨 [매수 실패] 해시키 재생성 오류", code)
                    return False
            else:
                send_message(f"🚨 [매수 실패] 토큰 갱신 실패", code)
                return False
        
        # 🔹 주문 결과 확인
        if res.status_code != 200:
            send_message(f"🚨 [매수 실패] API 응답 오류: {res.status_code}", code)
            return False
            
        res_data = res.json()
        if res_data['rt_cd'] == '0':
            send_message(f"✅ [매수 성공] {code} {qty}주 @${price:.2f}", code)
            return True
        else:
            send_message(f"🚨 [매수 실패] {res_data.get('msg1', '알 수 없는 오류 발생')}", code)
            return False
            
    except Exception as e:
        error_msg = str(e).lower()
        if 'access_token' in error_msg:
            send_message(f"🚨 [매수 중 토큰 오류] {str(e)}", code)
            # 토큰 갱신 시도
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                # 재귀적으로 다시 시도 (무한 루프 방지 필요)
                return buy(market, code, qty, price)
        else:
            send_message(f"🚨 [매수 실패] {str(e)}", code)
        return False
     ## 달러가 있어야 하는데 없으면 잔고 부족으로 나옴

def sell(market=MARKET, code=SYMBOLS, qty="all", price="0"):
    """미국 주식 지정가 매도 (보유 수량을 자동으로 설정 가능 + 토큰 오류 처리)"""
    global ACCESS_TOKEN

    # 각 종목별 시장 정보 매핑
    MARKET_MAP = {
        "PLTR": {"EXCD": "NAS", "MARKET": "NASD"},
        "NVDA": {"EXCD": "NAS", "MARKET": "NASD"},
        "TSLA": {"EXCD": "NAS", "MARKET": "NASD"},
        "IONQ": {"EXCD": "NYS", "MARKET": "NYSE"}
    }
    
    # 해당 심볼의 거래소 정보 가져오기
    market_info = MARKET_MAP.get(code, {"EXCD": EXCD_MARKET, "MARKET": MARKET})

    PATH = "uapi/overseas-stock/v1/trading/order"
    URL = f"{URL_BASE}/{PATH}"
    
    # 보유 주식 확인
    try:
        stock_dict = get_stock_balance(code)
        if code not in stock_dict:
            send_message(f"🚨 {code} 종목을 보유하고 있지 않습니다", code)
            return False

        held_qty = int(stock_dict[code])

        # 💡 "all" 입력 시 보유 수량 전량 매도
        if qty == "all":
            qty = held_qty

        try:
            # 🔹 주문 가격을 float으로 변환 후 소수점 2자리까지 제한
            price = round(float(price), 2)

            # 🔹 API 규칙: 주문 가격은 1$ 이상이어야 함
            if price < 1.00:
                send_message(f"🚨 [매도 실패] 주문 가격이 너무 낮습니다 (${price}). 1$ 이상이어야 합니다.", code)
                return False

            # 🔹 주문 수량을 정수로 변환
            qty = str(int(float(qty)))  

        except ValueError:
            send_message(f"🚨 [매도 실패] 주문 가격 또는 수량이 잘못된 형식입니다. (price={price}, qty={qty})", code)
            return False

        # 보유 수량보다 많은 수량을 매도하려는 경우 방지
        if int(qty) > held_qty:
            send_message(f"🚨 매도 수량({qty})이 보유 수량({held_qty})을 초과합니다", code)
            return False

        # 토큰 확인
        if not ACCESS_TOKEN:
            ACCESS_TOKEN = get_access_token()
            if not ACCESS_TOKEN:
                send_message(f"🚨 [매도 실패] 토큰이 없습니다.", code)
                return False

        send_message(f"💰 매도 주문: {code} {qty}주 @ ${price:.2f}", code)

        data = {
            "CANO": CANO,
            "ACNT_PRDT_CD": ACNT_PRDT_CD,
            "OVRS_EXCG_CD": market_info["MARKET"], # market_info["MARKET"] market market,
            "PDNO": code,
            "ORD_QTY": qty,  # ✅ 매도 가능 수량 반영
            "OVRS_ORD_UNPR": f"{price:.2f}",  # 🔹 가격을 소수점 2자리까지 변환
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00"
        }
        
        # 해시키 생성
        hash_key = hashkey(data)
        if not hash_key:
            send_message(f"🚨 [매도 실패] 해시키 생성 오류", code)
            return False
        
        headers = {
            "Content-Type": "application/json", 
            "authorization": f"Bearer {ACCESS_TOKEN}",
            "appKey": APP_KEY,
            "appSecret": APP_SECRET,
            "tr_id": "TTTT1006U",  # 미국 매도 주문
            "custtype": "P",
            "hashkey": hash_key
        }
        
        try:
            res = requests.post(URL, headers=headers, data=json.dumps(data))
            
            # 토큰 오류 처리
            if res.status_code == 401 or (res.status_code == 200 and 'access_token' in res.text.lower()):
                send_message(f"🚨 [매도 중 토큰 오류] 토큰 갱신 중...", code)
                ACCESS_TOKEN = get_access_token()
                if ACCESS_TOKEN:
                    # 새 토큰으로 다시 시도
                    headers["authorization"] = f"Bearer {ACCESS_TOKEN}"
                    hash_key = hashkey(data)  # 해시키 재생성
                    if hash_key:
                        headers["hashkey"] = hash_key
                        res = requests.post(URL, headers=headers, data=json.dumps(data))
                    else:
                        send_message(f"🚨 [매도 실패] 해시키 재생성 오류", code)
                        return False
                else:
                    send_message(f"🚨 [매도 실패] 토큰 갱신 실패", code)
                    return False
            
            # 주문 결과 확인
            if res.status_code != 200:
                send_message(f"🚨 [매도 실패] API 응답 오류: {res.status_code}", code)
                return False
                
            res_data = res.json()
            if res_data['rt_cd'] == '0':
                send_message(f"✅ [매도 성공] {code} {qty}주 @ ${price:.2f}", code)
                return True
            else:
                send_message(f"🚨 [매도 실패] {res_data.get('msg1', '알 수 없는 오류 발생')}", code)
                return False
                
        except Exception as e:
            error_msg = str(e).lower()
            if 'access_token' in error_msg:
                send_message(f"🚨 [매도 중 토큰 오류] {str(e)}", code)
                # 토큰 갱신 시도
                ACCESS_TOKEN = get_access_token()
                if ACCESS_TOKEN:
                    # 재귀적으로 다시 시도 (무한 루프 방지 필요)
                    return sell(market, code, qty, price)
            else:
                send_message(f"🚨 [매도 실패] {str(e)}", code)
            return False
            
    except Exception as e:
        send_message(f"🚨 [매도 준비 중 오류] {str(e)}", code)
        return False


#3파트

def main():
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
            
            # 매수 비율 설정 (100% 활용 가능)
            BUY_RATIO = 0.30  # 100% 사용

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
            
            # 내부 루프 - 정상 실행
            while True:
                current_time = datetime.now(tz)
                NAS_time = datetime.now(timezone('America/New_York'))
                
                # 토큰 갱신 (3시간마다)
                if (current_time - last_token_refresh).total_seconds() >= 10800:
                    refresh_token()
                    last_token_refresh = current_time
                
                # RSI 체크 조건
                minutes_elapsed = (current_time - last_check_time).total_seconds() / 60
                time_to_check = (NAS_time.minute == 0 or (NAS_time.minute == 1 and NAS_time.second <= 30))

                if force_first_check or (minutes_elapsed >= 19 and time_to_check):
                    # 시장 상태 확인
                    market_open = is_market_time()
                    if not market_open:
                        wait_for_market_open()
                        last_check_time = current_time
                        force_first_check = False
                        continue
                    
                    # 각 심볼에 대한 처리...
                    for symbol in SYMBOLS:
                        try:
                            KST_time = datetime.now(timezone('Asia/Seoul'))
                            
                            # RSI 조회 시도
                            try:
                                current_rsi = get_current_rsi(symbol)
                                if current_rsi is None:
                                    send_message(f"RSI 계산 실패, 다음 종목으로 넘어갑니다", symbol)
                                    continue
                                send_message(f"현재 RSI: {current_rsi:.2f}", symbol)
                            except Exception as e:
                                if 'access_token' in str(e).lower():
                                    send_message(f"토큰 오류 감지, 토큰 갱신 후 재시도합니다", symbol)
                                    ACCESS_TOKEN = get_access_token()
                                    if not ACCESS_TOKEN:
                                        raise Exception("토큰 재발급 실패")
                                    continue
                                else:
                                    send_message(f"RSI 계산 중 오류: {str(e)}", symbol)
                                    continue
                            
                            # 현재가 조회
                            try:
                                current_price = get_current_price(symbol)
                                if current_price is None:
                                    send_message(f"현재가 조회 실패", symbol)
                                    continue
                            except Exception as e:
                                if 'access_token' in str(e).lower():
                                    send_message(f"토큰 오류 감지, 토큰 갱신 후 재시도합니다", symbol)
                                    ACCESS_TOKEN = get_access_token()
                                    if not ACCESS_TOKEN:
                                        raise Exception("토큰 재발급 실패")
                                    continue
                                else:
                                    send_message(f"현재가 조회 중 오류: {str(e)}", symbol)
                                    continue
                            
                            # 매수 조건
                            if current_rsi <= 30:
                                send_message(f"매수 신호 감지 (RSI: {current_rsi:.2f})", symbol)
                                
                                # 현재 잔고 조회
                                try:
                                    cash_balance = get_balance(symbol)
                                    if cash_balance <= 0:
                                        send_message(f"주문 가능 잔고가 없습니다", symbol)
                                        continue
                                except Exception as e:
                                    if 'access_token' in str(e).lower():
                                        send_message(f"토큰 오류 감지, 토큰 갱신 후 재시도합니다", symbol)
                                        ACCESS_TOKEN = get_access_token()
                                        continue
                                    else:
                                        send_message(f"잔고 조회 중 오류: {str(e)}", symbol)
                                        continue
                                
                                # 환율 조회
                                #exchange_rate = get_exchange_rate()
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
                                        try:
                                            buy_result = buy(code=symbol, qty=str(qty), price=str(current_price))
                                            if buy_result:
                                                bought_list.append(symbol)
                                                send_message(f"✅ {symbol} {qty}주 매수 완료", symbol)
                                        except Exception as e:
                                            if 'access_token' in str(e).lower():
                                                send_message(f"매수 중 토큰 오류, 토큰 갱신 후 재시도합니다", symbol)
                                                ACCESS_TOKEN = get_access_token()
                                                continue
                                            else:
                                                send_message(f"매수 중 오류: {str(e)}", symbol)
                                    else:
                                        send_message(f"❌ 안전 마진 적용 후 주문 불가", symbol)
                                else:
                                    send_message(f"❌ 계산된 매수 수량이 0입니다", symbol)
                            
                            # 매도 조건
                            elif current_rsi >= 70:
                                send_message(f"매도 신호 감지 (RSI: {current_rsi:.2f})", symbol)
                                try:
                                    stock_dict = get_stock_balance(symbol)
                                    if symbol in stock_dict:
                                        qty = stock_dict[symbol]
                                        try:
                                            sell_result = sell(code=symbol, qty=str(qty), price=str(current_price))
                                            if sell_result:
                                                send_message(f"✅ {symbol} 매도 완료", symbol)
                                        except Exception as e:
                                            if 'access_token' in str(e).lower():
                                                send_message(f"매도 중 토큰 오류, 토큰 갱신 후 재시도합니다", symbol)
                                                ACCESS_TOKEN = get_access_token()
                                                continue
                                            else:
                                                send_message(f"매도 중 오류: {str(e)}", symbol)
                                    else:
                                        send_message(f"❌ {symbol}을 보유하고 있지 않습니다", symbol)
                                except Exception as e:
                                    if 'access_token' in str(e).lower():
                                        send_message(f"주식 잔고 조회 중 토큰 오류, 토큰 갱신 후 재시도합니다", symbol)
                                        ACCESS_TOKEN = get_access_token()
                                        continue
                                    else:
                                        send_message(f"주식 잔고 조회 중 오류: {str(e)}", symbol)
                                        continue
                        except Exception as symbol_error:
                            send_message(f"🚨 {symbol} 처리 중 오류: {str(symbol_error)}")
                            continue
                    
                    last_check_time = current_time
                    force_first_check = False
                    
                    # 다음 체크 시간 계산 60분 단위로 수정 원래는 30분
                    next_check_minutes = 60 - (NAS_time.minute % 60)
                    if next_check_minutes == 0:
                        next_check_minutes = 60
                    send_message(f"⏳ 다음 RSI 체크까지 약 {next_check_minutes}분 남았습니다")
                    
                    # 정확히 다음 RSI 체크까지 대기
                    time.sleep(next_check_minutes * 60)

                # 장 마감 체크
                if NAS_time.hour >= 16:
                    send_message("📉 미국 장 마감으로 프로그램을 종료합니다.")
                    wait_for_market_open()
                    continue
                
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