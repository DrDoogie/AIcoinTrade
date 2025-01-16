import pyupbit
import pandas as pd
import numpy as np
import ta
from datetime import datetime, timedelta

class ScalpingBacktester:
    def __init__(self, ticker="KRW-BTC", start_balance=1000000, fee_rate=0.0005):
        self.ticker = ticker
        self.start_balance = start_balance
        self.balance = start_balance
        self.coin_balance = 0
        self.trade_history = []
        self.fee_rate = fee_rate  # 거래 수수료 0.05%

    def get_historical_data(self, days=2):
        """최근 2일간의 분봉 데이터 수집"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # 1분 봉 데이터 수집
        df = pyupbit.get_ohlcv(
            ticker=self.ticker, 
            interval="minute1", 
            to=end_date, 
            count=60 * 24 * days  # 1분 봉 * 24시간 * days
        )
        
        return self._add_technical_indicators(df)

    def _add_technical_indicators(self, df):
        """기술적 지표 추가"""
        # RSI
        df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
        
        # 볼린저 밴드
        bollinger = ta.volatility.BollingerBands(close=df['close'], window=20)
        df['bb_upper'] = bollinger.bollinger_hband()
        df['bb_lower'] = bollinger.bollinger_lband()
        
        # ATR (변동성 지표)
        df['atr'] = ta.volatility.AverageTrueRange(
            high=df['high'], 
            low=df['low'], 
            close=df['close'], 
            window=14
        ).average_true_range()
        
        return df

    def apply_trading_strategy(self, df):
        """백테스팅 전략 적용"""
        trade_log = []
        
        for index, row in df.iterrows():
            # RSI 기반 매수/매도 조건
            buy_condition = (
                row['rsi'] <= 30 and  # 과매도 구간
                row['close'] <= row['bb_lower']  # 볼린저 밴드 하단 돌파
            )
            
            sell_condition = (
                row['rsi'] >= 70 and  # 과매수 구간
                row['close'] >= row['bb_upper']  # 볼린저 밴드 상단 돌파
            )
            
            # 매수 로직 (수수료 반영)
            if buy_condition and self.balance > 5000:
                # 총 자금의 3% 투자
                buy_amount = self.balance * 0.03
                buy_price = row['close']
                
                # 수수료 차감
                fee = buy_amount * self.fee_rate
                buy_amount_after_fee = buy_amount - fee
                
                buy_quantity = buy_amount_after_fee / buy_price
                
                self.balance -= buy_amount
                self.coin_balance += buy_quantity
                
                trade_log.append({
                    'timestamp': index,
                    'type': 'buy',
                    'price': buy_price,
                    'amount': buy_amount,
                    'fee': fee,
                    'quantity': buy_quantity
                })
            
            # 매도 로직 (수수료 반영)
            elif sell_condition and self.coin_balance > 0:
                sell_price = row['close']
                sell_quantity = self.coin_balance
                sell_amount = sell_quantity * sell_price
                
                # 수수료 차감
                fee = sell_amount * self.fee_rate
                sell_amount_after_fee = sell_amount - fee
                
                self.balance += sell_amount_after_fee
                self.coin_balance = 0
                
                trade_log.append({
                    'timestamp': index,
                    'type': 'sell',
                    'price': sell_price,
                    'amount': sell_amount,
                    'fee': fee,
                    'quantity': sell_quantity
                })
        
        return trade_log

    def calculate_performance(self, trade_log):
        """성과 분석"""
        # 최종 평가 자산
        final_balance = self.balance + (self.coin_balance * trade_log[-1]['price'])
        total_return = ((final_balance - self.start_balance) / self.start_balance) * 100
        
        # 거래 통계
        total_trades = len(trade_log)
        buy_trades = sum(1 for trade in trade_log if trade['type'] == 'buy')
        sell_trades = sum(1 for trade in trade_log if trade['type'] == 'sell')
        total_fees = sum(trade['fee'] for trade in trade_log)
        
        return {
            'start_balance': self.start_balance,
            'final_balance': final_balance,
            'total_return_percentage': total_return,
            'total_trades': total_trades,
            'buy_trades': buy_trades,
            'sell_trades': sell_trades,
            'total_fees': total_fees,
            'trade_log': trade_log
        }

    def run_backtest(self):
        """백테스팅 실행"""
        # 데이터 수집
        historical_data = self.get_historical_data()
        
        # 거래 전략 적용
        trade_log = self.apply_trading_strategy(historical_data)
        
        # 성과 분석
        performance = self.calculate_performance(trade_log)
        
        return performance

# 백테스팅 실행
def main():
    backtester = ScalpingBacktester()
    result = backtester.run_backtest()
    
    print("백테스팅 결과:")
    print(f"시작 자금: {result['start_balance']:,.0f} 원")
    print(f"최종 자금: {result['final_balance']:,.0f} 원")
    print(f"수익률: {result['total_return_percentage']:.2f}%")
    print(f"총 거래 횟수: {result['total_trades']}회")
    print(f"매수 거래: {result['buy_trades']}회")
    print(f"매도 거래: {result['sell_trades']}회")
    print(f"총 수수료: {result['total_fees']:,.0f} 원")

if __name__ == "__main__":
    main()