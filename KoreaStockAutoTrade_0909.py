#0404버전에서 
# # 국내 주식 거래  종목 변경
#0412버전에서
# # 국내 휴일 오류 수정 추가
#0505버전에서 매수 조건을 수정함
#장기이동평균 20일 대비 높은 가격일 경우에는 매수 하지 않도록 수정함
#0628버전에서 커거AI 코드 수정
#중복 메세지 차단 추가  
#추가 수정 하려고 준비중


#파트1

import requests
import json
import datetime
import time
import yaml
import pandas as pd
from pytz import timezone

# config.yaml 파일 로드
with open('config.yaml', encoding='UTF-8') as f:
    config = yaml.load(f, Loader=yaml.FullLoader)
APP_KEY = config['APP_KEY']
APP_SECRET = config['APP_SECRET']
ACCESS_TOKEN = ""
CANO = config['CANO']
ACNT_PRDT_CD = config['ACNT_PRDT_CD']
DISCORD_WEBHOOK_URL = config['DISCORD_WEBHOOK_URL']
URL_BASE = config['URL_BASE']

# 매매 대상 종목 리스트 (종목코드)
#SYMBOLS = ["005930","000660","069500", "371110" ]  # 삼성전자, SK하이닉스, 차이나항생테크, #LGDisplay
SYMBOLS = ["005930","000660","069500", "449450","064350","079550" ]  # 삼성전자, SK하이닉스, 차이나항생테크, PLUS K방산, 현대로템,LIG넥스원

# 매수/매도 기준 RSI 값
RSI_OVERSOLD = 28  # RSI가 이 값 이하면 매수 신호
RSI_OVERBOUGHT = 73  # RSI가 이 값 이상이면 매도 신호

# RSI 계산 기간 및 분봉 설정
RSI_PERIOD = 14  # RSI 계산 기간
MINUTE_CANDLE = 30  # 분봉 (30분봉 사용)

# 이동평균 설정
MA_PERIOD = 20  # 장기 이동평균 기간 (20일)

# 매도 설정
PROFIT_TAKE_PERCENT = 10.0          # 익절 기준: 수익률 (%) - 양수로 입력하세요

# 매매 비율 설정
BUY_RATIO = 0.3  # 계좌 잔고의 30%를 사용

# ===== 메시지 최적화 설정 =====
# 메시지 중요도 레벨
MESSAGE_LEVEL_CRITICAL = 1    # 오류, 매수/매도 완료, 손절매
MESSAGE_LEVEL_IMPORTANT = 2   # 매수/매도 신호, 잔고 정보
MESSAGE_LEVEL_INFO = 3        # 일반 정보, 분석 결과
MESSAGE_LEVEL_DEBUG = 4       # 상세 디버그 정보

# 전송할 메시지 레벨 (1=중요한 것만, 4=모든 메시지)
MESSAGE_SEND_LEVEL = MESSAGE_LEVEL_IMPORTANT

# 반복 메시지 필터링
MESSAGE_COOLDOWN = 300        # 같은 메시지 재전송 방지 시간 (초)
MESSAGE_HISTORY = {}          # 메시지 히스토리 저장

# 배치 발송 설정
ENABLE_BATCH_SEND = True      # 배치 발송 활성화
BATCH_SEND_INTERVAL = 60      # 배치 발송 간격 (초)
MAX_BATCH_SIZE = 10           # 최대 배치 크기
MESSAGE_BATCH = []            # 배치 메시지 저장
LAST_BATCH_SEND = 0           # 마지막 배치 발송 시간

# AWS 환경에서 메시지 압축
ENABLE_MESSAGE_COMPRESSION = True  # 메시지 압축 활성화
# ===== 메시지 최적화 설정 끝 =====

# ===== 토큰 발급 중복 방지 설정 =====
TOKEN_REQUEST_COOLDOWN = 120  # 토큰 발급 요청 간격 (초) - 서버 이상 대응을 위해 2분으로 조정
LAST_TOKEN_REQUEST_TIME = 0  # 마지막 토큰 발급 요청 시간
TOKEN_REQUEST_IN_PROGRESS = False  # 토큰 발급 진행 중 플래그
# ===== 토큰 발급 중복 방지 설정 끝 =====

