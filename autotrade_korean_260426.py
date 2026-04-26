# 0601버전에서 손실시 매도 하지 않는 내용 추가 수정
#1. RSI 기준으로 매수할 때 장기 이동 평균 보다 높은 가격이면 매수를 하지 않도록 해서 너무 높은 가격에 매수 하지 않게 조정 
#2. 매수한 후에는 RSI 매도 조건에 해당 되더라도 수익율이 2% 이상 되지 않으면 매도 하지 않도록 수정
#3. 매도,매수 저건에 해당되는 변수 들은 코드의 앞부분에 배치되도록 해서 수정이 쉽게 수정
#4. 매세지 발송이 반복적으로 많이 되지 않고, 중요하지 않은 메세지가 발송 되지 않도록 코드를 수정
#5. 파이썬 코딩의 띄어쓰기에 문제 없는지 점검 해서 수정 
#6. 디스코드 메시지 발송 조건 수정 
#1006 디스코드 메세지 발송 대기시간 반영
#260426 데이터 조회 빈도 조정
#260426 RSI 매수 기준점 조정
#260426 이동평균 대비 최대 가격 초과율 조정
#260426 최소 수익률 조정
#260426 매도 조건 조정

     




# 필요한 라이브러리 임포트
import os
import logging
import time
import sqlite3
import yaml
import schedule
import requests
from datetime import datetime
from dotenv import load_dotenv
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

# 로그 제어를 위한 전역 변수
last_log_time = {}
LOG_INTERVALS = {
    'market_data': 900,      # 시장 데이터 로그는 15분마다
    'hold_status': 1200,     # HOLD 상태 로그는 20분마다  
    'schedule_info': 3600,   # 스케줄 정보는 60분마다
    'error_logs': 300,       # 에러 로그는 5분마다 (중요도에 따라)
}

# ===========================================
# 매매 조건 설정 (쉬운 수정을 위해 상단에 배치)
# ===========================================
TRADING_CONFIG = {
    # 기본 설정
    'MAX_TRADE_PERCENTAGE': 30.0,     # 최대 거래 비중 30%
    'CONSECUTIVE_LOSS_LIMIT': 3,      # 연속 손실 허용 횟수
    'COOLDOWN_MINUTES': 30,           # 거래 재개 전 대기 시간
    'MARKET_STABILITY_WINDOW': 12,    # 시장 안정성 확인 기간
    'MIN_SUCCESS_RATE': 60.0,         # 최소 성공률 기준
    
    # 매수 조건
    'RSI_BUY_THRESHOLD': 32,          # RSI 매수 기준점 (이하일 때 매수)
    'MA_PRICE_FILTER': True,          # 장기 이동평균 필터 사용 여부
    'MA_PERIOD': 50,                  # 장기 이동평균 기간
    'MAX_PRICE_ABOVE_MA': 4.0,        # 이동평균 대비 최대 가격 초과율 (%)
    
    # 매도 조건
    'RSI_SELL_THRESHOLD': 70,         # RSI 매도 기준점 (이상일 때 매도)
    'MIN_PROFIT_FOR_SELL': 3.0,       # 최소 수익률 (% 이상일 때만 매도)
    'STOP_LOSS_RATE': -5.0,           # 손절매 기준 (% 이하일 때 강제 매도)
    'TAKE_PROFIT_RATE': 1.5,          # 기본 익절 목표 수익률 (%)
    
    # 기술적 지표 기준
    'RSI_PERIOD': 14,                 # RSI 계산 기간
    'BB_PERIOD': 20,                  # 볼린저 밴드 기간
    'BB_STD': 2,                      # 볼린저 밴드 표준편차
    'EMA_SHORT': 10,                  # 단기 EMA
    'EMA_LONG': 30                    # 장기 EMA
}

# Discord 웹훅 설정
try:
    with open('config.yaml', encoding='UTF-8') as f:
        _cfg = yaml.safe_load(f)
    DISCORD_WEBHOOK_URL = _cfg.get('DISCORD_WEBHOOK_URL', '')
