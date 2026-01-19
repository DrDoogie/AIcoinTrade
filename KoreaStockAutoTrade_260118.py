#0404버전에서 
# # 국내 주식 거래  종목 변경
#0412버전에서
# # 국내 휴일 오류 수정 추가
#0505버전에서 매수 조건을 수정함
#장기이동평균 20일 대비 높은 가격일 경우에는 매수 하지 않도록 수정함
#0628버전에서 커거AI 코드 수정
#중복 메세지 차단 추가  
#추가 수정 하려고 준비중
# 1. 토큰 발급 실패 시 재시도 로직 수정
# 기존: 1분 후 재시도 (time.sleep(60))
# 수정: 2분 후 재시도 (time.sleep(120))
# 적용 위치: 모든 토큰 발급 관련 함수들
# 목적: 서버 이상 대응 및 안정성 향상
# 2. 시장 개장/마감 메시지 추가
# 시장 개장: 🔔 한국 시장이 개장되었습니다! (CRITICAL 레벨)
# 시장 마감: 🔔 한국 시장이 마감되었습니다. 다음 개장일까지 대기합니다... (CRITICAL 레벨)
# 목적: 시장 상태 변경 시점을 명확하게 알림
# 3. 토큰 발급 중복 방지 로직 구현
# 토큰 발급 쿨다운: 120초 간격으로 제한
# 진행 중 플래그: 동시 토큰 발급 요청 차단
# 중복 방지: 서버에서 토큰 발급 거부 방지
# 목적: API 서버 부하 감소 및 안정성 향상
# 4. 반복적인 로그 메시지 개선
# 시장 상태 로그: 상태 변경 시에만 메시지 발송
# 데이터 조회 로그: 이모지와 간결한 형태로 개선
# 계산 완료 로그: ✅ 아이콘으로 성공 표시
# 목적: 로그 스팸 방지 및 가독성 향상
# 5. AWS 사용량 최적화
# 기존: 1초마다 메인 루프 실행
# 수정:
# 시장 개장 시: 30초마다 실행
# 시장 마감 시: 5분마다 실행
# 효과: AWS 사용량 60배 감소, 비용 50-70% 절감
# 6. 코드 품질 개선
# 사용하지 않는 numpy import 제거
# 중복된 딕셔너리 키 제거
# 사용하지 않는 함수 매개변수 제거
# 메시지 함수의 important 매개변수를 level 매개변수로 통일
# 7. 로그 스팸 방지
# 불필요한 로그 제거
# 로그 스팸 방지를 위해 일부 로그 메시지 제거

# 0920 추가 수정 사항
# 1. 로그 스팸 방지
# 로그 스팸 방지를 위해 일부 로그 메시지 제거
# 2. 일일 거래 요약 데이터 수집 설정
# 일일 거래 요약 데이터 수집 설정 추가
# 0929 메세지 분할 발송 기능 수정 
# 1004 RSI 계산 오류 수정
# 디스코드 메세지 발송전 대기 타임 반영
# 1008 메세지 가독성 향상
# 1008 종목별 매매 조건 개별 설정 추가
# 1213 이동평균 조건 미충족 메시지 수정
# 1213 종목별 매매 조건 개별 설정 추가
# 종목추가 (Tiger 차이나휴머노이드로봇)
# 1213 메시지 레벨 수정
# 1213 메시지 발송 오류 수정
# 260117 일일 요약 리포트 개선: 거래가 없어도 분석 내용을 포함한 리포트 발송
# 260117 모든 종목에 대해 매 체크마다 분석 데이터 수집 (거래 신호 없어도 분석 포인트 기록)
# 260117 미국 주식 파일과 동일한 리포트 형식으로 통일
# 260117 거래 미진행 사유 구분: 거래 조건 미충족 vs 잔고 부족을 리포트에 명확히 구분하여 표시
# 260117 RSI 체크 조건 완화: 30분 단위 제약 제거하여 더 자주 분석 데이터 수집 (time_to_check 조건 제거)
# 260117 프로그램 시작 메시지 간소화: 중복 내용 제거하고 요약 메시지로 통합 (7개 메시지 → 1개 요약 메시지)
# 260117 RSI/현재가 조회 실패 시에도 분석 데이터 수집 시도 (기본값 사용하여 리포트 누락 방지)
# 260117 일일 거래 요약 리포트에 종목명 표시: 종목 코드 대신 종목명(예: 삼성전자)으로 표시






#파트1

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
    config = yaml.load(f, Loader=yaml.FullLoader)
APP_KEY = config['APP_KEY']
APP_SECRET = config['APP_SECRET']
ACCESS_TOKEN = ""
CANO = config['CANO']
ACNT_PRDT_CD = config['ACNT_PRDT_CD']
DISCORD_WEBHOOK_URL = config['DISCORD_WEBHOOK_URL']
URL_BASE = config['URL_BASE']

# 매매 대상 종목 리스트 (종목코드)
#삼성전자, SK하이닉스, kodex200, PLUS K방산,,SOL 조선 top3, Tiger S&P, Tiger 차이나휴머노이드로봇
SYMBOLS = ["005930","000660","069500", "449450","466920","360750","0053L0"]

# 종목 코드와 종목명 매핑
SYMBOL_NAMES = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "069500": "KODEX 200",
    "449450": "PLUS K방산",
    "466920": "SOL 조선 TOP3",
    "360750": "Tiger S&P",
    "0053L0": "Tiger 차이나휴머노이드로봇"
}

def get_symbol_name(symbol):
    """종목 코드로 종목명 반환"""
    return SYMBOL_NAMES.get(symbol, symbol)  # 매핑이 없으면 코드 그대로 반환  


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