def send_message(msg, symbol=None, level=MESSAGE_LEVEL_INFO):
    """디스코드 메시지 전송 (최적화된 버전)"""
    global MESSAGE_HISTORY, MESSAGE_BATCH, LAST_BATCH_SEND
    
    # 메시지 레벨 필터링
    if level > MESSAGE_SEND_LEVEL:
        return  # 설정된 레벨보다 낮은 중요도면 전송하지 않음
    
    # 메시지 내용 생성
    now = datetime.datetime.now()
    symbol_info = f"[{symbol}] " if symbol else ""
    
    # 메시지 압축 (같은 내용 반복 방지)
    if ENABLE_MESSAGE_COMPRESSION:
        msg = compress_message(str(msg))
    
    full_message = f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {symbol_info}{str(msg)}"
    
    # 반복 메시지 필터링
    msg_hash = hash(f"{symbol}_{msg}")
    current_time = time.time()
    
    if msg_hash in MESSAGE_HISTORY:
        if current_time - MESSAGE_HISTORY[msg_hash] < MESSAGE_COOLDOWN:
            return  # 쿨다운 시간 내 같은 메시지는 전송하지 않음
    
    MESSAGE_HISTORY[msg_hash] = current_time
    
    # 배치 발송 처리
    if ENABLE_BATCH_SEND and level > MESSAGE_LEVEL_CRITICAL:
        MESSAGE_BATCH.append(full_message)
        
        # 배치가 가득 찼거나 시간이 지났으면 발송
        if len(MESSAGE_BATCH) >= MAX_BATCH_SIZE or (current_time - LAST_BATCH_SEND) >= BATCH_SEND_INTERVAL:
            send_batch_messages()
    else:
        # 중요한 메시지는 즉시 발송
        send_immediate_message(full_message)
    
    # 콘솔 출력 (로컬 디버깅용)
    print(f"[Level {level}] {full_message}")

def compress_message(msg):
    """메시지 압축 - 반복되는 패턴 제거"""
    # 불필요한 단어 제거
    unnecessary_words = [
        "조회 중...", "확인 중...", "처리 중...", "분석 중...",
        "데이터", "정보", "상태", "결과"
    ]
    
    compressed = msg
    for word in unnecessary_words:
        if word in compressed and len(compressed) > 50:  # 긴 메시지에서만 압축
            compressed = compressed.replace(word, "")
    
    return compressed.strip()

def send_immediate_message(message):
    """즉시 메시지 발송"""
    try:
        message_data = {"content": message}
        requests.post(DISCORD_WEBHOOK_URL, data=message_data, timeout=5)
    except Exception as e:
        print(f"메시지 발송 실패: {e}")

def send_batch_messages():
    """배치 메시지 발송"""
    global MESSAGE_BATCH, LAST_BATCH_SEND
    
    if not MESSAGE_BATCH:
        return
    
    try:
        # 배치 메시지를 하나로 합치기
        batch_content = "\n".join(MESSAGE_BATCH[-MAX_BATCH_SIZE:])  # 최대 크기 제한
        message_data = {"content": f"📊 **배치 업데이트**\n```\n{batch_content}\n```"}
        
        requests.post(DISCORD_WEBHOOK_URL, data=message_data, timeout=10)
        MESSAGE_BATCH.clear()
        LAST_BATCH_SEND = time.time()
        
        print(f"배치 메시지 발송 완료: {len(MESSAGE_BATCH)} 건")
    except Exception as e:
        print(f"배치 메시지 발송 실패: {e}")

def cleanup_message_history():
    """오래된 메시지 히스토리 정리"""
    global MESSAGE_HISTORY
    current_time = time.time()
    MESSAGE_HISTORY = {k: v for k, v in MESSAGE_HISTORY.items() 
                      if current_time - v < MESSAGE_COOLDOWN * 2}

