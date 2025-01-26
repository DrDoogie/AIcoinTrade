import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

def get_connection():
    return sqlite3.connect('bitcoin_trades.db')

def check_db_structure():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(trades)")
    columns = cursor.fetchall()
    conn.close()
    return [col[1] for col in columns]

def load_data():
    conn = get_connection()
    columns = check_db_structure()
    query = f"SELECT {', '.join(columns)} FROM trades"
    df = pd.read_sql_query(query, conn)
    conn.close()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df, columns

def main():
    st.set_page_config(layout="wide")
    st.title('Bitcoin Trading Dashboard')
    
    # 데이터 로드 및 컬럼 확인
    df, columns = load_data()
    
    # 기간 선택
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("시작일", df['timestamp'].min().date())
    with col2:
        end_date = st.date_input("종료일", df['timestamp'].max().date())
    
    mask = (df['timestamp'].dt.date >= start_date) & (df['timestamp'].dt.date <= end_date)
    filtered_df = df.loc[mask]
    
    # 거래 요약
    st.header('Trading Summary')
    col1, col2 = st.columns(2)
    with col1:
        total_trades = len(filtered_df)
        st.metric("Total Trades", total_trades)
    with col2:
        decisions = filtered_df['decision'].value_counts()
        st.write("Trading Decisions:", decisions)
    
    # 기술적 지표 차트 (있는 컬럼만 표시)
    st.header('Technical Indicators')
    technical_indicators = [col for col in columns if col not in ['id', 'timestamp', 'decision']]
    
    for indicator in technical_indicators:
        fig = px.line(filtered_df, x='timestamp', y=indicator,
                     title=f'{indicator.upper()} Over Time')
        st.plotly_chart(fig, use_container_width=True)
    
    # 거래 내역
    st.header('Trade History')
    st.dataframe(filtered_df.sort_values('timestamp', ascending=False))

if __name__ == "__main__":
    main()