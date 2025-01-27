## 실행 전 거래 비율 확인하기


##1파트 - 기본 설정 및 라이브러리 임포트

import os
import logging
import time
import sqlite3
import yaml
import schedule
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
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
        logging.FileHandler('trading_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 트레이딩 제약 조건 설정 
TRADING_CONFIG = {
    'CONSECUTIVE_LOSS_LIMIT': 3,     # 연속 손실 허용 횟수
    'RSI_LOWER_BOUND': 28,          # RSI 하한선
    'RSI_UPPER_BOUND': 68,          # RSI 상한선 68
    'STOCH_RSI_LOWER': 20,          # Stochastic RSI 하한선
    'STOCH_RSI_UPPER': 80,          # Stochastic RSI 상한선
    'VO_THRESHOLD': 5.0,            # Volume Oscillator 임계값
    'COOLDOWN_MINUTES': 30,         # 거래 재개 전 대기 시간
    'MARKET_STABILITY_WINDOW': 12,   # 시장 안정성 확인 기간
    'MIN_PROFIT_RATE': 2.0,         # 최소 수익률 기준
    'MIN_SUCCESS_RATE': 60.0,        # 최소 성공률 기준
    'MAX_TRADE_PERCENTAGE': 30.0,    # 최대 거래 비중 30.0
    'TRADE_WEIGHT_LEVELS': {
    'low': 0.010,     # 10% 비중
    'medium': 0.020,  # 20% 비중
    'high': 0.030    }  # 30% 비중
}
2
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
        print(message)  # 디스코드 메시지 콘솔 출력
    except Exception as e:
        logger.error(f"Discord 메시지 전송 실패: {e}")

# API 키 검증
access = os.getenv("UPBIT_ACCESS_KEY")
secret = os.getenv("UPBIT_SECRET_KEY")

if not all([access, secret, DISCORD_WEBHOOK_URL]):
    logger.error("필수 설정값이 누락되었습니다.")
    raise ValueError("모든 필수 설정값을 .env와 config.yaml 파일에 입력해주세요.")

# Upbit 클라이언트 초기화
upbit = pyupbit.Upbit(access, secret)



##2파트 - 데이터베이스 관련 함수

def init_database():
    """데이터베이스 초기화 함수"""
    
    
    try:
        conn = sqlite3.connect('bitcoin_trades.db')
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
                stoch_rsi REAL,
                rsi_value REAL,
                macd REAL,
                volume_osc REAL
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
                trade_status, stoch_rsi, rsi_value, macd, volume_osc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            trade_data.get('stoch_rsi', 0),
            trade_data.get('rsi_value', 0),
            trade_data.get('macd', 0),
            trade_data.get('volume_osc', 0)
        ))
        conn.commit()
        logger.info(f"거래 기록 완료: {trade_data['decision']} at {trade_data['current_price']:,}원")
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
    


##3파트 - 시장 데이터 수집 및 분석 함수

