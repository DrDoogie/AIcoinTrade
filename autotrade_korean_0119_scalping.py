## RSI, STOCH_RSI에 의한 조건 추가

import os
import logging
import time
import sqlite3
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pandas as pd
import numpy as np
import pyupbit
import ta
from openai import OpenAI

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

# 트레이딩 설정
TRADING_CONFIG = {
    'MAX_TRADE_PERCENTAGE': 30.0,    # 최대 거래 비중
    'MIN_TRADE_PERCENTAGE': 5.0,     # 최소 거래 비중
    'RSI_OVERSOLD': 28,             # RSI 과매도
    'RSI_OVERBOUGHT': 68,           # RSI 과매수
    'STOCH_RSI_OVERSOLD': 20,       # Stochastic RSI 과매도
    'STOCH_RSI_OVERBOUGHT': 80,     # Stochastic RSI 과매수
    'TRADING_INTERVAL': 5,          # 거래 주기 (분)
    'TRADING_HOURS': {              # 거래 시간 설정
        'START': '00:00',           # 거래 시작 시간 09:00
        'END': '23:59'              # 거래 종료 시간 23:59
    },
    'TRADING_DAYS': [0,1,2,3,4,5,6] # 거래 요일 (0:월요일 ~ 6:일요일)
}

class FastTradingBot:
    def __init__(self):
        """초기화"""
        self.upbit = pyupbit.Upbit(os.getenv("UPBIT_ACCESS_KEY"), os.getenv("UPBIT_SECRET_KEY"))
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.conn = self.init_database()

    def init_database(self):
        """데이터베이스 초기화"""
        conn = sqlite3.connect('bitcoin_trades.db')
        cursor = conn.cursor() #추가
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                decision TEXT,
                percentage REAL,
                btc_balance REAL,      
                price REAL,
                reason TEXT,
                rsi REAL,
                stoch_rsi REAL,
                macd REAL,
                bb_width REAL,
                vr REAL,
                atr REAL
            )
        ''')
        conn.commit()
        return conn

    def calculate_indicators(self, df):
        """기술적 지표 계산"""
        try:
            # RSI
            df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
            
            # Stochastic RSI
            stoch_rsi = ta.momentum.StochRSIIndicator(close=df['close'])
            df['stoch_rsi_k'] = stoch_rsi.stochrsi_k()
            df['stoch_rsi_d'] = stoch_rsi.stochrsi_d()
            
            # MACD
            macd = ta.trend.MACD(close=df['close'])
            df['macd'] = macd.macd()
            df['macd_signal'] = macd.macd_signal()
            
            # Bollinger Bands
            bb = ta.volatility.BollingerBands(close=df['close'])
            df['bb_upper'] = bb.bollinger_hband()
            df['bb_lower'] = bb.bollinger_lband()
            df['bb_width'] = ((df['bb_upper'] - df['bb_lower']) / df['close']) * 100
            
            # VR (Volume Ratio)
            df['volume_ma'] = df['volume'].rolling(window=20).mean()
            df['vr'] = (df['volume'] / df['volume_ma']) * 100
            
            # ATR
            df['atr'] = ta.volatility.AverageTrueRange(
                high=df['high'], 
                low=df['low'], 
                close=df['close']
            ).average_true_range()
            
            # Moving Averages
            df['ma5'] = df['close'].rolling(window=5).mean()
            df['ma10'] = df['close'].rolling(window=10).mean()
            df['ma20'] = df['close'].rolling(window=20).mean()
            
            return df.fillna(0)
            
        except Exception as e:
            logger.error(f"지표 계산 중 오류: {e}")
            return None

    def get_market_data(self):
        """시장 데이터 수집 및 지표 계산"""
        try:
            # 1분봉 데이터 수집
            df = pyupbit.get_ohlcv("KRW-BTC", interval="minute1", count=100)
            if df is None or df.empty:
                raise ValueError("데이터 수집 실패")

            # 기술적 지표 계산
            df = self.calculate_indicators(df)
            
            # 현재 지표값
            current_indicators = {
                'current_price': float(df['close'].iloc[-1]),
                'rsi': float(df['rsi'].iloc[-1]),
                'stoch_rsi_k': float(df['stoch_rsi_k'].iloc[-1]),
                'macd': float(df['macd'].iloc[-1]),
                'bb_width': float(df['bb_width'].iloc[-1]),
                'vr': float(df['vr'].iloc[-1]),
                'atr': float(df['atr'].iloc[-1]),
                'ma5': float(df['ma5'].iloc[-1]),
                'ma10': float(df['ma10'].iloc[-1]),
                'ma20': float(df['ma20'].iloc[-1])
            }
            
            return current_indicators
            
        except Exception as e:
            logger.error(f"시장 데이터 수집 중 오류: {e}")
            return None

    def get_gpt_decision(self, market_data):
        """GPT에게 거래 결정 요청"""
        try:
            messages = [
                {
                    "role": "system",
                    "content": """비트코인 트레이딩 전문가로서 현재 시장 상황을 분석하고 
                    매수/매도/홀드 결정과 함께 거래 비중(0~30%)을 제안해주세요. 
                    반드시 아래 JSON 형식으로만 응답하세요:
                    {"decision": "buy/sell/hold", "percentage": 15, "reason": "결정 이유"}"""
                },
                {
                    "role": "user",
                    "content": f"""
                    현재 시장 상황:
                    - 현재가: {market_data['current_price']:,.0f}원
                    - RSI: {market_data['rsi']:.2f}
                    - Stochastic RSI: {market_data['stoch_rsi_k']:.2f}
                    - MACD: {market_data['macd']:.2f}
                    - BB Width: {market_data['bb_width']:.2f}%
                    - Volume Ratio: {market_data['vr']:.2f}
                    - ATR: {market_data['atr']:.2f}
                    - MA5: {market_data['ma5']:,.0f}
                    - MA10: {market_data['ma10']:,.0f}
                    - MA20: {market_data['ma20']:,.0f}
                    
                    위 데이터를 기반으로 매수/매도/홀드 결정과 
                    0~30% 사이의 적절한 거래 비중을 제안해주세요.
                    단 RSI는 68미만, 28이상일 경우는 홀드 결정을 
                    Stochastic RSI가 0.80이상, 0.20미만일 경우에도 홀드 결정을
                    해주세요. 
                    """
                }
            ]

            response = self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=messages,
                max_tokens=200,
                temperature=0.7
            )

            result = json.loads(response.choices[0].message.content.strip())
            
            # 거래 비중 범위 제한
            result['percentage'] = min(max(
                float(result.get('percentage', 10)), 
                TRADING_CONFIG['MIN_TRADE_PERCENTAGE']
            ), TRADING_CONFIG['MAX_TRADE_PERCENTAGE'])
            
            logger.info(f"GPT 결정: {result['decision'].upper()} {result['percentage']}%")
            return result
            
        except Exception as e:
            logger.error(f"GPT 결정 요청 중 오류: {e}")
            return None

    # def execute_trade(self, decision, market_data):
    #     """거래 실행"""
    #     try:
    #         if decision['decision'] == 'buy':
    #             return self.execute_buy(decision['percentage'], market_data, decision['reason'])
    #         elif decision['decision'] == 'sell':
    #             return self.execute_sell(decision['percentage'], market_data, decision['reason'])
    #         return None
            
    #     except Exception as e:
    #         logger.error(f"거래 실행 중 오류: {e}")
    #         return None

    def execute_buy(self, percentage, market_data, reason):
        """매수 실행"""
        try:
            krw_balance = self.upbit.get_balance("KRW")
            if krw_balance is None or krw_balance < 5000:
                logger.warning(f"매수 가능 KRW 잔액 부족: {krw_balance:,.0f}원")
                return None
                
            buy_amount = krw_balance * (percentage / 100) * 0.9995
            if buy_amount < 5000:
                logger.warning(f"최소 주문금액(5,000원) 미달: {buy_amount:,.0f}원")
                return None
                
            order = self.upbit.buy_market_order("KRW-BTC", buy_amount)
            
            if order:
                self.log_trade('buy', percentage, market_data, reason)
                logger.info(f"매수 주문 체결: {buy_amount:,.0f}원")
                return True
                
            return None
            
        except Exception as e:
            logger.error(f"매수 실행 중 오류: {e}")
            return None

    def execute_sell(self, percentage, market_data, reason):
        """매도 실행"""
        try:
            btc_balance = self.upbit.get_balance("BTC")
            if btc_balance is None or btc_balance == 0:
                logger.warning("매도 가능한 BTC 잔액 없음")
                return None
                
            sell_amount = btc_balance * (percentage / 100)
            current_price = market_data['current_price']
            
            if sell_amount * current_price < 5000:
                logger.warning(f"최소 주문금액 미달: {sell_amount * current_price:,.0f}원")
                return None
                
            order = self.upbit.sell_market_order("KRW-BTC", sell_amount)
            
            if order:
                self.log_trade('sell', percentage, market_data, reason)
                logger.info(f"매도 주문 체결: {sell_amount:.8f} BTC")
                return True
                
            return None
            
        except Exception as e:
            logger.error(f"매도 실행 중 오류: {e}")
            return None

    def log_trade(self, decision, percentage, market_data, reason):
        """거래 기록"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO trades (
                    timestamp, decision, percentage, price, reason,
                    rsi, stoch_rsi, macd, bb_width, vr, atr
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                decision,
                percentage,
                market_data['current_price'],
                reason,
                market_data['rsi'],
                market_data['stoch_rsi_k'],
                market_data['macd'],
                market_data['bb_width'],
                market_data['vr'],
                market_data['atr']
            ))
            self.conn.commit()
            
        except Exception as e:
            logger.error(f"거래 기록 중 오류: {e}")

def is_trading_time():
    """현재 거래 가능 시간인지 확인"""
    now = datetime.now()
    
    # 요일 확인
    if now.weekday() not in TRADING_CONFIG['TRADING_DAYS']:
        return False
    
    # 시간 확인
    current_time = now.strftime('%H:%M')
    start_time = TRADING_CONFIG['TRADING_HOURS']['START']
    end_time = TRADING_CONFIG['TRADING_HOURS']['END']
    
    return start_time <= current_time <= end_time

def main():
    """메인 실행 함수"""
    bot = FastTradingBot()
    logger.info(f"Fast Trading Bot 시작 (거래 주기: {TRADING_CONFIG['TRADING_INTERVAL']}분)")
    
    last_trade_time = datetime.min
    
    try:
        while True:
            try:
                now = datetime.now()
                
                # 거래 가능 시간 확인
                if not is_trading_time():
                    time.sleep(60)  # 1분 대기
                    continue
                
                # 거래 주기 확인
                time_since_last_trade = (now - last_trade_time).total_seconds() / 60
                if time_since_last_trade < TRADING_CONFIG['TRADING_INTERVAL']:
                    time.sleep(10)  # 10초 대기
                    continue
                
                # 시장 데이터 수집
                market_data = bot.get_market_data()
                if not market_data:
                    logger.error("시장 데이터 수집 실패")
                    time.sleep(10)
                    continue

                # GPT 결정 요청
                decision = bot.get_gpt_decision(market_data)
                if not decision:
                    logger.error("GPT 결정 실패")
                    time.sleep(10)
                    continue

                # 거래 실행
                if decision['decision'] != 'hold':
                    if bot.execute_trade(decision, market_data):
                        last_trade_time = now
                        logger.info(f"다음 거래 가능 시간: {(last_trade_time + timedelta(minutes=TRADING_CONFIG['TRADING_INTERVAL'])).strftime('%H:%M:%S')}")

                # 10초 대기
                time.sleep(10)
                
            except Exception as e:
                logger.error(f"거래 사이클 중 오류: {e}")
                time.sleep(60)
                
    except KeyboardInterrupt:
        logger.info("프로그램 종료")
    finally:
        bot.conn.close()

if __name__ == "__main__":
    main()