except Exception as e:
    logger.error(f"설정 파일 로드 오류: {e}")
    DISCORD_WEBHOOK_URL = ''

# 메시지 발송 제어를 위한 전역 변수
last_hold_message_time = None
last_market_data_time = None
last_error_message_time = None
MESSAGE_COOLDOWN = 600  # 10분 (초 단위)
ERROR_MESSAGE_COOLDOWN = 300  # 에러 메시지는 5분마다

def should_log(log_type, force=False):
    """로그 출력 여부를 결정하는 함수"""
    if force:
        return True
    
    # 에러 로그는 항상 출력
    if 'error' in log_type.lower():
        return True
    
    current_time = datetime.now()
    if log_type not in last_log_time:
        last_log_time[log_type] = current_time
        return True
    
    time_diff = (current_time - last_log_time[log_type]).seconds
    if time_diff >= LOG_INTERVALS[log_type]:
        last_log_time[log_type] = current_time
        return True
    
    return False

def send_discord_message(msg, force_send=False):
    """디스코드 메시지 전송 함수 (중요하지 않은 메시지 필터링)"""
    global last_hold_message_time, last_error_message_time
    
    try:
        current_time = datetime.now()
        
        # HOLD 메시지는 10분마다만 발송
        if "거래 조건 미충족" in str(msg) or "💤" in str(msg):
            if not force_send and last_hold_message_time:
                if (current_time - last_hold_message_time).seconds < MESSAGE_COOLDOWN:
                    return
            last_hold_message_time = current_time
        
        # 에러 메시지도 5분마다만 발송
        elif "🚨" in str(msg) or "오류" in str(msg):
            if not force_send and last_error_message_time:
                if (current_time - last_error_message_time).seconds < ERROR_MESSAGE_COOLDOWN:
                    return
            last_error_message_time = current_time
        
        message = {"content": f"[{current_time.strftime('%H:%M')}] {str(msg)}"}
        requests.post(DISCORD_WEBHOOK_URL, json=message, timeout=10)
        # print 제거 (콘솔 출력 최소화)
        
    except Exception as e:
        logger.error(f"Discord 전송 실패: {e}")

# API 키 검증
access = os.getenv("UPBIT_ACCESS_KEY")
secret = os.getenv("UPBIT_SECRET_KEY")

if not all([access, secret, DISCORD_WEBHOOK_URL]):
    logger.error("필수 설정값이 누락되었습니다.")
    raise ValueError("모든 필수 설정값을 .env와 config.yaml 파일에 입력해주세요.")

# Upbit 클라이언트 초기화
upbit = pyupbit.Upbit(access, secret)

# 데이터베이스 초기화 함수
def init_database():
    try:
        conn = sqlite3.connect('trading_bot.db') #매매 기록이 여기에 저장됨 지우지 말것 
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
        send_discord_message(f"🚨 데이터베이스 초기화 실패: {e}", force_send=True)
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
            trade_data.get('rsi', trade_data.get('rsi_value', 0)),
            trade_data['bb_width']
        ))
        conn.commit()
        logger.info("거래 기록: %s", trade_data['decision'].upper())
    except Exception as e:
        conn.rollback()
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

# 시장 데이터 캐싱을 위한 전역 변수
cached_market_data = None
cache_timestamp = None
CACHE_DURATION = 180  # 3분 캐시 (기존 1분에서 증가)

