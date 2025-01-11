import os
import logging
import time
import sqlite3
import json
import yaml
import schedule
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv
from openai import OpenAI
import pyupbit
import ta

# 환경 변수 및 설정 로드
load_dotenv()

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 트레이딩 제약 조건 설정
TRADING_CONFIG = {
    'MAX_TRADE_PERCENTAGE': 3.0,  # 최대 거래 비중 3%로 제한
    'CONSECUTIVE_LOSS_LIMIT': 3,  # 연속 손실 허용 횟수
    'RSI_LOWER_BOUND': 20,        # RSI 하한선
    'RSI_UPPER_BOUND': 80,        # RSI 상한선
}

# Discord 웹훅 설정
try:
    with open('config.yaml', encoding='UTF-8') as f:
        _cfg = yaml.safe_load(f)
    DISCORD_WEBHOOK_URL = _cfg.get('DISCORD_WEBHOOK_URL', '')
except Exception as e:
    logger.error(f"설정 파일 로드 오류: {e}")
    DISCORD_WEBHOOK_URL = ''

def send_discord_message(msg):
    """디스코드 메시지 전송 함수"""
    try:
        now = datetime.now()
        message = {"content": f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {str(msg)}"}
        requests.post(DISCORD_WEBHOOK_URL, json=message)
        print(message)
    except Exception as e:
        logger.error(f"Discord 메시지 전송 실패: {e}")

# API 키 검증
access = os.getenv("UPBIT_ACCESS_KEY")
secret = os.getenv("UPBIT_SECRET_KEY")
openai_api_key = os.getenv("OPENAI_API_KEY")

if not all([access, secret, openai_api_key, DISCORD_WEBHOOK_URL]):
    logger.error("필수 설정값이 누락되었습니다.")
    raise ValueError("모든 필수 설정값을 .env와 config.yaml 파일에 입력해주세요.")

# Upbit 및 OpenAI 클라이언트 초기화
upbit = pyupbit.Upbit(access, secret)
openai_client = OpenAI(api_key=openai_api_key)

# 고급 변동성 지표 계산 함수
def calculate_volatility_indicators(df):
    try:
        if df is None or df.empty:
            return None

        # ATR (Average True Range): 변동성 측정
        df['atr'] = ta.volatility.AverageTrueRange(
            high=df['high'], 
            low=df['low'], 
            close=df['close'], 
            window=14
        ).average_true_range()

        # 볼린저 밴드 폭: 변동성 강도 측정
        bollinger = ta.volatility.BollingerBands(close=df['close'], window=20)
        df['bb_width'] = (bollinger.bollinger_hband() - bollinger.bollinger_lband()) / df['close'] * 100

        return df
    except Exception as e:
        logger.error(f"변동성 지표 계산 오류: {e}")
        return None

# 데이터베이스 초기화 함수
def init_database():
    try:
        conn = sqlite3.connect('advanced_scalping_trades.db')
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                decision TEXT,
                percentage REAL,
                reason TEXT,
                btc_balance REAL,
                krw_balance REAL,
                entry_price REAL,
                stop_loss_price REAL,
                take_profit_price REAL,
                profit_percentage REAL,
                trade_result TEXT,
                volatility_atr REAL,
                rsi_value REAL
            )
        ''')
        conn.commit()
        return conn
    except Exception as e:
        logger.error(f"데이터베이스 초기화 오류: {e}")
        send_discord_message(f"🚨 데이터베이스 초기화 실패: {e}")
        return None
    
# 기술적 지표 계산 함수 (변경)
def calculate_technical_indicators(df):
    try:
        if df is None or df.empty:
            return None

        # 기존 지표 + 변동성 지표
        df = calculate_volatility_indicators(df)

        # 볼린저 밴드
        bollinger = ta.volatility.BollingerBands(close=df['close'], window=20)
        df['bb_upper'] = bollinger.bollinger_hband()
        df['bb_lower'] = bollinger.bollinger_lband()

        # RSI (엄격한 구간 강조)
        rsi = ta.momentum.RSIIndicator(close=df['close'], window=14)
        df['rsi'] = rsi.rsi()

        # MACD
        macd = ta.trend.MACD(close=df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()

        # EMA
        df['ema_short'] = ta.trend.EMAIndicator(close=df['close'], window=10).ema_indicator()
        df['ema_long'] = ta.trend.EMAIndicator(close=df['close'], window=30).ema_indicator()

        return df
    except Exception as e:
        logger.error(f"기술적 지표 계산 오류: {e}")
        return None

# 연속 손실 확인 함수
def check_consecutive_losses(conn):
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT trade_result 
            FROM trades 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (TRADING_CONFIG['CONSECUTIVE_LOSS_LIMIT'],))
        
        recent_trades = [row[0] for row in cursor.fetchall()]
        
        # 모든 거래가 손실인지 확인
        return all(result == 'loss' for result in recent_trades)
    except Exception as e:
        logger.error(f"연속 손실 확인 중 오류: {e}")
        return False

# 시장 데이터 수집 함수 (변경)
def collect_market_data():
    try:
        # 1분 및 5분 차트 데이터
        df_1m = pyupbit.get_ohlcv("KRW-BTC", interval="minute1", count=50)
        df_5m = pyupbit.get_ohlcv("KRW-BTC", interval="minute5", count=20)

        if df_1m is None or df_5m is None:
            logger.error("시장 데이터 수집 실패")
            return None

        # 기술적 지표 계산
        df_1m = calculate_technical_indicators(df_1m)
        df_5m = calculate_technical_indicators(df_5m)

        # 호가 데이터
        orderbook = pyupbit.get_orderbook("KRW-BTC")

        market_data = {
            "1m_data": df_1m,
            "5m_data": df_5m,
            "orderbook": orderbook,
            "current_price": df_1m['close'].iloc[-1],
            "volatility": {
                "atr": df_1m['atr'].iloc[-1],
                "bb_width": df_1m['bb_width'].iloc[-1]
            }
        }

        return market_data
    except Exception as e:
        logger.error(f"시장 데이터 수집 중 오류: {e}")
        return None

# 거래 가능성 평가 함수
def evaluate_trade_possibility(market_data):
    try:
        rsi = market_data['1m_data']['rsi'].iloc[-1]
        atr = market_data['volatility']['atr']
        bb_width = market_data['volatility']['bb_width']

        # RSI 기반 거래 조건
        rsi_condition = (
            rsi <= TRADING_CONFIG['RSI_LOWER_BOUND'] or 
            rsi >= TRADING_CONFIG['RSI_UPPER_BOUND']
        )

        # 변동성 기반 조건
        volatility_condition = bb_width > 2.0  # 변동성 임계값 설정

        return {
            'is_tradable': rsi_condition and volatility_condition,
            'rsi': rsi,
            'atr': atr,
            'bb_width': bb_width
        }
    except Exception as e:
        logger.error(f"거래 가능성 평가 중 오류: {e}")
        return {'is_tradable': False}

# 고급 손절매/수익실현 전략 함수
def advanced_stop_strategy(market_data, entry_price):
    try:
        atr = market_data['volatility']['atr']
        current_price = market_data['current_price']
        
        # ATR 기반 동적 손절매/수익실현 계산
        stop_loss_rate = min(max(atr / current_price * 100, 0.5), 3.0)
        take_profit_rate = min(max(atr / current_price * 100 * 1.5, 1.0), 5.0)
        
        stop_loss_price = entry_price * (1 - stop_loss_rate/100)
        take_profit_price = entry_price * (1 + take_profit_rate/100)
        
        return {
            'stop_loss_price': stop_loss_price,
            'take_profit_price': take_profit_price,
            'stop_loss_rate': stop_loss_rate,
            'take_profit_rate': take_profit_rate
        }
    except Exception as e:
        logger.error(f"고급 손절매 전략 계산 오류: {e}")
        return None

# AI 트레이딩 의사결정 함수
def ai_trading_decision(market_data, conn):
    try:
        # 연속 손실 확인
        if check_consecutive_losses(conn):
            send_discord_message("🚨 연속 손실 발생! 거래 일시 중지")
            return None
        
        # 거래 가능성 평가
        trade_evaluation = evaluate_trade_possibility(market_data)
        
        if not trade_evaluation['is_tradable']:
            logger.info("현재 시장 조건에서 거래 불가")
            return None
        
        market_summary = {
            "current_price": float(market_data['current_price']),
            "rsi": trade_evaluation['rsi'],
            "atr": trade_evaluation['atr'],
            "bb_width": trade_evaluation['bb_width']
        }

        messages = [
            {
                "role": "system",
                "content": """비트코인 스캘핑 트레이딩 전문가로서 
                변동성과 RSI를 엄격히 고려하여 
                신중한 거래 결정을 내려주세요."""
            },
            {
                "role": "user",
                "content": f"""
                시장 데이터: {json.dumps(market_summary)}
                
                거래 의사결정 조건:
                - RSI 20 미만 또는 80 초과 시 거래
                - 변동성 지표(ATR, 볼린저 밴드 폭) 고려
                - 최대 거래 비중 3% 제한
                
                JSON 형식으로 응답:
                {{
                    "decision": "buy" 또는 "sell" 또는 "hold",
                    "percentage": 0-3 사이 숫자,
                    "reason": "결정 이유"
                }}
                """
            }
        ]

        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            max_tokens=300,
            temperature=0.7
        )

        result_text = response.choices[0].message.content.strip()
        
        # JSON 파싱
        try:
            result = json.loads(result_text)
        except json.JSONDecodeError:
            logger.error(f"JSON 파싱 실패: {result_text}")
            return None

        # 거래 전략 세부 설정
        return {
            'decision': result.get('decision', 'hold'),
            'percentage': min(result.get('percentage', 0), TRADING_CONFIG['MAX_TRADE_PERCENTAGE']),
            'reason': result.get('reason', '')
        }
    
    except Exception as e:
        logger.error(f"AI 트레이딩 의사결정 오류: {e}")
        return None

# 메인 트레이딩 봇 함수
def trading_bot():
    try:
        # 데이터베이스 연결
        conn = init_database()
        if not conn:
            return
        
        # 시장 데이터 수집
        market_data = collect_market_data()
        if not market_data:
            send_discord_message("❌ 시장 데이터 수집 실패")
            return

        # AI 트레이딩 의사결정
        decision = ai_trading_decision(market_data, conn)
        if not decision:
            logger.info("현재 거래 조건 미충족")
            return

        # 고급 손절매 전략 적용
        current_price = market_data['current_price']
        stop_strategy = advanced_stop_strategy(market_data, current_price)

        # 거래 실행 및 로깅 로직 (기존과 유사)
        
        conn.close()
    
    except Exception as e:
        logger.error(f"트레이딩 봇 실행 오류: {e}")
        send_discord_message(f"🚨 트s레이딩 봇 오류: {e}")

def main():
    send_discord_message("🚀 비트코인 스캘핑 트레이딩 봇 시작")
    
    # 5분마다 트레이딩 봇 실행
    schedule.every(5).minutes.do(trading_bot)
    
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except KeyboardInterrupt:
            send_discord_message("🛑 트레이딩 봇 수동 중지")
            break
        except Exception as e:
            logger.error(f"메인 루프 오류: {e}")
            send_discord_message(f"🚨 메인 루프 오류: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
