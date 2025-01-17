import os
import sqlite3
import logging
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import pyupbit
import ta
import pandas as pd
from pathlib import Path

# 기본 경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, 'logs')
DB_DIR = os.path.join(BASE_DIR, 'db')
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')

# 필요한 디렉토리 생성
for directory in [LOG_DIR, DB_DIR, OUTPUT_DIR]:
    os.makedirs(directory, exist_ok=True)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'trading_visualization.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def get_db_paths():
    """데이터베이스 경로 설정"""
    try:
        trading_bot_db = os.path.join(DB_DIR, 'trading_bot.db')
        bitcoin_trades_db = os.path.join(DB_DIR, 'bitcoin_trades.db')
        
        # DB 파일 존재 여부 확인
        missing_dbs = []
        if not os.path.exists(trading_bot_db):
            missing_dbs.append('trading_bot.db')
        if not os.path.exists(bitcoin_trades_db):
            missing_dbs.append('bitcoin_trades.db')
            
        if missing_dbs:
            logger.warning(f"Missing database files: {', '.join(missing_dbs)}")
            
        return trading_bot_db, bitcoin_trades_db
        
    except Exception as e:
        logger.error(f"데이터베이스 경로 설정 오류: {e}")
        raise

def get_trades_from_dbs():
    """두 데이터베이스에서 거래 기록 조회"""
    all_trades = []
    trading_bot_db, bitcoin_trades_db = get_db_paths()
    
    # trading_bot.db에서 거래 기록 조회
    if os.path.exists(trading_bot_db):
        try:
            conn1 = sqlite3.connect(trading_bot_db)
            cursor1 = conn1.cursor()
            cursor1.execute("""
                SELECT 
                    timestamp,
                    decision,
                    current_price as price,
                    rsi_value,
                    'trading_bot' as source
                FROM trades
                WHERE trade_status = 'executed'
                ORDER BY timestamp DESC
            """)
            trades1 = cursor1.fetchall()
            all_trades.extend(trades1)
            logger.info(f"trading_bot.db에서 {len(trades1)}개의 거래 기록 로드")
        except Exception as e:
            logger.error(f"trading_bot.db 조회 오류: {e}")
        finally:
            if 'conn1' in locals():
                conn1.close()
    
    # bitcoin_trades.db에서 거래 기록 조회
    if os.path.exists(bitcoin_trades_db):
        try:
            conn2 = sqlite3.connect(bitcoin_trades_db)
            cursor2 = conn2.cursor()
            cursor2.execute("""
                SELECT 
                    timestamp,
                    decision,
                    btc_krw_price as price,
                    0 as rsi_value,
                    'ai_bot' as source
                FROM trades
                WHERE decision IN ('buy', 'sell')
                ORDER BY timestamp DESC
            """)
            trades2 = cursor2.fetchall()
            all_trades.extend(trades2)
            logger.info(f"bitcoin_trades.db에서 {len(trades2)}개의 거래 기록 로드")
        except Exception as e:
            logger.error(f"bitcoin_trades.db 조회 오류: {e}")
        finally:
            if 'conn2' in locals():
                conn2.close()
    
    # 거래 기록이 없는 경우
    if not all_trades:
        logger.warning("거래 기록이 없습니다")
        return pd.DataFrame()
    
    # 거래 기록을 DataFrame으로 변환
    trades_df = pd.DataFrame(all_trades, columns=['timestamp', 'decision', 'price', 'rsi', 'source'])
    
    # timestamp 형식 변환
    def convert_timestamp(ts, source):
        try:
            if source == 'trading_bot':
                return pd.to_datetime(ts, format='%Y-%m-%d %H:%M:%S')
            else:  # ai_bot
                return pd.to_datetime(ts)  # ISO format
        except Exception as e:
            logger.error(f"Timestamp 변환 오류: {ts}, {source}, {e}")
            return None

    trades_df['timestamp'] = trades_df.apply(
        lambda row: convert_timestamp(row['timestamp'], row['source']), 
        axis=1
    )
    
    # 변환 실패한 데이터 제거
    trades_df = trades_df.dropna(subset=['timestamp'])
    
    return trades_df