# 시장 데이터 수집 및 분석 함수
def collect_market_data():
    """시장 데이터 수집 및 기술적 지표 계산 (캐싱 적용)"""
    global cached_market_data, cache_timestamp
    
    try:
        current_time = datetime.now()
        
        # 캐시된 데이터가 유효한지 확인
        if (cached_market_data and cache_timestamp and 
            (current_time - cache_timestamp).seconds < CACHE_DURATION):
            # 캐시 사용시에는 로그 출력하지 않음 (너무 빈번함)
            return cached_market_data
        
        # 1분봉과 5분봉 데이터 수집
        df_5m = pyupbit.get_ohlcv("KRW-BTC", interval="minute5", count=100)
        df_10m = pyupbit.get_ohlcv("KRW-BTC", interval="minute10", count=20)
        
        if df_5m is None or df_10m is None:
            logger.error("OHLCV 데이터 수집 실패")
            return None
            
        # 기술적 지표 계산
        df_5m = calculate_indicators(df_5m)
        df_10m = calculate_indicators(df_10m)
        
        # 현재가 조회
        current_price = float(df_5m['close'].iloc[-1])
        
        # 장기 이동평균 계산
        ma_long = float(df_5m['close'].rolling(window=TRADING_CONFIG['MA_PERIOD']).mean().iloc[-1])
        
        market_data = {
            'current_price': current_price,
            'rsi': float(df_5m['rsi'].iloc[-1]),
            'bb_width': float(df_5m['bb_width'].iloc[-1]),
            'macd': float(df_5m['macd'].iloc[-1]),
            'macd_signal': float(df_5m['macd_signal'].iloc[-1]),
            'ema_short': float(df_5m['ema_short'].iloc[-1]),
            'ema_long': float(df_5m['ema_long'].iloc[-1]),
            'volatility': float(df_5m['volatility'].iloc[-1]),
            'ma_long': ma_long,  # 장기 이동평균 추가
            'trend': calculate_trend(df_10m),
            'df_5m': df_5m,
            'df_10m': df_10m
        }
        
        # 캐시 업데이트
        cached_market_data = market_data
        cache_timestamp = current_time
        
        if should_log('market_data'):
            logger.info(f"데이터 업데이트: RSI {market_data['rsi']:.1f}")
        
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
        df['rsi'] = ta.momentum.RSIIndicator(
            close=df['close'], 
            window=TRADING_CONFIG['RSI_PERIOD']
        ).rsi()
        
        # 볼린저 밴드
        bb = ta.volatility.BollingerBands(
            close=df['close'], 
            window=TRADING_CONFIG['BB_PERIOD'], 
            window_dev=TRADING_CONFIG['BB_STD']
        )
        df['bb_upper'] = bb.bollinger_hband()
        df['bb_lower'] = bb.bollinger_lband()
        df['bb_width'] = ((df['bb_upper'] - df['bb_lower']) / df['close']) * 100
        
        # MACD
        macd = ta.trend.MACD(close=df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        
        # EMA
        df['ema_short'] = ta.trend.EMAIndicator(
            close=df['close'], 
            window=TRADING_CONFIG['EMA_SHORT']
        ).ema_indicator()
        df['ema_long'] = ta.trend.EMAIndicator(
            close=df['close'], 
            window=TRADING_CONFIG['EMA_LONG']
        ).ema_indicator()
        
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
    """거래 가능성 평가 (개선된 조건)"""
    try:
        rsi = market_data['rsi']
        bb_width = market_data['bb_width']
        macd = market_data['macd']
        macd_signal = market_data['macd_signal']
        current_price = market_data['current_price']
        ma_long = market_data['ma_long']
        
        # 매수 조건 평가
        buy_conditions = []
        
        # 1. RSI 조건
        rsi_buy_signal = rsi <= TRADING_CONFIG['RSI_BUY_THRESHOLD']
        buy_conditions.append(('RSI', rsi_buy_signal, f"RSI {rsi:.2f} <= {TRADING_CONFIG['RSI_BUY_THRESHOLD']}"))
        
        # 2. 가격이 장기 이동평균 대비 너무 높지 않은지 확인
        price_above_ma_rate = ((current_price - ma_long) / ma_long) * 100
        price_filter_pass = True
        if TRADING_CONFIG['MA_PRICE_FILTER']:
            price_filter_pass = price_above_ma_rate <= TRADING_CONFIG['MAX_PRICE_ABOVE_MA']
        buy_conditions.append(('Price Filter', price_filter_pass, 
                              f"가격이 MA{TRADING_CONFIG['MA_PERIOD']} 대비 {price_above_ma_rate:.2f}% 높음"))
        
        # 3. MACD 조건
        macd_buy_signal = macd > macd_signal
        buy_conditions.append(('MACD', macd_buy_signal, f"MACD > Signal"))
        
        # 매도 조건 평가
        sell_conditions = []
        
        # 1. RSI 조건
        rsi_sell_signal = rsi >= TRADING_CONFIG['RSI_SELL_THRESHOLD']
        sell_conditions.append(('RSI', rsi_sell_signal, f"RSI {rsi:.2f} >= {TRADING_CONFIG['RSI_SELL_THRESHOLD']}"))
        
        # 거래 신호 결정
        all_buy_conditions_met = all(condition[1] for condition in buy_conditions)
        any_sell_condition_met = any(condition[1] for condition in sell_conditions)
        
        signal = 'hold'
        reason_parts = []
        
        if all_buy_conditions_met:
            signal = 'buy'
            reason_parts = [f"{cond[0]}: {cond[2]}" for cond in buy_conditions if cond[1]]
        elif any_sell_condition_met:
            signal = 'sell'
            reason_parts = [f"{cond[0]}: {cond[2]}" for cond in sell_conditions if cond[1]]
        else:
            # HOLD 이유 설명
            failed_buy = [f"{cond[0]} 미충족" for cond in buy_conditions if not cond[1]]
            failed_sell = [f"{cond[0]} 미충족" for cond in sell_conditions if not cond[1]]
            reason_parts = failed_buy + failed_sell
        
        trade_signal = {
            'signal': signal,
            'rsi': rsi,
            'bb_width': bb_width,
            'price_above_ma_rate': price_above_ma_rate,
            'reason': " | ".join(reason_parts[:2])  # 메시지 길이 제한
        }
        
        # 중요한 신호만 로그 출력
        if signal != 'hold' or should_log('hold_status'):
            logger.info(f"신호: {trade_signal['signal'].upper()} - {trade_signal['reason'][:50]}")
        
        return trade_signal
        
    except Exception as e:
        logger.error(f"거래 가능성 평가 중 오류: {e}")
        return {'signal': 'hold', 'reason': '평가 오류'}

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
                'stop_loss_price': current_price * (1 + TRADING_CONFIG['STOP_LOSS_RATE'] / 100),
                'take_profit_price': current_price * (1 + TRADING_CONFIG['TAKE_PROFIT_RATE'] / 100),
                'trade_status': 'executed',
                'rsi_value': market_data['rsi'],
                'bb_width': market_data['bb_width']
            }
            
            send_discord_message(
                f"✅ 매수 체결 완료\n"
                f"• 주문금액: {buy_amount:,.0f}원\n"
                f"• 현재가: {current_price:,.0f}원\n"
                f"• RSI: {market_data['rsi']:.2f}\n"
                f"• 목표 수익률: +{TRADING_CONFIG['MIN_PROFIT_FOR_SELL']}%",
                force_send=True
            )
            
            return trade_data
            
        else:
            logger.error("매수 주문 실패")
            return None
            
    except Exception as e:
        logger.error(f"매수 실행 중 오류: {e}")
        send_discord_message(f"🚨 매수 실행 오류: {e}", force_send=True)
        return None