def get_access_token():
    """토큰 발급 (중복 방지 로직 포함)"""
    global LAST_TOKEN_REQUEST_TIME, TOKEN_REQUEST_IN_PROGRESS
    
    current_time = time.time()
    
    # 토큰 발급 진행 중이면 대기
    if TOKEN_REQUEST_IN_PROGRESS:
        send_message("토큰 발급이 이미 진행 중입니다. 대기합니다...", level=MESSAGE_LEVEL_DEBUG)
        return None
    
    # 쿨다운 시간 체크
    if current_time - LAST_TOKEN_REQUEST_TIME < TOKEN_REQUEST_COOLDOWN:
        remaining_time = TOKEN_REQUEST_COOLDOWN - (current_time - LAST_TOKEN_REQUEST_TIME)
        send_message(f"토큰 발급 쿨다운 중입니다. {remaining_time:.0f}초 후 재시도 가능합니다.", level=MESSAGE_LEVEL_DEBUG)
        return None
    
    # 토큰 발급 시작
    TOKEN_REQUEST_IN_PROGRESS = True
    LAST_TOKEN_REQUEST_TIME = current_time
    
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
            send_message(f"토큰 발급 실패: 상태 코드 {res.status_code}", level=MESSAGE_LEVEL_CRITICAL)
            return None
            
        access_token = res.json()["access_token"]
        send_message("✅ 새로운 토큰 발급 완료", level=MESSAGE_LEVEL_IMPORTANT)
        return access_token
        
    except Exception as e:
        send_message(f"🚨 토큰 발급 중 오류 발생: {str(e)}", level=MESSAGE_LEVEL_CRITICAL)
        return None
    finally:
        # 토큰 발급 완료 (성공/실패 관계없이)
        TOKEN_REQUEST_IN_PROGRESS = False

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

def is_korean_holiday(date=None):
    """주어진 날짜가 한국 공휴일인지 확인합니다.
    날짜를 지정하지 않으면 현재 날짜를 사용합니다."""
    
    if date is None:
        date = datetime.datetime.now(timezone('Asia/Seoul'))
    
    # 날짜를 YYYY-MM-DD 형식으로 변환
    date_str = date.strftime('%Y-%m-%d')
    
    # 고정 연간 공휴일 목록 (MM-DD 형식)
    annual_holidays = {
        '01-01': '신정',        # 신정
        '03-01': '삼일절',      # 삼일절
        '05-05': '어린이날',    # 어린이날
        '06-06': '현충일',      # 현충일
        '08-15': '광복절',      # 광복절
        '10-03': '개천절',      # 개천절
        '10-09': '한글날',      # 한글날
        '12-25': '크리스마스'   # 크리스마스
    }
    
    # 특별 공휴일 (연도별로 업데이트 필요)
    special_holidays = {
        '2025-05-06': '어린이날 연휴', # 어린이날 다음날
        '2025-06-03': '대통령선거', 
        # 필요에 따라 2025년 다른 특별 공휴일 추가
    }
    
    # 고정 연간 공휴일 확인
    mm_dd = date.strftime('%m-%d')
    if mm_dd in annual_holidays:
        return True, annual_holidays[mm_dd]
    
    # 특별 공휴일 확인
    if date_str in special_holidays:
        return True, special_holidays[date_str]
    
    return False, None

