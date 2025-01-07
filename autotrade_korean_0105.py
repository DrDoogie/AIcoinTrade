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
    logger.error("API 키를 찾을 수 없습니다.")
    raise ValueError("API 키가 없습니다.")
upbit = pyupbit.Upbit(access, secret)

# Pydantic 모델
class TradingDecision(BaseModel):
    decision: str
    percentage: int
    reason: str

def init_db():
    """데이터베이스 초기화"""
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
    """거래 기록 저장"""
    c = conn.cursor()
    timestamp = datetime.now().isoformat()
    c.execute("""INSERT INTO trades 
                 (timestamp, decision, percentage, reason, btc_balance, krw_balance, btc_avg_buy_price, btc_krw_price, reflection) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (timestamp, decision, percentage, reason, btc_balance, krw_balance, btc_avg_buy_price, btc_krw_price, reflection))
    conn.commit()

def get_recent_trades(conn, days=7):
    """최근 거래 내역 조회"""
    c = conn.cursor()
    seven_days_ago = (datetime.now() - timedelta(days=days)).isoformat()
    c.execute("SELECT * FROM trades WHERE timestamp > ? ORDER BY timestamp DESC", (seven_days_ago,))
    columns = [column[0] for column in c.description]
    return pd.DataFrame.from_records(data=c.fetchall(), columns=columns)

def calculate_performance(trades_df):
    """투자 성과 계산"""
    if trades_df.empty:
        return 0
    initial_balance = trades_df.iloc[-1]['krw_balance'] + trades_df.iloc[-1]['btc_balance'] * trades_df.iloc[-1]['btc_krw_price']
    final_balance = trades_df.iloc[0]['krw_balance'] + trades_df.iloc[0]['btc_balance'] * trades_df.iloc[0]['btc_krw_price']
    return (final_balance - initial_balance) / initial_balance * 100

def add_indicators(df):
    """기술적 지표 추가"""
    # 볼린저 밴드
    indicator_bb = ta.volatility.BollingerBands(close=df['close'], window=20, window_dev=2)
    df['bb_bbm'] = indicator_bb.bollinger_mavg()
    df['bb_bbh'] = indicator_bb.bollinger_hband()
    df['bb_bbl'] = indicator_bb.bollinger_lband()
    
    # RSI
    df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
    
    # MACD
    macd = ta.trend.MACD(close=df['close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df['macd_diff'] = macd.macd_diff()
    
    # 이동평균선
    df['sma_20'] = ta.trend.SMAIndicator(close=df['close'], window=20).sma_indicator()
    df['ema_12'] = ta.trend.EMAIndicator(close=df['close'], window=12).ema_indicator()
    
    return df

def get_fear_and_greed_index():
    """공포/탐욕 지수 조회"""
    url = "https://api.alternative.me/fng/"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()['data'][0]
    except Exception as e:
        logger.error(f"공포/탐욕 지수 조회 실패: {e}")
        return {"value": 50, "status": "Neutral"}

def get_bitcoin_news():
    """비트코인 관련 뉴스 조회"""
    serpapi_key = os.getenv("SERPAPI_API_KEY")
    if not serpapi_key:
        logger.error("SERPAPI API key is missing.")
        return []
    
    try:
        response = requests.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google_news",
                "q": "btc",
                "api_key": serpapi_key
            },
            timeout=10
        )
        response.raise_for_status()
        news_results = response.json().get("news_results", [])
        return [{
            "title": item.get("title", ""),
            "date": item.get("date", "")
        } for item in news_results[:5]]
    except Exception as e:
        logger.error(f"뉴스 데이터 조회 실패: {e}")
        return []
def generate_reflection(trades_df, current_market_data):
    """투자 분석 및 반성 생성"""
    performance = calculate_performance(trades_df)
    
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    if not client.api_key:
        logger.error("OpenAI API 키가 없거나 유효하지 않습니다.")
        return None
    
    try:
        recent_trades = trades_df.tail(5).to_dict(orient='records')
        
        market_summary = {
            "fear_greed": current_market_data.get("fear_greed_index", {}).get("value", "N/A"),
            "news_headlines": current_market_data.get("news_headlines", []),
            "current_price": float(current_market_data["daily_ohlcv"]["close"].iloc[-1]) if not current_market_data["daily_ohlcv"].empty else "N/A"
        }

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": """당신은 비트코인 트레이딩 전문가입니다. 최근 거래와 시장 상황을 분석하여 
                    핵심적인 인사이트를 제공해주세요."""
                },
                {
                    "role": "user",
                    "content": f"""
                    최근 거래 내역:
                    {json.dumps(recent_trades, ensure_ascii=False)}
                    
                    시장 현황:
                    {json.dumps(market_summary, ensure_ascii=False)}
                    
                    7일간 수익률: {performance:.2f}%
                    
                    다음 항목들을 분석해주세요:
                    1. 최근 거래 평가
                    2. 개선이 필요한 부분
                    3. 향후 전략 제안
                    """
                }
            ],
            max_tokens=500,
            temperature=0.7
        )

        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"투자 분석 생성 중 오류 발생: {e}")
        return None
    
def create_driver():
    """Selenium WebDriver 생성"""
    logger.info("ChromeDriver 설정 중...")
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    
    try:
        service = Service('/usr/bin/chromedriver')
        return webdriver.Chrome(service=service, options=chrome_options)
    except Exception as e:
        logger.error(f"ChromeDriver 생성 실패: {e}")
        raise

def get_trading_decision(market_data, trade_history, chart_image=None):
    """AI 트레이딩 결정 생성"""
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        with open("strategy.txt", "r", encoding="utf-8") as f:
            strategy = f.read()

        market_summary = {
            "current_price": float(market_data["daily_ohlcv"]["close"].iloc[-1]),
            "daily_change": float((market_data["daily_ohlcv"]["close"].iloc[-1] - market_data["daily_ohlcv"]["close"].iloc[-2]) / market_data["daily_ohlcv"]["close"].iloc[-2] * 100),
            "rsi": float(market_data["daily_ohlcv"]["rsi"].iloc[-1]),
            "macd": float(market_data["daily_ohlcv"]["macd"].iloc[-1]),
            "fear_greed": market_data["fear_greed_index"]["value"]
        }
        
        messages = [
            {
                "role": "system",
                "content": f"""당신은 비트코인 투자 전문가입니다. 제공된 데이터를 분석하여 현 시점에서 매수, 매도, 홀드 여부를 결정하세요. 
                다음 요소들을 분석에 고려하세요:

                - 기술적 지표와 시장 데이터
                - 최근 뉴스 헤드라인과 비트코인 가격에 미칠 영향
                - 공포탐욕지수와 그 의미
                - 전반적인 시장 심리
                - 차트에서 보이는 패턴과 트렌드

                전략:
                {strategy}

                이 전략을 기반으로 현재 시장 상황을 분석하고, 제공된 데이터를 종합하여 판단을 내리세요.

                응답 형식:
                {{
                    "decision": "매수" 또는 "매도" 또는 "홀드",
                    "percentage": 매수/매도시 1-100 사이의 정수 (홀드시 0),
                    "reason": "결정 이유를 한글로 상세히 설명"
                }}"""
            },
            {
                "role": "user",
                "content": f"""
                시장 데이터: {json.dumps(market_summary, ensure_ascii=False)}
                뉴스 헤드라인: {json.dumps(market_data.get('news_headlines', []), ensure_ascii=False)}
                """
            }
        ]

        if chart_image:
            messages[1]["content"] = [
                {"type": "text", "text": messages[1]["content"]},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{chart_image}"}}
            ]

        logger.info("AI 트레이딩 결정 요청 중...")
        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            max_tokens=500,
            temperature=0.7
        )

        result = json.loads(response.choices[0].message.content)
        
        # decision 값을 영어로 변환
        decision_map = {"매수": "buy", "매도": "sell", "홀드": "hold"}
        result["decision"] = decision_map.get(result["decision"], "hold")

        return TradingDecision(
            decision=result["decision"],
            percentage=result["percentage"],
            reason=result["reason"]
        )

    except Exception as e:
        logger.error(f"트레이딩 결정 생성 중 오류 발생: {e}")
        return None

def ai_trading():
    """메인 트레이딩 로직"""
    try:
        # 시장 데이터 수집
        df_daily = pyupbit.get_ohlcv("KRW-BTC", interval="day", count=30)
        df_daily = dropna(df_daily)
        df_daily = add_indicators(df_daily)
        
        df_hourly = pyupbit.get_ohlcv("KRW-BTC", interval="minute60", count=24)
        df_hourly = dropna(df_hourly)
        df_hourly = add_indicators(df_hourly)
        
        market_data = {
            "daily_ohlcv": df_daily,
            "hourly_ohlcv": df_hourly,
            "fear_greed_index": get_fear_and_greed_index(),
            "news_headlines": get_bitcoin_news()
        }

        # 차트 이미지 캡처 (선택적)
        chart_image = None
        if os.getenv("CAPTURE_CHART", "false").lower() == "true":
            try:
                driver = create_driver()
                driver.get("https://upbit.com/full_chart?code=CRIX.UPBIT.KRW-BTC")
                time.sleep(20)
                chart_image = driver.get_screenshot_as_base64()
            except Exception as e:
                logger.error(f"차트 캡처 실패: {e}")
            finally:
                if driver:
                    driver.quit()

        # 트레이딩 결정 및 실행
        with sqlite3.connect('bitcoin_trades.db') as conn:
            recent_trades = get_recent_trades(conn)
            decision = get_trading_decision(market_data, recent_trades, chart_image)
            
            if not decision:
                return
                
            logger.info(f"AI 결정: {decision.decision.upper()}")
            logger.info(f"결정 이유: {decision.reason}")

            # 거래 실행
            executed = False
            if decision.decision == "buy":
                krw_balance = upbit.get_balance("KRW")
                if krw_balance:
                    amount = krw_balance * (decision.percentage / 100) * 0.9995
                    if amount > 5000:
                        result = upbit.buy_market_order("KRW-BTC", amount)
                        executed = bool(result)
            elif decision.decision == "sell":
                btc_balance = upbit.get_balance("BTC")
                if btc_balance:
                    amount = btc_balance * (decision.percentage / 100)
                    current_price = pyupbit.get_current_price("KRW-BTC")
                    if amount * current_price > 5000:
                        result = upbit.sell_market_order("KRW-BTC", amount)
                        executed = bool(result)

            # 거래 기록
            time.sleep(1)
            balances = upbit.get_balances()
            btc_balance = next((float(balance['balance']) for balance in balances if balance['currency'] == 'BTC'), 0)
            krw_balance = next((float(balance['balance']) for balance in balances if balance['currency'] == 'KRW'), 0)
            btc_avg_price = next((float(balance['avg_buy_price']) for balance in balances if balance['currency'] == 'BTC'), 0)
            current_price = pyupbit.get_current_price("KRW-BTC")

            reflection = generate_reflection(recent_trades, market_data)
            log_trade(
                conn, 
                decision.decision,
                decision.percentage if executed else 0,
                decision.reason,
                btc_balance,
                krw_balance,
                btc_avg_price,
                current_price,
                reflection
            )

            performance = calculate_performance(get_recent_trades(conn))
            logger.info(f"현재 BTC 잔액: {btc_balance:.8f} BTC")
            logger.info(f"현재 KRW 잔액: {krw_balance:,.0f} KRW")
            logger.info(f"7일 수익률: {performance:.2f}%")

    except Exception as e:
        logger.error(f"트레이딩 실행 중 오류 발생: {e}")

if __name__ == "__main__":
    init_db()
    trading_in_progress = False

    def job():
        global trading_in_progress
        if trading_in_progress:
            return
        try:
            trading_in_progress = True
            ai_trading()
        except Exception as e:
            logger.error(f"작업 실행 중 오류 발생: {e}")
        finally:
            trading_in_progress = False

    # 스케줄 설정
    trading_times = os.getenv("TRADING_TIMES", "06:00,13:00,21:00").split(",")
    for trade_time in trading_times:
        schedule.every().day.at(trade_time.strip()).do(job)
    
    logger.info("Bitcoin Trading Bot 시작")
    logger.info(f"거래 스케줄: {', '.join(trading_times)}")
    
    # 테스트 모드
    if os.getenv("TEST_MODE", "false").lower() == "true":
        logger.info("테스트 모드로 즉시 실행")
        job()
    
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
            time.sleep(60)   