def execute_sell(percentage, market_data):
    """매도 실행 (개선된 수익률 조건)"""
    try:
        btc_balance = upbit.get_balance("BTC")
        current_price = market_data['current_price']
        
        if btc_balance is None or btc_balance == 0:
            logger.warning("매도 가능한 BTC 잔액 없음")
            return None
        
        # 최근 매수 거래 기록 조회하여 매수가 확인
        conn = sqlite3.connect('trading_bot.db')
        cursor = conn.cursor()
        
        # 가장 최근 매수 거래의 entry_price 조회
        cursor.execute("""
            SELECT entry_price, timestamp 
            FROM trades 
            WHERE decision = 'buy' AND btc_balance > 0
            ORDER BY timestamp DESC 
            LIMIT 1
        """)
        
        last_buy_record = cursor.fetchone()
        conn.close()
        
        if not last_buy_record:
            logger.warning("매수 기록을 찾을 수 없습니다. 안전을 위해 매도를 진행합니다.")
        else:
            entry_price = float(last_buy_record[0])
            
            # 수익률 계산
            profit_rate = ((current_price - entry_price) / entry_price) * 100
            
            logger.info(f"매도 신호 분석 - 매수가: {entry_price:,.0f}원, 현재가: {current_price:,.0f}원, 수익률: {profit_rate:.2f}%")
            
            # 손절매 조건 확인 (강제 매도)
            if profit_rate <= TRADING_CONFIG['STOP_LOSS_RATE']:
                logger.warning(f"손절매 조건 충족 - 강제 매도 진행 (손실률: {profit_rate:.2f}%)")
                send_discord_message(
                    f"🚨 손절매 실행\n"
                    f"• 매수가: {entry_price:,.0f}원\n"
                    f"• 현재가: {current_price:,.0f}원\n"
                    f"• 손실률: {profit_rate:.2f}%",
                    force_send=True
                )
            # 최소 수익률 미달 시 홀드
            elif profit_rate < TRADING_CONFIG['MIN_PROFIT_FOR_SELL']:
                hold_message = (
                    f"⏸️ 목표 수익률 미달로 홀드\n"
                    f"• 매수가: {entry_price:,.0f}원\n"
                    f"• 현재가: {current_price:,.0f}원\n"
                    f"• 현재 수익률: {profit_rate:.2f}%\n"
                    f"• 목표 수익률: {TRADING_CONFIG['MIN_PROFIT_FOR_SELL']}%"
                )
                send_discord_message(hold_message)
                logger.info(f"목표 수익률 미달로 인한 매도 취소 (현재: {profit_rate:.2f}%, 목표: {TRADING_CONFIG['MIN_PROFIT_FOR_SELL']}%)")
                return None
            else:
                # 목표 수익률 달성 시 매도 진행
                profit_message = (
                    f"✅ 목표 수익률 달성 - 매도 진행\n"
                    f"• 매수가: {entry_price:,.0f}원\n"
                    f"• 현재가: {current_price:,.0f}원\n"
                    f"• 수익률: +{profit_rate:.2f}%"
                )
                send_discord_message(profit_message, force_send=True)
                logger.info(f"목표 수익률 달성으로 매도 진행 (수익률: +{profit_rate:.2f}%)")
        
        # 매도 실행
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
                'reason': market_data.get('reason', 'RSI 기반 익절 매도'),
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
                f"• RSI: {market_data['rsi']:.2f}",
                force_send=True
            )
            
            return trade_data
            
        else:
            logger.error("매도 주문 실패")
            return None
            
    except Exception as e:
        logger.error(f"매도 실행 중 오류: {e}")
        send_discord_message(f"🚨 매도 실행 오류: {e}", force_send=True)
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

