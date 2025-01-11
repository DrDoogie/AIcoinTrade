#1 파트

# 필요한 라이브러리 임포트
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

# 환경 변수 로드
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
    'MAX_TRADE_PERCENTAGE': 10.0,    # 최대 거래 비중
    'CONSECUTIVE_LOSS_LIMIT': 3,     # 연속 손실 허용 횟수
    'RSI_LOWER_BOUND': 30,          # RSI 하한선 20
    'RSI_UPPER_BOUND': 70,          # RSI 상한선 80
    'COOLDOWN_MINUTES': 30,         # 거래 재개 전 대기 시간
    'MARKET_STABILITY_WINDOW': 12,   # 시장 안정성 확인 기간
    'MIN_PROFIT_RATE': 1.5,         # 최소 수익률 기준
    'MIN_SUCCESS_RATE': 60.0        # 최소 성공률 기준
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


##2파트

# 데이터베이스 초기화 함수
def init_database():
    try:
        conn = sqlite3.connect('advanced_scalping_trades.db')
        cursor = conn.cursor()
        
        # 거래 기록 테이블
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
                rsi_value REAL,
                recovery_status TEXT
            )
        ''')
        
        # 거래 재개 상태 관리 테이블
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS recovery_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                last_loss_time TEXT,
                cooldown_end_time TEXT,
                consecutive_losses INTEGER,
                market_stability_confirmed INTEGER,
                performance_confirmed INTEGER
            )
        ''')
        
        conn.commit()
        return conn
    except Exception as e:
        logger.error(f"데이터베이스 초기화 오류: {e}")
        send_discord_message(f"🚨 데이터베이스 초기화 실패: {e}")
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
        
        if len(recent_trades) < TRADING_CONFIG['CONSECUTIVE_LOSS_LIMIT']:
            return False
            
        # 모든 거래가 손실인지 확인
        return all(result == 'loss' for result in recent_trades)
        
    except Exception as e:
        logger.error(f"연속 손실 확인 중 오류: {e}")
        return False

# 거래 재개 상태 확인 함수
def check_recovery_status(conn):
    try:
        cursor = conn.cursor()
        
        # 현재 시간 기준으로 상태 확인
        now = datetime.now()
        
        # 가장 최근의 recovery_state 조회
        cursor.execute("""
            SELECT last_loss_time, cooldown_end_time, 
                   market_stability_confirmed, performance_confirmed 
            FROM recovery_state 
            ORDER BY id DESC LIMIT 1
        """)
        
        row = cursor.fetchone()
        if not row:
            return True  # 첫 거래 시작시
            
        last_loss_time = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
        cooldown_end_time = datetime.strptime(row[1], '%Y-%m-%d %H:%M:%S')
        market_stable = bool(row[2])
        performance_ok = bool(row[3])
        
        # 1. 시간 기반 확인
        time_ok = now >= cooldown_end_time
        
        # 모든 조건이 충족되어야 거래 재개
        can_trade = time_ok and market_stable and performance_ok
        
        if can_trade:
            # 거래 재개 가능 상태를 기록
            cursor.execute("""
                UPDATE recovery_state 
                SET recovery_status = 'completed' 
                WHERE id = (SELECT MAX(id) FROM recovery_state)
            """)
            conn.commit()
            
            send_discord_message("✅ 모든 거래 재개 조건이 충족되어 거래를 재개합니다.")
            
        return can_trade
        
    except Exception as e:
        logger.error(f"거래 재개 상태 확인 오류: {e}")
        return False
    


## 3파트

# 시장 데이터 수집 함수
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

# 기술적 지표 계산 함수
def calculate_technical_indicators(df):
    try:
        if df is None or df.empty:
            return None

        # ATR (Average True Range) 계산
        df['atr'] = ta.volatility.AverageTrueRange(
            high=df['high'], 
            low=df['low'], 
            close=df['close'], 
            window=14
        ).average_true_range()

        # 볼린저 밴드
        bollinger = ta.volatility.BollingerBands(close=df['close'], window=20)
        df['bb_width'] = (bollinger.bollinger_hband() - bollinger.bollinger_lband()) / df['close'] * 100
        df['bb_upper'] = bollinger.bollinger_hband()
        df['bb_lower'] = bollinger.bollinger_lband()

        # RSI
        df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()

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

