import os
import logging
import time
import sqlite3
import json
import yaml
import schedule
import requests
import pandas as pd
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

# 데이터클래스 정의
class ScalpingDecision:
    def __init__(self, decision, percentage, reason, stop_loss_rate, take_profit_rate):
        self.decision = decision
        self.percentage = percentage
        self.reason = reason
        self.stop_loss_rate = stop_loss_rate
        self.take_profit_rate = take_profit_rate

# 데이터베이스 초기화 함수
def init_database():
    try:
        conn = sqlite3.connect('scalping_trades.db')
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
                take_profit_price REAL
            )
        ''')
        conn.commit()
        return conn
    except Exception as e:
        logger.error(f"데이터베이스 초기화 오류: {e}")
        send_discord_message(f"🚨 데이터베이스 초기화 실패: {e}")
        return None

# 기술적 지표 계산 함수
def calculate_technical_indicators(df):
    try:
        if df is None or df.empty:
            return None

        # 볼린저 밴드
        bollinger = ta.volatility.BollingerBands(close=df['close'], window=20)
        df['bb_upper'] = bollinger.bollinger_hband()
        df['bb_lower'] = bollinger.bollinger_lband()

        # RSI
        df['rsi'] = ta.momentum.RSIIndicator(close=df['close']).rsi()

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
            "current_price": df_1m['close'].iloc[-1]
        }

        return market_data
    except Exception as e:
        logger.error(f"시장 데이터 수집 중 오류: {e}")
        return None

# AI 트레이딩 의사결정 함수

#수정
def ai_trading_decision(market_data):
    try:
        market_summary = {
            "current_price": float(market_data['current_price']),
            "rsi": float(market_data['1m_data']['rsi'].iloc[-1]),
            "macd": float(market_data['1m_data']['macd'].iloc[-1]),
            "bb_lower": float(market_data['1m_data']['bb_lower'].iloc[-1]),
            "bb_upper": float(market_data['1m_data']['bb_upper'].iloc[-1]),
            "ema_short": float(market_data['1m_data']['ema_short'].iloc[-1]),
            "ema_long": float(market_data['1m_data']['ema_long'].iloc[-1])
        }

        messages = [
            {
                "role": "system",
                "content": """비트코인 스캘핑 트레이딩 전문가로서 시장 데이터를 분석하고 
                정확한 거래 결정을 내려주세요. 반드시 JSON 형식으로 응답해주세요:
                {
                    "decision": "buy" 또는 "sell" 또는 "hold",
                    "percentage": 0-5 사이의 숫자,
                    "reason": "결정 이유"
                }"""
            },
            {
                "role": "user",
                "content": f"현재 시장 데이터: {json.dumps(market_summary)}"
            }
        ]

        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            max_tokens=300,
            temperature=0.7
        )

        result_text = response.choices[0].message.content.strip()
        
        # 로그에 전체 응답 출력
        logger.info(f"OpenAI 전체 응답: {result_text}")
        
        # JSON 파싱 시도
        try:
            result = json.loads(result_text)
        except json.JSONDecodeError:
            logger.error(f"JSON 파싱 실패: {result_text}")
            return ScalpingDecision(
                decision="hold",
                percentage=0,
                reason="JSON 파싱 실패",
                stop_loss_rate=0.3,
                take_profit_rate=0.5
            )

        return ScalpingDecision(
            decision=result.get('decision', 'hold'),
            percentage=min(result.get('percentage', 0), 5),
            reason=result.get('reason', ''),
            stop_loss_rate=0.3,
            take_profit_rate=0.5
        )
    except Exception as e:
        logger.error(f"AI 트레이딩 의사결정 오류: {e}")
        return None
    


# 거래 실행 함수
def execute_trade(decision):
    try:
        current_price = pyupbit.get_current_price("KRW-BTC")
        my_btc = upbit.get_balance("KRW-BTC")
        my_krw = upbit.get_balance("KRW")

        trade_details = {
            'decision': decision.decision,
            'percentage': decision.percentage,
            'reason': decision.reason,
            'entry_price': current_price,
            'btc_balance': my_btc,
            'krw_balance': my_krw,
            'stop_loss_price': current_price * (1 - decision.stop_loss_rate),
            'take_profit_price': current_price * (1 + decision.take_profit_rate)
        }

        if decision.decision == "buy" and my_krw > 5000:
            buy_amount = my_krw * (decision.percentage / 100) * 0.9995
            order = upbit.buy_market_order("KRW-BTC", buy_amount)
            
            if order:
                send_discord_message(f"✅ 매수: {buy_amount:,.0f} KRW")
                return trade_details
        
        elif decision.decision == "sell" and my_btc > 0:
            sell_amount = my_btc * (decision.percentage / 100)
            order = upbit.sell_market_order("KRW-BTC", sell_amount)
            
            if order:
                send_discord_message(f"✅ 매도: {sell_amount:,.4f} BTC")
                return trade_details
        
        return None
    except Exception as e:
        logger.error(f"거래 실행 오류: {e}")
        return None

# 거래 로깅 함수
def log_trade(conn, trade_details):
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO trades 
            (timestamp, decision, percentage, reason, 
            btc_balance, krw_balance, entry_price, 
            stop_loss_price, take_profit_price) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            trade_details['decision'],
            trade_details['percentage'],
            trade_details['reason'],
            trade_details['btc_balance'],
            trade_details['krw_balance'],
            trade_details['entry_price'],
            trade_details['stop_loss_price'],
            trade_details['take_profit_price']
        ))
        conn.commit()
    except Exception as e:
        logger.error(f"거래 로깅 오류: {e}")

# 메인 트레이딩 봇 함수

def trading_bot():
    try:
        logger.info("트레이딩 봇 실행 시작")
        
        # 데이터베이스 연결
        conn = init_database()
        if not conn:
            logger.error("데이터베이스 연결 실패")
            return

        # 시장 데이터 수집
        market_data = collect_market_data()
        if not market_data:
            logger.error("시장 데이터 수집 실패")
            send_discord_message("❌ 시장 데이터 수집 실패")
            return

        logger.info("시장 데이터 수집 완료")

        # AI 트레이딩 의사결정
        decision = ai_trading_decision(market_data)
        if not decision:
            logger.error("트레이딩 의사결정 실패")
            send_discord_message("❌ 트레이딩 의사결정 실패")
            return

        logger.info(f"트레이딩 의사결정: {decision.decision}")

        # 거래 실행
        trade_details = execute_trade(decision)
        if trade_details:
            log_trade(conn, trade_details)
            send_discord_message(f"📊 트레이딩 결정: {decision.decision}")

        conn.close()
        logger.info("트레이딩 봇 실행 완료")
    except Exception as e:
        logger.error(f"트레이딩 봇 실행 오류: {e}")
        send_discord_message(f"🚨 트레이딩 봇 오류: {e}")


# 메인 실행 로직
def main():
    send_discord_message("🚀 비트코인 스캘핑 트레이딩 봇 시작")
    
    # 5분마다 트레이딩 봇 실행
    schedule.every(1).minutes.do(trading_bot)
    
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


## 비율이 너무 작나? 
