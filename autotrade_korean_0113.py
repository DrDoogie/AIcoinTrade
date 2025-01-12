##1파트

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
    'RSI_LOWER_BOUND': 35,          # RSI 하한선
    'RSI_UPPER_BOUND': 65,          # RSI 상한선
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




## 2파트
# 데이터베이스 초기화 함수
def init_database():
    try:
        conn = sqlite3.connect('trading_bot.db')
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
                current_price REAL,
                stop_loss_price REAL,
                take_profit_price REAL,
                profit_percentage REAL,
                trade_status TEXT,
                rsi_value REAL,
                bb_width REAL
            )
        ''')
        
        # 트레이딩 상태 테이블
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trading_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                is_active INTEGER,
                last_trade_time TEXT,
                consecutive_losses INTEGER,
                total_trades INTEGER,
                successful_trades INTEGER,
                current_profit_rate REAL
            )
        ''')
        
        conn.commit()
        return conn
    except Exception as e:
        logger.error(f"데이터베이스 초기화 오류: {e}")
        send_discord_message(f"🚨 데이터베이스 초기화 실패: {e}")
        return None

def log_trade(conn, trade_data):
    """거래 기록 함수"""
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO trades (
                timestamp, decision, percentage, reason,
                btc_balance, krw_balance, entry_price, current_price,
                stop_loss_price, take_profit_price, profit_percentage,
                trade_status, rsi_value, bb_width
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            trade_data['decision'],
            trade_data['percentage'],
            trade_data['reason'],
            trade_data['btc_balance'],
            trade_data['krw_balance'],
            trade_data.get('entry_price', 0),
            trade_data['current_price'],
            trade_data.get('stop_loss_price', 0),
            trade_data.get('take_profit_price', 0),
            trade_data.get('profit_percentage', 0),
            trade_data.get('trade_status', 'executed'),
            trade_data['rsi'],
            trade_data['bb_width']
        ))
        conn.commit()
        logger.info(f"거래 기록 완료: {trade_data['decision']} at {trade_data['current_price']:,}원")
    except Exception as e:
        conn.rollback()  ## 추가된 부분
        logger.error(f"거래 기록 중 오류: {e}")

def update_trading_state(conn, state_data):
    """트레이딩 상태 업데이트 함수"""
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO trading_state (
                timestamp, is_active, last_trade_time,
                consecutive_losses, total_trades,
                successful_trades, current_profit_rate
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            state_data['is_active'],
            state_data['last_trade_time'],
            state_data['consecutive_losses'],
            state_data['total_trades'],
            state_data['successful_trades'],
            state_data['current_profit_rate']
        ))
        conn.commit()
    except Exception as e:
        logger.error(f"트레이딩 상태 업데이트 오류: {e}")