# 시장 안정성 분석 함수
def analyze_market_stability(market_data, conn):
    try:
        df_5m = market_data['5m_data']
        
        # 변동성 지표 분석
        avg_atr = df_5m['atr'].mean()
        current_atr = df_5m['atr'].iloc[-1]
        
        # 볼린저 밴드 폭 분석
        avg_bb_width = df_5m['bb_width'].mean()
        current_bb_width = df_5m['bb_width'].iloc[-1]
        
        # RSI 추세 분석
        rsi_trend = df_5m['rsi'].diff().rolling(window=5).mean().iloc[-1]
        
        # 시장 안정성 조건 정의
        stability_conditions = {
            'atr_stable': current_atr <= avg_atr * 1.2,  # ATR이 평균보다 20% 이상 높지 않음
            'bb_stable': current_bb_width <= avg_bb_width * 1.3,  # 밴드 폭이 평균보다 30% 이상 넓지 않음
            'rsi_stable': abs(rsi_trend) < 5  # RSI 추세가 급격하지 않음
        }
        
        # 모든 안정성 조건이 충족되는지 확인
        market_stable = all(stability_conditions.values())
        
        if market_stable:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE recovery_state 
                SET market_stability_confirmed = 1 
                WHERE id = (SELECT MAX(id) FROM recovery_state)
            """)
            conn.commit()
            
            send_discord_message("📊 시장 안정성 조건이 충족되었습니다.")
            
        return market_stable
        
    except Exception as e:
        logger.error(f"시장 안정성 분석 오류: {e}")
        return False

# 거래 성과 분석 함수
def analyze_trading_performance(conn):
    try:
        cursor = conn.cursor()
        
        # 최근 20개 거래의 성과 분석
        cursor.execute("""
            SELECT trade_result, profit_percentage 
            FROM trades 
            ORDER BY timestamp DESC 
            LIMIT 20
        """)
        
        trades = cursor.fetchall()
        if len(trades) < 5:  # 최소 5개 이상의 거래 기록 필요
            return False
            
        # 승률 계산
        wins = sum(1 for trade in trades if trade[0] == 'win')
        success_rate = (wins / len(trades)) * 100
        
        # 평균 수익률 계산
        avg_profit = sum(trade[1] for trade in trades) / len(trades)
        
        # 성과 조건 확인
        performance_ok = (
            success_rate >= TRADING_CONFIG['MIN_SUCCESS_RATE'] and 
            avg_profit >= TRADING_CONFIG['MIN_PROFIT_RATE']
        )
        
        if performance_ok:
            cursor.execute("""
                UPDATE recovery_state 
                SET performance_confirmed = 1 
                WHERE id = (SELECT MAX(id) FROM recovery_state)
            """)
            conn.commit()
            
            send_discord_message(f"📈 거래 성과 조건이 충족되었습니다. (승률: {success_rate:.1f}%, 평균수익률: {avg_profit:.2f}%)")
            
        return performance_ok
        
    except Exception as e:
        logger.error(f"거래 성과 분석 오류: {e}")
        return False

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
    


#4 파트

# AI 트레이딩 의사결정 함수
def ai_trading_decision(market_data, conn):
    try:
        # 연속 손실 확인
        if check_consecutive_losses(conn):
            handle_consecutive_losses(conn)
            return None
        
        # 거래 가능성 평가
        trade_evaluation = evaluate_trade_possibility(market_data)
        
        if not trade_evaluation.get('is_tradable', False):
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
                - RSI 30 미만 또는 70 초과 시 거래
                - 변동성 지표(ATR, 볼린저 밴드 폭) 고려
                - 최대 거래 비중 20% 제한
                """
            }
        ]

        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            max_tokens=300,
            temperature=0.7
        )

        result = json.loads(response.choices[0].message.content.strip())
        
        return {
            'decision': result.get('decision', 'hold'),
            'percentage': min(result.get('percentage', 0), TRADING_CONFIG['MAX_TRADE_PERCENTAGE']),
            'reason': result.get('reason', '')
        }
    
    except Exception as e:
        logger.error(f"AI 트레이딩 의사결정 오류: {e}")
        return None

