import sqlite3
import logging
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import pyupbit
import ta
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

def get_trades_from_db():
    """trading_bot.db에서 거래 기록 조회"""
    try:
        conn = sqlite3.connect('trading_bot.db')
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                timestamp,
                decision,
                current_price as price,
                rsi_value,
                stoch_rsi,
                macd,
                volume_osc,
                trade_status,
                reason
            FROM trades
            WHERE trade_status = 'executed'
            ORDER BY timestamp DESC
        """)
        trades = cursor.fetchall()
        logger.info(f"trading_bot.db에서 {len(trades)}개의 거래 기록 로드")
        
        # DataFrame 변환
        trades_df = pd.DataFrame(trades, columns=[
            'timestamp', 'decision', 'price', 'rsi', 
            'stoch_rsi', 'macd', 'volume_osc', 'status', 'reason'
        ])
        trades_df['timestamp'] = pd.to_datetime(trades_df['timestamp'])
        
        return trades_df
        
    except Exception as e:
        logger.error(f"거래 기록 조회 오류: {e}")
        return pd.DataFrame()
    finally:
        if 'conn' in locals():
            conn.close()

def get_market_data(days=14):
    """비트코인 시장 데이터 수집 및 지표 계산"""
    try:
        end_date = datetime.now()
        df = pyupbit.get_ohlcv("KRW-BTC", interval="minute1", to=end_date, count=1440*days)
        
        if df is None or df.empty:
            raise ValueError("데이터 수집 실패")
        
        # 기술적 지표 계산
        df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
        
        # Stochastic RSI
        stoch_rsi = ta.momentum.StochRSIIndicator(close=df['close'], window=14, smooth1=3, smooth2=3)
        df['stoch_rsi_k'] = stoch_rsi.stochrsi_k()
        df['stoch_rsi_d'] = stoch_rsi.stochrsi_d()
        
        # MACD
        macd = ta.trend.MACD(close=df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        df['macd_diff'] = macd.macd_diff()
        
        # Volume Oscillator
        df['volume_sma_short'] = df['volume'].rolling(window=5).mean()
        df['volume_sma_long'] = df['volume'].rolling(window=10).mean()
        df['volume_osc'] = ((df['volume_sma_short'] - df['volume_sma_long']) / df['volume_sma_long']) * 100
        
        logger.info(f"{len(df)}개의 시장 데이터 포인트 수집")
        return df
        
    except Exception as e:
        logger.error(f"시장 데이터 수집 오류: {e}")
        return None

def create_analysis_chart(market_data, trades_df):
    """기술적 지표를 포함한 분석 차트 생성"""
    try:
        fig = make_subplots(
            rows=5, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            subplot_titles=('가격', 'Stochastic RSI', 'RSI', 'MACD', 'Volume OSC'),
            row_heights=[0.4, 0.15, 0.15, 0.15, 0.15]
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

        # Stochastic RSI
        fig.add_trace(
            go.Scatter(x=market_data.index, y=market_data['stoch_rsi_k'], 
                      name='Stoch RSI K', line=dict(color='blue')),
            row=2, col=1
        )
        fig.add_trace(
            go.Scatter(x=market_data.index, y=market_data['stoch_rsi_d'], 
                      name='Stoch RSI D', line=dict(color='orange')),
            row=2, col=1
        )

        # RSI
        fig.add_trace(
            go.Scatter(x=market_data.index, y=market_data['rsi'], 
                      name='RSI', line=dict(color='purple')),
            row=3, col=1
        )

        # MACD
        fig.add_trace(
            go.Scatter(x=market_data.index, y=market_data['macd'], 
                      name='MACD', line=dict(color='blue')),
            row=4, col=1
        )
        fig.add_trace(
            go.Scatter(x=market_data.index, y=market_data['macd_signal'], 
                      name='Signal', line=dict(color='orange')),
            row=4, col=1
        )

        # Volume Oscillator
        fig.add_trace(
            go.Scatter(x=market_data.index, y=market_data['volume_osc'], 
                      name='Vol OSC', line=dict(color='green')),
            row=5, col=1
        )

        # 거래 시점 표시
        for idx, trade in trades_df.iterrows():
            color = 'red' if trade['decision'] == 'sell' else 'green'
            marker_symbol = 'triangle-down' if trade['decision'] == 'sell' else 'triangle-up'
            
            fig.add_trace(
                go.Scatter(
                    x=[trade['timestamp']],
                    y=[trade['price']],
                    mode='markers',
                    marker=dict(symbol=marker_symbol, size=12, color=color),
                    name=f"{trade['decision']}",
                    text=f"{trade['decision'].upper()}<br>"
                         f"가격: {trade['price']:,.0f}원<br>"
                         f"RSI: {trade['rsi']:.1f}<br>"
                         f"Stoch RSI: {trade['stoch_rsi']:.1f}<br>"
                         f"MACD: {trade['macd']:.1f}<br>"
                         f"Vol OSC: {trade['volume_osc']:.1f}<br>"
                         f"사유: {trade['reason']}",
                    hoverinfo='text'
                ),
                row=1, col=1
            )

        # 기준선 추가
        fig.add_hline(y=80, line_dash="dash", line_color="red", row=2, col=1)
        fig.add_hline(y=20, line_dash="dash", line_color="green", row=2, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)

        # 레이아웃 설정
        fig.update_layout(
            title_text="비트코인 거래 분석 (with Technical Indicators)",
            title_x=0.5,
            height=1500,
            showlegend=True,
            xaxis_rangeslider_visible=False
        )

        return fig

    except Exception as e:
        logger.error(f"차트 생성 오류: {e}")
        return None

def main():
    try:
        trades_df = get_trades_from_db()
        if trades_df.empty:
            logger.warning("거래 기록이 없습니다")
            return
            
        first_trade_date = trades_df['timestamp'].min()
        days_diff = (datetime.now() - first_trade_date).days + 1
        
        market_data = get_market_data(days=days_diff)
        if market_data is None:
            logger.error("시장 데이터 수집 실패")
            return

        fig = create_analysis_chart(market_data, trades_df)
        if fig is not None:
            fig.write_html("bitcoin_trading_analysis.html")
            logger.info("분석 차트 생성 완료: bitcoin_trading_analysis.html")

    except Exception as e:
        logger.error(f"프로그램 실행 중 오류: {e}")

if __name__ == "__main__":
    main()