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
        logging.FileHandler('trading_scalping.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 트레이딩 제약 조건 설정 
TRADING_CONFIG = {
    'MAX_TRADE_PERCENTAGE': 30.0,    # 최대 거래 비중을 30%로 수정
    'MIN_TRADE_PERCENTAGE': 0.0,     # 최소 거래 비중 추가
#    'MAX_TRADE_PERCENTAGE': 10.0,    # 최대 거래 비중
    'CONSECUTIVE_LOSS_LIMIT': 3,     # 연속 손실 허용 횟수
    'RSI_LOWER_BOUND': 28,          # RSI 하한선
    'RSI_UPPER_BOUND': 63,          # RSI 상한선
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
        conn = sqlite3.connect('trading_bot.db')  #trading_bot.db
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
            trade_data['entry_price'],
            trade_data['current_price'],
            trade_data.get('stop_loss_price', 0),
            trade_data.get('take_profit_price', 0),
            trade_data.get('profit_percentage', 0),
            trade_data.get('trade_status', 'executed'),
            trade_data.get('rsi', trade_data.get('rsi_value', 0)), # 'rsi' 또는 'rsi_value' 사용 수정한 내용
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

#수정하기
def evaluate_trade_possibility(market_data):
    """거래 가능성 평가"""
    try:
        rsi = market_data['rsi']
        bb_width = market_data['bb_width']
        macd = market_data['macd']
        macd_signal = market_data['macd_signal']
        
        # RSI 조건 평가
        rsi_condition = rsi <= TRADING_CONFIG['RSI_LOWER_BOUND'] or rsi >= TRADING_CONFIG['RSI_UPPER_BOUND']
        
        # BB Width 조건 추가
        bb_width_condition = bb_width >= 0.2  # 변동성이 충분한 경우에만 거래
        
        # MACD 크로스 확인
        macd_condition = False
        if rsi <= TRADING_CONFIG['RSI_LOWER_BOUND'] and macd > macd_signal:
            macd_condition = True  # 매수 시그널
        elif rsi >= TRADING_CONFIG['RSI_UPPER_BOUND'] and macd < macd_signal:
            macd_condition = True  # 매도 시그널
            
        # 거래 신호 결정 (BB Width 조건 포함)
        signal = 'hold'
        if (rsi_condition or macd_condition) and bb_width_condition:
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

def get_gpt_trade_percentage(market_data, signal):
    """GPT에게 거래 비중 문의"""
    try:
        messages = [
            {
                "role": "system",
                "content": """비트코인 트레이딩 전문가로서 현재 시장 상황을 분석하고 
                적절한 거래 비중(0~30%)을 제안해주세요. 반드시 아래 JSON 형식으로만 응답하세요:
                {"percentage": 15, "reason": "거래 비중 선택 이유"}"""
            },
            {
                "role": "user",
                "content": f"""
                현재 시장 상황:
                - 거래 유형: {signal.upper()}
                - 현재가: {market_data['current_price']:,.0f}원
                - RSI: {market_data['rsi']:.2f}
                - BB Width: {market_data['bb_width']:.2f}%
                - MACD: {market_data['macd']:.2f}
                - 추세: {market_data['trend']}
                
                위 데이터를 기반으로 0~30% 사이의 적절한 거래 비중을 제안해주세요.
                극단적인 RSI나 명확한 매수/매도 시그널이 있을 때는 더 높은 비중을,
                불확실성이 높을 때는 더 낮은 비중을 제안해주세요.
                """
            }
        ]

        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            max_tokens=200,
            temperature=0.7
        )

        result = json.loads(response.choices[0].message.content.strip())
        
        # 거래 비중 범위 제한
        percentage = min(max(result.get('percentage', 10), 
                           TRADING_CONFIG['MIN_TRADE_PERCENTAGE']), 
                           TRADING_CONFIG['MAX_TRADE_PERCENTAGE'])
        
        logger.info(f"GPT 거래 비중 제안: {percentage}% ({result.get('reason', '')})")
        
        return {
            'percentage': percentage,
            'reason': result.get('reason', '기본 거래 비중 적용')
        }
        
    except Exception as e:
        logger.error(f"GPT 거래 비중 문의 중 오류: {e}")
        return {'percentage': 10, 'reason': '기본 거래 비중 적용 (오류 발생)'}

#거래 비중 문의
# def get_gpt_trade_percentage(market_data, signal):
#     """GPT에게 거래 비중 문의"""
#     try:
#         messages = [
#             {
#                 "role": "system",
#                 "content": """비트코인 트레이딩 전문가로서 현재 시장 상황을 분석하고 
#                 적절한 거래 비중(0~30%)을 제안해주세요. 반드시 아래 JSON 형식으로만 응답하세요:
#                 {"percentage": 15, "reason": "거래 비중 선택 이유"}"""
#             },
#             {
#                 "role": "user",
#                 "content": f"""
#                 현재 시장 상황:
#                 - 거래 유형: {signal.upper()}
#                 - 현재가: {market_data['current_price']:,.0f}원
#                 - RSI: {market_data['rsi']:.2f}
#                 - BB Width: {market_data['bb_width']:.2f}%
#                 - MACD: {market_data['macd']:.2f}
#                 - 추세: {market_data['trend']}
                
#                 위 데이터를 기반으로 0~30% 사이의 적절한 거래 비중을 제안해주세요.
#                 극단적인 RSI나 명확한 매수/매도 시그널이 있을 때는 더 높은 비중을,
#                 불확실성이 높을 때는 더 낮은 비중을 제안해주세요.
#                 """
#             }
#         ]

#         response = openai_client.chat.completions.create(
#             model="gpt-4",
#             messages=messages,
#             max_tokens=200,
#             temperature=0.7
#         )

#         result = json.loads(response.choices[0].message.content.strip())
        
#         # 거래 비중 범위 제한
#         percentage = min(max(result.get('percentage', 10), 
#                            TRADING_CONFIG['MIN_TRADE_PERCENTAGE']), 
#                            TRADING_CONFIG['MAX_TRADE_PERCENTAGE'])
        
#         logger.info(f"GPT 거래 비중 제안: {percentage}% ({result.get('reason', '')})")
        
#         return {
#             'percentage': percentage,
#             'reason': result.get('reason', '기본 거래 비중 적용')
#         }
        
#     except Exception as e:
#         logger.error(f"GPT 거래 비중 문의 중 오류: {e}")
#         return {'percentage': 10, 'reason': '기본 거래 비중 적용 (오류 발생)'}
    
##4파트

def execute_trade(signal, market_data):
    """실제 거래 실행"""
    try:
        # GPT에게 거래 비중 문의
        trade_advice = get_gpt_trade_percentage(market_data, signal)
        percentage = trade_advice['percentage']
        
        if signal == 'buy':
            return execute_buy(percentage, market_data, trade_advice['reason'])
        elif signal == 'sell':
            return execute_sell(percentage, market_data, trade_advice['reason'])
        return None
    except Exception as e:
        logger.error(f"거래 실행 중 오류: {e}")
        return None
    
# 거래 실행 함수들
# def execute_trade(signal, percentage, market_data):
#     """실제 거래 실행"""
#     try:
#         if signal == 'buy':
#             return execute_buy(percentage, market_data)
#         elif signal == 'sell':
#             return execute_sell(percentage, market_data)
#         return None
#     except Exception as e:
#         logger.error(f"거래 실행 중 오류: {e}")
#         return None


## 수정하기 
## 수정 

def execute_buy(percentage, market_data, reason):
    try:
        krw_balance = upbit.get_balance("KRW")
        if krw_balance is None or krw_balance < 5000:
            logger.warning(f"매수 가능 KRW 잔액 부족: {krw_balance:,.0f}원")
            return None
            
        buy_amount = krw_balance * (percentage / 100) * 0.9995
        if buy_amount < 5000:
            logger.warning(f"최소 주문금액(5,000원) 미달: {buy_amount:,.0f}원")
            return None
            
        # 매수 주문 실행
        order = upbit.buy_market_order("KRW-BTC", buy_amount)
        if order:
            time.sleep(2)  # 체결 대기 시간 증가
            
            # 실제 체결 가격 확인
            try:
                order_detail = upbit.get_order(order['uuid'])
                if order_detail and 'trades' in order_detail and order_detail['trades']:
                    executed_price = float(order_detail['trades'][0]['price'])
                else:
                    executed_price = market_data['current_price']
            except Exception as e:
                logger.error(f"체결 가격 조회 실패: {e}")
                executed_price = market_data['current_price']

            # 현재가 재조회
            current_price = pyupbit.get_current_price("KRW-BTC")
            if not current_price:
                current_price = market_data['current_price']

            profit_percentage = calculate_profit_loss(executed_price, current_price, 'buy')
            
            trade_data = {
                'decision': 'buy',
                'percentage': percentage,
                'reason': reason,
                'btc_balance': upbit.get_balance("BTC"),
                'krw_balance': upbit.get_balance("KRW"),
                'entry_price': executed_price,
                'current_price': current_price,
                'profit_percentage': profit_percentage,
                'stop_loss_price': executed_price * 0.99,
                'take_profit_price': executed_price * 1.02,
                'trade_status': 'executed',
                'rsi_value': market_data['rsi'],
                'bb_width': market_data['bb_width']
            }
            
            logger.info(f"매수 거래 데이터: {json.dumps(trade_data, indent=2)}")
            return trade_data
            
    except Exception as e:
        logger.error(f"매수 실행 중 오류: {e}")
        return None
    

# def execute_buy(percentage, market_data):
#     """매수 실행"""
#     try:
#         krw_balance = upbit.get_balance("KRW")
#         if krw_balance is None or krw_balance < 5000:
#             logger.warning(f"매수 가능 KRW 잔액 부족: {krw_balance:,.0f}원")
#             return None
            
#         buy_amount = krw_balance * (percentage / 100) * 0.9995  # 수수료 고려
#         if buy_amount < 5000:
#             logger.warning(f"최소 주문금액(5,000원) 미달: {buy_amount:,.0f}원")
#             return None
            
#         logger.info(f"매수 주문 시도: {buy_amount:,.0f}원")
#         order = upbit.buy_market_order("KRW-BTC", buy_amount)
        
#         if order:
#             # 주문 체결 대기
#             time.sleep(1)

#             # 체결 가격 확인 (추가)
#             executed_price = float(order['price'])  # 실제 체결 가격
#             current_price = market_data['current_price']
#             profit_percentage = calculate_profit_loss(executed_price, current_price, 'buy')

#             # 거래 데이터 구성
#             btc_balance = upbit.get_balance("BTC")
#             krw_balance = upbit.get_balance("KRW")
#             current_price = market_data['current_price']
            
#             trade_data = {
#                 'decision': 'buy',
#                 'percentage': percentage,
#                 'reason': market_data.get('reason', 'RSI 기반 매수'),
#                 'btc_balance': btc_balance,
#                 'krw_balance': krw_balance,
#                 'entry_price': executed_price,  # 실제 체결가로 수정
#                 'current_price': current_price,
#                 'profit_percentage': profit_percentage,  # 수익률 추가
#                 'trade_status': 'executed',
#                 'stop_loss_price': current_price * 0.99,  # 1% 손절
#                 'take_profit_price': current_price * 1.02,  # 2.0% 익절
#                 'trade_status': 'executed',
#                 'rsi_value': market_data['rsi'],
#                 'bb_width': market_data['bb_width']
#             }
            
#             # 디스코드 메시지에 수익률 정보 추가
#             send_discord_message(
#                 f"✅ 매수 체결 완료\n"
#                 f"• 주문금액: {buy_amount:,.0f}원\n"
#                 f"• 체결가: {executed_price:,.0f}원\n"
#                 f"• 현재가: {current_price:,.0f}원\n"
#                 f"• 수익률: {profit_percentage:.2f}%\n"
#                 f"• RSI: {market_data['rsi']:.2f}"
            
#             )
            
#             return trade_data
            
#         else:
#             logger.error("매수 주문 실패")
#             return None
            
#     except Exception as e:
#         logger.error(f"매수 실행 중 오류: {e}")
#         send_discord_message(f"🚨 매수 실행 오류: {e}")
#         return None

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


## 수정

def calculate_profit_loss(entry_price, current_price, trade_type='buy'):
    """수익률 계산"""
    try:
        # 기본 유효성 검사
        if not entry_price or not current_price:
            logger.error(f"수익률 계산 오류: 가격 데이터 누락 (entry_price: {entry_price}, current_price: {current_price})")
            return 0.0
        
        # 0으로 나누기 방지
        if float(entry_price) <= 0:
            logger.error(f"수익률 계산 오류: 진입 가격이 0이하 (entry_price: {entry_price})")
            return 0.0

        # 숫자형으로 변환
        entry_price = float(entry_price)
        current_price = float(current_price)
        
        # 수익률 계산
        if trade_type.lower() == 'buy':
            profit_percentage = ((current_price - entry_price) / entry_price) * 100
        else:  # sell의 경우 반대로 계산
            profit_percentage = ((entry_price - current_price) / current_price) * 100
        
        # 비정상적인 수익률 체크 (500%로 상향 조정)
        if abs(profit_percentage) > 500:
            logger.warning(f"높은 수익률 감지: {profit_percentage:.2f}% (entry: {entry_price:,.0f}, current: {current_price:,.0f})")
            
        # 소수점 2자리까지 반올림
        return round(profit_percentage, 2)

    except Exception as e:
        logger.error(f"수익률 계산 중 오류 발생: {str(e)}")
        return 0.0

        
# def calculate_profit_loss(entry_price, current_price, trade_type='buy'):
#     """수익률 계산"""
#     try:
#         if not entry_price or not current_price or entry_price == 0:
#             logger.error(f"수익률 계산 오류: 잘못된 가격 데이터 (entry_price: {entry_price}, current_price: {current_price})")
#             return 0.0

#         if trade_type == 'buy':
#             profit_percentage = ((current_price - entry_price) / entry_price) * 100
#         else:  # sell
#             profit_percentage = ((entry_price - current_price) / entry_price) * 100

#         # 비정상적인 수익률 체크
#         if abs(profit_percentage) > 100:  # 100% 이상의 수익률은 오류로 간주
#             logger.error(f"비정상적인 수익률 감지: {profit_percentage}% (entry: {entry_price}, current: {current_price})")
#             return 0.0

#         return profit_percentage

#     except Exception as e:
#         logger.error(f"수익률 계산 중 오류: {e}")
#         return 0.0
    


# def calculate_profit_loss(entry_price, current_price, trade_type='buy'):
#     """수익률 계산"""
#     try:
#         if trade_type == 'buy':
#             return ((current_price - entry_price) / entry_price) * 100
#         else:  # sell
#             return ((entry_price - current_price) / entry_price) * 100
#     except Exception as e:
#         logger.error(f"수익률 계산 중 오류: {e}")
#         return 0.0
    
def get_recent_trades(conn, limit=10):
    """최근 거래 내역 조회"""
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp, decision, entry_price, current_price,
                   profit_percentage, rsi_value
            FROM trades
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
        
        trades = cursor.fetchall()
        for trade in trades:
            logger.info(
                f"거래 기록: {trade[0]} - {trade[1].upper()}, "
                f"진입가: {trade[2]:,.0f}원, "
                f"현재가: {trade[3]:,.0f}원, "
                f"수익률: {trade[4]:.2f}%, "
                f"RSI: {trade[5]:.2f}"
            )
        
        return trades
    except Exception as e:
        logger.error(f"거래 내역 조회 중 오류: {e}")
        return []
    
#5파트
# 메인 트레이딩 봇 함수


def trading_bot():
    """메인 트레이딩 로직"""
    try:
        conn = init_database()
        if not conn:
            return
            
        try:
            # 최근 거래 내역 확인 (추가된 부분)
            recent_trades = get_recent_trades(conn, limit=5)  # 최근 5개 거래 확인
            if recent_trades:
                total_profit = sum(trade[4] for trade in recent_trades)  # profit_percentage 합계
                avg_profit = total_profit / len(recent_trades)
                logger.info(f"최근 {len(recent_trades)}개 거래 평균 수익률: {avg_profit:.2f}%")

                        
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
            # trade_result = execute_trade(
            #     trade_signal['signal'],
            #     TRADING_CONFIG['MAX_TRADE_PERCENTAGE'],
            #     market_data

            trade_result = execute_trade(
                trade_signal['signal'],
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
        

        # 1시간마다 거래 내역 요약 출력 (추가된 부분)
        def print_trade_summary():
            conn = init_database()
            if conn:
                try:
                    recent_trades = get_recent_trades(conn, limit=10)
                    if recent_trades:
                        send_discord_message(
                            f"📊 최근 거래 내역 요약\n"
                            f"• 거래 횟수: {len(recent_trades)}회\n"
                            f"• 평균 수익률: {sum(trade[4] for trade in recent_trades)/len(recent_trades):.2f}%"
                        )
                finally:
                    conn.close()
                    
        schedule.every(1).hours.do(print_trade_summary)


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