# 연속 손실 처리 함수
def handle_consecutive_losses(conn):
    try:
        cursor = conn.cursor()
        
        # 현재 시간 기준으로 대기 시간 계산
        now = datetime.now()
        cooldown_end = now + timedelta(minutes=TRADING_CONFIG['COOLDOWN_MINUTES'])
        
        # recovery_state 테이블에 새로운 상태 추가
        cursor.execute("""
            INSERT INTO recovery_state (
                last_loss_time, 
                cooldown_end_time, 
                consecutive_losses,
                market_stability_confirmed,
                performance_confirmed
            ) VALUES (?, ?, ?, 0, 0)
        """, (
            now.strftime('%Y-%m-%d %H:%M:%S'),
            cooldown_end.strftime('%Y-%m-%d %H:%M:%S'),
            TRADING_CONFIG['CONSECUTIVE_LOSS_LIMIT']
        ))
        
        conn.commit()
        
        send_discord_message(
            f"🚨 연속 손실 발생! 거래 일시 중지\n"
            f"• 대기 시간: {TRADING_CONFIG['COOLDOWN_MINUTES']}분\n"
            f"• 재개 예정 시간: {cooldown_end.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
    except Exception as e:
        logger.error(f"연속 손실 처리 오류: {e}")

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

# 메인 트레이딩 봇 함수

# 메인 트레이딩 봇 함수 (수정됨)
def trading_bot():
    try:
        # 데이터베이스 연결
        conn = init_database()
        if not conn:
            return
            
        # 거래 재개 상태 확인
        if not check_recovery_status(conn):
            # 시장 데이터 수집 및 분석
            market_data = collect_market_data()
            if market_data:
                # 시장 안정성 분석
                analyze_market_stability(market_data, conn)
                # 거래 성과 분석
                analyze_trading_performance(conn)
            send_discord_message("⏳ 거래 재개 대기 중...")
            return
        
        # 시장 데이터 수집
        market_data = collect_market_data()
        if not market_data:
            send_discord_message("❌ 시장 데이터 수집 실패")
            return

        # AI 트레이딩 의사결정
        decision = ai_trading_decision(market_data, conn)
        if not decision:
            current_price = market_data['current_price']
            rsi = market_data['1m_data']['rsi'].iloc[-1]
            bb_width = market_data['volatility']['bb_width']
            
            message = (
                f"💤 현재 거래 조건 미충족\n"
                f"• 현재가: {current_price:,.0f}원\n"
                f"• RSI: {rsi:.2f}\n"
                f"• BB Width: {bb_width:.2f}%"
            )
            logger.info(message)
            send_discord_message(message)
            return

        current_price = market_data['current_price']
        stop_strategy = advanced_stop_strategy(market_data, current_price)
        
        # 거래 실행 및 로깅
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO trades (
                timestamp, decision, percentage, reason,
                btc_balance, krw_balance, entry_price,
                stop_loss_price, take_profit_price,
                volatility_atr, rsi_value
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            decision['decision'],
            decision['percentage'],
            decision['reason'],
            upbit.get_balance('BTC'),
            upbit.get_balance('KRW'),
            current_price,
            stop_strategy['stop_loss_price'],
            stop_strategy['take_profit_price'],
            market_data['volatility']['atr'],
            market_data['1m_data']['rsi'].iloc[-1]
        ))
        conn.commit()
        
    except Exception as e:
        logger.error(f"트레이딩 봇 실행 오류: {e}")
        send_discord_message(f"🚨 트레이딩 봇 오류: {e}")
    finally:
        if conn:
            conn.close()
            
# def trading_bot():
#     try:
#         # 데이터베이스 연결
#         conn = init_database()
#         if not conn:
#             return
            
#         # 거래 재개 상태 확인
#         if not check_recovery_status(conn):
#             # 시장 데이터 수집 및 분석
#             market_data = collect_market_data()
#             if market_data:
#                 # 시장 안정성 분석
#                 analyze_market_stability(market_data, conn)
#                 # 거래 성과 분석
#                 analyze_trading_performance(conn)
#             return
        
#         # 시장 데이터 수집
#         market_data = collect_market_data()
#         if not market_data:
#             send_discord_message("❌ 시장 데이터 수집 실패")
#             return

#         # AI 트레이딩 의사결정
#         decision = ai_trading_decision(market_data, conn)
#         if not decision:
#             logger.info("현재 거래 조건 미충족")
#             return

#         current_price = market_data['current_price']
#         stop_strategy = advanced_stop_strategy(market_data, current_price)
        
#         # 거래 실행 및 로깅
#         cursor = conn.cursor()
#         cursor.execute("""
#             INSERT INTO trades (
#                 timestamp, decision, percentage, reason,
#                 btc_balance, krw_balance, entry_price,
#                 stop_loss_price, take_profit_price,
#                 volatility_atr, rsi_value
#             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
#         """, (
#             datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
#             decision['decision'],
#             decision['percentage'],
#             decision['reason'],
#             upbit.get_balance('BTC'),
#             upbit.get_balance('KRW'),
#             current_price,
#             stop_strategy['stop_loss_price'],
#             stop_strategy['take_profit_price'],
#             market_data['volatility']['atr'],
#             market_data['1m_data']['rsi'].iloc[-1]
#         ))
#         conn.commit()
    # except Exception as e:
    #     logger.error(f"트레이딩 봇 실행 오류: {e}")
    #     send_discord_message(f"🚨 트레이딩 봇 오류: {e}")
    # finally:
    #     if conn:
    #         conn.close()

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

