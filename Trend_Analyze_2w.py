import logging
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio
from datetime import datetime, timedelta
import pyupbit
import pandas as pd
import ta

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_visualization.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
pio.templates.default = "plotly_dark"

def collect_market_data():
    """시장 데이터 수집 및 기술적 지표 계산"""
    try:
        # 2주치 데이터 수집 (1분봉: 20160개, 5분봉: 4032개)
        df_1m = pyupbit.get_ohlcv("KRW-BTC", interval="minute1", count=20160)  # 14일 * 24시간 * 60분
        df_5m = pyupbit.get_ohlcv("KRW-BTC", interval="minute5", count=4032)   # 14일 * 24시간 * 12(5분단위)
        
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
            'df_1m': df_1m,
            'df_5m': df_5m
        }
        
        logger.info(f"시장 데이터 수집 완료: 현재가 {current_price:,.0f}원")
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
        
        return df
        
    except Exception as e:
        logger.error(f"기술적 지표 계산 중 오류: {e}")
        return None

def visualize_trading_data(market_data):
    """비트코인 차트와 기술적 지표 시각화"""
    try:
        df_1m = market_data['df_1m']
        df_5m = market_data['df_5m']
        
        # 서브플롯 생성
        fig = make_subplots(
            rows=4, cols=2,
            subplot_titles=('1분봉 차트', '5분봉 차트', 
                          'RSI (1분봉)', 'RSI (5분봉)',
                          'MACD (1분봉)', 'MACD (5분봉)',
                          '볼린저밴드 (1분봉)', '볼린저밴드 (5분봉)'),
            vertical_spacing=0.05,
            horizontal_spacing=0.05
        )

        # 1분봉 캔들차트
        fig.add_trace(
            go.Candlestick(
                x=df_1m.index,
                open=df_1m['open'],
                high=df_1m['high'],
                low=df_1m['low'],
                close=df_1m['close'],
                name='1분봉'
            ),
            row=1, col=1
        )

        # 5분봉 캔들차트
        fig.add_trace(
            go.Candlestick(
                x=df_5m.index,
                open=df_5m['open'],
                high=df_5m['high'],
                low=df_5m['low'],
                close=df_5m['close'],
                name='5분봉'
            ),
            row=1, col=2
        )

        # RSI (1분봉)
        fig.add_trace(
            go.Scatter(
                x=df_1m.index,
                y=df_1m['rsi'],
                name='RSI (1분)',
                line=dict(color='yellow')
            ),
            row=2, col=1
        )

        # RSI (5분봉)
        fig.add_trace(
            go.Scatter(
                x=df_5m.index,
                y=df_5m['rsi'],
                name='RSI (5분)',
                line=dict(color='yellow')
            ),
            row=2, col=2
        )

        # MACD (1분봉)
        fig.add_trace(
            go.Scatter(
                x=df_1m.index,
                y=df_1m['macd'],
                name='MACD (1분)',
                line=dict(color='blue')
            ),
            row=3, col=1
        )
        fig.add_trace(
            go.Scatter(
                x=df_1m.index,
                y=df_1m['macd_signal'],
                name='Signal (1분)',
                line=dict(color='red')
            ),
            row=3, col=1
        )

        # MACD (5분봉)
        fig.add_trace(
            go.Scatter(
                x=df_5m.index,
                y=df_5m['macd'],
                name='MACD (5분)',
                line=dict(color='blue')
            ),
            row=3, col=2
        )
        fig.add_trace(
            go.Scatter(
                x=df_5m.index,
                y=df_5m['macd_signal'],
                name='Signal (5분)',
                line=dict(color='red')
            ),
            row=3, col=2
        )

        # 볼린저밴드 (1분봉)
        fig.add_trace(
            go.Scatter(
                x=df_1m.index,
                y=df_1m['bb_upper'],
                name='상단밴드 (1분)',
                line=dict(color='gray', dash='dash')
            ),
            row=4, col=1
        )
        fig.add_trace(
            go.Scatter(
                x=df_1m.index,
                y=df_1m['close'],
                name='종가 (1분)',
                line=dict(color='white')
            ),
            row=4, col=1
        )
        fig.add_trace(
            go.Scatter(
                x=df_1m.index,
                y=df_1m['bb_lower'],
                name='하단밴드 (1분)',
                line=dict(color='gray', dash='dash'),
                fill='tonexty'
            ),
            row=4, col=1
        )

        # 볼린저밴드 (5분봉)
        fig.add_trace(
            go.Scatter(
                x=df_5m.index,
                y=df_5m['bb_upper'],
                name='상단밴드 (5분)',
                line=dict(color='gray', dash='dash')
            ),
            row=4, col=2
        )
        fig.add_trace(
            go.Scatter(
                x=df_5m.index,
                y=df_5m['close'],
                name='종가 (5분)',
                line=dict(color='white')
            ),
            row=4, col=2
        )
        fig.add_trace(
            go.Scatter(
                x=df_5m.index,
                y=df_5m['bb_lower'],
                name='하단밴드 (5분)',
                line=dict(color='gray', dash='dash'),
                fill='tonexty'
            ),
            row=4, col=2
        )

        # 레이아웃 업데이트
        fig.update_layout(
            height=1200,
            width=1600,
            showlegend=True,
            title_text=f"비트코인 기술적 분석 대시보드 (업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')})",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )

        # RSI 기준선 추가
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=2)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=2)

        # 차트 저장
        fig.write_html("bitcoin_analysis.html")
        logger.info("차트 파일 생성 완료: bitcoin_analysis.html")
        return fig

    except Exception as e:
        logger.error(f"차트 생성 중 오류 발생: {e}")
        return None

def main():
    """메인 실행 함수"""
    try:
        # 시장 데이터 수집
        market_data = collect_market_data()
        if market_data is None:
            logger.error("시장 데이터 수집 실패")
            return

        # 차트 생성 및 저장
        fig = visualize_trading_data(market_data)
        if fig is not None:
            logger.info("차트 생성 완료")
            
    except Exception as e:
        logger.error(f"프로그램 실행 중 오류 발생: {e}")

if __name__ == "__main__":
    main()