def collect_market_data():
    """시장 데이터 수집 및 기술적 지표 계산"""
    try:
        # 1분봉 데이터 수집
        #df = pyupbit.get_ohlcv("KRW-BTC", interval="minute1", count=50400) #200
        df = pyupbit.get_ohlcv("KRW-BTC", interval="minute5", count=10080)  # 5분봉 35일치
        
        # 지표별 필요 데이터 포인트
        # RSI = 14일 = 14 * 24 * 60 = 20,160분
        # MACD = (26 + 9)일 = 35 * 24 * 60 = 50,400분
        # Stochastic RSI = 28일 = 28 * 24 * 60 = 40,320분
        # 볼린저밴드 = 20일 = 20 * 24 * 60 = 28,800분

        # # 수정 제안
        # df = pyupbit.get_ohlcv("KRW-BTC", interval="minute1", count=50400)

        if df is None:
            logger.error("OHLCV 데이터 수집 실패")
            return None
            
        # 기술적 지표 계산
        df = calculate_indicators(df)
        
        # 현재가 조회
        current_price = float(df['close'].iloc[-1])
        
        market_data = {
            'current_price': current_price,
            'stoch_rsi': float(df['stoch_rsi_k'].iloc[-1]),
            'rsi': float(df['rsi'].iloc[-1]),
            'macd': float(df['macd'].iloc[-1]),
            'macd_signal': float(df['macd_signal'].iloc[-1]),
            'volume_osc': float(df['volume_osc'].iloc[-1]),
            'df': df
        }
        
        # 지표 값 출력
        print(f"\n현재 기술적 지표:")  # 필요시 주석 처리 가능
        print(f"Stochastic RSI: {market_data['stoch_rsi']:.2f}")  # 필요시 주석 처리 가능
        print(f"RSI: {market_data['rsi']:.2f}")  # 필요시 주석 처리 가능
        print(f"MACD: {market_data['macd']:.2f}")  # 필요시 주석 처리 가능
        print(f"MACD Signal: {market_data['macd_signal']:.2f}")  # 필요시 주석 처리 가능
        print(f"Volume Oscillator: {market_data['volume_osc']:.2f}\n")  # 필요시 주석 처리 가능
        
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
        #df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
        df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14*288).rsi()

        # Stochastic RSI
        stoch_rsi = ta.momentum.StochRSIIndicator(
        close=df['close'],
        window=14*288,
        smooth1=3,
        smooth2=3
        )
        # stoch_rsi = ta.momentum.StochRSIIndicator(
        #     close=df['close'],
        #     window=14,
        #     smooth1=3,
        #     smooth2=3
        # )

        df['stoch_rsi_k'] = stoch_rsi.stochrsi_k()
        df['stoch_rsi_d'] = stoch_rsi.stochrsi_d()
        
        # MACD
        # macd = ta.trend.MACD(close=df['close'])
        macd = ta.trend.MACD(
        close=df['close'], 
        window_slow=26*288,
        window_fast=12*288,
        window_sign=9*288
        )
        
        
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        df['macd_diff'] = macd.macd_diff()
        
        # Volume Oscillator
        df['volume_sma_short'] = df['volume'].rolling(window=5).mean()
        df['volume_sma_long'] = df['volume'].rolling(window=10).mean()
        df['volume_osc'] = ((df['volume_sma_short'] - df['volume_sma_long']) / df['volume_sma_long']) * 100
        
        return df
        
    except Exception as e:
        logger.error(f"기술적 지표 계산 중 오류: {e}")
        return None
    

##4파트 - 거래 실행 함수들


def evaluate_trade_possibility(market_data):
   try:
       stoch_rsi = market_data['stoch_rsi']
       rsi = market_data['rsi']
       macd = market_data['macd']
       macd_signal = market_data['macd_signal']
       volume_osc = market_data['volume_osc']
       
       # 신호 강도 계산
       signal_strength = 'low'
       if abs(macd) > abs(macd_signal) * 1.5 and abs(volume_osc) > 15:
           signal_strength = 'high'
       elif abs(macd) > abs(macd_signal) * 1.2 and abs(volume_osc) > 10:
           signal_strength = 'medium'
           
       # 거래 비중 결정
       trade_weight = TRADING_CONFIG['TRADE_WEIGHT_LEVELS'][signal_strength]
       
       # 매수/매도 조건
       buy_condition = (
           (stoch_rsi < TRADING_CONFIG['STOCH_RSI_LOWER'] or    
           rsi < TRADING_CONFIG['RSI_LOWER_BOUND']) and
           macd > macd_signal 
           # and volume_osc > TRADING_CONFIG['VO_THRESHOLD']  # 임계값 상향 조정
           # volume_osc > 5.0
       )
       
       sell_condition = (
           (stoch_rsi > TRADING_CONFIG['STOCH_RSI_UPPER'] or    
           rsi > TRADING_CONFIG['RSI_UPPER_BOUND']) and
           macd < macd_signal 
           # and volume_osc > TRADING_CONFIG['VO_THRESHOLD']  # 임계값 상향 조정
           # and volume_osc > 5.0
       )
       
       # 거래 신호 결정
       signal = 'hold'
       if buy_condition:
           signal = 'buy'
       elif sell_condition:
           signal = 'sell'
           
       reason = (
           f"Stoch RSI: {stoch_rsi:.2f}, RSI: {rsi:.2f}, "
           f"MACD: {macd:.2f}, Signal: {macd_signal:.2f}, "
           f"Volume OSC: {volume_osc:.2f}, "
           f"Signal Strength: {signal_strength} ({trade_weight*100}%)"
       )
       
       trade_details = {
           'signal': signal,
           'trade_weight': trade_weight,
           'signal_strength': signal_strength,
           'stoch_rsi': stoch_rsi,
           'rsi': rsi,
           'macd': macd,
           'volume_osc': volume_osc,
           'reason': reason
       }
       
       market_data.update({'reason': reason})
       return trade_details
       
   except Exception as e:
       logger.error(f"거래 가능성 평가 중 오류: {e}")
       return {'signal': 'hold', 'reason': '평가 오류', 'trade_weight': 0}
   