def is_market_open():
    """국내 시장 시간 체크 - 공휴일 포함"""
    try:
        KST_time = datetime.datetime.now(timezone('Asia/Seoul'))
        print(f"현재 한국시간: {KST_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 주말 체크
        if KST_time.weekday() >= 5:
            print("주말 - 시장 닫힘")
            return False
        
        # 공휴일 체크
        is_holiday, holiday_name = is_korean_holiday(KST_time)
        if is_holiday:
            print(f"공휴일({holiday_name}) - 시장 닫힘")
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
    """시장 개장 대기 (주말 및 공휴일 처리)"""
    try:
        send_message("한국 시장이 닫혀 있습니다. 개장까지 대기합니다...")
        
        while not is_market_open():
            # 현재 한국 시간 확인
            kst_time = datetime.datetime.now(timezone('Asia/Seoul'))
            
            # 공휴일 확인
            is_holiday, holiday_name = is_korean_holiday(kst_time)
            
            # 다음 체크 시간 결정
            next_check = 60  # 기본 대기 시간 60분
            
            # 개장일(월~금) 확인
            weekday = kst_time.weekday()  # 0=월요일, 6=일요일
            is_weekend = weekday >= 5  # 주말 여부
            
            if is_holiday:
                # 공휴일인 경우
                send_message(f"오늘은 {holiday_name}입니다. 장이 열리지 않습니다.")
                next_check = 240  # 공휴일에는 4시간 간격으로 체크
            elif is_weekend:
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
            
            day_name = ['월','화','수','목','금','토','일'][weekday]
            status_msg = f"한국시간: {kst_time.strftime('%Y-%m-%d %H:%M')} {day_name}요일"
            if is_holiday:
                status_msg += f" ({holiday_name})"
            send_message(f"다음 확인까지 {next_check}분 대기... ({status_msg})")
            time.sleep(next_check * 60)
        
        send_message("🔔 한국 시장이 개장되었습니다!", level=MESSAGE_LEVEL_CRITICAL)
        if not refresh_token():  # 시장 개장 시 토큰 갱신
            send_message("토큰 갱신에 실패했습니다. 2분 후 다시 시도합니다.", level=MESSAGE_LEVEL_IMPORTANT)
            time.sleep(120)
            refresh_token()
    except Exception as e:
        send_message(f"🚨 시장 개장 대기 중 오류: {str(e)}")
        time.sleep(60)  # 오류 발생 시 1분 대기 후 재시도

def get_daily_data(code):
    """일봉 데이터 조회 (이동평균 계산용)"""
    global ACCESS_TOKEN
    
    print(f"일봉 데이터 조회 시작 - 종목: {code}")
    PATH = "uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    URL = f"{URL_BASE}/{PATH}"
    
    # 토큰 체크
    if not ACCESS_TOKEN:
        ACCESS_TOKEN = get_access_token()
        if not ACCESS_TOKEN:
            send_message("토큰 발급 실패, 2분 후 재시도합니다.", level=MESSAGE_LEVEL_IMPORTANT)
            time.sleep(120)
            ACCESS_TOKEN = get_access_token()
            if not ACCESS_TOKEN:
                send_message("토큰 재발급도 실패, 다음 체크에서 재시도합니다.", level=MESSAGE_LEVEL_CRITICAL)
                return None
    
    headers = {
        "Content-Type": "application/json", 
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "tr_id": "FHKST03010100",
        "custtype": "P"
    }
    
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": code,
        "FID_INPUT_DATE_1": "",
        "FID_INPUT_DATE_2": "",
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "1"
    }
    
    try:
        res = requests.get(URL, headers=headers, params=params)
        
        # 응답 코드가 만료된 토큰 오류인 경우
        if res.status_code == 401 or (res.status_code == 200 and 'access_token' in res.text.lower()):
            send_message("토큰이 만료되었습니다. 새 토큰을 발급합니다.", level=MESSAGE_LEVEL_IMPORTANT)
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                # 새 토큰으로 다시 시도
                headers['authorization'] = f"Bearer {ACCESS_TOKEN}"
                res = requests.get(URL, headers=headers, params=params)
            else:
                print("토큰 재발급 실패, 1분 후 다시 시도합니다.")
                time.sleep(60)
                return None
        
        if res.status_code == 200:
            data = res.json()
            if "output2" in data and data["output2"]:
                print(f"{code} 일봉 데이터 조회 완료: {len(data['output2'])} 일")
                return data
            else:
                print(f"요청 코드: {code}, 일봉 데이터 없음")
                return None
        else:
            print(f"일봉 API 호출 실패. 상태 코드: {res.status_code}, 응답 내용: {res.text}")
            return None
    except Exception as e:
        print(f"일봉 데이터 요청 중 오류 발생: {e}")
        return None