def get_trading_state(conn):
    """현재 트레이딩 상태 조회 함수"""
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT is_active, consecutive_losses, total_trades,
                   successful_trades, current_profit_rate
            FROM trading_state 
            ORDER BY timestamp DESC LIMIT 1
        """)
        row = cursor.fetchone()
        
        if row:
            return {
                'is_active': bool(row[0]),
                'consecutive_losses': row[1],
                'total_trades': row[2],
                'successful_trades': row[3],
                'current_profit_rate': row[4]
            }
        else:
            return {
                'is_active': True,
                'consecutive_losses': 0,
                'total_trades': 0,
                'successful_trades': 0,
                'current_profit_rate': 0.0
            }
    except Exception as e:
        logger.error(f"트레이딩 상태 조회 오류: {e}")
        return None

def check_trading_conditions(conn):
    """거래 조건 확인 함수"""
    try:
        state = get_trading_state(conn)
        if not state:
            return False
            
        # 연속 손실 체크
        if state['consecutive_losses'] >= TRADING_CONFIG['CONSECUTIVE_LOSS_LIMIT']:
            logger.warning(f"연속 손실 제한 도달: {state['consecutive_losses']} 회")
            return False
            
        return state['is_active']
            
    except Exception as e:
        logger.error(f"거래 조건 확인 중 오류: {e}")
        return False
    


#3파트
# 시장 데이터 수집 및 분석 함수
def collect_market_data():
    """시장 데이터 수집 및 기술적 지표 계산"""
    try:
        # 1분봉과 5분봉 데이터 수집
        df_1m = pyupbit.get_ohlcv("KRW-BTC", interval="minute1", count=100)
        df_5m = pyupbit.get_ohlcv("KRW-BTC", interval="minute5", count=20)
        
        if df_1m is None or df_5m is None:
            logger.error("OHLCV 데이터 수집 실패")
            return None
            
        # 기술적 지표 계산
        df_1m = calculate_indicators(df_1m)
        df_5m = calculate_indicators(df_5m)
        
        # 현재가 조회
        current_price = float(df_1m['close'].iloc[-1])
        
        market_data = {
            'current_price': current_price,
            'rsi': float(df_1m['rsi'].iloc[-1]),
            'bb_width': float(df_1m['bb_width'].iloc[-1]),
            'macd': float(df_1m['macd'].iloc[-1]),
            'macd_signal': float(df_1m['macd_signal'].iloc[-1]),
            'ema_short': float(df_1m['ema_short'].iloc[-1]),
            'ema_long': float(df_1m['ema_long'].iloc[-1]),
            'volatility': float(df_1m['volatility'].iloc[-1]),
            'trend': calculate_trend(df_5m),
            'df_1m': df_1m,
            'df_5m': df_5m
        }
        
        logger.info(f"시장 데이터 수집 완료: RSI {market_data['rsi']:.2f}, BB Width {market_data['bb_width']:.2f}%")
        return market_data
        
    except Exception as e:
        logger.error(f"시장 데이터 수집 중 오류: {e}")
        return None

def calculate_indicators(df):
    """기술적 지표 계산"""
    try:
        if df is None or df.empty:
            return None
            
        # RSI
        df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
        
        # 볼린저 밴드
        bb = ta.volatility.BollingerBands(close=df['close'], window=20, window_dev=2)
        df['bb_upper'] = bb.bollinger_hband()
        df['bb_lower'] = bb.bollinger_lband()
        df['bb_width'] = ((df['bb_upper'] - df['bb_lower']) / df['close']) * 100
        
        # MACD
        macd = ta.trend.MACD(close=df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        
        # EMA
        df['ema_short'] = ta.trend.EMAIndicator(close=df['close'], window=10).ema_indicator()
        df['ema_long'] = ta.trend.EMAIndicator(close=df['close'], window=30).ema_indicator()
        
        # 변동성
        df['volatility'] = df['high'].div(df['low']).sub(1).mul(100)
        
        return df
        
    except Exception as e:
        logger.error(f"기술적 지표 계산 중 오류: {e}")
        return None

def calculate_trend(df):
    """추세 분석"""
    try:
        # 단순 이동평균 기반 추세 판단
        last_price = df['close'].iloc[-1]
        sma_20 = df['close'].rolling(window=20).mean().iloc[-1]
        sma_50 = df['close'].rolling(window=50).mean().iloc[-1]
        
        if last_price > sma_20 > sma_50:
            return "상승"
        elif last_price < sma_20 < sma_50:
            return "하락"
        else:
            return "횡보"
            
    except Exception as e:
        logger.error(f"추세 분석 중 오류: {e}")
        return "알 수 없음"

def evaluate_trade_possibility(market_data):
    """거래 가능성 평가"""
    try:
        rsi = market_data['rsi']
        bb_width = market_data['bb_width']
        macd = market_data['macd']
        macd_signal = market_data['macd_signal']
        
        # RSI 조건 평가
        rsi_condition = rsi <= TRADING_CONFIG['RSI_LOWER_BOUND'] or rsi >= TRADING_CONFIG['RSI_UPPER_BOUND']
        
        # MACD 크로스 확인
        macd_condition = False
        if rsi <= TRADING_CONFIG['RSI_LOWER_BOUND'] and macd > macd_signal:   #and -> or ??
            macd_condition = True  # 매수 시그널
        elif rsi >= TRADING_CONFIG['RSI_UPPER_BOUND'] and macd < macd_signal: #and -> or ??
            macd_condition = True  # 매도 시그널
            
        # 거래 신호 결정
        signal = 'hold'
        if rsi_condition or macd_condition: #and -> or
            signal = 'buy' if rsi <= TRADING_CONFIG['RSI_LOWER_BOUND'] else 'sell'
        
        trade_signal = {
            'signal': signal,
            'rsi': rsi,
            'bb_width': bb_width,
            'reason': f"RSI: {rsi:.2f}, BB Width: {bb_width:.2f}%, MACD Cross: {macd_condition}"
        }
        
        logger.info(f"거래 신호 분석: {trade_signal['signal']} ({trade_signal['reason']})")
        return trade_signal
        
    except Exception as e:
        logger.error(f"거래 가능성 평가 중 오류: {e}")
        return {'signal': 'hold', 'reason': '평가 오류'}
    
##4파트
# 거래 실행 함수들
def execute_trade(signal, percentage, market_data):
    """실제 거래 실행"""
    try:
        if signal == 'buy':
            return execute_buy(percentage, market_data)
        elif signal == 'sell':
            return execute_sell(percentage, market_data)
        return None
    except Exception as e:
        logger.error(f"거래 실행 중 오류: {e}")
        return None

def execute_buy(percentage, market_data):
    """매수 실행"""
    try:
        krw_balance = upbit.get_balance("KRW")
        if krw_balance is None or krw_balance < 5000:
            logger.warning(f"매수 가능 KRW 잔액 부족: {krw_balance:,.0f}원")
            return None
            
        buy_amount = krw_balance * (percentage / 100) * 0.9995  # 수수료 고려
        if buy_amount < 5000:
            logger.warning(f"최소 주문금액(5,000원) 미달: {buy_amount:,.0f}원")
            return None
            
        logger.info(f"매수 주문 시도: {buy_amount:,.0f}원")
        order = upbit.buy_market_order("KRW-BTC", buy_amount)
        
        if order:
            # 주문 체결 대기
            time.sleep(1)
            
            # 거래 데이터 구성
            btc_balance = upbit.get_balance("BTC")
            krw_balance = upbit.get_balance("KRW")
            current_price = market_data['current_price']
            
            trade_data = {
                'decision': 'buy',
                'percentage': percentage,
                'reason': market_data.get('reason', 'RSI 기반 매수'),
                'btc_balance': btc_balance,
                'krw_balance': krw_balance,
                'entry_price': current_price,
                'current_price': current_price,
                'stop_loss_price': current_price * 0.99,  # 1% 손절
                'take_profit_price': current_price * 1.015,  # 1.5% 익절
                'trade_status': 'executed',
                'rsi_value': market_data['rsi'],
                'bb_width': market_data['bb_width']
            }
            
            send_discord_message(
                f"✅ 매수 체결 완료\n"
                f"• 주문금액: {buy_amount:,.0f}원\n"
                f"• 현재가: {current_price:,.0f}원\n"
                f"• RSI: {market_data['rsi']:.2f}"
            )
            
            return trade_data
            
        else:
            logger.error("매수 주문 실패")
            return None
            
    except Exception as e:
        logger.error(f"매수 실행 중 오류: {e}")
        send_discord_message(f"🚨 매수 실행 오류: {e}")
        return None

def execute_sell(percentage, market_data):
    """매도 실행"""
    try:
        btc_balance = upbit.get_balance("BTC")
        current_price = market_data['current_price']
        
        if btc_balance is None or btc_balance == 0:
            logger.warning("매도 가능한 BTC 잔액 없음")
            return None
            
        sell_amount = btc_balance * (percentage / 100)
        if sell_amount * current_price < 5000:
            logger.warning(f"최소 주문금액(5,000원) 미달: {sell_amount * current_price:,.0f}원")
            return None
            
        logger.info(f"매도 주문 시도: {sell_amount:.8f} BTC")
        order = upbit.sell_market_order("KRW-BTC", sell_amount)
        
        if order:
            # 주문 체결 대기
            time.sleep(1)
            
            # 거래 데이터 구성
            new_btc_balance = upbit.get_balance("BTC")
            krw_balance = upbit.get_balance("KRW")
            
            trade_data = {
                'decision': 'sell',
                'percentage': percentage,
                'reason': market_data.get('reason', 'RSI 기반 매도'),
                'btc_balance': new_btc_balance,
                'krw_balance': krw_balance,
                'entry_price': current_price,
                'current_price': current_price,
                'trade_status': 'executed',
                'rsi_value': market_data['rsi'],
                'bb_width': market_data['bb_width']
            }
            
            send_discord_message(
                f"✅ 매도 체결 완료\n"
                f"• 매도수량: {sell_amount:.8f} BTC\n"
                f"• 현재가: {current_price:,.0f}원\n"
                f"• RSI: {market_data['rsi']:.2f}"
            )
            
            return trade_data
            
        else:
            logger.error("매도 주문 실패")
            return None
            
    except Exception as e:
        logger.error(f"매도 실행 중 오류: {e}")
        send_discord_message(f"🚨 매도 실행 오류: {e}")
        return None

def calculate_profit_loss(entry_price, current_price, trade_type='buy'):
    """수익률 계산"""
    try:
        if trade_type == 'buy':
            return ((current_price - entry_price) / entry_price) * 100
        else:  # sell
            return ((entry_price - current_price) / entry_price) * 100
    except Exception as e:
        logger.error(f"수익률 계산 중 오류: {e}")
        return 0.0
    

#5파트
# 메인 트레이딩 봇 함수
def trading_bot():
    """메인 트레이딩 로직"""
    try:
        conn = init_database()
        if not conn:
            return
            
        try:
            # 거래 조건 확인
            if not check_trading_conditions(conn):
                logger.info("거래 조건 미충족 (연속 손실 또는 거래 중지 상태)")
                return
                
            # 시장 데이터 수집
            market_data = collect_market_data()
            if not market_data:
                send_discord_message("❌ 시장 데이터 수집 실패")
                return
                
            # 거래 가능성 평가
            trade_signal = evaluate_trade_possibility(market_data)
            
            if trade_signal['signal'] == 'hold':
                # 현재 상태 로깅 (1분마다 하지 않도록 수정 가능)
                message = (
                    f"💤 현재 거래 조건 미충족\n"
                    f"• 현재가: {market_data['current_price']:,.0f}원\n"
                    f"• RSI: {trade_signal['rsi']:.2f}\n"
                    f"• BB Width: {trade_signal['bb_width']:.2f}%"
                )
                logger.info(message)
                return
                
            # 실제 거래 실행
            trade_result = execute_trade(
                trade_signal['signal'],
                TRADING_CONFIG['MAX_TRADE_PERCENTAGE'],
                market_data
            )
            
            # 거래 결과 처리
            if trade_result:
                log_trade(conn, trade_result)
                
                # 트레이딩 상태 업데이트
                update_trading_state(conn, {
                    'is_active': True,
                    'last_trade_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'consecutive_losses': 0,  # 성공적인 거래로 리셋
                    'total_trades': get_trading_state(conn)['total_trades'] + 1,
                    'successful_trades': get_trading_state(conn)['successful_trades'] + 1,
                    'current_profit_rate': calculate_profit_loss(
                        trade_result['entry_price'],
                        trade_result['current_price'],
                        trade_result['decision']
                    )
                })
            
        except Exception as e:
            logger.error(f"트레이딩 프로세스 중 오류: {e}")
            send_discord_message(f"🚨 트레이딩 오류: {e}")
            
    finally:
        if conn:
            conn.close()

def run_scheduled_trading():
    """스케줄된 트레이딩 실행"""
    try:
        logger.info("스케줄된 트레이딩 시작")
        trading_bot()
        logger.info("스케줄된 트레이딩 완료")
    except Exception as e:
        logger.error(f"스케줄된 트레이딩 중 오류: {e}")

def main():
    """메인 실행 함수"""
    try:
        # 시작 메시지
        start_message = (
            "🚀 비트코인 트레이딩 봇 시작\n"
            f"• RSI 범위: {TRADING_CONFIG['RSI_LOWER_BOUND']} - {TRADING_CONFIG['RSI_UPPER_BOUND']}\n"
            f"• 최대 거래 비중: {TRADING_CONFIG['MAX_TRADE_PERCENTAGE']}%\n"
            f"• 연속 손실 제한: {TRADING_CONFIG['CONSECUTIVE_LOSS_LIMIT']}회"
        )
        send_discord_message(start_message)
        
        # 1분마다 트레이딩 봇 실행
        schedule.every(5).minutes.do(run_scheduled_trading)  #1분간격 ~ 5분간격
        logger.info("트레이딩 스케줄 설정 완료")
        
        # 메인 루프
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
                time.sleep(60)  # 오류 발생시 1분 대기
                
    except Exception as e:
        logger.error(f"프로그램 시작 중 오류: {e}")
        send_discord_message(f"🚨 프로그램 시작 오류: {e}")

if __name__ == "__main__":
    main()

