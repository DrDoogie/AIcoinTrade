import os
from dotenv import load_dotenv
import pyupbit
import pandas as pd
import json
from openai import OpenAI
import ta
from ta.utils import dropna
import time
import requests
import base64
from PIL import Image
import io
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, WebDriverException, NoSuchElementException
import logging
from youtube_transcript_api import YouTubeTranscriptApi
from pydantic import BaseModel
import sqlite3
from datetime import datetime, timedelta
import schedule

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

# Upbit 객체 생성
access = os.getenv("UPBIT_ACCESS_KEY")
secret = os.getenv("UPBIT_SECRET_KEY")
if not access or not secret:
    logger.error("API 키를 찾을 수 없습니다. .env 파일을 확인하세요.")
    raise ValueError("API 키가 없습니다. .env 파일을 확인하세요.")
upbit = pyupbit.Upbit(access, secret)

# Pydantic 모델
class TradingDecision(BaseModel):
    decision: str
    percentage: int
    reason: str

# 데이터베이스 함수들
def init_db():
    conn = sqlite3.connect('bitcoin_trades.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS trades
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp TEXT,
                  decision TEXT,
                  percentage INTEGER,
                  reason TEXT,
                  btc_balance REAL,
                  krw_balance REAL,
                  btc_avg_buy_price REAL,
                  btc_krw_price REAL,
                  reflection TEXT)''')
    conn.commit()
    return conn

def log_trade(conn, decision, percentage, reason, btc_balance, krw_balance, btc_avg_buy_price, btc_krw_price, reflection=''):
    c = conn.cursor()
    timestamp = datetime.now().isoformat()
    c.execute("""INSERT INTO trades 
                 (timestamp, decision, percentage, reason, btc_balance, krw_balance, btc_avg_buy_price, btc_krw_price, reflection) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (timestamp, decision, percentage, reason, btc_balance, krw_balance, btc_avg_buy_price, btc_krw_price, reflection))
    conn.commit()

def get_recent_trades(conn, days=7):
    c = conn.cursor()
    seven_days_ago = (datetime.now() - timedelta(days=days)).isoformat()
    c.execute("SELECT * FROM trades WHERE timestamp > ? ORDER BY timestamp DESC", (seven_days_ago,))
    columns = [column[0] for column in c.description]
    return pd.DataFrame.from_records(data=c.fetchall(), columns=columns)

def calculate_performance(trades_df):
    if trades_df.empty:
        return 0
    initial_balance = trades_df.iloc[-1]['krw_balance'] + trades_df.iloc[-1]['btc_balance'] * trades_df.iloc[-1]['btc_krw_price']
    final_balance = trades_df.iloc[0]['krw_balance'] + trades_df.iloc[0]['btc_balance'] * trades_df.iloc[0]['btc_krw_price']
    return (final_balance - initial_balance) / initial_balance * 100


# 최적화된 Reflection 생성 함수

#에러 수정 

def generate_reflection(trades_df, current_market_data):
    performance = calculate_performance(trades_df)
    
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    if not client.api_key:
        logger.error("OpenAI API 키가 없거나 유효하지 않습니다.")
        return None
    
    try:
        # 데이터 전처리로 토큰 수 감소
        recent_trades = trades_df.tail(5).to_dict(orient='records')  # 최근 5개 거래만
        
        # current_market_data에서 필요한 데이터 추출
        market_summary = {
            "fear_greed": current_market_data.get("fear_greed", {}).get("value", "N/A"),
            "latest_price": current_market_data.get("daily_data", {})["close"].iloc[-1] if not current_market_data.get("daily_data", {}).empty else "N/A",
            "daily_change": ((current_market_data.get("daily_data", {})["close"].iloc[-1] - 
                            current_market_data.get("daily_data", {})["close"].iloc[-2]) / 
                           current_market_data.get("daily_data", {})["close"].iloc[-2] * 100) if not current_market_data.get("daily_data", {}).empty else "N/A"
        }

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",  # 비용 절감을 위해 GPT-3.5 사용
            messages=[
                {
                    "role": "system",
                    "content": """비트코인 트레이딩 전문가로서 최근 거래와 시장 상황을 간단히 분석하여 
                    핵심적인 인사이트만 제공해주세요. 반드시 한국어로 응답하세요."""
                },
                {
                    "role": "user",
                    "content": f"""
                    최근 거래 요약:
                    {json.dumps(recent_trades, ensure_ascii=False)}
                    
                    시장 현황:
                    {json.dumps(market_summary, ensure_ascii=False)}
                    
                    7일 수익률: {performance:.2f}%
                    
                    다음을 간단히 분석해주세요:
                    1. 최근 거래 평가
                    2. 개선점
                    3. 향후 제안
                    
                    150단어 이내로 작성해주세요.
                    """
                }
            ],
            max_tokens=500,
            temperature=0.7
        )

        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"반성 내용 생성 중 오류 발생: {e}")
        return None

def ai_trading():
    """메인 트레이딩 로직"""
    try:
        # 시장 데이터 수집
        market_data = get_market_data()
        if not market_data:
            logger.error("시장 데이터 수집 실패")
            return

        # 차트 이미지 캡처 (선택적)
        chart_image = None
        if os.getenv("CAPTURE_CHART", "false").lower() == "true":
            try:
                driver = create_driver()
                driver.get("https://upbit.com/full_chart?code=CRIX.UPBIT.KRW-BTC")
                time.sleep(20)  # 로딩 대기 시간 최적화
                perform_chart_actions(driver)
                chart_image = capture_and_encode_screenshot(driver)
            except Exception as e:
                logger.error(f"차트 캡처 실패: {e}")
            finally:
                if driver:
                    driver.quit()

        # 데이터베이스 연결
        with sqlite3.connect('bitcoin_trades.db') as conn:
            # 최근 거래 내역 조회
            recent_trades = get_recent_trades(conn)
            
            # AI 트레이딩 결정 요청
            decision = get_trading_decision(market_data, recent_trades, chart_image)
            if not decision:
                logger.error("트레이딩 결정 생성 실패")
                return

            logger.info(f"AI 결정: {decision.decision.upper()}")
            logger.info(f"결정 이유: {decision.reason}")

            # 거래 실행
            order_executed = execute_trade(decision.decision, decision.percentage, decision.reason)
            
            # 거래 후 잔고 조회 및 기록
            time.sleep(1)  # API 호출 제한 고려
            try:
                balances = upbit.get_balances()
                btc_balance = next((float(balance['balance']) for balance in balances if balance['currency'] == 'BTC'), 0)
                krw_balance = next((float(balance['balance']) for balance in balances if balance['currency'] == 'KRW'), 0)
                btc_avg_buy_price = next((float(balance['avg_buy_price']) for balance in balances if balance['currency'] == 'BTC'), 0)
                current_btc_price = pyupbit.get_current_price("KRW-BTC")

                # Reflection 생성 및 거래 기록
                reflection = generate_reflection(recent_trades, market_data)  # market_data 전달
                log_trade(
                    conn, 
                    decision.decision,
                    decision.percentage if order_executed else 0,
                    decision.reason,
                    btc_balance,
                    krw_balance,
                    btc_avg_buy_price,
                    current_btc_price,
                    reflection
                )
                
                # 성과 분석 로깅
                performance = calculate_performance(get_recent_trades(conn))
                logger.info(f"현재 BTC 잔액: {btc_balance:.8f} BTC")
                logger.info(f"현재 KRW 잔액: {krw_balance:,.0f} KRW")
                logger.info(f"7일 수익률: {performance:.2f}%")

            except Exception as e:
                logger.error(f"거래 기록 중 오류 발생: {e}")

    except Exception as e:
        logger.error(f"트레이딩 실행 중 오류 발생: {e}")


    # 기술적 지표 추가 함수
def add_indicators(df):
    try:
        # 필수 지표만 계산하여 토큰 사용량 최적화
        # 볼린저 밴드
        indicator_bb = ta.volatility.BollingerBands(close=df['close'], window=20, window_dev=2)
        df['bb_upper'] = indicator_bb.bollinger_hband()
        df['bb_lower'] = indicator_bb.bollinger_lband()
        
        # RSI
        df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
        
        # MACD (중요 지표이므로 유지)
        macd = ta.trend.MACD(close=df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        
        return df
    except Exception as e:
        logger.error(f"지표 계산 중 오류 발생: {e}")
        return df


# 에러 발생시 오류 수정 
# 시장 데이터 수집 함수
def get_market_data():
    """시장 데이터 수집 함수"""
    try:
        # 차트 데이터
        df_daily = pyupbit.get_ohlcv("KRW-BTC", interval="day", count=30)
        df_hourly = pyupbit.get_ohlcv("KRW-BTC", interval="minute60", count=24)
        
        if df_daily is None or df_hourly is None:
            logger.error("OHLCV 데이터 조회 실패")
            return None
            
        if df_daily.empty or df_hourly.empty:
            logger.error("OHLCV 데이터가 비어있음")
            return None

        # 기술적 지표 추가
        df_daily = dropna(df_daily)
        df_daily = add_indicators(df_daily)
        
        df_hourly = dropna(df_hourly)
        df_hourly = add_indicators(df_hourly)
        
        # 호가 데이터
        try:
            orderbook = pyupbit.get_orderbook("KRW-BTC")
            if not orderbook:
                logger.warning("호가 데이터 조회 실패")
                orderbook = []
        except Exception as e:
            logger.warning(f"호가 데이터 조회 오류: {e}")
            orderbook = []
        
        # 공포/탐욕 지수
        fear_greed = {"value": 50, "status": "Neutral"}  # 기본값
        try:
            fng_response = requests.get("https://api.alternative.me/fng/", timeout=5)
            if fng_response.status_code == 200:
                fear_greed = fng_response.json()['data'][0]
        except Exception as e:
            logger.warning(f"공포/탐욕 지수 조회 실패: {e}")
        
        market_data = {
            "daily_data": df_daily,
            "hourly_data": df_hourly,
            "orderbook": orderbook,
            "fear_greed": fear_greed,
            "current_price": float(df_daily['close'].iloc[-1]) if not df_daily.empty else None,
            "price_change_24h": float(((df_daily['close'].iloc[-1] - df_daily['close'].iloc[-2]) / df_daily['close'].iloc[-2]) * 100) if not df_daily.empty and len(df_daily) > 1 else None
        }

        logger.info("시장 데이터 수집 완료")
        return market_data

    except Exception as e:
        logger.error(f"시장 데이터 수집 중 오류 발생: {e}")
        return None
    
def add_indicators(df):
    """기술적 지표 추가 함수"""
    try:
        if df is None or df.empty:
            return df
            
        # 볼린저 밴드
        indicator_bb = ta.volatility.BollingerBands(close=df['close'], window=20, window_dev=2)
        df['bb_upper'] = indicator_bb.bollinger_hband()
        df['bb_lower'] = indicator_bb.bollinger_lband()
        
        # RSI
        df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
        
        # MACD
        macd = ta.trend.MACD(close=df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        
        return df
    except Exception as e:
        logger.error(f"지표 계산 중 오류 발생: {e}")
        return df

# generate_reflection 함수도 수정
def generate_reflection(trades_df, current_market_data):
    performance = calculate_performance(trades_df)
    
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    if not client.api_key:
        logger.error("OpenAI API 키가 없거나 유효하지 않습니다.")
        return None
    
    try:
        # 데이터 전처리로 토큰 수 감소
        recent_trades = trades_df.tail(5).to_dict(orient='records')  # 최근 5개 거래만
        
        # 안전한 데이터 추출
        market_summary = {
            "fear_greed": current_market_data.get("fear_greed", {}).get("value", "N/A"),
            "current_price": current_market_data.get("current_price", "N/A"),
            "price_change_24h": current_market_data.get("price_change_24h", "N/A")
        }

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": """비트코인 트레이딩 전문가로서 최근 거래와 시장 상황을 간단히 분석하여 
                    핵심적인 인사이트만 제공해주세요. 반드시 한국어로 응답하세요."""
                },
                {
                    "role": "user",
                    "content": f"""
                    최근 거래 요약:
                    {json.dumps(recent_trades, ensure_ascii=False)}
                    
                    시장 현황:
                    {json.dumps(market_summary, ensure_ascii=False)}
                    
                    7일 수익률: {performance:.2f}%
                    
                    다음을 간단히 분석해주세요:
                    1. 최근 거래 평가
                    2. 개선점
                    3. 향후 제안
                    
                    150단어 이내로 작성해주세요.
                    """
                }
            ],
            max_tokens=500,
            temperature=0.7
        )

        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"반성 내용 생성 중 오류 발생: {e}")
        return None    

def execute_trade(decision, percentage, reason):
    """거래 실행 함수"""
    try:
        order_executed = False
        
        if decision == "buy":
            my_krw = upbit.get_balance("KRW")
            if my_krw is None:
                logger.error("KRW 잔고 조회 실패")
                return False
                
            buy_amount = my_krw * (percentage / 100) * 0.9995  # 수수료 고려
            if buy_amount > 5000:
                logger.info(f"매수 주문 실행: 보유 KRW의 {percentage}%")
                order = upbit.buy_market_order("KRW-BTC", buy_amount)
                if order:
                    logger.info(f"매수 주문 성공: {order}")
                    order_executed = True
                else:
                    logger.error("매수 주문 실패")
            else:
                logger.warning("매수 실패: 최소 주문금액(5000 KRW) 미달")
                
        elif decision == "sell":
            my_btc = upbit.get_balance("KRW-BTC")
            if my_btc is None:
                logger.error("BTC 잔고 조회 실패")
                return False
                
            sell_amount = my_btc * (percentage / 100)
            current_price = pyupbit.get_current_price("KRW-BTC")
            if sell_amount * current_price > 5000:
                logger.info(f"매도 주문 실행: 보유 BTC의 {percentage}%")
                order = upbit.sell_market_order("KRW-BTC", sell_amount)
                if order:
                    logger.info(f"매도 주문 성공: {order}")
                    order_executed = True
                else:
                    logger.error("매도 주문 실패")
            else:
                logger.warning("매도 실패: 최소 주문금액(5000 KRW) 미달")
        
        elif decision == "hold":
            logger.info("홀드 결정: 포지션 유지")
            return True
            
        return order_executed
        
    except Exception as e:
        logger.error(f"주문 실행 중 오류 발생: {e}")
        return False

#에러 수정

def get_trading_decision(market_data, trade_history, chart_image=None):
    """AI 트레이딩 결정 생성 함수"""
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        # 전략 파일 읽기
        with open("strategy.txt", "r", encoding="utf-8") as f:
            strategy = f.read()
        
        # 중요 데이터만 선택하여 전송
        market_summary = {
            "current_price": float(market_data["daily_data"]["close"].iloc[-1]),
            "daily_change": float((market_data["daily_data"]["close"].iloc[-1] - market_data["daily_data"]["close"].iloc[-2]) / market_data["daily_data"]["close"].iloc[-2] * 100),
            "rsi": float(market_data["daily_data"]["rsi"].iloc[-1]),
            "macd": float(market_data["daily_data"]["macd"].iloc[-1]),
            "bb_position": float((market_data["daily_data"]["close"].iloc[-1] - market_data["daily_data"]["bb_lower"].iloc[-1]) / (market_data["daily_data"]["bb_upper"].iloc[-1] - market_data["daily_data"]["bb_lower"].iloc[-1])),
            "fear_greed": market_data["fear_greed"]["value"]
        }
        
        messages = [
            {
                "role": "system",
                "content": """당신은 비트코인 트레이딩 전문가입니다. 제공된 데이터를 분석하고 
                매수/매도/홀드 결정을 내려주세요. 반드시 아래 JSON 형식으로만 응답해주세요:
                
                {
                    "decision": "buy" 또는 "sell" 또는 "hold",
                    "percentage": 0-100 사이의 정수,
                    "reason": "결정 이유를 한글로 설명"
                }
                
                decision이 hold인 경우 percentage는 반드시 0이어야 합니다.
                buy나 sell인 경우 percentage는 1-100 사이여야 합니다."""
            },
            {
                "role": "user",
                "content": f"""
                시장 데이터: {json.dumps(market_summary, ensure_ascii=False)}
                전략: {strategy}
                
                위 데이터를 기반으로 투자 결정을 JSON 형식으로 제공해주세요.
                """
            }
        ]
        
        if chart_image:
            messages[1]["content"] = [
                {"type": "text", "text": messages[1]["content"]},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{chart_image}"}}
            ]

        logger.info("AI에 트레이딩 결정 요청 중...")
        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            max_tokens=500,
            temperature=0.7
        )

        response_text = response.choices[0].message.content.strip()
        logger.info(f"AI 응답: {response_text}")

        try:
            result = json.loads(response_text)
            
            # 응답 검증
            if "decision" not in result or "percentage" not in result or "reason" not in result:
                raise ValueError("응답에 필수 필드가 누락됨")
                
            if result["decision"] not in ["buy", "sell", "hold"]:
                raise ValueError(f"잘못된 결정: {result['decision']}")
                
            if not isinstance(result["percentage"], (int, float)):
                raise ValueError(f"퍼센테이지가 숫자가 아님: {result['percentage']}")
                
            result["percentage"] = int(result["percentage"])
            
            if result["decision"] == "hold" and result["percentage"] != 0:
                result["percentage"] = 0
                
            if result["decision"] in ["buy", "sell"] and (result["percentage"] < 1 or result["percentage"] > 100):
                raise ValueError(f"잘못된 퍼센테이지: {result['percentage']}")

            return TradingDecision(
                decision=result["decision"],
                percentage=result["percentage"],
                reason=result["reason"]
            )

        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 오류: {response_text}")
            raise
        except Exception as e:
            logger.error(f"응답 검증 오류: {str(e)}")
            raise

    except Exception as e:
        logger.error(f"트레이딩 결정 생성 중 오류 발생: {str(e)}")
        return None


def ai_trading():
    """메인 트레이딩 로직"""
    try:
        # 시장 데이터 수집
        market_data = get_market_data()
        if not market_data:
            logger.error("시장 데이터 수집 실패")
            return

        # 차트 이미지 캡처 (선택적)
        chart_image = None
        if os.getenv("CAPTURE_CHART", "false").lower() == "true":
            try:
                driver = create_driver()
                driver.get("https://upbit.com/full_chart?code=CRIX.UPBIT.KRW-BTC")
                time.sleep(20)  # 로딩 대기 시간 최적화
                perform_chart_actions(driver)
                chart_image = capture_and_encode_screenshot(driver)
            except Exception as e:
                logger.error(f"차트 캡처 실패: {e}")
            finally:
                if driver:
                    driver.quit()

        # 데이터베이스 연결
        with sqlite3.connect('bitcoin_trades.db') as conn:
            # 최근 거래 내역 조회
            recent_trades = get_recent_trades(conn)
            
            # AI 트레이딩 결정 요청
            decision = get_trading_decision(market_data, recent_trades, chart_image)
            if not decision:
                logger.error("트레이딩 결정 생성 실패")
                return

            logger.info(f"AI 결정: {decision.decision.upper()}")
            logger.info(f"결정 이유: {decision.reason}")

            # 거래 실행
            order_executed = execute_trade(decision.decision, decision.percentage, decision.reason)
            
            # 거래 후 잔고 조회 및 기록
            time.sleep(1)  # API 호출 제한 고려
            try:
                balances = upbit.get_balances()
                btc_balance = next((float(balance['balance']) for balance in balances if balance['currency'] == 'BTC'), 0)
                krw_balance = next((float(balance['balance']) for balance in balances if balance['currency'] == 'KRW'), 0)
                btc_avg_buy_price = next((float(balance['avg_buy_price']) for balance in balances if balance['currency'] == 'BTC'), 0)
                current_btc_price = pyupbit.get_current_price("KRW-BTC")

                # Reflection 생성 및 거래 기록
                reflection = generate_reflection(recent_trades, market_data)
                log_trade(
                    conn, 
                    decision.decision,
                    decision.percentage if order_executed else 0,
                    decision.reason,
                    btc_balance,
                    krw_balance,
                    btc_avg_buy_price,
                    current_btc_price,
                    reflection
                )
                
                # 성과 분석 로깅
                performance = calculate_performance(get_recent_trades(conn))
                logger.info(f"현재 BTC 잔액: {btc_balance:.8f} BTC")
                logger.info(f"현재 KRW 잔액: {krw_balance:,.0f} KRW")
                logger.info(f"7일 수익률: {performance:.2f}%")

            except Exception as e:
                logger.error(f"거래 기록 중 오류 발생: {e}")

    except Exception as e:
        logger.error(f"트레이딩 실행 중 오류 발생: {e}")

# 전역 변수 선언 (파일 상단, import 문 아래에 추가)
trading_in_progress = False

# run_scheduled_trading 함수 수정
def run_scheduled_trading():
    """스케줄된 트레이딩 실행"""
    global trading_in_progress  # 전역 변수 사용 선언
    
    if trading_in_progress:
        logger.warning("이전 거래가 아직 진행 중입니다.")
        return
        
    try:
        trading_in_progress = True
        logger.info("스케줄된 트레이딩 시작")
        ai_trading()
        logger.info("스케줄된 트레이딩 완료")
    except Exception as e:
        logger.error(f"스케줄된 트레이딩 중 오류 발생: {e}")
    finally:
        trading_in_progress = False

if __name__ == "__main__":
    # 데이터베이스 초기화
    init_db()
    
    # 환경 변수에서 스케줄 설정 읽기
    trading_times = os.getenv("TRADING_TIMES", "06:00,13:00,21:00").split(",")
    
    # 트레이딩 스케줄 설정
    for trade_time in trading_times:
        schedule.every().day.at(trade_time.strip()).do(run_scheduled_trading)
    
    logger.info("Bitcoin Trading Bot 시작")
    logger.info(f"거래 스케줄: {', '.join(trading_times)}")
    
    # 테스트 모드 확인
    if os.getenv("TEST_MODE", "false").lower() == "true":
        logger.info("테스트 모드로 즉시 실행")
        run_scheduled_trading()
    
    # 메인 루프
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except KeyboardInterrupt:
            logger.info("프로그램 종료")
            break
        except Exception as e:
            logger.error(f"메인 루프 오류: {e}")
            time.sleep(60)  # 오류 발생시 1분 대기
           