def calculate_moving_average(data, periods=MA_PERIOD):
    """이동평균 계산"""
    try:
        # 데이터 유효성 확인
        if "output2" not in data or not data["output2"]:
            print("이동평균 계산을 위한 데이터가 부족합니다")
            return None

        # 데이터프레임 생성
        df = pd.DataFrame(data["output2"])
        print(f"이동평균 계산을 위한 데이터 프레임 생성 완료: {len(df)} 행")
        
        # 가격 컬럼 확인 (일봉에서는 종가 사용)
        if 'stck_clpr' in df.columns:
            df['close_price'] = pd.to_numeric(df['stck_clpr'], errors='coerce')
        else:
            print("종가 데이터 컬럼을 찾을 수 없습니다:", df.columns)
            return None
        
        # 결측값 처리
        df = df.dropna(subset=['close_price'])
        
        # 날짜 컬럼 처리
        if 'stck_bsop_date' in df.columns:
            df['date'] = pd.to_datetime(df['stck_bsop_date'], format='%Y%m%d')
        else:
            print("날짜 컬럼 생성 실패")
            return None
        
        # 데이터 정렬 (오래된 순서대로)
        df = df.sort_values(by='date').reset_index(drop=True)
        
        # 데이터 충분성 확인
        if len(df) < periods:
            print(f"이동평균 계산을 위한 데이터 부족 (필요: {periods}, 현재: {len(df)})")
            return None
        
        # 이동평균 계산
        df['ma'] = df['close_price'].rolling(window=periods).mean()
        
        # 최신 이동평균 값 추출
        latest_ma = df['ma'].iloc[-1]
        if pd.isna(latest_ma):
            print("이동평균 계산 결과가 NaN입니다")
            return None
            
        latest_ma = round(latest_ma, 2)
        print(f"{periods}일 이동평균 계산 완료: {latest_ma}")
        return latest_ma
    
    except Exception as e:
        print(f"이동평균 계산 중 오류 발생: {e}")
        return None

def get_moving_average(code, periods=MA_PERIOD):
    """종목의 이동평균 조회"""
    global ACCESS_TOKEN
    print(f"이동평균 조회 시작: {code} ({periods}일)")
    try:
        # 액세스 토큰 확인 및 갱신
        if not ACCESS_TOKEN:
            ACCESS_TOKEN = get_access_token()
            if not ACCESS_TOKEN:
                send_message("토큰 발급 실패, 다음 체크에서 재시도합니다.", level=MESSAGE_LEVEL_IMPORTANT)
                ACCESS_TOKEN = get_access_token()
                if not ACCESS_TOKEN:
                    return None
        
        # 일봉 데이터 조회
        data = get_daily_data(code)
        
        if not data:
            send_message(f"{code} 일봉 데이터 조회 실패, 이동평균 계산 불가", code)
            return None
            
        # 이동평균 계산
        ma_value = calculate_moving_average(data, periods)
        
        if ma_value is not None:
            print(f"종목 {code}의 {periods}일 이동평균: {ma_value}")
        return ma_value
    
    except Exception as e:
        error_msg = str(e).lower()
        if 'access_token' in error_msg:
            send_message(f"{code} 이동평균 조회 중 토큰 오류 발생. 토큰 갱신 시도 중...", code)
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                send_message("토큰 갱신 성공. 다시 시도합니다.", code)
                return get_moving_average(code, periods)
        else:
            send_message(f"{code} 이동평균 조회 중 오류: {e}", code)
        return None
    

#파트2