# 전역 데이터베이스 연결 (재사용을 위해)
global_db_conn = None

def get_database_connection():
    """데이터베이스 연결을 재사용하거나 새로 생성"""
    global global_db_conn
    try:
        if global_db_conn is None:
            global_db_conn = init_database()
        return global_db_conn
    except Exception as e:
        logger.error(f"데이터베이스 연결 오류: {e}")
        return None

# 메인 트레이딩 봇 함수
def trading_bot():
    """메인 트레이딩 로직"""
    try:
        conn = get_database_connection()
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
                send_discord_message("❌ 시장 데이터 수집 실패", force_send=True)
                return
                
            # 거래 가능성 평가
            trade_signal = evaluate_trade_possibility(market_data)
            
            if trade_signal['signal'] == 'hold':
                # Hold 상태는 간헐적으로만 간소 로그 출력
                if should_log('hold_status'):
                    logger.info(f"HOLD: RSI {trade_signal['rsi']:.1f}")
                # 거래 조건 미충족시에는 디스코드 메시지 발신하지 않음
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
                current_state = get_trading_state(conn)
                update_trading_state(conn, {
                    'is_active': True,
                    'last_trade_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'consecutive_losses': 0,  # 성공적인 거래로 리셋
                    'total_trades': current_state['total_trades'] + 1,
                    'successful_trades': current_state['successful_trades'] + 1,
                    'current_profit_rate': calculate_profit_loss(
                        trade_result['entry_price'],
                        trade_result['current_price'],
                        trade_result['decision']
                    )
                })
            
        except Exception as e:
            logger.error(f"트레이딩 프로세스 중 오류: {e}")
            send_discord_message(f"🚨 트레이딩 오류: {e}", force_send=True)
            
    except Exception as e:
        logger.error(f"트레이딩 봇 실행 중 오류: {e}")
        send_discord_message(f"🚨 트레이딩 봇 오류: {e}", force_send=True)

