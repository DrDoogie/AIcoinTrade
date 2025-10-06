#해외주식거래코드

#0308버전에서 Access Token 오류 수정 버전
#0322버전에서 손절 기능 추가 
#0412버전에서 RSI가 매도 조건이라도 손실일 경우는 매도 하지 않는 내용 수정
#0601버전에서 손절매 기능 수정(손절매 기능 제대로 수행이 안되서서)
#0601버전에서 매수 조건을 수정함
#장기이동평균 20일 대비 높은 가격일 경우에는 매수 하지 않도록 수정함
#커서AI로 오류 수정함
#CRCL추가
#0716 버전에서 수익울 10% 이상일 경우 매도 하도록 수정함
#0716  버전에서 메시지 최적화 설정 추가함
# 0907 현재 거래 조건 미충족시 메세지 발송 제한 추가
# 0919 # 로그 최적화: 
# 0919 AWS 사용량 저감: 
# 0919 매도 전략 개선: 매도 신호 발생 시 보유 수량이 1주 이상만 매도
# 0920 Log내용 최적화 및 일일 거래 요약 데이터 추가
# 0920 일일 거래 요약 데이터 초기화 기능 추가
# 0929 메세지 분할 발송 기능 수정 
# 1004 종목 코드 수정 
# 1006 메세지 레이트 리미터 추가



# 1파트

import pandas as pd
import numpy as np
import requests
import json
import time
from datetime import datetime, timedelta
from pytz import timezone
import yaml
from functools import wraps

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
SYMBOLS = ["PLTR", "NVDA","IONQ","TSLA","MSFT","AAPL","GOOGL","TSM"]  # 여러 심볼 추가 "IONQ" 제외외 "TSLA"

# ===== 매매 조건 설정 (수정 필요시 이 부분만 변경) =====
# RSI 설정
RSI_PERIODS = 14                    # RSI 계산 기간
RSI_BUY_THRESHOLD = 30             # 매수 조건: RSI 이하일 때 (과매도)
RSI_SELL_THRESHOLD = 70            # 매도 조건: RSI 이상일 때 (과매수)

# 이동평균선 설정
MA_SHORT_PERIOD = 20               # 단기 이동평균 기간
MA_LONG_PERIOD = 50                # 장기 이동평균 기간
MAX_PRICE_ABOVE_MA_PERCENT = 3     # 장기이평 대비 최대 허용 상승률 (%)

# 손절매 설정
STOP_LOSS_PERCENT = 8             # 손절매 기준: 하락률 (%) - 음수로 입력하지 마세요

# 매도 설정
PROFIT_TAKE_PERCENT = 8.0          # 익절 기준: 수익률 (%) - 양수로 입력하세요

# 매수 설정
BUY_RATIO = 0.20                   # 보유 현금 대비 매수 비율 (0.30 = 30%)
SAFETY_MARGIN = 0.01               # 안전 마진 (0.01 = 1%)

# 데이터 수집 설정
MINUTE_INTERVAL = 30               # 분봉 데이터 간격 (분)
DATA_PERIOD = 3                    # 데이터 수집 기간 (분봉 단위)

# 체크 주기 설정
RSI_CHECK_INTERVAL = 19            # RSI 체크 간격 (분)
STOP_LOSS_CHECK_INTERVAL = 5       # 손절매 체크 간격 (분)
TOKEN_REFRESH_INTERVAL = 10800     # 토큰 갱신 간격 (초, 3시간 = 10800초)

# ===== 일일 거래 요약 데이터 수집 설정 =====
DAILY_SUMMARY_DATA = {}  # 종목별 일일 분석 데이터 저장
# ===== 일일 거래 요약 데이터 수집 설정 끝 =====

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

# ===== 전역 전송 레이트 리미터 설정 =====
LAST_DISCORD_SEND_TIME = 0
MIN_DISCORD_SEND_INTERVAL = 2  # 초 단위 최소 간격

def send_message(msg, symbol=None, level=MESSAGE_LEVEL_INFO):
    """디스코드 메시지 전송 (최적화된 버전)"""
    global MESSAGE_HISTORY, MESSAGE_BATCH, LAST_BATCH_SEND
    
    # 메시지 레벨 필터링
    if level > MESSAGE_SEND_LEVEL:
        return  # 설정된 레벨보다 낮은 중요도면 전송하지 않음
    
    # 메시지 내용 생성
    now = datetime.now()
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
    """즉시 메시지 발송 (레이트 리미터 적용)"""
    global LAST_DISCORD_SEND_TIME
    try:
        # 전송 간 최소 간격 보장
        now = time.time()
        elapsed = now - LAST_DISCORD_SEND_TIME
        if elapsed < MIN_DISCORD_SEND_INTERVAL:
            time.sleep(MIN_DISCORD_SEND_INTERVAL - elapsed)
        message_data = {"content": message}
        requests.post(DISCORD_WEBHOOK_URL, data=message_data, timeout=5)
        LAST_DISCORD_SEND_TIME = time.time()
    except Exception as e:
        print(f"메시지 발송 실패: {e}")

def send_batch_messages():
    """배치 메시지 발송 (레이트 리미터 적용)"""
    global MESSAGE_BATCH, LAST_BATCH_SEND, LAST_DISCORD_SEND_TIME
    
    if not MESSAGE_BATCH:
        return
    
    try:
        # 배치 메시지를 하나로 합치기
        batch_content = "\n".join(MESSAGE_BATCH[-MAX_BATCH_SIZE:])  # 최대 크기 제한
        message_data = {"content": f"📊 **배치 업데이트**\n```\n{batch_content}\n```"}
        
        # 전송 간 최소 간격 보장
        now = time.time()
        elapsed = now - LAST_DISCORD_SEND_TIME
        if elapsed < MIN_DISCORD_SEND_INTERVAL:
            time.sleep(MIN_DISCORD_SEND_INTERVAL - elapsed)
        requests.post(DISCORD_WEBHOOK_URL, data=message_data, timeout=10)
        LAST_DISCORD_SEND_TIME = time.time()
        MESSAGE_BATCH.clear()
        LAST_BATCH_SEND = time.time()
        
        print(f"배치 메시지 발송 완료: {len(MESSAGE_BATCH)} 건")
    except Exception as e:
        print(f"배치 메시지 발송 실패: {e}")

def collect_daily_summary_data(symbol, analysis_result, buy_signal, sell_signal, buy_reason, sell_reason):
    """일일 거래 요약 데이터 수집"""
    global DAILY_SUMMARY_DATA
    
    current_time = datetime.now(timezone('Asia/Seoul'))
    time_str = current_time.strftime('%H:%M')
    
    if symbol not in DAILY_SUMMARY_DATA:
        DAILY_SUMMARY_DATA[symbol] = {
            'symbol': symbol,
            'analysis_points': [],
            'buy_signals': [],
            'sell_signals': [],
            'trades': [],
            'rsi_range': {'min': 100, 'max': 0},
            'price_range': {'min': float('inf'), 'max': 0},
            'start_time': time_str,
            'last_time': time_str
        }
    
    # 분석 포인트 추가
    analysis_point = {
        'time': time_str,
        'rsi': analysis_result['rsi'],
        'current_price': analysis_result['current_price'],
        'ma_short': analysis_result['ma_short'],
        'ma_long': analysis_result['ma_long'],
        'price_vs_ma_long_percent': analysis_result['price_vs_ma_long_percent'],
        'ma_trend': analysis_result['ma_trend'],
        'buy_signal': buy_signal,
        'sell_signal': sell_signal,
        'buy_reason': buy_reason,
        'sell_reason': sell_reason
    }
    
    DAILY_SUMMARY_DATA[symbol]['analysis_points'].append(analysis_point)
    DAILY_SUMMARY_DATA[symbol]['last_time'] = time_str
    
    # RSI 범위 업데이트
    rsi = analysis_result['rsi']
    if rsi < DAILY_SUMMARY_DATA[symbol]['rsi_range']['min']:
        DAILY_SUMMARY_DATA[symbol]['rsi_range']['min'] = rsi
    if rsi > DAILY_SUMMARY_DATA[symbol]['rsi_range']['max']:
        DAILY_SUMMARY_DATA[symbol]['rsi_range']['max'] = rsi
    
    # 가격 범위 업데이트
    price = analysis_result['current_price']
    if price < DAILY_SUMMARY_DATA[symbol]['price_range']['min']:
        DAILY_SUMMARY_DATA[symbol]['price_range']['min'] = price
    if price > DAILY_SUMMARY_DATA[symbol]['price_range']['max']:
        DAILY_SUMMARY_DATA[symbol]['price_range']['max'] = price
    
    # 매수/매도 신호 기록
    if buy_signal:
        DAILY_SUMMARY_DATA[symbol]['buy_signals'].append({
            'time': time_str,
            'reason': buy_reason,
            'price': price,
            'rsi': rsi
        })
    
    if sell_signal:
        DAILY_SUMMARY_DATA[symbol]['sell_signals'].append({
            'time': time_str,
            'reason': sell_reason,
            'price': price,
            'rsi': rsi
        })