def get_minute_data(code, time_unit=MINUTE_CANDLE, period=30):
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
            send_message("토큰 발급 실패, 2분 후 재시도합니다.", level=MESSAGE_LEVEL_IMPORTANT)
            time.sleep(120)
            ACCESS_TOKEN = get_access_token()
            if not ACCESS_TOKEN:
                send_message("토큰 재발급도 실패, 다음 체크에서 재시도합니다.", level=MESSAGE_LEVEL_CRITICAL)
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
            "CTX_AREA_FK100": next_key,
            "CTX_AREA_NK100": ""
        }
        
        try:
            res = requests.get(URL, headers=headers, params=params)
            
            # 응답 코드가 만료된 토큰 오류인 경우
            if res.status_code == 401 or (res.status_code == 200 and 'access_token' in res.text.lower()):
                send_message("토큰이 만료되었습니다. 새 토큰을 발급합니다.", level=MESSAGE_LEVEL_IMPORTANT)
                ACCESS_TOKEN = get_access_token()
                if ACCESS_TOKEN:
                    # 새 토큰으로 다시 시도
                    headers['authorization'] = f"Bearer {ACCESS_TOKEN}"
                    res = requests.get(URL, headers=headers, params=params)
                else:
                    send_message("토큰 재발급 실패, 2분 후 다시 시도합니다.", level=MESSAGE_LEVEL_IMPORTANT)
                    time.sleep(120)
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


# 2. calculate_rsi 개선 (None 반환, 가격 컬럼 자동 탐색)
def calculate_rsi(data, periods=RSI_PERIOD):
    try:
        if "output2" not in data or not data["output2"]:
            print("RSI 계산을 위한 데이터가 부족합니다")
            return None
        df = pd.DataFrame(data["output2"])
        price_candidates = ['stck_prpr', 'close', 'last']
        price_col = next((col for col in price_candidates if col in df.columns), None)
        if not price_col:
            print("가격 데이터 컬럼을 찾을 수 없습니다:", df.columns)
            return None
        df['price'] = pd.to_numeric(df[price_col], errors='coerce')
        df = df.dropna(subset=['price'])
        if len(df) < periods:
            print(f"데이터 부족 (필요: {periods}, 현재: {len(df)})")
            return None
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
        return None


def get_current_rsi(code, periods=RSI_PERIOD, time_unit=MINUTE_CANDLE):
    """현재 RSI 조회"""
    global ACCESS_TOKEN
    print(f"RSI 조회 시작: {code}")
    try:
        # 액세스 토큰 확인 및 갱신
        if not ACCESS_TOKEN:
            ACCESS_TOKEN = get_access_token()
            if not ACCESS_TOKEN:
                send_message("토큰 발급 실패, 다음 체크에서 재시도합니다.", level=MESSAGE_LEVEL_IMPORTANT)
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
        
        if rsi_value is None:
            send_message(f"{code} RSI 계산 불가, 건너뜀", code)
            return 50

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
        send_message(f"주문 가능 현금 잔고: {cash}원", level=MESSAGE_LEVEL_INFO)
        
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
        
        send_message(f"====주식 보유잔고====", level=MESSAGE_LEVEL_INFO)
        for stock in stock_list:
            if int(stock['hldg_qty']) > 0:
                stock_dict[stock['pdno']] = stock['hldg_qty']
                send_message(f"{stock['prdt_name']}({stock['pdno']}): {stock['hldg_qty']}주", level=MESSAGE_LEVEL_INFO)
                time.sleep(0.1)
        
        send_message(f"주식 평가 금액: {evaluation[0]['scts_evlu_amt']}원", level=MESSAGE_LEVEL_INFO)
        time.sleep(0.1)
        send_message(f"평가 손익 합계: {evaluation[0]['evlu_pfls_smtl_amt']}원", level=MESSAGE_LEVEL_INFO)
        time.sleep(0.1)
        send_message(f"=================", level=MESSAGE_LEVEL_INFO)
        
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