def run_scheduled_trading():
    """스케줄된 트레이딩 실행"""
    try:
        if should_log('schedule_info'):
            logger.info("거래 시작")
        trading_bot()
        if should_log('schedule_info'):
            logger.info("거래 완료")
    except Exception as e:
        logger.error(f"거래 오류: {e}")

def cleanup_database():
    """데이터베이스 연결 정리"""
    global global_db_conn
    if global_db_conn:
        global_db_conn.close()
        global_db_conn = None

def main():
    """메인 실행 함수"""
    try:
        # 시작 메시지
        start_message = (
            f"🚀 개선된 비트코인 트레이딩 봇 시작\n"
            f"📊 **매수 조건**\n"
            f"• RSI ≤ {TRADING_CONFIG['RSI_BUY_THRESHOLD']}\n"
            f"• 현재가 ≤ MA{TRADING_CONFIG['MA_PERIOD']} + {TRADING_CONFIG['MAX_PRICE_ABOVE_MA']}%\n"
            f"• MACD > Signal\n"
            f"💰 **매도 조건**\n"
            f"• RSI ≥ {TRADING_CONFIG['RSI_SELL_THRESHOLD']} AND 수익률 ≥ {TRADING_CONFIG['MIN_PROFIT_FOR_SELL']}%\n"
            f"• 또는 손절매: 손실률 ≤ {TRADING_CONFIG['STOP_LOSS_RATE']}%\n"
            f"⚙️ **기본 설정**\n"
            f"• 최대 거래 비중: {TRADING_CONFIG['MAX_TRADE_PERCENTAGE']}%\n"
            f"• 연속 손실 제한: {TRADING_CONFIG['CONSECUTIVE_LOSS_LIMIT']}회"
        )
        send_discord_message(start_message, force_send=True)
        
        # 1시간마다 트레이딩 봇 실행 (데이터 조회 빈도 저감)
        schedule.every(1).hours.do(run_scheduled_trading)
        if should_log('schedule_info'):
            logger.info("스케줄 설정: 1시간 간격")
        
        # 메인 루프
        while True:
            try:
                schedule.run_pending()
                time.sleep(1)
            except KeyboardInterrupt:
                send_discord_message("🛑 트레이딩 봇 수동 중지", force_send=True)
                break
            except Exception as e:
                logger.error(f"메인 루프 오류: {e}")
                send_discord_message(f"🚨 메인 루프 오류: {e}", force_send=True)
                time.sleep(60)  # 오류 발생시 1분 대기
                
    except Exception as e:
        logger.error(f"프로그램 시작 중 오류: {e}")
        send_discord_message(f"🚨 프로그램 시작 오류: {e}", force_send=True)
    finally:
        cleanup_database()

if __name__ == "__main__":
    main()