def get_market_data(days=14):
    """비트코인 시장 데이터 수집"""
    try:
        # 최근 거래일로부터 데이터 수집
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # 1분봉 데이터 수집
        df = pyupbit.get_ohlcv("KRW-BTC", interval="minute1", to=end_date, count=1440*days)
        
        if df is None or df.empty:
            raise ValueError("데이터 수집 실패")
            
        # 기술적 지표 계산
        df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
        
        bb = ta.volatility.BollingerBands(close=df['close'], window=20, window_dev=2)
        df['bb_upper'] = bb.bollinger_hband()
        df['bb_lower'] = bb.bollinger_lband()
        
        macd = ta.trend.MACD(close=df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        
        logger.info(f"{len(df)}개의 시장 데이터 포인트 수집")
        return df
        
    except Exception as e:
        logger.error(f"시장 데이터 수집 오류: {e}")
        return None

def create_combined_chart(market_data, trades_df):
    """통합 차트 생성"""
    try:
        # 서브플롯 생성
        fig = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.05,
            subplot_titles=('가격', 'RSI', 'MACD'),
            row_heights=[0.5, 0.25, 0.25]
        )

        # 캔들스틱 차트
        fig.add_trace(
            go.Candlestick(
                x=market_data.index,
                open=market_data['open'],
                high=market_data['high'],
                low=market_data['low'],
                close=market_data['close'],
                name='BTC/KRW'
            ),
            row=1, col=1
        )

        # RSI
        fig.add_trace(
            go.Scatter(
                x=market_data.index,
                y=market_data['rsi'],
                name='RSI',
                line=dict(color='purple')
            ),
            row=2, col=1
        )

        # MACD
        fig.add_trace(
            go.Scatter(
                x=market_data.index,
                y=market_data['macd'],
                name='MACD',
                line=dict(color='blue')
            ),
            row=3, col=1
        )
        fig.add_trace(
            go.Scatter(
                x=market_data.index,
                y=market_data['macd_signal'],
                name='Signal',
                line=dict(color='orange')
            ),
            row=3, col=1
        )

        # 거래 시점 표시
        for idx, trade in trades_df.iterrows():
            # 거래 종류에 따른 색상 설정
            color = 'red' if trade['decision'] == 'sell' else 'green'
            marker_symbol = 'triangle-down' if trade['decision'] == 'sell' else 'triangle-up'
            
            # 가격 차트에 거래 표시
            fig.add_trace(
                go.Scatter(
                    x=[trade['timestamp']],
                    y=[trade['price']],
                    mode='markers',
                    marker=dict(
                        symbol=marker_symbol,
                        size=12,
                        color=color
                    ),
                    name=f"{trade['source']} {trade['decision']}",
                    text=f"{trade['decision'].upper()}<br>{trade['price']:,.0f}원<br>RSI: {trade['rsi']:.1f}",
                    hoverinfo='text'
                ),
                row=1, col=1
            )
            
            # 세로선 추가
            fig.add_vline(
                x=trade['timestamp'],
                line_dash="dash",
                line_color=color,
                opacity=0.5,
                line_width=1
            )

        # RSI 기준선
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)

        # 레이아웃 설정
        fig.update_layout(
            title_text=f"비트코인 거래 분석 ({datetime.now().strftime('%Y-%m-%d %H:%M')} 기준)",
            title_x=0.5,
            height=1200,
            showlegend=True,
            xaxis_rangeslider_visible=False
        )

        # Y축 레이블 설정
        fig.update_yaxes(title_text="가격 (KRW)", row=1, col=1)
        fig.update_yaxes(title_text="RSI", row=2, col=1)
        fig.update_yaxes(title_text="MACD", row=3, col=1)

        return fig

    except Exception as e:
        logger.error(f"차트 생성 오류: {e}")
        return None

def main():
    """메인 실행 함수"""
    try:
        logger.info("차트 생성 프로그램 시작")
        
        # 거래 기록 로드
        trades_df = get_trades_from_dbs()
        if trades_df.empty:
            logger.warning("거래 기록이 없어 프로그램을 종료합니다")
            return
            
        # 데이터 수집 기간 계산
        first_trade_date = trades_df['timestamp'].min()
        days_diff = (datetime.now() - first_trade_date).days + 1
        
        # 시장 데이터 수집
        market_data = get_market_data(days=days_diff)
        if market_data is None:
            logger.error("시장 데이터 수집 실패")
            return

        # 차트 생성 및 저장
        fig = create_combined_chart(market_data, trades_df)
        if fig is not None:
            output_file = os.path.join(OUTPUT_DIR, f'trading_analysis_{datetime.now().strftime("%Y%m%d_%H%M")}.html')
            fig.write_html(output_file)
            logger.info(f"차트 파일 생성 완료: {output_file}")
        else:
            logger.error("차트 생성 실패")

    except Exception as e:
        logger.error(f"프로그램 실행 중 오류: {e}")
    finally:
        logger.info("프로그램 종료")

if __name__ == "__main__":
    main()