def add_trade_record(symbol, trade_type, qty, price, time_str=None):
    """거래 내역 추가"""
    global DAILY_SUMMARY_DATA
    
    if time_str is None:
        time_str = datetime.now(timezone('Asia/Seoul')).strftime('%H:%M')
    
    if symbol not in DAILY_SUMMARY_DATA:
        DAILY_SUMMARY_DATA[symbol] = {
            'symbol': symbol,
            'analysis_points': [],
            'buy_signals': [],
            'sell_signals': [],
            'trades': [],
            'rsi_range': {'min': 100, 'max': 0},
            'price_range': {'min': float('inf'), 'max': 0},
            'start_time': time_str,
            'last_time': time_str
        }
    
    DAILY_SUMMARY_DATA[symbol]['trades'].append({
        'time': time_str,
        'type': trade_type,  # 'buy' or 'sell'
        'qty': qty,
        'price': price
    })

def generate_daily_summary_message(symbol):
    """일일 거래 요약 메시지 생성"""
    global DAILY_SUMMARY_DATA
    
    if symbol not in DAILY_SUMMARY_DATA:
        return None
    
    data = DAILY_SUMMARY_DATA[symbol]
    current_date = datetime.now(timezone('Asia/Seoul')).strftime('%Y-%m-%d')
    
    # 마지막 분석 포인트에서 최종 데이터 가져오기
    if data['analysis_points']:
        last_analysis = data['analysis_points'][-1]
        final_price = last_analysis['current_price']
        final_ma_short = last_analysis['ma_short']
        final_ma_long = last_analysis['ma_long']
        final_price_vs_ma = last_analysis['price_vs_ma_long_percent']
    else:
        final_price = 0
        final_ma_short = 0
        final_ma_long = 0
        final_price_vs_ma = 0
    
    # 주요 체크 시점 선택 (시작, 중간, 끝)
    key_points = []
    if len(data['analysis_points']) >= 4:
        # 시작, 1/3, 2/3, 끝
        indices = [0, len(data['analysis_points'])//3, 2*len(data['analysis_points'])//3, -1]
        key_points = [data['analysis_points'][i] for i in indices]
    else:
        key_points = data['analysis_points']
    
    # 메시지 생성
    message = f"**[{symbol} 일일 거래 요약]**\n"
    message += f"📅 분석 일자: {current_date} | ⏰ 분석 구간: {data['start_time']} ~ {data['last_time']} (KST)\n\n"
    
    message += "**1️⃣ 분석 요약**\n"
    message += f"RSI 범위: {data['rsi_range']['min']:.2f} → {data['rsi_range']['max']:.2f}"
    if data['rsi_range']['max'] >= 70:
        message += " (과매수 상태)"
    elif data['rsi_range']['min'] <= 30:
        message += " (과매도 상태)"
    message += "\n"
    
    message += f"종가(마감): ${final_price:.2f} | 20MA: ${final_ma_short:.2f} | 50MA: ${final_ma_long:.2f}\n"
    message += f"장기이평 대비 상승률: {final_price_vs_ma:+.2f}%\n"
    
    # 매수/매도 조건 요약
    if data['buy_signals'] or data['sell_signals']:
        message += f"매수 신호: {len(data['buy_signals'])}회, 매도 신호: {len(data['sell_signals'])}회\n\n"
    else:
        message += "매수/매도 조건: 발생하지 않음"
        if final_price_vs_ma > 3:
            message += " (장기이평 대비 상승률 초과 구간 유지)"
        message += "\n\n"
    
    message += "**2️⃣ 주요 체크 시점**\n"
    for point in key_points:
        signal_status = "❌ 신호 없음"
        if point['buy_signal']:
            signal_status = "✅ 매수 신호"
        elif point['sell_signal']:
            signal_status = "✅ 매도 신호"
        
        message += f"{point['time']} | RSI {point['rsi']:.2f} | ${point['current_price']:.2f} | "
        message += f"20MA ${point['ma_short']:.2f} | 50MA ${point['ma_long']:.2f} → {signal_status}\n"
    
    message += "\n**3️⃣ 거래 내역**\n"
    if data['trades']:
        for trade in data['trades']:
            trade_type_emoji = "🟢" if trade['type'] == 'buy' else "🔴"
            message += f"{trade_type_emoji} {trade['time']} | {trade['type'].upper()} {trade['qty']}주 @ ${trade['price']:.2f}\n"
    else:
        message += "매수·매도 조건이 충족되지 않아 거래 없음.\n"
    
    message += "\n**4️⃣ 간단 결론**\n"
    
    # 결론 생성
    if data['rsi_range']['max'] >= 70:
        message += "📈 강한 상승 추세 지속. 과매수 상태로 신규 진입은 위험 구간.\n"
        message += "📌 조치: 관망 유지, 조건 충족 시 다음 거래 실행.\n"
    elif data['rsi_range']['min'] <= 30:
        message += "📉 하락 추세 지속. 과매도 상태로 매수 기회 모니터링 필요.\n"
        message += "📌 조치: 매수 조건 충족 시 진입 검토.\n"
    else:
        message += "📊 중립적 추세. 기술적 지표 변화 모니터링 필요.\n"
        message += "📌 조치: 조건 충족 시 거래 실행.\n"
    
    return message

def generate_daily_summary_messages(symbol):
    """일일 거래 요약 메시지들을 분할하여 생성"""
    global DAILY_SUMMARY_DATA
    
    if symbol not in DAILY_SUMMARY_DATA:
        return None
    
    data = DAILY_SUMMARY_DATA[symbol]
    current_date = datetime.now(timezone('Asia/Seoul')).strftime('%Y-%m-%d')
    
    # 마지막 분석 포인트에서 최종 데이터 가져오기
    if data['analysis_points']:
        last_analysis = data['analysis_points'][-1]
        final_price = last_analysis['current_price']
        final_ma_short = last_analysis['ma_short']
        final_ma_long = last_analysis['ma_long']
        final_price_vs_ma = last_analysis['price_vs_ma_long_percent']
    else:
        final_price = 0
        final_ma_short = 0
        final_ma_long = 0
        final_price_vs_ma = 0
    
    # 주요 체크 시점 선택 (시작, 중간, 끝)
    key_points = []
    if len(data['analysis_points']) >= 4:
        # 시작, 1/3, 2/3, 끝
        indices = [0, len(data['analysis_points'])//3, 2*len(data['analysis_points'])//3, -1]
        key_points = [data['analysis_points'][i] for i in indices]
    else:
        key_points = data['analysis_points']
    
    messages = []
    
    # 메시지 1: 헤더 + 분석 요약
    message1 = f"**[{symbol} 일일 거래 요약]**\n"
    message1 += f"📅 분석 일자: {current_date} | ⏰ 분석 구간: {data['start_time']} ~ {data['last_time']} (KST)\n\n"
    
    message1 += "**1️⃣ 분석 요약**\n"
    message1 += f"RSI 범위: {data['rsi_range']['min']:.2f} → {data['rsi_range']['max']:.2f}"
    if data['rsi_range']['max'] >= 70:
        message1 += " (과매수 상태)"
    elif data['rsi_range']['min'] <= 30:
        message1 += " (과매도 상태)"
    message1 += "\n"
    
    message1 += f"종가(마감): ${final_price:.2f} | 20MA: ${final_ma_short:.2f} | 50MA: ${final_ma_long:.2f}\n"
    message1 += f"장기이평 대비 상승률: {final_price_vs_ma:+.2f}%\n"
    
    # 매수/매도 조건 요약
    if data['buy_signals'] or data['sell_signals']:
        message1 += f"매수 신호: {len(data['buy_signals'])}회, 매도 신호: {len(data['sell_signals'])}회\n"
    else:
        message1 += "매수/매도 조건: 발생하지 않음\n"
    
    messages.append(message1)
    
    # 메시지 2: 주요 체크 시점
    if key_points:
        message2 = "**2️⃣ 주요 체크 시점**\n"
        for point in key_points:
            signal_status = "❌ 신호 없음"
            if point['buy_signal']:
                signal_status = "✅ 매수 신호"
            elif point['sell_signal']:
                signal_status = "✅ 매도 신호"
            
            message2 += f"{point['time']} | RSI {point['rsi']:.2f} | ${point['current_price']:.2f} | "
            message2 += f"20MA ${point['ma_short']:.2f} | 50MA ${point['ma_long']:.2f} → {signal_status}\n"
        
        messages.append(message2)
    
    # 메시지 3: 거래 내역 + 결론
    message3 = "**3️⃣ 거래 내역**\n"
    if data['trades']:
        for trade in data['trades']:
            trade_type_emoji = "🟢" if trade['type'] == 'buy' else "🔴"
            message3 += f"{trade_type_emoji} {trade['time']} | {trade['type'].upper()} {trade['qty']}주 @ ${trade['price']:.2f}\n"
    else:
        message3 += "매수·매도 조건이 충족되지 않아 거래 없음.\n"
    
    message3 += "\n**4️⃣ 간단 결론**\n"
    
    # 결론 생성
    if data['rsi_range']['max'] >= 70:
        message3 += "📈 강한 상승 추세 지속. 과매수 상태로 신규 진입은 위험 구간.\n"
        message3 += "📌 조치: 관망 유지, 조건 충족 시 다음 거래 실행.\n"
    elif data['rsi_range']['min'] <= 30:
        message3 += "📉 하락 추세 지속. 과매도 상태로 매수 기회 모니터링 필요.\n"
        message3 += "📌 조치: 매수 조건 충족 시 진입 검토.\n"
    else:
        message3 += "📊 중립적 추세. 기술적 지표 변화 모니터링 필요.\n"
        message3 += "📌 조치: 조건 충족 시 거래 실행.\n"
    
    messages.append(message3)
    
    return messages

def send_daily_summary():
    """일일 요약 메시지 발송 (분할 발송)"""
    global DAILY_SUMMARY_DATA
    
    # 디스코드 연속 발송 오류 예방: 요약 시작 전 5초 대기
    time.sleep(5)
    
    for symbol in DAILY_SUMMARY_DATA.keys():
        messages = generate_daily_summary_messages(symbol)
        if messages:
            for i, message in enumerate(messages):
                if i == 0:
                    # 첫 번째 메시지에 종목명 포함
                    send_message(message, symbol, level=MESSAGE_LEVEL_CRITICAL)
                else:
                    # 나머지 메시지는 종목명 없이 발송
                    send_message(message, level=MESSAGE_LEVEL_CRITICAL)
                time.sleep(5)  # 메시지 간 간격(증가)
    """오래된 메시지 히스토리 정리"""
    global MESSAGE_HISTORY
    current_time = time.time()
    MESSAGE_HISTORY = {k: v for k, v in MESSAGE_HISTORY.items() 
                      if current_time - v < MESSAGE_COOLDOWN * 2}


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
            send_message(f"토큰 발급 실패: 상태 코드 {res.status_code}", level=MESSAGE_LEVEL_CRITICAL)
            return None
            
        ACCESS_TOKEN = res.json()["access_token"]
        print(f"새로운 토큰 발급")
        return ACCESS_TOKEN
    except Exception as e:
        send_message(f"🚨 토큰 발급 중 오류 발생: {str(e)}", level=MESSAGE_LEVEL_CRITICAL)
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
        send_message(f"🚨 토큰 갱신 중 오류 발생: {str(e)}", level=MESSAGE_LEVEL_CRITICAL)
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
        send_message(f"🚨 해시키 생성 중 오류 발생: {str(e)}", level=MESSAGE_LEVEL_CRITICAL)
        return None

def is_market_time():
    """미국 시장 시간 체크"""
    try:
        NAS_time = datetime.now(timezone('America/New_York'))
        # print(f"현재 미국시간: {NAS_time.strftime('%Y-%m-%d %H:%M:%S')}")  # 로그 스팸 방지
        
        if NAS_time.weekday() >= 5:
            print("주말 - 시장 닫힘")
            return False
            
        market_start = NAS_time.replace(hour=9, minute=30, second=0, microsecond=0)
        market_end = NAS_time.replace(hour=16, minute=0, second=0, microsecond=0)
        is_market_open = market_start <= NAS_time <= market_end
        
        # print(f"시장 개장 상태: {'열림' if is_market_open else '닫힘'}")  # 로그 스팸 방지
        return is_market_open
    except Exception as e:
        send_message(f"🚨 시장 시간 확인 중 오류: {str(e)}", level=MESSAGE_LEVEL_CRITICAL)
        # 오류 발생 시 기본적으로 닫힘으로 처리
        return False


def wait_for_market_open():
    """시장 개장 대기 (주말 처리 개선)"""
    try:
        send_message("미국 시장이 닫혀 있습니다. 개장까지 대기합니다...", level=MESSAGE_LEVEL_IMPORTANT)
        
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
                # 토요일 또는 일요일 오전 - 여전히 많은 시간 남음
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
            
            #send_message(f"다음 확인까지 {next_check}분 대기... (미국시간: {nas_time.strftime('%Y-%m-%d %H:%M')} {['월','화','수','목','금','토','일'][weekday]}요일)")
            time.sleep(next_check * 60)
        
        send_message("미국 시장이 개장되었습니다!", level=MESSAGE_LEVEL_IMPORTANT)
        if not refresh_token():  # 시장 개장 시 토큰 갱신
            send_message("토큰 갱신에 실패했습니다. 1.5분 후 다시 시도합니다.", level=MESSAGE_LEVEL_CRITICAL)
            time.sleep(90)
            refresh_token()
    except Exception as e:
        send_message(f"🚨 시장 개장 대기 중 오류: {str(e)}", level=MESSAGE_LEVEL_CRITICAL)
        time.sleep(60)  # 오류 발생 시 1분 대기 후 재시도

#2파트

def get_minute_data(symbol, nmin=30, period=2, access_token=""):
    """분봉 데이터 조회 (다중 심볼 대응 + 토큰 오류 처리)"""
    global ACCESS_TOKEN
    
    # print(f"분봉 데이터 조회 시작 - 종목: {symbol}, 시간간격: {nmin}분")  # 로그 스팸 방지
    PATH = "/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
    URL = f"{URL_BASE}/{PATH}"
    
    # 각 종목별 시장 정보 매핑
    MARKET_MAP = {
        "PLTR": {"EXCD": "NAS", "MARKET": "NASD"},
        "NVDA": {"EXCD": "NAS", "MARKET": "NASD"},
        "TSLA": {"EXCD": "NAS", "MARKET": "NASD"},
        "MSFT": {"EXCD": "NAS", "MARKET": "NASD"},
        "AAPL": {"EXCD": "NAS", "MARKET": "NASD"},
        "GOOGL": {"EXCD": "NAS", "MARKET": "NASD"},
        "IONQ": {"EXCD": "NYS", "MARKET": "NYSE"},
        "CRCL": {"EXCD": "NYS", "MARKET": "NYSE"},
        "TSM": {"EXCD": "NYS", "MARKET": "NYSE"}
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

def calculate_rsi(data, periods=RSI_PERIODS):
    """RSI 계산 (강화된 다중 심볼 대응 버전)"""
    try:
        # 데이터 유효성 확인
        if "output2" not in data or not data["output2"]:
            print("RSI 계산을 위한 데이터가 부족합니다")
            return 50

        # 데이터프레임 생성
        df = pd.DataFrame(data["output2"])
        # print(f"RSI 계산을 위한 데이터 프레임 생성 완료: {len(df)} 행")  # 로그 스팸 방지
        
        # 가격 컬럼 동적 탐색 및 처리
        price_columns = ['stck_prpr', 'ovrs_nmix_prpr', 'close', 'last', 'stck_clpr']
        
        # 가격 컬럼 찾기 및 데이터 정제
        price_col = None
        for col in price_columns:
            if col in df.columns:
                # 숫자가 아닌 값 제거, 빈 문자열 처리
                df[col] = pd.to_numeric(df[col].replace('', np.nan), errors='coerce')
                if not df[col].isnull().all():  # Series 조건문 오류 수정
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
        # iloc 오류 수정: rsi가 Series, ndarray, float 모두 처리
        latest_rsi = None
        if hasattr(rsi, 'iloc'):
            latest_rsi = round(rsi.iloc[-1], 2)
        elif isinstance(rsi, np.ndarray):
            latest_rsi = round(rsi[-1], 2)
        elif isinstance(rsi, float):
            latest_rsi = round(rsi, 2)
        else:
            latest_rsi = 50
        print(f"RSI 계산 완료: {latest_rsi}")
        return latest_rsi
    
    except Exception as e:
        print(f"RSI 계산 중 오류 발생: {e}")
        return 50

# 다중 심볼 RSI 조회 헬퍼 함수 (선택사항)
def get_current_rsi(symbol, periods=RSI_PERIODS, nmin=MINUTE_INTERVAL):
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

# 1분 캐시 데코레이터
def cache_1min(func):
    cache = {}
    @wraps(func)
    def wrapper(*args, **kwargs):
        key = (func.__name__, args, tuple(sorted(kwargs.items())))
        now = time.time()
        if key in cache:
            value, timestamp = cache[key]
            if now - timestamp < 60:
                return value
        value = func(*args, **kwargs)
        cache[key] = (value, now)
        return value
    return wrapper

@cache_1min
def get_current_price(symbol, market=MARKET):
    global ACCESS_TOKEN
    MARKET_MAP = {
        "PLTR": {"EXCD": "NAS", "MARKET": "NASD"},
        "NVDA": {"EXCD": "NAS", "MARKET": "NASD"},
        "TSLA": {"EXCD": "NAS", "MARKET": "NASD"},
        "IONQ": {"EXCD": "NYS", "MARKET": "NYSE"},
        "CRCL": {"EXCD": "NYS", "MARKET": "NYSE"},
        "TSM": {"EXCD": "NYS", "MARKET": "NYSE"}
    }
    market_info = MARKET_MAP.get(symbol, {"EXCD": EXCD_MARKET, "MARKET": MARKET})
    PATH = "uapi/overseas-price/v1/quotations/price"
    URL = f"{URL_BASE}/{PATH}"
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
        "EXCD": market_info["EXCD"],
        "SYMB": symbol,
    }
    try:
        res = requests.get(URL, headers=headers, params=params)
        if res.status_code == 401 or (res.status_code == 200 and 'access_token' in res.text.lower()):
            send_message(f"{symbol} 현재가 조회 중 토큰 오류. 토큰 갱신 중...", symbol)
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
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
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                return get_current_price(symbol, market)
        else:
            send_message(f"{symbol} 현재가 조회 중 오류: {e}", symbol)
        return None

@cache_1min
def get_balance(symbol, retry_count=0):
    MAX_RETRIES = 2
    global ACCESS_TOKEN
    MARKET_MAP = {
        "PLTR": {"EXCD": "NAS", "MARKET": "NASD"},
        "NVDA": {"EXCD": "NAS", "MARKET": "NASD"},
        "TSLA": {"EXCD": "NAS", "MARKET": "NASD"},
        "IONQ": {"EXCD": "NYS", "MARKET": "NYSE"},
        "CRCL": {"EXCD": "NYS", "MARKET": "NYSE"},
        "TSM": {"EXCD": "NYS", "MARKET": "NYSE"}
    }
    market_info = MARKET_MAP.get(symbol, {"EXCD": EXCD_MARKET, "MARKET": MARKET})
    PATH = "/uapi/overseas-stock/v1/trading/inquire-psamount"
    URL = f"{URL_BASE}/{PATH}"
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
    current_price = get_current_price(symbol)
    if current_price is None:
        send_message(f"{symbol} 잔고 조회를 위한 현재가 조회 실패", symbol)
        return 0
    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "ITEM_CD": symbol,
        "OVRS_EXCG_CD": market_info["MARKET"],
        "OVRS_ORD_UNPR": str(current_price)
    }
    try:
        res = requests.get(URL, headers=headers, params=params)
        if res.status_code == 401 or (res.status_code == 200 and 'access_token' in res.text.lower()):
            send_message(f"{symbol} 잔고 조회 중 토큰 오류. 토큰 갱신 중...", symbol)
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN and retry_count < MAX_RETRIES:
                headers["authorization"] = f"Bearer {ACCESS_TOKEN}"
                return get_balance(symbol, retry_count + 1)
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
        if 'access_token' in error_msg and retry_count < MAX_RETRIES:
            send_message(f"{symbol} 잔고 조회 중 토큰 오류: {e}", symbol)
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                return get_balance(symbol, retry_count + 1)
        else:
            send_message(f"{symbol} 잔고 조회 중 오류: {e}", symbol)
        return 0

@cache_1min
def get_stock_balance(symbol):
    """주식 잔고조회 (심볼 인자 추가 + 토큰 오류 처리 + 손절매용 손익률 정보 추가)"""
    global ACCESS_TOKEN
    
    # 각 종목별 시장 정보 매핑
    MARKET_MAP = {
        "PLTR": {"EXCD": "NAS", "MARKET": "NASD"},
        "NVDA": {"EXCD": "NAS", "MARKET": "NASD"},
        "TSLA": {"EXCD": "NAS", "MARKET": "NASD"},
        "IONQ": {"EXCD": "NYS", "MARKET": "NYSE"},
        "CRCL": {"EXCD": "NYS", "MARKET": "NYSE"},
        "TSM": {"EXCD": "NYS", "MARKET": "NYSE"}
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
        "OVRS_EXCG_CD": market_info["MARKET"],
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
                # 🔹 수정된 부분: 현재가 처리 개선
                current_price_str = stock.get('ovrs_now_pric', '0')
                if current_price_str == '' or current_price_str == 'N/A':
                    current_price_str = '0'
                
                current_price = float(current_price_str) if current_price_str != '0' else 0.0
                
                # 손절매를 위한 추가 정보 포함
                stock_dict[stock['ovrs_pdno']] = {
                    'qty': stock['ovrs_cblc_qty'],
                    'current_price': current_price,  # 🔹 수정: N/A 처리 개선
                    'purchase_price': float(stock.get('pchs_avg_pric', '0')),
                    'profit_rate': float(stock.get('evlu_pfls_rt', '0')),
                    'profit_amount': float(stock.get('evlu_pfls_amt', '0'))
                }
                
                send_message(f"{stock['ovrs_item_name']}({stock['ovrs_pdno']}): {stock['ovrs_cblc_qty']}주", symbol)
                send_message(f"  - 매입가: ${stock.get('pchs_avg_pric', 'N/A')}", symbol)
                # 🔹 수정된 부분: 현재가 표시 개선
                current_price_display = f"${current_price:.2f}" if current_price > 0 else "조회 필요"
                send_message(f"  - 현재가: {current_price_display}", symbol)
                send_message(f"  - 손익률: {stock.get('evlu_pfls_rt', 'N/A')}%", symbol)
                time.sleep(0.1)
        
        send_message(f"주식 평가 금액: ${evaluation['tot_evlu_pfls_amt']}", symbol)
        time.sleep(0.1)
        send_message(f"평가 손익 합계: ${evaluation['ovrs_tot_pfls']}", symbol)
        time.sleep(0.1)
        #send_message(f"=================", symbol)
        
        return stock_dict
        
    except Exception as e:
        error_msg = str(e).lower()
        if 'access_token' in error_msg:
            send_message(f"{symbol} 주식 잔고 조회 중 토큰 오류: {e}", symbol)
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                return get_stock_balance(symbol)
        else:
            send_message(f"{symbol} 주식 잔고 조회 중 오류: {e}", symbol)
        return {}

# RSI + 이동평균선 조합 매매 전략 - 복사 붙여넣기용

# 1. 이동평균선 계산 함수 추가 (기존 코드에 추가)
def calculate_moving_averages(data, short_period=MA_SHORT_PERIOD, long_period=MA_LONG_PERIOD):
    """이동평균선 계산 (20일, 50일 이동평균)"""
    try:
        # 데이터 유효성 확인
        if "output2" not in data or not data["output2"]:
            print("이동평균 계산을 위한 데이터가 부족합니다")
            return None, None, None

        # 데이터프레임 생성
        df = pd.DataFrame(data["output2"])
        # print(f"이동평균 계산을 위한 데이터 프레임 생성 완료: {len(df)} 행")  # 로그 스팸 방지
        
        # 가격 컬럼 동적 탐색 및 처리
        price_columns = ['stck_prpr', 'ovrs_nmix_prpr', 'close', 'last', 'stck_clpr']
        
        # 가격 컬럼 찾기 및 데이터 정제
        price_col = None
        for col in price_columns:
            if col in df.columns:
                # 숫자가 아닌 값 제거, 빈 문자열 처리
                df[col] = pd.to_numeric(df[col].replace('', np.nan), errors='coerce')
                if not df[col].isnull().all():  # Series 조건문 오류 수정
                    price_col = col
                    break
        
        if not price_col:
            print("가격 데이터 컬럼을 찾을 수 없습니다:", df.columns)
            return None, None, None
        
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
        if len(df) < long_period:
            print(f"이동평균 계산을 위한 데이터 부족 (필요: {long_period}, 현재: {len(df)})")
            return None, None, None
        
        # 이동평균선 계산
        df['ma_short'] = df['price'].rolling(window=short_period).mean()
        df['ma_long'] = df['price'].rolling(window=long_period).mean()
        
        # 최신 값들 추출
        current_price = df['price'].iloc[-1]
        current_ma_short = df['ma_short'].iloc[-1]
        current_ma_long = df['ma_long'].iloc[-1]
        
        print(f"현재가: {current_price:.2f}")
        # print(f"{short_period}일 이동평균: {current_ma_short:.2f}")  # 로그 스팸 방지
        # print(f"{long_period}일 이동평균: {current_ma_long:.2f}")  # 로그 스팸 방지
        
        return current_price, current_ma_short, current_ma_long
    
    except Exception as e:
        print(f"이동평균 계산 중 오류 발생: {e}")
        return None, None, None

# 2. RSI + 이동평균 조합 분석 함수 (기존 코드에 추가)
def get_technical_analysis(symbol, rsi_periods=RSI_PERIODS, ma_short=MA_SHORT_PERIOD, ma_long=MA_LONG_PERIOD, nmin=MINUTE_INTERVAL):
    """RSI와 이동평균을 함께 분석하는 함수"""
    global ACCESS_TOKEN
    # print(f"기술적 분석 시작: {symbol}")  # 로그 스팸 방지
    
    try:
        # 액세스 토큰 확인 및 갱신
        if not ACCESS_TOKEN:
            ACCESS_TOKEN = get_access_token()
            if not ACCESS_TOKEN:
                print("토큰 발급 실패, 1분 후 재시도...")
                time.sleep(60)
                ACCESS_TOKEN = get_access_token()
                if not ACCESS_TOKEN:
                    return None
        
        # 더 많은 데이터 조회 (이동평균 계산을 위해)
        data = get_minute_data(
            symbol=symbol, 
            nmin=nmin, 
            period=DATA_PERIOD,  # 더 많은 데이터 조회
            access_token=ACCESS_TOKEN
        )
        
        if not data:
            send_message(f"{symbol} 데이터 조회 실패, 기술적 분석 불가", symbol)
            return None
            
        # RSI 계산
        rsi_value = calculate_rsi(data, rsi_periods)
        
        # 이동평균선 계산
        current_price, ma_short_value, ma_long_value = calculate_moving_averages(
            data, ma_short, ma_long
        )
        
        if ma_short_value is None or ma_long_value is None:
            send_message(f"{symbol} 이동평균 계산 실패", symbol)
            return {
                'rsi': rsi_value,
                'current_price': current_price,
                'ma_short': None,
                'ma_long': None,
                'price_vs_ma_long_percent': None,
                'ma_trend': None
            }
        
        # 현재가와 장기 이동평균 대비 비율 계산
        price_vs_ma_long_percent = ((current_price - ma_long_value) / ma_long_value) * 100
        
        # 이동평균선 추세 판단 (단기 > 장기 = 상승 추세)
        ma_trend = "상승" if ma_short_value > ma_long_value else "하락"
        
        analysis_result = {
            'rsi': rsi_value,
            'current_price': current_price,
            'ma_short': ma_short_value,
            'ma_long': ma_long_value,
            'price_vs_ma_long_percent': price_vs_ma_long_percent,
            'ma_trend': ma_trend
        }
        
        # 기술적 분석 결과와 결론을 함께 출력
        print(f"📊 {symbol} 기술적 분석:")
        print(f"  - RSI: {rsi_value:.2f}")
        print(f"  - 현재가: ${current_price:.2f}")
        print(f"  - {ma_short}일 이평: ${ma_short_value:.2f}")
        print(f"  - {ma_long}일 이평: ${ma_long_value:.2f}")
        print(f"  - 장기이평 대비: {price_vs_ma_long_percent:+.2f}%")
        print(f"  - 이평 추세: {ma_trend}")
        
        return analysis_result
    
    except Exception as e:
        error_msg = str(e).lower()
        if 'access_token' in error_msg:
            send_message(f"{symbol} 기술적 분석 중 토큰 오류 발생. 토큰 갱신 시도 중...", symbol)
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                send_message("토큰 갱신 성공. 다시 시도합니다.", symbol)
                return get_technical_analysis(symbol, rsi_periods, ma_short, ma_long, nmin)
        else:
            send_message(f"{symbol} 기술적 분석 중 오류: {e}", symbol)
        return None

# 3. 개선된 매수 조건 판단 함수 (기존 코드에 추가)
def should_buy(analysis, max_price_above_ma_percent=MAX_PRICE_ABOVE_MA_PERCENT):
    """
    매수 조건 판단
    analysis: get_technical_analysis 결과
    max_price_above_ma_percent: 장기이동평균 대비 최대 허용 상승률(%)
    """
    if not analysis:
        return False, "기술적 분석 데이터 없음"
    
    rsi = analysis['rsi']
    price_vs_ma_long = analysis['price_vs_ma_long_percent']
    
    # 기본 RSI 과매도 조건
    rsi_oversold = rsi <= 30
    
    # 장기이동평균 대비 가격이 너무 높지 않은지 확인
    price_not_too_high = price_vs_ma_long is not None and price_vs_ma_long <= max_price_above_ma_percent
    
    # 매수 조건 종합 판단
    if rsi_oversold and price_not_too_high:
        return True, f"매수 조건 충족 (RSI: {rsi:.2f}, 장기이평 대비: {price_vs_ma_long:+.2f}%)"
    
    # 매수 조건 미충족 사유 반환
    reasons = []
    if not rsi_oversold:
        reasons.append(f"RSI 과매도 아님({rsi:.2f})")
    if not price_not_too_high:
        if price_vs_ma_long is not None:
            reasons.append(f"장기이평 대비 과도한 상승({price_vs_ma_long:+.2f}% > {max_price_above_ma_percent}%)")
        else:
            reasons.append("이동평균 데이터 없음")
    
    return False, f"매수 조건 미충족: {', '.join(reasons)}"


# 4. 기존 매도 조건 유지 함수 (기존 코드에 추가)
def should_sell(analysis, profit_rate):
    """
    매도 조건 판단 (RSI 설정값 이상 + 수익률 10% 이상일 때)
    보유 수량이 1주 이하인 경우 매도하지 않음 (추세 확인용)
    analysis: get_technical_analysis 결과
    profit_rate: 현재 수익률
    """
    if not analysis:
        return False, "기술적 분석 데이터 없음"
    
    rsi = analysis['rsi']
    
    # 매도 조건: RSI 과매수 + 수익률 5% 이상
    rsi_overbought = rsi >= RSI_SELL_THRESHOLD
    is_profitable_enough = profit_rate >= PROFIT_TAKE_PERCENT
    
    # 매도 조건: RSI 설정값 이상이면서 수익률 5% 이상일 때
    if rsi_overbought and is_profitable_enough:
        return True, f"매도 조건 충족 (RSI: {rsi:.2f}, 수익률: {profit_rate:+.2f}% >= {PROFIT_TAKE_PERCENT}%)"
    
    # 매도 조건 미충족 사유
    reasons = []
    if not rsi_overbought:
        reasons.append(f"RSI 과매수 아님({rsi:.2f} < {RSI_SELL_THRESHOLD})")
    if not is_profitable_enough:
        if profit_rate >= 0:
            reasons.append(f"수익률 부족({profit_rate:+.2f}% < {PROFIT_TAKE_PERCENT}%)")
        else:
            reasons.append(f"손실 상태({profit_rate:+.2f}%)")
    
    return False, f"매도 조건 미충족: {', '.join(reasons)}"


def buy(market=MARKET, code="", qty="1", price="0"): 
    """미국 주식 지정가 매수 (토큰 오류 처리 추가)"""
    global ACCESS_TOKEN
    PATH = "uapi/overseas-stock/v1/trading/order"
    URL = f"{URL_BASE}/{PATH}"

    # 각 종목별 시장 정보 매핑
    MARKET_MAP = {
        "PLTR": {"EXCD": "NAS", "MARKET": "NASD"},
        "NVDA": {"EXCD": "NAS", "MARKET": "NASD"},
        "TSLA": {"EXCD": "NAS", "MARKET": "NASD"},
        "IONQ": {"EXCD": "NYS", "MARKET": "NYSE"},
        "CRCL": {"EXCD": "NYS", "MARKET": "NYSE"},
        "TSM": {"EXCD": "NYS", "MARKET": "NYSE"}
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
            send_message(f"✅ [매수 성공] {code} {qty}주 @${price:.2f}", code, level=MESSAGE_LEVEL_CRITICAL)
            return True
        else:
            send_message(f"🚨 [매수 실패] {res_data.get('msg1', '알 수 없는 오류 발생')}", code, level=MESSAGE_LEVEL_CRITICAL)
            return False
            
    except Exception as e:
        error_msg = str(e).lower()
        if 'access_token' in error_msg:
            send_message(f"🚨 [매수 중 토큰 오류] {str(e)}", code)
            # 토큰 갱신 시도
            ACCESS_TOKEN = get_access_token()
            if ACCESS_TOKEN:
                # 재귀적으로 다시 시도 (무한 루프 방지 필요)
                return buy(market, code, qty, str(price))  # float -> str 변환
        else:
            send_message(f"🚨 [매수 실패] {str(e)}", code)
        return False
     ## 달러가 있어야 하는데 없으면 잔고 부족으로 나옴

def sell(market=MARKET, code="", qty="all", price="0"):
    """미국 주식 지정가 매도 (보유 수량을 자동으로 설정 가능 + 토큰 오류 처리)"""
    global ACCESS_TOKEN

    # 각 종목별 시장 정보 매핑
    MARKET_MAP = {
        "PLTR": {"EXCD": "NAS", "MARKET": "NASD"},
        "NVDA": {"EXCD": "NAS", "MARKET": "NASD"},
        "TSLA": {"EXCD": "NAS", "MARKET": "NASD"},
        "IONQ": {"EXCD": "NYS", "MARKET": "NYSE"},
        "CRCL": {"EXCD": "NYS", "MARKET": "NYSE"},
        "TSM": {"EXCD": "NYS", "MARKET": "NYSE"}
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

        held_qty = int(stock_dict[code]['qty'])

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
                send_message(f"✅ [매도 성공] {code} {qty}주 @ ${price:.2f}", code, level=MESSAGE_LEVEL_CRITICAL)
                return True
            else:
                send_message(f"🚨 [매도 실패] {res_data.get('msg1', '알 수 없는 오류 발생')}", code, level=MESSAGE_LEVEL_CRITICAL)
                return False
                
        except Exception as e:
            error_msg = str(e).lower()
            if 'access_token' in error_msg:
                send_message(f"🚨 [매도 중 토큰 오류] {str(e)}", code)
                # 토큰 갱신 시도
                ACCESS_TOKEN = get_access_token()
                if ACCESS_TOKEN:
                    # 재귀적으로 다시 시도 (무한 루프 방지 필요)
                    return sell(market, code, qty, str(price))  # float -> str 변환
            else:
                send_message(f"🚨 [매도 실패] {str(e)}", code)
            return False
            
    except Exception as e:
        send_message(f"🚨 [매도 준비 중 오류] {str(e)}", code)
        return False

# 손절매 함수 추가
def check_stop_loss(symbol, stop_loss_percent=STOP_LOSS_PERCENT, max_retries=3):
    try:
        stock_dict = get_stock_balance(symbol)
        if symbol not in stock_dict:
            return False
        stock_info = stock_dict[symbol]
        loss_percent = float(stock_info['profit_rate'])
        quantity = stock_info['qty']
        current_price = None
        for attempt in range(max_retries):
            current_price = get_current_price(symbol)
            if current_price is not None and current_price > 0:
                break
            time.sleep(2)
        if current_price is None or current_price <= 0:
            send_message(f"⚠️ {symbol} 현재가 조회 실패로 손절매 건너뜀 (재시도 {max_retries}회)", symbol)
            return False
        purchase_price = float(stock_info['purchase_price'])
        if loss_percent <= -stop_loss_percent:
            send_message(f"⚠️ 손절매 조건 충족: {symbol}", symbol, level=MESSAGE_LEVEL_CRITICAL)
            send_message(f"- 매입가: ${purchase_price:.2f}", symbol, level=MESSAGE_LEVEL_IMPORTANT)
            send_message(f"- 현재가: ${current_price:.2f}", symbol, level=MESSAGE_LEVEL_IMPORTANT)
            send_message(f"- 손실률: {loss_percent:.2f}%", symbol, level=MESSAGE_LEVEL_IMPORTANT)
            send_message(f"- 손절매 기준: -{stop_loss_percent}%", symbol, level=MESSAGE_LEVEL_INFO)
            sell_result = sell(code=symbol, qty=quantity, price=str(current_price))
            if sell_result:
                send_message(f"✅ 손절매 완료: {symbol} {quantity}주 @ ${current_price:.2f}", symbol, level=MESSAGE_LEVEL_CRITICAL)
                return True
            else:
                send_message(f"❌ 손절매 실패: {symbol}", symbol, level=MESSAGE_LEVEL_CRITICAL)
                return False
        else:
            # 손절매 조건 미충족 메시지 제거 (너무 빈번함)
            pass
    except Exception as e:
        send_message(f"🚨 손절매 검사 중 오류: {str(e)}", symbol)
        return False
    return False

#3파트


def main():
    global ACCESS_TOKEN
    
    token_retry_count = 0
    max_token_retries = 5
    
    # 설정값들은 파일 상단의 전역 변수에서 가져옴
    # 손절매 비율: STOP_LOSS_PERCENT
    # RSI 기간: RSI_PERIODS
    # 이동평균: MA_SHORT_PERIOD, MA_LONG_PERIOD
    # 장기이평 대비 최대 허용 상승률: MAX_PRICE_ABOVE_MA_PERCENT
    # 분봉 간격: MINUTE_INTERVAL
    
    while True:  # 메인 무한 루프
        try:
            # 토큰이 없거나 토큰 오류 후 재시작한 경우
            if not ACCESS_TOKEN:
                ACCESS_TOKEN = get_access_token()
                if not ACCESS_TOKEN:
                    send_message("토큰 발급 실패, 2분 후 재시도...", level=MESSAGE_LEVEL_IMPORTANT)
                    time.sleep(120)  # AWS 사용량 저감을 위해 2분으로 증가
                    token_retry_count += 1
                    if token_retry_count > max_token_retries:
                        send_message(f"토큰 발급 {max_token_retries}회 실패, 10분 후 다시 시도합니다.")
                        time.sleep(600)
                        token_retry_count = 0
                    continue
                token_retry_count = 0
                
            bought_list = []  # 매수 완료된 종목 리스트
            
            # 매수 비율은 파일 상단의 BUY_RATIO 변수에서 가져옴

            send_message(f"=== 자동매매 프로그램 시작 ({MARKET}) ===", level=MESSAGE_LEVEL_IMPORTANT)
            send_message(f"종목: {SYMBOLS} | 매수비율: {BUY_RATIO*100}% | 손절: {STOP_LOSS_PERCENT}% | 익절: {PROFIT_TAKE_PERCENT}%", level=MESSAGE_LEVEL_INFO)
            send_message(f"RSI: {RSI_PERIODS}일 | 이평: {MA_SHORT_PERIOD}/{MA_LONG_PERIOD}일 | 분봉: {MINUTE_INTERVAL}분", level=MESSAGE_LEVEL_DEBUG)
            
            # 시간대 설정
            tz = timezone('America/New_York')
            last_token_refresh = datetime.now(tz)
            
            # 초기 실행 설정
            force_first_check = True
            last_check_time = datetime.now(tz) - timedelta(minutes=31)
            last_stop_loss_check_time = datetime.now(tz) - timedelta(minutes=6)  # 손절매 체크 타이머 추가
            
            # 초기 시장 체크
            market_open = is_market_time()
            if not market_open:
                wait_for_market_open()
            
            # 시장 상태 추적 변수
            last_market_status = None
            
            # 내부 루프 - 정상 실행
            while True:
                current_time = datetime.now(tz)
                NAS_time = datetime.now(timezone('America/New_York'))
                
                # 토큰 갱신 (설정된 간격마다)
                if (current_time - last_token_refresh).total_seconds() >= TOKEN_REFRESH_INTERVAL:
                    refresh_token()
                    last_token_refresh = current_time
                    
                    # 메시지 히스토리 정리 (토큰 갱신 시마다)
                    # 오래된 메시지 히스토리 정리
                    current_time = time.time()
                    MESSAGE_HISTORY = {k: v for k, v in MESSAGE_HISTORY.items() 
                                      if current_time - v < MESSAGE_COOLDOWN * 2}
                
                # 시장 상태 확인 (상태 변경 시에만 메시지 발송 및 로그 기록)
                current_market_status = is_market_time()
                if current_market_status != last_market_status:
                    if current_market_status:
                        print("🔔 미국 시장이 개장되었습니다!")
                        send_message("🔔 미국 시장이 개장되었습니다!", level=MESSAGE_LEVEL_CRITICAL)
                        
                        # 시장 개장 시 이전 데이터 정리 (새로운 거래일 시작)
                        if DAILY_SUMMARY_DATA:
                            print("📊 새로운 거래일 시작 - 이전 데이터 정리 중...")
                            DAILY_SUMMARY_DATA.clear()
                            print("✅ 이전 거래일 데이터 정리 완료")
                    else:
                        print("🔔 미국 시장이 마감되었습니다. 다음 개장일까지 대기합니다...")
                        send_message("🔔 미국 시장이 마감되었습니다. 다음 개장일까지 대기합니다...", level=MESSAGE_LEVEL_CRITICAL)
                        wait_for_market_open()
                        continue
                    last_market_status = current_market_status
                elif not current_market_status:
                    # 시장이 닫혀있으면 대기
                    wait_for_market_open()
                    continue
                
                # RSI 체크 조건
                minutes_elapsed = (current_time - last_check_time).total_seconds() / 60
                time_to_check = (NAS_time.minute == 0 or (NAS_time.minute == 1 and NAS_time.second <= 30))

                # 손절매 체크 조건 (설정된 간격마다)
                stop_loss_minutes_elapsed = (current_time - last_stop_loss_check_time).total_seconds() / 60
                
                # 손절매 체크 로직 (설정된 간격마다)
                if is_market_time() and stop_loss_minutes_elapsed >= STOP_LOSS_CHECK_INTERVAL:
                    # send_message("손절매 조건 확인 중...", level=MESSAGE_LEVEL_DEBUG)  # 로그 스팸 방지
                    
                    # 한 번만 전체 잔고를 조회하여 효율성 향상
                    all_holdings = {}
                    for symbol in SYMBOLS:
                        try:
                            stock_dict = get_stock_balance(symbol)
                            if symbol in stock_dict:
                                all_holdings[symbol] = stock_dict[symbol]
                        except Exception as e:
                            send_message(f"{symbol} 잔고 조회 중 오류: {str(e)}", symbol, level=MESSAGE_LEVEL_CRITICAL)
                    
                    # 보유 종목에 대해서만 손절매 체크
                    for symbol, holding_info in all_holdings.items():
                        try:
                            # 손절매 확인 메시지 제거 (너무 빈번함)
                            
                            # 이미 조회한 잔고 정보를 활용
                            loss_percent = float(holding_info['profit_rate'])
                            quantity = holding_info['qty']
                            
                            # 현재가를 별도로 조회
                            current_price = get_current_price(symbol)
                            if current_price is None or current_price <= 0:
                                send_message(f"⚠️ {symbol} 현재가 조회 실패로 손절매 건너뜀", symbol, level=MESSAGE_LEVEL_IMPORTANT)
                                continue
                                
                            purchase_price = float(holding_info['purchase_price'])
                            
                            # 손절매 조건 확인
                            if check_stop_loss(symbol, STOP_LOSS_PERCENT):
                                send_message(f"✅ 손절매 완료: {symbol} {quantity}주 @ ${current_price:.2f}", symbol, level=MESSAGE_LEVEL_CRITICAL)
                            # 손절매 실패 메시지 제거 (너무 빈번함)
                                
                        except Exception as e:
                            send_message(f"{symbol} 손절매 체크 중 오류: {str(e)}", symbol, level=MESSAGE_LEVEL_CRITICAL)
                    
                    # 미보유 종목 메시지 제거 (불필요함)
                    
                    last_stop_loss_check_time = current_time
                    # 손절매 완료 메시지 제거 (너무 빈번함)

                # RSI + 이동평균 기반 매매 로직
                if force_first_check or (minutes_elapsed >= RSI_CHECK_INTERVAL and time_to_check):
                    # 시장 상태 확인
                    market_open = is_market_time()
                    if not market_open:
                        wait_for_market_open()
                        last_check_time = current_time
                        force_first_check = False
                        continue
                    
                    # 각 심볼에 대한 처리
                    for symbol in SYMBOLS:
                        try:
                            KST_time = datetime.now(timezone('Asia/Seoul'))
                            
                            # RSI 매매 전 손절매 우선 체크 (중복 잔고 조회 방지)
                            # 최근 설정된 시간 이내에 손절매 체크를 했다면 건너뜀
                            recent_stop_loss_check = (current_time - last_stop_loss_check_time).total_seconds() < (STOP_LOSS_CHECK_INTERVAL * 60)
                            
                            if not recent_stop_loss_check:
                                # 개별 종목 손절매 체크 (설정된 간격마다 체크를 하지 않았을 때만)
                                try:
                                    stock_dict = get_stock_balance(symbol)
                                    if symbol in stock_dict:
                                        # 손절매 조건 확인
                                        loss_percent = float(stock_dict[symbol]['profit_rate'])
                                        if check_stop_loss(symbol, STOP_LOSS_PERCENT):
                                            current_price = get_current_price(symbol)
                                            if current_price and current_price > 0:
                                                quantity = stock_dict[symbol]['qty']
                                                send_message(f"⚠️ RSI 체크 중 손절매 조건 발견: {symbol} (손실률: {loss_percent:.2f}%)", symbol)
                                                sell_result = sell(code=symbol, qty=quantity, price=str(current_price))
                                                if sell_result:
                                                    send_message(f"✅ {symbol} 손절매 완료, 다음 종목으로 넘어갑니다.", symbol)
                                                    continue
                                except Exception as e:
                                    send_message(f"{symbol} 손절매 사전 체크 중 오류: {str(e)}", symbol)
                            
                            # RSI + 이동평균 기반 기술적 분석
                            #send_message(f"기술적 분석 시작 (RSI + 이동평균)", symbol)
                            technical_analysis = get_technical_analysis(symbol, RSI_PERIODS, MA_SHORT_PERIOD, MA_LONG_PERIOD, MINUTE_INTERVAL)
                            if technical_analysis is None:
                                send_message(f"기술적 분석 실패, 다음 종목으로 넘어갑니다", symbol, level=MESSAGE_LEVEL_DEBUG)
                                continue

                            # 현재가 정보 (technical_analysis에서 가져옴)
                            current_price = technical_analysis['current_price']
                            if current_price is None:
                                send_message(f"현재가 조회 실패", symbol, level=MESSAGE_LEVEL_DEBUG)
                                continue

                            # 개선된 매수 조건 판단 (RSI + 이동평균 조합)
                            buy_signal, buy_reason = should_buy(technical_analysis)
                            # 매수 분석 메시지는 DEBUG 레벨로 (너무 빈번함) - 주석 처리로 로그 스팸 방지
                            # send_message(f"매수 분석: {buy_reason}", symbol, level=MESSAGE_LEVEL_DEBUG)

                            # 일일 요약 데이터 수집
                            collect_daily_summary_data(symbol, technical_analysis, buy_signal, False, buy_reason, "")

                            if buy_signal:
                                print(f"🎯 {symbol} 매수 신호 감지: {buy_reason}")
                                send_message(f"✅ 매수 신호 감지", symbol, level=MESSAGE_LEVEL_IMPORTANT)
                                
                                # 현재 잔고 조회
                                try:
                                    cash_balance = get_balance(symbol)
                                    if cash_balance <= 0:
                                        send_message(f"주문 가능 잔고가 없습니다", symbol, level=MESSAGE_LEVEL_INFO)
                                        continue
                                except Exception as e:
                                    if 'access_token' in str(e).lower():
                                        send_message(f"토큰 오류 감지, 토큰 갱신 후 재시도합니다", symbol)
                                        ACCESS_TOKEN = get_access_token()
                                        continue
                                    else:
                                        send_message(f"잔고 조회 중 오류: {str(e)}", symbol)
                                        continue
                                
                                # 매수 로직
                                usd_balance = cash_balance
                                available_usd = usd_balance * BUY_RATIO
                                share_price_with_margin = current_price * (1 + SAFETY_MARGIN)
                                qty = max(1, int(available_usd / share_price_with_margin))
                                
                                if qty > 0:
                                    total_cost = qty * current_price
                                    
                                    send_message(f"- 매수 가능 금액: ${available_usd:.2f}", symbol)
                                    send_message(f"- 주문 수량: {qty}주", symbol)
                                    send_message(f"- 주문 가격: ${current_price:.2f}", symbol)
                                    send_message(f"- 총 주문 금액: ${total_cost:.2f}", symbol)
                                    send_message(f"- 장기이평 대비: {technical_analysis['price_vs_ma_long_percent']:+.2f}%", symbol)
                                    
                                    if total_cost <= (available_usd * (1 - SAFETY_MARGIN)):
                                        try:
                                            buy_result = buy(code=symbol, qty=str(qty), price=str(current_price))
                                            if buy_result:
                                                bought_list.append(symbol)
                                                send_message(f"✅ {symbol} {qty}주 매수 완료", symbol)
                                                # 거래 내역 추가
                                                add_trade_record(symbol, 'buy', qty, current_price)
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

                            else:
                                print(f"❌ {symbol} 매수 신호 없음: {buy_reason}")
                                # 기존 매도 조건 확인 (보유 종목이 있을 때만)
                                try:
                                    stock_dict = get_stock_balance(symbol)
                                    if symbol in stock_dict:
                                        stock_info = stock_dict[symbol]
                                        profit_rate = float(stock_info['profit_rate'])
                                        current_price_from_balance = float(stock_info['current_price'])
                                        purchase_price = float(stock_info['purchase_price'])
                                        qty = stock_info['qty']
                                        
                                        send_message(f"보유 정보 - 매입가: ${purchase_price:.2f}, 손익률: {profit_rate:.2f}%", symbol, level=MESSAGE_LEVEL_DEBUG)
                                        
                                        # 매도 조건: RSI 설정값 이상 + 수익률 10% 이상일 때
                                        sell_signal, sell_reason = should_sell(technical_analysis, profit_rate)
                                        # 매도 분석 메시지를 DEBUG 레벨로 (너무 빈번함)
                                        send_message(f"매도 분석: {sell_reason}", symbol, level=MESSAGE_LEVEL_DEBUG)
                                        
                                        # 일일 요약 데이터 수집 (매도 신호)
                                        collect_daily_summary_data(symbol, technical_analysis, False, sell_signal, "", sell_reason)
                                        
                                        if sell_signal:
                                            print(f"🎯 {symbol} 매도 신호 감지: {sell_reason}")
                                            # 보유 수량이 1주 이하인 경우 매도하지 않음
                                            if int(qty) <= 1:
                                                send_message(f"⚠️ {symbol} 보유 수량이 {qty}주로 매도하지 않습니다 (추세 확인용 1주 유지)", symbol, level=MESSAGE_LEVEL_IMPORTANT)
                                            else:
                                                # 1주를 남기고 나머지만 매도
                                                sell_qty = int(qty) - 1
                                                send_message(f"✅ 매도 신호 감지 - {sell_qty}주 매도 (1주 유지)", symbol, level=MESSAGE_LEVEL_IMPORTANT)
                                                try:
                                                    sell_result = sell(code=symbol, qty=str(sell_qty), price=str(current_price))
                                                    if sell_result:
                                                        send_message(f"✅ {symbol} {sell_qty}주 매도 완료 (1주 유지로 추세 확인)", symbol, level=MESSAGE_LEVEL_CRITICAL)
                                                        # 거래 내역 추가
                                                        add_trade_record(symbol, 'sell', sell_qty, current_price)
                                                except Exception as e:
                                                    if 'access_token' in str(e).lower():
                                                        send_message(f"매도 중 토큰 오류, 토큰 갱신 후 재시도합니다", symbol)
                                                        ACCESS_TOKEN = get_access_token()
                                                        continue
                                                    else:
                                                        send_message(f"매도 중 오류: {str(e)}", symbol)
                                        else:
                                            print(f"❌ {symbol} 매도 신호 없음: {sell_reason}")
                                            # 매도 조건 미충족 메시지 제거 (너무 빈번함)
                                            pass
                                            # 참고용으로만 장기이평 대비 위치 표시 (DEBUG 레벨로)
                                            if technical_analysis['price_vs_ma_long_percent'] is not None:
                                                send_message(f"- 장기이평 대비: {technical_analysis['price_vs_ma_long_percent']:+.2f}% (참고용)", symbol, level=MESSAGE_LEVEL_DEBUG)
                                    else:
                                        # 미보유 종목 메시지를 DEBUG 레벨로 (너무 빈번함)
                                        send_message(f"📊 {symbol}을 보유하고 있지 않습니다", symbol, level=MESSAGE_LEVEL_DEBUG)
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
                    
                    # 다음 체크 시간 계산
                    next_check_minutes = 60 - (NAS_time.minute % 60)
                    if next_check_minutes == 0:
                        next_check_minutes = 60
                    # 다음 체크 시간 메시지를 DEBUG 레벨로 (너무 빈번함)
                    send_message(f"⏳ 다음 기술적 분석까지 약 {next_check_minutes}분 남았습니다", level=MESSAGE_LEVEL_DEBUG)
                    
                    # 정확히 다음 체크까지 대기
                    time.sleep(next_check_minutes * 60)

                # 장 마감 체크
                if NAS_time.hour >= 16:
                    send_message("📉 미국 장 마감으로 프로그램을 종료합니다.", level=MESSAGE_LEVEL_IMPORTANT)
                    
                    # 일일 요약 메시지 발송
                    send_message("📊 일일 거래 요약을 발송합니다...", level=MESSAGE_LEVEL_IMPORTANT)
                    send_daily_summary()
                    
                    wait_for_market_open()
                    continue
                
                # AWS 사용량 저감을 위한 대기 시간 최적화
                if is_market_time():
                    time.sleep(30)  # 시장 개장 시: 30초마다 체크
                else:
                    time.sleep(300)  # 시장 마감 시: 5분마다 체크
                
        except Exception as main_error:
            error_msg = str(main_error).lower()
            send_message(f"🚨 [메인 루프 오류 발생] {error_msg}")
            
            # 토큰 관련 오류인 경우
            if 'access_token' in error_msg:
                send_message("토큰 오류로 인한 재시작, 2분 후 토큰 재발급을 시도합니다.", level=MESSAGE_LEVEL_IMPORTANT)
                ACCESS_TOKEN = None  # 토큰 초기화
                time.sleep(120)  # AWS 사용량 저감을 위해 2분으로 증가
            else:
                # 그 외 오류는 5분 대기 후 재시작 (AWS 사용량 저감)
                send_message("5분 후 프로그램을 재시작합니다...", level=MESSAGE_LEVEL_IMPORTANT)
                time.sleep(300)  # AWS 사용량 저감을 위해 5분으로 증가

if __name__ == "__main__":
    main()