# def evaluate_trade_possibility(market_data):
    
    
#     try:
#         stoch_rsi = market_data['stoch_rsi']
#         rsi = market_data['rsi']
#         macd = market_data['macd']
#         macd_signal = market_data['macd_signal']
#         volume_osc = market_data['volume_osc']
        
        
#         # 신호 강도 계산
#         signal_strength = 'low'
#         if abs(macd) > abs(macd_signal) * 1.5 and abs(volume_osc) > 15:
#             signal_strength = 'high'
#         elif abs(macd) > abs(macd_signal) * 1.2 and abs(volume_osc) > 10:
#             signal_strength = 'medium'
            
#         # 거래 비중 결정
#         trade_weight = TRADING_CONFIG['TRADE_WEIGHT_LEVELS'][signal_strength]
        
#         # 매수/매도 조건 완화
#         buy_condition = (
#             (stoch_rsi < TRADING_CONFIG['STOCH_RSI_LOWER'] or    # AND를 OR로 변경
#             rsi < TRADING_CONFIG['RSI_LOWER_BOUND']) and
#             macd > macd_signal 
#             # and volume_osc > TRADING_CONFIG['VO_THRESHOLD']  # 임계값 상향 조정
#         )
        
#         sell_condition = (
#             (stoch_rsi > TRADING_CONFIG['STOCH_RSI_UPPER'] or    # AND를 OR로 변경
#             rsi > TRADING_CONFIG['RSI_UPPER_BOUND']) and
#             macd < macd_signal 
#             # and volume_osc > TRADING_CONFIG['VO_THRESHOLD']  # 임계값 상향 조정
#         )

        
#         # 매수/매도 조건 (거래가 너무 안됨)
#         # buy_condition = (
#         #     stoch_rsi < TRADING_CONFIG['STOCH_RSI_LOWER'] and    #
#         #     rsi < TRADING_CONFIG['RSI_LOWER_BOUND'] and
#         #     macd > macd_signal and
#         #     volume_osc > TRADING_CONFIG['VO_THRESHOLD']
#         # )
        
#         # sell_condition = (
#         #     stoch_rsi > TRADING_CONFIG['STOCH_RSI_UPPER'] and    #
#         #     rsi > TRADING_CONFIG['RSI_UPPER_BOUND'] and
#         #     macd < macd_signal and
#         #     volume_osc > TRADING_CONFIG['VO_THRESHOLD']
#         # )
        
#         # 거래 신호 결정
#         signal = 'hold'
#         if buy_condition:
#             signal = 'buy'
#         elif sell_condition:
#             signal = 'sell'
        
            
#         reason = (
#             f"Stoch RSI: {stoch_rsi:.2f}, RSI: {rsi:.2f}, "
#             f"MACD: {macd:.2f}, Signal: {macd_signal:.2f}, "
#             f"Volume OSC: {volume_osc:.2f}, "
#             f"Signal Strength: {signal_strength} ({trade_weight*100}%)"
#         )
        
