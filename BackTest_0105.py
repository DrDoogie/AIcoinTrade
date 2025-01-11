import os
import sqlite3
import pandas as pd
import pyupbit
import ta
from datetime import datetime, timedelta

class BacktestAnalyzer:
    def __init__(self, db_path='bitcoin_trades.db', days=2, fee_rate=0.0005):
        self.db_path = db_path
        self.days = days
        self.fee_rate = fee_rate  # 0.05% 수수료

    def get_trades(self):
        """최근 2일간의 거래 내역 조회"""
        conn = sqlite3.connect(self.db_path)
        
        # 2일 전부터 현재까지의 거래 조회
        two_days_ago = (datetime.now() - timedelta(days=self.days)).isoformat()
        
        query = """
        SELECT * FROM trades 
        WHERE timestamp > ? 
        ORDER BY timestamp
        """
        
        trades_df = pd.read_sql_query(query, conn, params=(two_days_ago,))
        conn.close()
        
        return trades_df

    def calculate_performance(self, trades_df):
        """거래 성과 분석"""
        if trades_df.empty:
            return {
                'total_trades': 0,
                'buy_trades': 0,
                'sell_trades': 0,
                'total_profit': 0,
                'average_profit': 0
            }

        # 매수/매도 거래 분리
        buy_trades = trades_df[trades_df['decision'] == 'buy']
        sell_trades = trades_df[trades_df['decision'] == 'sell']

        # 거래별 수익률 계산
        def calculate_trade_profit(row):
            # 수수료 차감
            fee_amount = row['krw_balance'] * self.fee_rate
            return row['krw_balance'] - fee_amount

        buy_trades['trade_profit'] = buy_trades.apply(calculate_trade_profit, axis=1)
        sell_trades['trade_profit'] = sell_trades.apply(calculate_trade_profit, axis=1)

        # 성과 분석
        performance = {
            'total_trades': len(trades_df),
            'buy_trades': len(buy_trades),
            'sell_trades': len(sell_trades),
            'total_profit': buy_trades['trade_profit'].sum() + sell_trades['trade_profit'].sum(),
            'average_profit': (buy_trades['trade_profit'].mean() + sell_trades['trade_profit'].mean()) / 2
        }

        return performance

    def detailed_trade_analysis(self, trades_df):
        """상세 거래 분석"""
        if trades_df.empty:
            return "거래 내역이 없습니다."

        # 상세 분석 문자열 생성
        analysis = "🔍 거래 상세 분석:\n"
        analysis += f"총 거래 건수: {len(trades_df)}건\n"
        analysis += f"매수 거래: {len(trades_df[trades_df['decision'] == 'buy'])}건\n"
        analysis += f"매도 거래: {len(trades_df[trades_df['decision'] == 'sell'])}건\n"

        # 각 거래의 상세 정보
        for index, trade in trades_df.iterrows():
            analysis += f"\n{trade['timestamp']} - {trade['decision'].upper()} 거래\n"
            analysis += f"  거래 사유: {trade['reason']}\n"
            analysis += f"  거래 비율: {trade['percentage']}%\n"
            analysis += f"  BTC 잔액: {trade['btc_balance']:.4f} BTC\n"
            analysis += f"  KRW 잔액: {trade['krw_balance']:,.0f} KRW\n"

        return analysis

    def run_analysis(self):
        """전체 분석 수행"""
        # 거래 내역 조회
        trades_df = self.get_trades()

        # 성과 분석
        performance = self.calculate_performance(trades_df)

        # 상세 분석
        detailed_analysis = self.detailed_trade_analysis(trades_df)

        # 결과 출력
        print("🚀 백테스팅 결과:")
        print(f"총 거래 건수: {performance['total_trades']}건")
        print(f"매수 거래: {performance['buy_trades']}건")
        print(f"매도 거래: {performance['sell_trades']}건")
        print(f"총 수익: {performance['total_profit']:,.0f} KRW")
        print(f"평균 수익: {performance['average_profit']:,.0f} KRW")

        return {
            'performance': performance,
            'detailed_analysis': detailed_analysis
        }

def main():
    analyzer = BacktestAnalyzer()
    result = analyzer.run_analysis()
    
    # 상세 분석 내용 출력
    print("\n상세 분석:")
    print(result['detailed_analysis'])

if __name__ == "__main__":
    main()
    