def check_sell_conditions(code, current_rsi, profit_rate):
    """매도 조건 종합 검사 (RSI + 수익률)"""
    try:
        # RSI 조건 확인
        if current_rsi < RSI_OVERBOUGHT:
            # RSI 조건 미충족 메시지를 DEBUG 레벨로 (너무 빈번함)
            send_message(f"RSI 매도 조건 미충족 (현재: {current_rsi:.2f}, 기준: {RSI_OVERBOUGHT} 이상)", code, level=MESSAGE_LEVEL_DEBUG)
            return False
        
        # 수익률 조건 확인
        if profit_rate < PROFIT_TAKE_PERCENT:
            if profit_rate >= 0:
                # 수익률 부족 메시지를 DEBUG 레벨로 (너무 빈번함)
                send_message(f"수익률 부족 (현재: {profit_rate:.2f}%, 기준: {PROFIT_TAKE_PERCENT}% 이상)", code, level=MESSAGE_LEVEL_DEBUG)
            else:
                # 손실 상태 메시지를 DEBUG 레벨로 (너무 빈번함)
                send_message(f"손실 상태 (수익률: {profit_rate:.2f}%)", code, level=MESSAGE_LEVEL_DEBUG)
            return False
        
        # 모든 조건 충족
        send_message(f"✅ 매도 조건 충족 - RSI: {current_rsi:.2f}, 수익률: {profit_rate:.2f}%", code, level=MESSAGE_LEVEL_IMPORTANT)
        return True
        
    except Exception as e:
        send_message(f"매도 조건 확인 중 오류: {str(e)}", code, level=MESSAGE_LEVEL_CRITICAL)
        return False

def check_buy_conditions(code, current_rsi, current_price):
    """매수 조건 종합 검사"""
    try:
        # 1. RSI 조건 확인
        if current_rsi > RSI_OVERSOLD:
            # RSI 조건 미충족 메시지를 DEBUG 레벨로 (너무 빈번함)
            send_message(f"RSI 조건 미충족 (현재: {current_rsi:.2f}, 기준: {RSI_OVERSOLD} 이하)", code, level=MESSAGE_LEVEL_DEBUG)
            return False
        
        # 2. 이동평균 조건 확인
        ma_value = get_moving_average(code, MA_PERIOD)
        if ma_value is None:
            send_message(f"이동평균 조회 실패로 매수 조건 확인 불가", code, level=MESSAGE_LEVEL_IMPORTANT)
            return False
        
        print(f"{MA_PERIOD}일 이동평균: {ma_value}원")
        
        # 현재가가 이동평균보다 높으면 매수하지 않음
        if current_price > ma_value:
            price_diff = current_price - ma_value
            price_diff_percent = (price_diff / ma_value) * 100
            # 이동평균 조건 미충족 메시지를 DEBUG 레벨로 (너무 빈번함)
            send_message(f"이동평균 조건 미충족 - 현재가({current_price})가 {MA_PERIOD}일 이동평균({ma_value})보다 {price_diff_percent:.2f}% 높음", code, level=MESSAGE_LEVEL_DEBUG)
            return False
        
        # 모든 조건 충족
        price_diff = ma_value - current_price
        price_diff_percent = (price_diff / ma_value) * 100
        send_message(f"✅ 매수 조건 충족 - 현재가가 {MA_PERIOD}일 이동평균보다 {price_diff_percent:.2f}% 낮음", code, level=MESSAGE_LEVEL_IMPORTANT)
        return True
        
    except Exception as e:
        send_message(f"매수 조건 확인 중 오류: {str(e)}", code, level=MESSAGE_LEVEL_CRITICAL)
        return False


