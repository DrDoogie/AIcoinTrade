import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
from datetime import datetime

# 페이지 설정
st.set_page_config(
    page_title="Bitcoin Trade Viewer",
    page_icon="📈",
    layout="wide"
)

# 스타일 적용
st.markdown("""
    <style>
    .main {
        padding: 2rem;
    }
    .stPlotlyChart {
        margin: 1rem 0;
    }
    </style>
""", unsafe_allow_html=True)

# 데이터베이스 연결 함수
@st.cache_resource
def get_connection():
    return sqlite3.connect('bitcoin_trades.db', check_same_thread=False)

# 데이터 로드 함수
@st.cache_data
def load_data():
    conn = get_connection()
    query = """
    SELECT 
        timestamp,
        decision,
        percentage,
        reason,
        btc_balance,
        krw_balance,
        btc_avg_buy_price,
        btc_krw_price,
        reflection
    FROM trades
    ORDER BY timestamp DESC
    """
    df = pd.read_sql_query(query, conn)
    
    # 타임스탬프 변환
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # 수익률 계산
    df['profit_rate'] = ((df['btc_krw_price'] - df['btc_avg_buy_price']) / df['btc_avg_buy_price'] * 100).round(2)
    
    return df

def main():
    st.title('📊 Bitcoin Trading Dashboard')
    
    # 데이터 로드
    df = load_data()
    
    # 사이드바에 기간 선택 필터 추가
    st.sidebar.header('📅 기간 선택')
    date_range = st.sidebar.date_input(
        "거래 기간 선택",
        value=(df['timestamp'].min().date(), df['timestamp'].max().date())
    )
    
    # 선택된 기간으로 데이터 필터링
    mask = (df['timestamp'].dt.date >= date_range[0]) & (df['timestamp'].dt.date <= date_range[1])
    filtered_df = df.loc[mask]
    
    # 주요 지표 (KPI)
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("현재 BTC 잔액", f"{filtered_df['btc_balance'].iloc[0]:.8f} BTC")
    with col2:
        st.metric("현재 KRW 잔액", f"{filtered_df['krw_balance'].iloc[0]:,.0f} KRW")
    with col3:
        st.metric("현재 BTC 가격", f"{filtered_df['btc_krw_price'].iloc[0]:,.0f} KRW")
    with col4:
        profit_rate = filtered_df['profit_rate'].iloc[0]
        st.metric("현재 수익률", f"{profit_rate:.2f}%")
    
    # 차트 섹션
    st.header('📈 거래 분석')
    
    col1, col2 = st.columns(2)
    
    with col1:
        # 거래 결정 분포
        decision_counts = filtered_df['decision'].value_counts()
        fig = px.pie(
            values=decision_counts.values,
            names=decision_counts.index,
            title='거래 결정 분포',
            color_discrete_sequence=px.colors.qualitative.Set3
        )
        st.plotly_chart(fig, use_container_width=True)
        
    with col2:
        # 거래량 분포
        fig = px.bar(
            filtered_df,
            x='timestamp',
            y='percentage',
            color='decision',
            title='거래량 분포',
            color_discrete_sequence=px.colors.qualitative.Set3
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # 가격 및 잔액 변화 그래프
    col1, col2 = st.columns(2)
    
    with col1:
        fig = px.line(
            filtered_df,
            x='timestamp',
            y=['btc_balance', 'krw_balance'],
            title='잔액 변화 추이',
            labels={'value': '잔액', 'timestamp': '날짜'},
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        fig = px.line(
            filtered_df,
            x='timestamp',
            y='btc_krw_price',
            title='BTC 가격 변화',
            labels={'btc_krw_price': '가격(KRW)', 'timestamp': '날짜'}
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # 거래 내역 테이블
    st.header('📝 상세 거래 내역')
    
    # 테이블에 표시할 컬럼 선택 및 이름 변경
    display_columns = {
        'timestamp': '날짜',
        'decision': '결정',
        'percentage': '비율(%)',
        'btc_balance': 'BTC잔액',
        'krw_balance': 'KRW잔액',
        'btc_krw_price': 'BTC가격',
        'profit_rate': '수익률(%)',
        'reason': '결정이유'
    }
    
    table_df = filtered_df[display_columns.keys()].copy()
    table_df.columns = display_columns.values()
    st.dataframe(
        table_df,
        use_container_width=True,
        column_config={
            "날짜": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            "BTC잔액": st.column_config.NumberColumn(format="%.8f"),
            "KRW잔액": st.column_config.NumberColumn(format="%d"),
            "BTC가격": st.column_config.NumberColumn(format="%d"),
            "수익률(%)": st.column_config.NumberColumn(format="%.2f")
        }
    )

if __name__ == "__main__":
    main()



# streamlit run webviewer.py로 실행하기 