#         return {
#             'signal': signal,
#             'trade_weight': trade_weight,
#             'signal_strength': signal_strength,
#             'stoch_rsi': stoch_rsi,
#             'rsi': rsi,
#             'macd': macd,
#             'volume_osc': volume_osc,
#             'reason': reason
#         }
        
#     except Exception as e:
#         logger.error(f"거래 가능성 평가 중 오류: {e}")
#         return {'signal': 'hold', 'reason': '평가 오류', 'trade_weight': 0}
    

def execute_buy(percentage, market_data):
    """매수 실행"""
    try:
        krw_balance = upbit.get_balance("KRW")
        if krw_balance is None or krw_balance < 5000:
            logger.warning(f"매수 가능 KRW 잔액 부족: {krw_balance:,.0f}원")
            return None
            
        buy_amount = krw_balance * (percentage / 100) * 0.9995
        if buy_amount < 5000:
            logger.warning(f"최소 주문금액(5,000원) 미달: {buy_amount:,.0f}원")
            return None
            
        order = upbit.buy_market_order("KRW-BTC", buy_amount)
        
        if order:
            time.sleep(1)
            btc_balance = upbit.get_balance("BTC")
            krw_balance = upbit.get_balance("KRW")
            current_price = market_data['current_price']
            
            trade_data = {
                'decision': 'buy',
                'percentage': percentage,
                'reason': market_data.get('reason', '기술적 지표 기반 매수 신호'),  # 기본값 설정

                #'reason': market_data.get('reason', '기술적 지표 기반 매수'),
                'btc_balance': btc_balance,
                'krw_balance': krw_balance,
                'entry_price': current_price,
                'current_price': current_price,
                'stop_loss_price': current_price * 0.98,  #손절 2%
                'take_profit_price': current_price * 1.025, #익절 #2.5%
                'trade_status': 'executed',
                'stoch_rsi': market_data['stoch_rsi'],
                'rsi_value': market_data['rsi'],
                'macd': market_data['macd'],
                'volume_osc': market_data['volume_osc']
            }
            
            send_discord_message(
                f"✅ 매수 체결 완료\n"
                f"• 주문금액: {buy_amount:,.0f}원\n"
                f"• 현재가: {current_price:,.0f}원\n"
                f"• 기술적 지표:\n{market_data['reason']}"
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
            
        order = upbit.sell_market_order("KRW-BTC", sell_amount)
        
        if order:
            time.sleep(1)
            new_btc_balance = upbit.get_balance("BTC")
            krw_balance = upbit.get_balance("KRW")
            
            trade_data = {
                'decision': 'sell',
                'percentage': percentage,
                'reason': market_data.get('reason', '기술적 지표 기반 매도'),
                'btc_balance': new_btc_balance,
                'krw_balance': krw_balance,
                'entry_price': current_price,
                'current_price': current_price,
                'trade_status': 'executed',
                'stoch_rsi': market_data['stoch_rsi'],
                'rsi_value': market_data['rsi'],
                'macd': market_data['macd'],
                'volume_osc': market_data['volume_osc']
            }
            
            send_discord_message(
                f"✅ 매도 체결 완료\n"
                f"• 매도수량: {sell_amount:.8f} BTC\n"
                f"• 현재가: {current_price:,.0f}원\n"
                f"• 기술적 지표:\n{market_data['reason']}"
            )
            
            return trade_data
        else:
            logger.error("매도 주문 실패")
            return None
    except Exception as e:
        logger.error(f"매도 실행 중 오류: {e}")
        send_discord_message(f"🚨 매도 실행 오류: {e}")
        return None

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

def calculate_profit_loss(entry_price, current_price, trade_type='buy'):
    """수익률 계산"""
    try:
        if trade_type == 'buy':
            return ((current_price - entry_price) / entry_price) * 100
        else:
            return ((entry_price - current_price) / entry_price) * 100
    except Exception as e:
        logger.error(f"수익률 계산 중 오류: {e}")
        return 0.0
    


    
##5파트 - 메인 실행 함수

def trading_bot():
    """메인 트레이딩 로직"""
    try:
        conn = init_database()
        if not conn:
            return
            
        try:
            # 시장 데이터 수집
            market_data = collect_market_data()
            if not market_data:
                send_discord_message("❌ 시장 데이터 수집 실패")
                return
                
            # 거래 가능성 평가
            trade_signal = evaluate_trade_possibility(market_data)
            
            if trade_signal['signal'] == 'hold':
            # 기술지표 데이터 가져오기
                rsi = trade_signal.get('rsi', 0)
                stoch_rsi = trade_signal.get('stoch_rsi', 0)
                macd = trade_signal.get('macd', 0)
                macd_signal = trade_signal.get('macd_signal', 0)
                volume_osc = trade_signal.get('volume_oscillator', 0)

                discord_msg = (
                    f"❌ 현재 거래 조건 미충족\n"
                    #f"🔍 **분석 지표**\n"
                    # f"• RSI: {rsi:.2f}\n"
                    # f"• Stoch RSI: {stoch_rsi:.2f}\n"
                    # f"• MACD: {macd:.2f}\n" 
                    # f"• MACD Signal: {macd_signal:.2f}\n"
                    # f"• Volume Oscillator: {volume_osc:.2f}\n\n"
                    f"📝 사유: {trade_signal['reason']}"
                )
   
                logger.info(f"💤 현재 거래 조건 미충족\n거래 신호: {trade_signal['reason']}")
                send_discord_message(discord_msg)
                return



            # if trade_signal['signal'] == 'hold':
            #     # 현재 상태 로깅
            #     logger.info(f"💤 현재 거래 조건 미충족\n거래 신호: {trade_signal['reason']}")
            #     send_discord_message("❌ 현재 거래 조건 미충족")
            #     return

            
            # 실제 거래 실행
            trade_result = execute_trade(
                trade_signal['signal'],
                TRADING_CONFIG['MAX_TRADE_PERCENTAGE'],
                market_data
            )
            
            # 거래 결과 처리 및 DB 업데이트
            if trade_result:
                log_trade(conn, trade_result)
                update_trading_state(conn, {
                    'is_active': True,
                    'last_trade_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'consecutive_losses': 0,
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


def main():
    """메인 실행 함수"""
    try:
        mode = os.getenv("TRADING_MODE", "1")
        interval = int(os.getenv("TRADING_INTERVAL", "30"))
                
        start_message = (
            "🚀 비트코인 트레이딩 봇 시작\n"
            f"• 실행 방식: {'정해진 시간' if mode == '1' else f'{interval}분 간격'}\n"
            f"• Stochastic RSI: {TRADING_CONFIG['STOCH_RSI_LOWER']} - {TRADING_CONFIG['STOCH_RSI_UPPER']}\n"
            f"• RSI: {TRADING_CONFIG['RSI_LOWER_BOUND']} - {TRADING_CONFIG['RSI_UPPER_BOUND']}\n"
            f"• Volume OSC: {TRADING_CONFIG['VO_THRESHOLD']}"
        )
        send_discord_message(start_message)
        
        if mode == "1":
            schedule.every().day.at("06:00").do(trading_bot)
            schedule.every().day.at("12:00").do(trading_bot)
            schedule.every().day.at("18:00").do(trading_bot)
            schedule.every().day.at("00:00").do(trading_bot)
            logger.info("정해진 시간 실행 모드 (06:00, 12:00, 18:00, 00:00)")
        else:
            schedule.every(interval).minutes.do(trading_bot)
            logger.info(f"{interval}분 간격 실행 모드")
        
        logger.info("트레이딩 스케줄 설정 완료")
        
        while True:
            try:
                schedule.run_pending()
                time.sleep(1)
            except KeyboardInterrupt:
                send_discord_message("🛑 트레이딩 봇 종료")
                break
            except Exception as e:
                logger.error(f"메인 루프 오류: {e}")
                send_discord_message(f"🚨 메인 루프 오류: {e}")
                time.sleep(60)
                
    except Exception as e:
        logger.error(f"프로그램 시작 중 오류: {e}")
        send_discord_message(f"🚨 프로그램 시작 오류: {e}")

if __name__ == "__main__":
    main()