#파트3

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
                    send_message("토큰 발급 실패, 2분 후 재시도합니다.", level=MESSAGE_LEVEL_IMPORTANT)
                    time.sleep(120)
                    token_retry_count += 1
                    if token_retry_count > max_token_retries:
                        send_message(f"토큰 발급 {max_token_retries}회 실패, 10분 후 다시 시도합니다.", level=MESSAGE_LEVEL_CRITICAL)
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
            send_message(f"매수 조건: RSI {RSI_OVERSOLD} 이하 + 현재가가 {MA_PERIOD}일 이동평균 이하")
            send_message(f"매도 조건: RSI {RSI_OVERBOUGHT} 이상")
            
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
                    
                    # 메시지 히스토리 정리 (토큰 갱신 시마다)
                    cleanup_message_history()
                
                # 시장 상태 확인
                market_open = is_market_open()
                if not market_open:
                    send_message("🔔 한국 시장이 마감되었습니다. 다음 개장일까지 대기합니다...", level=MESSAGE_LEVEL_CRITICAL)
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
                            send_message(f"현재 RSI: {current_rsi:.2f}", code, level=MESSAGE_LEVEL_INFO)
                            
                            # 현재가 조회
                            current_price = get_current_price(code)
                            if current_price is None:
                                send_message(f"현재가 조회 실패", code)
                                continue
                            send_message(f"현재가: {current_price}원", code, level=MESSAGE_LEVEL_INFO)
                            
                            # 매수 조건 (RSI + 이동평균 조건 모두 충족)
                            if current_rsi <= RSI_OVERSOLD:
                                if len(bought_list) < target_buy_count and code not in bought_list:
                                    # 종합 매수 조건 검사 (RSI + 이동평균)
                                    if check_buy_conditions(code, current_rsi, current_price):
                                        send_message(f"🎯 종합 매수 신호 감지!", code, level=MESSAGE_LEVEL_IMPORTANT)
                                        
                                        # 매수 수량 계산
                                        qty = int(buy_amount // current_price)
                                        
                                        if qty > 0:
                                            total_cost = qty * current_price
                                            
                                            send_message(f"- 매수 가능 금액: {buy_amount:.0f}원", code, level=MESSAGE_LEVEL_INFO)
                                            send_message(f"- 주문 수량: {qty}주", code, level=MESSAGE_LEVEL_INFO)
                                            send_message(f"- 주문 가격: {current_price}원", code, level=MESSAGE_LEVEL_INFO)
                                            send_message(f"- 총 주문 금액: {total_cost:.0f}원", code, level=MESSAGE_LEVEL_INFO)
                                            
                                            # 매수 실행
                                            buy_result = buy(code, qty)
                                            if buy_result:
                                                bought_list.append(code)
                                                send_message(f"✅ {code} {qty}주 매수 완료", code, level=MESSAGE_LEVEL_CRITICAL)
                                        else:
                                            send_message(f"❌ 계산된 매수 수량이 0입니다", code, level=MESSAGE_LEVEL_INFO)
                                    # else 부분은 check_buy_conditions 함수에서 이미 메시지 출력
                                else:
                                    if code in bought_list:
                                        send_message(f"이미 보유 중인 종목입니다", code, level=MESSAGE_LEVEL_DEBUG)
                                    else:
                                        send_message(f"최대 매수 종목 수({target_buy_count})에 도달했습니다", code, level=MESSAGE_LEVEL_DEBUG)
                            
                            # 매도 조건 (RSI + 수익률 조건)
                            elif current_rsi >= RSI_OVERBOUGHT:
                                if code in stock_dict:
                                    # 수익률 계산
                                    stock_info = stock_dict[code]
                                    profit_rate = float(stock_info.get('profit_rate', 0))
                                    
                                    # 종합 매도 조건 검사 (RSI + 수익률)
                                    if check_sell_conditions(code, current_rsi, profit_rate):
                                        send_message(f"🎯 종합 매도 신호 감지!", code, level=MESSAGE_LEVEL_IMPORTANT)
                                        sell_result = sell(code, "all")
                                        if sell_result:
                                            if code in bought_list:
                                                bought_list.remove(code)
                                            send_message(f"✅ {code} 매도 완료", code, level=MESSAGE_LEVEL_CRITICAL)
                                    # else 부분은 check_sell_conditions 함수에서 이미 메시지 출력
                            
                            # 그 외 상태 메시지
                            else:
                                print(f"현재 RSI {current_rsi:.2f}는 매수/매도 구간이 아닙니다", code)
                                
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
                
                # 짧은 대기 후 루프 계속
                time.sleep(1)
                
        except Exception as main_error:
            error_msg = str(main_error).lower()
            send_message(f"🚨 [메인 루프 오류 발생] {error_msg}")
            
            # 토큰 관련 오류인 경우
            if 'access_token' in error_msg:
                send_message("토큰 오류로 인한 재시작, 2분 후 토큰 재발급을 시도합니다.", level=MESSAGE_LEVEL_CRITICAL)
                ACCESS_TOKEN = None  # 토큰 초기화
                time.sleep(120)
            else:
                # 그 외 오류는 3분 대기 후 재시작
                send_message("3분 후 프로그램을 재시작합니다...")
                time.sleep(180)

if __name__ == "__main__":
    main()