# ===== 종목별 매매 설정 =====
# 기본 설정 (모든 종목에 공통 적용)
DEFAULT_CONFIG = {
    'rsi_oversold': 28,
    'rsi_overbought': 73,
    'profit_take_percent': 10.0,
    'buy_ratio': 0.3,
    'ma_period': 20,
    'max_price_above_ma_percent': 0  # 이동평균 대비 최대 허용 상승률 (0이면 이동평균 이하만 매수)
}

# 종목별 개별 설정 (변동성과 특성에 맞게 조정)
SYMBOL_CONFIGS = {
    # 대형주 (안정적, 낮은 변동성)
    "005930": {  # 삼성전자
        'rsi_oversold': 28,
        'rsi_overbought': 72,
        'profit_take_percent': 8.0,
        'buy_ratio': 0.35,
        'ma_period': 20
    },
    "000660": {  # SK하이닉스
        'rsi_oversold': 28,
        'rsi_overbought': 72,
        'profit_take_percent': 10.0,
        'buy_ratio': 0.30,
        'ma_period': 20
    },
    
    # ETF (안정적)
    "069500": {  # KODEX 200
        'rsi_oversold': 32,
        'rsi_overbought': 68,
        'profit_take_percent': 6.0,
        'buy_ratio': 0.40,
        'ma_period': 20
    },
    
    # 테마주 (중간 변동성)
    "449450": {  # PLUS K방산
        'rsi_oversold': 25,
        'rsi_overbought': 75,
        'profit_take_percent': 12.0,
        'buy_ratio': 0.25,
        'ma_period': 20
    },
    "466920": {  # SOL 조선 TOP3
        'rsi_oversold': 25,
        'rsi_overbought': 75,
        'profit_take_percent': 12.0,
        'buy_ratio': 0.25,
        'ma_period': 20
    },
    "360750": {  # Tiger S&P
        'rsi_oversold': 30,
        'rsi_overbought': 70,
        'profit_take_percent': 8.0,
        'buy_ratio': 0.30,
        'ma_period': 20,
        'max_price_above_ma_percent': 0
    },
    "0053L0": {  # Tiger 차이나휴머노이드로봇
        'rsi_oversold': 28,
        'rsi_overbought': 72,
        'profit_take_percent': 12.0,
        'buy_ratio': 0.25,
        'ma_period': 20,
        'max_price_above_ma_percent': 0
    }
}

def get_symbol_config(symbol):
    """종목별 설정값 반환 (없으면 기본값 사용)"""
    config = DEFAULT_CONFIG.copy()
    if symbol in SYMBOL_CONFIGS:
        config.update(SYMBOL_CONFIGS[symbol])
    return config

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

# ===== 종목 정보 파일 저장 설정 =====
# JSON 파일 저장 기능 제거 - API에서 실시간 조회하므로 불필요
# ===== 종목 정보 파일 저장 설정 끝 =====

# ===== 일일 거래 요약 데이터 수집 설정 =====
DAILY_SUMMARY_DATA = {}  # 종목별 일일 분석 데이터 저장
# ===== 일일 거래 요약 데이터 수집 설정 끝 =====

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

def collect_daily_summary_data(symbol, rsi_value, current_price, ma_value, buy_signal, sell_signal, buy_reason, sell_reason, trade_failure_reason=None):
    """일일 거래 요약 데이터 수집
    trade_failure_reason: 거래 미진행 사유 ('insufficient_balance': 잔고 부족, 'condition_not_met': 조건 미충족, None: 정상)
    """
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
            'trade_failures': [],  # 거래 실패 내역 추가
            'rsi_range': {'min': 100, 'max': 0},
            'price_range': {'min': float('inf'), 'max': 0},
            'start_time': time_str,
            'last_time': time_str
        }
    
    # 분석 포인트 추가
    analysis_point = {
        'time': time_str,
        'rsi': rsi_value,
        'current_price': current_price,
        'ma_value': ma_value,
        'buy_signal': buy_signal,
        'sell_signal': sell_signal,
        'buy_reason': buy_reason,
        'sell_reason': sell_reason,
        'trade_failure_reason': trade_failure_reason  # 거래 실패 사유 추가
    }
    
    # 거래 실패 내역 기록 (매수 신호는 있지만 거래가 진행되지 않은 경우)
    if buy_signal and trade_failure_reason:
        DAILY_SUMMARY_DATA[symbol]['trade_failures'].append({
            'time': time_str,
            'type': 'buy',
            'reason': trade_failure_reason,
            'reason_detail': buy_reason if trade_failure_reason == 'condition_not_met' else '잔고 부족으로 매수 불가',
            'price': current_price,
            'rsi': rsi_value
        })
    
    DAILY_SUMMARY_DATA[symbol]['analysis_points'].append(analysis_point)
    DAILY_SUMMARY_DATA[symbol]['last_time'] = time_str
    
    # RSI 범위 업데이트
    if rsi_value < DAILY_SUMMARY_DATA[symbol]['rsi_range']['min']:
        DAILY_SUMMARY_DATA[symbol]['rsi_range']['min'] = rsi_value
    if rsi_value > DAILY_SUMMARY_DATA[symbol]['rsi_range']['max']:
        DAILY_SUMMARY_DATA[symbol]['rsi_range']['max'] = rsi_value
    
    # 가격 범위 업데이트
    if current_price < DAILY_SUMMARY_DATA[symbol]['price_range']['min']:
        DAILY_SUMMARY_DATA[symbol]['price_range']['min'] = current_price
    if current_price > DAILY_SUMMARY_DATA[symbol]['price_range']['max']:
        DAILY_SUMMARY_DATA[symbol]['price_range']['max'] = current_price
    
    # 매수/매도 신호 기록
    if buy_signal:
        DAILY_SUMMARY_DATA[symbol]['buy_signals'].append({
            'time': time_str,
            'reason': buy_reason,
            'price': current_price,
            'rsi': rsi_value
        })
    
    if sell_signal:
        DAILY_SUMMARY_DATA[symbol]['sell_signals'].append({
            'time': time_str,
            'reason': sell_reason,
            'price': current_price,
            'rsi': rsi_value
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
        final_rsi = last_analysis['rsi']
        final_ma = last_analysis['ma_value']
    else:
        final_price = 0
        final_rsi = 0
        final_ma = 0
    
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
    
    message += f"종가(마감): ₩{final_price:,.0f} | RSI: {final_rsi:.2f} | {MA_PERIOD}일 이평: ₩{final_ma:,.0f}\n"
    
    # 매수/매도 조건 요약
    if data['buy_signals'] or data['sell_signals']:
        message += f"매수 신호: {len(data['buy_signals'])}회, 매도 신호: {len(data['sell_signals'])}회\n\n"
    else:
        message += "매수/매도 조건: 발생하지 않음\n\n"
    
    message += "**2️⃣ 주요 체크 시점**\n"
    for point in key_points:
        signal_status = "❌ 신호 없음"
        if point['buy_signal']:
            signal_status = "✅ 매수 신호"
        elif point['sell_signal']:
            signal_status = "✅ 매도 신호"
        
        message += f"{point['time']} | RSI {point['rsi']:.2f} | ₩{point['current_price']:,.0f} | "
        message += f"{MA_PERIOD}일 이평 ₩{point['ma_value']:,.0f} → {signal_status}\n"
    
    message += "\n**3️⃣ 거래 내역**\n"
    if data['trades']:
        for trade in data['trades']:
            trade_type_emoji = "🟢" if trade['type'] == 'buy' else "🔴"
            message += f"{trade_type_emoji} {trade['time']} | {trade['type'].upper()} {trade['qty']}주 @ ₩{trade['price']:,.0f}\n"
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
    """일일 거래 요약 메시지들을 분할하여 생성 (간소화)"""
    global DAILY_SUMMARY_DATA
    
    if symbol not in DAILY_SUMMARY_DATA:
        print(f"❌ {symbol} 데이터 없음")
        return None
    
    data = DAILY_SUMMARY_DATA[symbol]
    current_date = datetime.now(timezone('Asia/Seoul')).strftime('%Y-%m-%d')
    symbol_name = get_symbol_name(symbol)  # 종목명 가져오기
    print(f"📊 {symbol_name}({symbol}) 일일 요약 생성 시작 - 분석 포인트: {len(data['analysis_points'])}개")
    
    # 최종 데이터
    if data['analysis_points']:
        last_analysis = data['analysis_points'][-1]
        final_price = last_analysis['current_price']
        final_rsi = last_analysis['rsi']
        final_ma = last_analysis['ma_value']
    else:
        final_price = 0
        final_rsi = 0
        final_ma = 0
    
    # 주요 포인트 선택 (최대 3개)
    key_points = []
    if len(data['analysis_points']) >= 3:
        indices = [0, len(data['analysis_points'])//2, -1]
        key_points = [data['analysis_points'][i] for i in indices]
    else:
        key_points = data['analysis_points'][-3:]  # 최근 3개만
    
    messages = []
    
    # 메시지 1: 기본 요약 (매우 짧게) - 종목명 사용
    message1 = f"**[{symbol_name}({symbol}) 일일 요약 {current_date}]**\n"
    message1 += f"시간: {data['start_time']}~{data['last_time']} | 종가: ₩{final_price:,:.0f}\n"
    message1 += f"RSI: {data['rsi_range']['min']:.1f}~{data['rsi_range']['max']:.1f} | 이평: ₩{final_ma:,.0f}\n"
    message1 += f"신호: 매수{len(data['buy_signals'])}회/매도{len(data['sell_signals'])}회\n"
    
    messages.append(message1)
    
    # 메시지 2: 주요 포인트 (줄여서)
    if key_points:
        message2 = f"**주요 체크포인트**\n"
        for i, point in enumerate(key_points):
            signal = "매수" if point['buy_signal'] else ("매도" if point['sell_signal'] else "")
            signal_emoji = "✅" if signal else "⚪"
            message2 += f"{point['time'][5:]} RSI{point['rsi']:.1f} ₩{point['current_price']:,.0f} {signal_emoji}{signal}\n"
        
        messages.append(message2)
    
    # 메시지 3: 거래내역 + 거래 실패 내역 + 결론
    message3 = f"**거래내역**\n"
    if data['trades']:
        for trade in data['trades']:
            emoji = "🟢" if trade['type'] == 'buy' else "🔴"
            message3 += f"{emoji}{trade['time'][5:]} {trade['type'].upper()} {trade['qty']}주 ₩{trade['price']:,.0f}\n"
    else:
        message3 += "거래 없음\n"
    
    # 거래 실패 내역 추가
    if 'trade_failures' in data and data['trade_failures']:
        message3 += f"\n**거래 미진행 내역**\n"
        for failure in data['trade_failures']:
            if failure['reason'] == 'insufficient_balance':
                message3 += f"⚠️ {failure['time'][5:]} 매수 신호 발생, 잔고 부족으로 거래 미진행\n"
            elif failure['reason'] == 'condition_not_met':
                message3 += f"⚪ {failure['time'][5:]} 거래 조건 미충족 (RSI {failure['rsi']:.1f})\n"
    
    message3 += f"\n**전략결론**\n"
    if data['rsi_range']['max'] >= 70:
        message3 += "과매수 상태. 관망 유지"
    elif data['rsi_range']['min'] <= 30:
        message3 += "과매도 상태. 매수 기회 모니터링"
    else:
        message3 += "중립 추세. 조건 충족 시 거래 실행"
    
    messages.append(message3)
    
    # 각 메시지 길이 확인
    for i, msg in enumerate(messages):
        print(f"메시지{i+1} 길이: {len(msg)}자")
        if len(msg) > 1900:  # 여유를 두고 1900자 제한
            print(f"⚠️ 메시지{i+1}이 너무 김!")
    
    return messages

def send_daily_summary():
    """일일 요약 메시지 발송 (분활 및 디버깅 포함)"""
    global DAILY_SUMMARY_DATA
    
    # DAILY_SUMMARY_DATA가 비어있는 경우 처리 (거래가 없어도 분석 데이터가 있으면 리포트 발송)
    if not DAILY_SUMMARY_DATA:
        send_message("📊 오늘은 분석 데이터가 없어 요약 리포트를 발송하지 않습니다", level=MESSAGE_LEVEL_CRITICAL)
        return
    
    print(f"📊 일일 요약 발송 시작 - 종목 수: {len(DAILY_SUMMARY_DATA)}")
    
    # 디스코드 연속 발송 오류 예방: 요약 시작 전 2초 대기
    time.sleep(2)
    
    for symbol_index, symbol in enumerate(DAILY_SUMMARY_DATA.keys()):
        symbol_name = get_symbol_name(symbol)  # 종목명 가져오기
        print(f"📤 {symbol_name}({symbol}) 요약 메시지 생성 중...")
        messages = generate_daily_summary_messages(symbol)
        
        if messages:
            print(f"✅ {symbol_name}({symbol}) 메시지 {len(messages)}개 생성 완료")
            
            for i, message in enumerate(messages):
                print(f"📨 {symbol_name}({symbol}) 메시지{i+1} 발송 시작 (길이: {len(message)}자)")
                try:
                    if i == 0:
                        # 심볼 간 구분을 위해 심볼 위에 빈 줄 3줄 추가 (모든 심볼에 적용)
                        send_message("", level=MESSAGE_LEVEL_CRITICAL)
                        send_message("", level=MESSAGE_LEVEL_CRITICAL)
                        send_message("", level=MESSAGE_LEVEL_CRITICAL)
                        # 첫 번째 메시지에 종목명 포함
                        send_message(message, symbol, level=MESSAGE_LEVEL_CRITICAL)
                        print(f"✅ {symbol_name}({symbol}) 메시지{i+1} 발송 완료")
                    else:
                        # 나머지 메시지는 종목명 없이 발송
                        send_message(message, level=MESSAGE_LEVEL_CRITICAL)
                        print(f"✅ 메시지{i+1} 발송 완료")
                    
                    time.sleep(2)  # 메시지 간 간격(연속 발송 방지) - 5초에서 2초로 단축
                except Exception as e:
                    print(f"❌ {symbol} 메시지{i+1} 발송 실패: {str(e)}")
        else:
            print(f"❌ {symbol} 메시지 생성 실패")
    
    # 오래된 메시지 히스토리 정리
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
            # send_message(f"토큰 발급 실패: 상태 코드 {res.status_code}", level=MESSAGE_LEVEL_CRITICAL)  # 로그 스팸 방지
            return None
            
        access_token = res.json()["access_token"]
        # send_message("✅ 새로운 토큰 발급 완료", level=MESSAGE_LEVEL_IMPORTANT)  # 로그 스팸 방지
        return access_token
        
    except Exception as e:
        # send_message(f"🚨 토큰 발급 중 오류 발생: {str(e)}", level=MESSAGE_LEVEL_CRITICAL)  # 로그 스팸 방지
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
            print(f"✅ 토큰 갱신 완료: {datetime.datetime.now().strftime('%H:%M:%S')}")
            return True
        else:
            print("❌ 토큰 갱신 실패")
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
        
        # 주말 체크
        if KST_time.weekday() >= 5:
            return False
        
        # 공휴일 체크
        is_holiday, _ = is_korean_holiday(KST_time)
        if is_holiday:
            return False
            
        market_start = KST_time.replace(hour=9, minute=0, second=0, microsecond=0)
        market_end = KST_time.replace(hour=15, minute=30, second=0, microsecond=0)
        is_market_open = market_start <= KST_time <= market_end
        
        return is_market_open
    except Exception as e:
        send_message(f"🚨 시장 시간 확인 중 오류: {str(e)}")
        # 오류 발생 시 기본적으로 닫힘으로 처리
        return False

def wait_for_market_open():
    """시장 개장 대기 (주말 및 공휴일 처리)"""
    try:
        print("[정보] 한국 시장이 닫혀 있습니다. 개장까지 대기합니다...")
        send_message("한국 시장이 닫혀 있습니다. 개장까지 대기합니다...", level=MESSAGE_LEVEL_IMPORTANT)
        
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
                print(f"[정보] 오늘은 {holiday_name}입니다. 장이 열리지 않습니다.")
                send_message(f"오늘은 {holiday_name}입니다. 장이 열리지 않습니다.", level=MESSAGE_LEVEL_IMPORTANT)
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
            print(f"[대기] 다음 확인까지 {next_check}분 대기... ({status_msg})")
            # 대기 메시지는 너무 빈번하므로 INFO 레벨로 (필요시 IMPORTANT로 변경 가능)
            send_message(f"다음 확인까지 {next_check}분 대기... ({status_msg})", level=MESSAGE_LEVEL_INFO)
            time.sleep(next_check * 60)
        
        print("[성공] 🔔 한국 시장이 개장되었습니다!")
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
    
    print(f"📊 일봉 데이터 조회: {code}")
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
                print(f"✅ {code} 일봉 데이터 조회 완료: {len(data['output2'])} 일")
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
        print(f"✅ {periods}일 이동평균 계산 완료: {latest_ma}")
        return latest_ma
    
    except Exception as e:
        print(f"이동평균 계산 중 오류 발생: {e}")
        return None

def get_moving_average(code, periods=MA_PERIOD):
    """종목의 이동평균 조회"""
    global ACCESS_TOKEN
    print(f"📊 이동평균 조회: {code} ({periods}일)")
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
            print(f"📊 종목 {code}의 {periods}일 이동평균: {ma_value}")
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
    
    print(f"📈 분봉 데이터 조회: {code} ({time_unit}분)")
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
    
        print(f"✅ {code} 분봉 데이터 조회 완료: {len(all_data)} 건")
    return {"output2": all_data} if all_data else None


# 2. calculate_rsi 개선 (None 반환, 가격 컬럼 자동 탐색)
def calculate_rsi(data, periods=RSI_PERIOD):
    """표준 RSI 계산 공식 적용"""
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
        if len(df) < periods + 1:
            print(f"RSI 데이터 부족 (필요: {periods + 1}, 현재: {len(df)})")
            return None
        
        # 가격 변화량 계산
        df['price_change'] = df['price'].diff()
        
        # 상승분과 하락분 분리
        df['gain'] = df['price_change'].where(df['price_change'] > 0, 0)
        df['loss'] = -df['price_change'].where(df['price_change'] < 0, 0)
        
        # 초기 평균 계산 (단순 평균)
        df['avg_gain'] = 0.0
        df['avg_loss'] = 0.0
        
        # 첫 번째 EMA 계산 (periods + 1 번째부터)
        if len(df) >= periods + 1:
            df.loc[periods - 1, 'avg_gain'] = df['gain'].iloc[1:periods + 1].mean()
            df.loc[periods - 1, 'avg_loss'] = df['loss'].iloc[1:periods + 1].mean()
        
        # 이후 EMA 계산
        alpha = 1.0 / periods
        for i in range(periods, len(df)):
            if i > 0:
                df.loc[i, 'avg_gain'] = alpha * df['gain'].iloc[i] + (1 - alpha) * df['avg_gain'].iloc[i - 1]
                df.loc[i, 'avg_loss'] = alpha * df['loss'].iloc[i] + (1 - alpha) * df['avg_loss'].iloc[i - 1]
        
        # RSI 계산
        df['rs'] = df['avg_gain'] / df['avg_loss'].replace(0, np.nan)
        df['rsi'] = 100 - (100 / (1 + df['rs']))
        
        # 마지막 유효한 RSI 값 반환
        last_valid_rsi = df['rsi'].dropna().iloc[-1]
        
        # 디버깅 정보 출력 (문제 발생 시 전환)
        price_volatility = df['price'].iloc[-5:].max() - df['price'].iloc[-5:].min()
        current_price = df['price'].iloc[-1]
        
        print(f"🔍 RSI 디버깅 - 최근5일 가격범위: {price_volatility:.0f}원")
        print(f"🔍 RSI 값: {last_valid_rsi:.2f} | 최신가격: {current_price:.0f}원")
        
        # RSI 이상값 감지
        if abs(last_valid_rsi - 50) > 40:
            avg_gain_val = df['avg_gain'].iloc[-1]
            avg_loss_val = df['avg_loss'].iloc[-1]
            print(f"⚠️ RSI 극값 - Gain:{avg_gain_val:.2f}, Loss:{avg_loss_val:.2f}, RS:{avg_gain_val/avg_loss_val:.3f}")
        
        return round(last_valid_rsi, 2)
        
    except Exception as e:
        print(f"RSI 계산 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return None


def debug_rsi_calculation(code):
    """RSI 계산 디버깅용 함수"""
    global ACCESS_TOKEN
    
    print(f"\n🔍 {code} RSI 계산 디버깅 시작 ====")
    
    data = get_minute_data(code=code, time_unit=30)
    if not data:
        print("❌ 분봉 데이터 조회 실패")
        return None
        
    rsi_value = calculate_rsi(data)
    print(f"✅ {code} 최종 RSI: {rsi_value}")
    print(f"==== {code} RSI 디버깅 종료 ====\n")
    
    return rsi_value

def get_current_rsi(code, periods=RSI_PERIOD, time_unit=MINUTE_CANDLE):
    """현재 RSI 조회"""
    global ACCESS_TOKEN
    # print(f"📈 RSI 조회: {code}")  # 로그 스팸 방지
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

        # print(f"📈 종목 {code}의 RSI 값: {rsi_value}")  # 로그 스팸 방지
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
                # 수익률 계산
                avg_price = float(stock.get('pchs_avg_pric', 0))  # 평균 매수가
                current_price = float(stock.get('prpr', 0))  # 현재가
                
                if avg_price > 0 and current_price > 0:
                    profit_rate = ((current_price - avg_price) / avg_price) * 100
                    print(f"📊 {stock['prdt_name']} 수익률 계산: 평균매수가 {avg_price:,.0f}원, 현재가 {current_price:,.0f}원 → 수익률 {profit_rate:.2f}%")
                else:
                    profit_rate = 0
                    print(f"⚠️ {stock['prdt_name']} 수익률 계산 불가: 평균매수가 {avg_price}, 현재가 {current_price}")
                
                # 종목 정보 저장 (API에서 실시간 조회 가능한 정보는 제외)
                stock_dict[stock['pdno']] = {
                    'hldg_qty': stock['hldg_qty'],
                    'profit_rate': profit_rate
                }
                
                send_message(f"{stock['prdt_name']}({stock['pdno']}): {stock['hldg_qty']}주, 수익률: {profit_rate:.2f}%", level=MESSAGE_LEVEL_INFO)
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

        held_qty = int(stock_dict[code]['hldg_qty'])

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
    """매도 조건 종합 검사 (RSI + 수익률, 종목별 설정 적용)"""
    try:
        # 종목별 설정 가져오기
        config = get_symbol_config(code)
        
        # RSI 조건 확인
        if current_rsi < config['rsi_overbought']:
            # RSI 조건 미충족 메시지를 DEBUG 레벨로 (너무 빈번함)
            send_message(f"RSI 매도 조건 미충족 (현재: {current_rsi:.2f}, 기준: {config['rsi_overbought']} 이상)", code, level=MESSAGE_LEVEL_DEBUG)
            return False
        
        # 수익률 조건 확인
        if profit_rate < config['profit_take_percent']:
            if profit_rate >= 0:
                # 수익률 부족 메시지를 DEBUG 레벨로 (너무 빈번함)
                send_message(f"수익률 부족 (현재: {profit_rate:.2f}%, 기준: {config['profit_take_percent']}% 이상)", code, level=MESSAGE_LEVEL_DEBUG)
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
    """매수 조건 종합 검사 (종목별 설정 적용)"""
    try:
        # 종목별 설정 가져오기
        config = get_symbol_config(code)
        
        # 1. RSI 조건 확인
        if current_rsi > config['rsi_oversold']:
            # RSI 조건 미충족 메시지를 DEBUG 레벨로 (너무 빈번함)
            send_message(f"RSI 조건 미충족 (현재: {current_rsi:.2f}, 기준: {config['rsi_oversold']} 이하)", code, level=MESSAGE_LEVEL_DEBUG)
            return False
        
        # 2. 이동평균 조건 확인
        ma_value = get_moving_average(code, config['ma_period'])
        if ma_value is None:
            send_message(f"이동평균 조회 실패로 매수 조건 확인 불가", code, level=MESSAGE_LEVEL_IMPORTANT)
            return False
        
        print(f"📊 {config['ma_period']}일 이동평균: {ma_value}원")
        
        # 현재가와 이동평균 비교 (종목별 max_price_above_ma_percent 설정 적용)
        price_diff_percent = ((current_price - ma_value) / ma_value) * 100
        max_allowed = config.get('max_price_above_ma_percent', 0)
        
        if price_diff_percent > max_allowed:
            # 이동평균 조건 미충족 메시지를 DEBUG 레벨로 (너무 빈번함)
            send_message(f"이동평균 조건 미충족 - 현재가({current_price})가 {config['ma_period']}일 이동평균({ma_value})보다 {price_diff_percent:.2f}% 높음 (허용기준: {max_allowed}%)", code, level=MESSAGE_LEVEL_DEBUG)
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
    
    print("=" * 60)
    print("한국 주식 자동매매 프로그램 시작")
    print("=" * 60)
    print(f"현재 시간: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    token_retry_count = 0
    max_token_retries = 5
    
    while True:  # 메인 무한 루프
        try:
            # 토큰이 없거나 토큰 오류 후 재시작한 경우
            if not ACCESS_TOKEN:
                print("\n[토큰 발급 시도 중...]")
                ACCESS_TOKEN = get_access_token()
                if not ACCESS_TOKEN:
                    print("[경고] 토큰 발급 실패, 2분 후 재시도합니다.")
                    send_message("토큰 발급 실패, 2분 후 재시도합니다.", level=MESSAGE_LEVEL_IMPORTANT)
                    time.sleep(120)
                    token_retry_count += 1
                    if token_retry_count > max_token_retries:
                        print(f"[에러] 토큰 발급 {max_token_retries}회 실패, 10분 후 다시 시도합니다.")
                        send_message(f"토큰 발급 {max_token_retries}회 실패, 10분 후 다시 시도합니다.", level=MESSAGE_LEVEL_CRITICAL)
                        time.sleep(600)
                        token_retry_count = 0
                    continue
                print("[성공] 토큰 발급 완료")
                token_retry_count = 0
                
            bought_list = []  # 매수 완료된 종목 리스트
            
            # 초기 시장 체크
            print("\n[시장 상태 확인 중...]")
            market_open = is_market_open()
            if not market_open:
                print("[정보] 시장이 닫혀 있습니다. 개장까지 대기합니다...")
                wait_for_market_open()
                continue
            print("[정보] 시장이 열려 있습니다.")
            
            # 매매 대상 종목 수와 매수 비율 설정
            target_buy_count = min(3, len(SYMBOLS))  # 최대 3개 종목 매수
            
            # 프로그램 시작 메시지 (콘솔 출력)
            print("\n" + "=" * 60)
            print("프로그램 초기화 완료")
            print("=" * 60)
            print(f"매수 대상 종목: {SYMBOLS}")
            print(f"기본 매수 비율: 보유 금액의 {BUY_RATIO*100}%")
            print(f"기본 매수 조건: RSI {RSI_OVERSOLD} 이하 + 현재가가 {MA_PERIOD}일 이동평균 이하")
            print(f"기본 매도 조건: RSI {RSI_OVERBOUGHT} 이상")
            print("\n종목별 개별 설정:")
            for symbol in SYMBOLS:
                symbol_config = get_symbol_config(symbol)
                print(f"  {symbol}: RSI매수 {symbol_config['rsi_oversold']} | RSI매도 {symbol_config['rsi_overbought']} | 익절 {symbol_config['profit_take_percent']}% | 매수비율 {symbol_config['buy_ratio']*100}%")
            print("=" * 60 + "\n")
            
            # 디스코드 메시지 간소화 (요약 메시지로 통합)
            summary_msg = f"🚀 **한국 주식 자동매매 프로그램 시작**\n"
            summary_msg += f"📊 종목: {len(SYMBOLS)}개 ({', '.join(SYMBOLS[:3])}{'...' if len(SYMBOLS) > 3 else ''})\n"
            summary_msg += f"⚙️ 기본 설정: 매수비율 {BUY_RATIO*100}% | RSI매수 {RSI_OVERSOLD}↓ | RSI매도 {RSI_OVERBOUGHT}↑ | 이평 {MA_PERIOD}일\n"
            summary_msg += f"📈 분석 주기: 30분마다 | 리포트: 시장 마감 시 발송"
            send_message(summary_msg, level=MESSAGE_LEVEL_IMPORTANT)
            
            # 시간대 설정
            tz = timezone('Asia/Seoul')
            last_token_refresh = datetime.datetime.now(tz)
            
            # 초기 실행 설정
            force_first_check = True
            last_check_time = datetime.datetime.now(tz) - datetime.timedelta(minutes=31)
            
            # 시장 상태 추적 변수
            last_market_status = None
            
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
                
                # 시장 상태 확인 (상태 변경 시에만 메시지 발송)
                current_market_status = is_market_open()
                if current_market_status != last_market_status:
                    if current_market_status:
                        send_message("🔔 한국 시장이 개장되었습니다!", level=MESSAGE_LEVEL_CRITICAL)
                        
                        # 시장 개장 시 이전 데이터 정리 (새로운 거래일 시작)
                        if DAILY_SUMMARY_DATA:
                            print("📊 새로운 거래일 시작 - 이전 데이터 정리 중...")
                            DAILY_SUMMARY_DATA.clear()
                            print("✅ 이전 거래일 데이터 정리 완료")
                    else:
                        send_message("🔔 한국 시장이 마감되었습니다. 다음 개장일까지 대기합니다...", level=MESSAGE_LEVEL_CRITICAL)
                        
                        # 일일 요약 메시지 발송 (거래가 없어도 분석 데이터가 있으면 리포트 발송)
                        if DAILY_SUMMARY_DATA:
                            send_message("📊 자동 매매 요약 리포트를 발송하겠습니다", level=MESSAGE_LEVEL_CRITICAL)
                            # 요약 발송 전 추가 2초 대기
                            time.sleep(2)
                            send_daily_summary()
                        else:
                            send_message("📊 오늘은 분석 데이터가 없어 요약 리포트를 발송하지 않습니다", level=MESSAGE_LEVEL_CRITICAL)
                        
                        wait_for_market_open()
                        continue
                    last_market_status = current_market_status
                elif not current_market_status:
                    # 시장이 닫혀있으면 대기
                    wait_for_market_open()
                    continue
                
                # RSI 체크 조건 (매 30분마다 또는 첫 실행 시) - 30분 단위 제약 제거하여 더 자주 체크
                minutes_elapsed = (current_time - last_check_time).total_seconds() / 60
                
                if force_first_check or minutes_elapsed >= 29:
                    # 현금 잔고 확인
                    total_cash = get_balance()
                    if total_cash <= 0:
                        send_message("💰 주문 가능 현금이 없습니다. 다음 체크까지 대기...")
                        time.sleep(60)
                        continue
                        
                    # 종목별 매수 금액 계산 (기본값 사용, 개별 종목에서는 재계산)
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
                                # RSI 조회 실패 시에도 분석 데이터 수집 시도 (기본값 사용)
                                current_price = get_current_price(code)
                                if current_price is not None:
                                    ma_value = get_moving_average(code, MA_PERIOD)
                                    if ma_value is not None:
                                        collect_daily_summary_data(code, 50.0, current_price, ma_value, False, False, "RSI 계산 실패", "", None)
                                continue
                            send_message(f"현재 RSI: {current_rsi:.2f}", code, level=MESSAGE_LEVEL_INFO)
                            
                            # 현재가 조회
                            current_price = get_current_price(code)
                            if current_price is None:
                                send_message(f"현재가 조회 실패", code)
                                # 현재가 조회 실패 시에도 분석 데이터 수집 시도 (기본값 사용)
                                ma_value = get_moving_average(code, MA_PERIOD)
                                if ma_value is not None:
                                    collect_daily_summary_data(code, current_rsi, 0, ma_value, False, False, "", "현재가 조회 실패", None)
                                continue
                            send_message(f"현재가: {current_price}원", code, level=MESSAGE_LEVEL_INFO)
                            
                            # 종목별 설정 가져오기
                            config = get_symbol_config(code)
                            
                            # 매수 조건 (RSI + 이동평균 조건 모두 충족, 종목별 설정 적용)
                            if current_rsi <= config['rsi_oversold']:
                                if len(bought_list) < target_buy_count and code not in bought_list:
                                    # 종합 매수 조건 검사 (RSI + 이동평균)
                                    if check_buy_conditions(code, current_rsi, current_price):
                                        send_message(f"🎯 종합 매수 신호 감지!", code, level=MESSAGE_LEVEL_IMPORTANT)
                                        
                                        # 일일 요약 데이터 수집 (매수 신호 - 거래 실패 사유는 아래에서 기록)
                                        ma_value = get_moving_average(code, MA_PERIOD)
                                        if ma_value is not None:
                                            collect_daily_summary_data(code, current_rsi, current_price, ma_value, True, False, "RSI 과매도 + 이동평균 조건 충족", "", None)
                                        
                                        # 매수 수량 계산 (종목별 설정 적용)
                                        symbol_buy_amount = total_cash * config['buy_ratio']
                                        qty = int(symbol_buy_amount // current_price)
                                        
                                        if qty > 0:
                                            total_cost = qty * current_price
                                            
                                            send_message(f"- 매수 가능 금액: {symbol_buy_amount:.0f}원", code, level=MESSAGE_LEVEL_INFO)
                                            send_message(f"- 주문 수량: {qty}주", code, level=MESSAGE_LEVEL_INFO)
                                            send_message(f"- 주문 가격: {current_price}원", code, level=MESSAGE_LEVEL_INFO)
                                            send_message(f"- 총 주문 금액: {total_cost:.0f}원", code, level=MESSAGE_LEVEL_INFO)
                                            
                                            # 매수 실행
                                            buy_result = buy(code, qty)
                                            if buy_result:
                                                bought_list.append(code)
                                                send_message(f"✅ {code} {qty}주 매수 완료", code, level=MESSAGE_LEVEL_CRITICAL)
                                                # 거래 내역 추가
                                                add_trade_record(code, 'buy', qty, current_price)
                                            else:
                                                # 매수 실행 실패 (잔고 부족 등)
                                                send_message(f"❌ {code} 매수 실행 실패 (잔고 부족 등)", code, level=MESSAGE_LEVEL_IMPORTANT)
                                                ma_value = get_moving_average(code, MA_PERIOD)
                                                if ma_value is not None:
                                                    collect_daily_summary_data(code, current_rsi, current_price, ma_value, True, False, "RSI 과매도 + 이동평균 조건 충족", "", "insufficient_balance")
                                        else:
                                            # 계산된 매수 수량이 0 (잔고 부족)
                                            send_message(f"❌ 계산된 매수 수량이 0입니다 (잔고 부족)", code, level=MESSAGE_LEVEL_INFO)
                                            ma_value = get_moving_average(code, MA_PERIOD)
                                            if ma_value is not None:
                                                collect_daily_summary_data(code, current_rsi, current_price, ma_value, True, False, "RSI 과매도 + 이동평균 조건 충족", "", "insufficient_balance")
                                    else:
                                        # 매수 조건 미충족
                                        ma_value = get_moving_average(code, MA_PERIOD)
                                        if ma_value is not None:
                                            collect_daily_summary_data(code, current_rsi, current_price, ma_value, False, False, "", "", "condition_not_met")
                                    # else 부분은 check_buy_conditions 함수에서 이미 메시지 출력
                                else:
                                    if code in bought_list:
                                        send_message(f"이미 보유 중인 종목입니다", code, level=MESSAGE_LEVEL_DEBUG)
                                    else:
                                        send_message(f"최대 매수 종목 수({target_buy_count})에 도달했습니다", code, level=MESSAGE_LEVEL_DEBUG)
                                    # 매수 조건 미충족이어도 분석 데이터 수집
                                    ma_value = get_moving_average(code, MA_PERIOD)
                                    if ma_value is not None:
                                        collect_daily_summary_data(code, current_rsi, current_price, ma_value, False, False, "", "")
                            
                            # 매도 조건 (RSI + 수익률 조건, 종목별 설정 적용)
                            elif current_rsi >= config['rsi_overbought']:
                                if code in stock_dict:
                                    # 수익률 가져오기
                                    stock_info = stock_dict[code]
                                    profit_rate = stock_info.get('profit_rate', 0)
                                    
                                    # 종합 매도 조건 검사 (RSI + 수익률)
                                    if check_sell_conditions(code, current_rsi, profit_rate):
                                        send_message(f"🎯 종합 매도 신호 감지!", code, level=MESSAGE_LEVEL_IMPORTANT)
                                        
                                        # 일일 요약 데이터 수집 (매도 신호)
                                        ma_value = get_moving_average(code, MA_PERIOD)
                                        if ma_value is not None:
                                            collect_daily_summary_data(code, current_rsi, current_price, ma_value, False, True, "", f"RSI 과매수 + 수익률 {profit_rate:.2f}%")
                                        sell_result = sell(code, "all")
                                        if sell_result:
                                            if code in bought_list:
                                                bought_list.remove(code)
                                            send_message(f"✅ {code} 매도 완료", code, level=MESSAGE_LEVEL_CRITICAL)
                                            # 거래 내역 추가
                                            add_trade_record(code, 'sell', "all", current_price)
                                    else:
                                        # 매도 조건 미충족이어도 분석 데이터 수집
                                        ma_value = get_moving_average(code, MA_PERIOD)
                                        if ma_value is not None:
                                            collect_daily_summary_data(code, current_rsi, current_price, ma_value, False, False, "", "")
                                    # else 부분은 check_sell_conditions 함수에서 이미 메시지 출력
                                else:
                                    # 보유하지 않은 종목이어도 분석 데이터 수집
                                    ma_value = get_moving_average(code, MA_PERIOD)
                                    if ma_value is not None:
                                        collect_daily_summary_data(code, current_rsi, current_price, ma_value, False, False, "", "")
                            
                            # 그 외 상태 메시지
                            else:
                                print(f"📊 현재 RSI {current_rsi:.2f}는 매수/매도 구간이 아닙니다")
                                # 거래 신호가 없어도 분석 데이터 수집 (요약 리포트에 포함)
                                ma_value = get_moving_average(code, MA_PERIOD)
                                if ma_value is not None:
                                    collect_daily_summary_data(code, current_rsi, current_price, ma_value, False, False, "", "")
                                
                        except Exception as e:
                            send_message(f"🚨 {code} 처리 중 오류: {str(e)}", code)
                            continue
                    
                    # 다음 체크를 위한 설정 업데이트
                    last_check_time = current_time
                    force_first_check = False
                    
                    # 다음 체크 시간 계산 (30분 후)
                    next_check_minutes = 30
                    send_message(f"⏳ 다음 분석 체크까지 약 {next_check_minutes}분 남았습니다", level=MESSAGE_LEVEL_DEBUG)
                
                # 효율적인 대기 시간 설정
                if is_market_open():
                    # 시장 개장 시: 30초마다 체크 (RSI 체크 시간 고려)
                    time.sleep(30)
                else:
                    # 시장 마감 시: 5분마다 체크 (시장 상태 변경 감지용)
                    time.sleep(300)
                
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