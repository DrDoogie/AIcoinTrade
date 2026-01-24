# RSI 추이 확인 스크립트
# 각 종목별 RSI 값을 조회하고 최근 1주일간의 RSI 추이를 그래프로 확인하는 스크립트

import requests
import json
import datetime
import time
import yaml
import pandas as pd
import numpy as np
from pytz import timezone
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import font_manager
import warnings
warnings.filterwarnings('ignore')

# 한글 폰트 설정
plt.rcParams['font.family'] = 'Malgun Gothic'  # Windows
plt.rcParams['axes.unicode_minus'] = False

# config.yaml 파일 로드
with open('config.yaml', encoding='UTF-8') as f:
    config = yaml.load(f, Loader=yaml.FullLoader)
APP_KEY = config['APP_KEY']
APP_SECRET = config['APP_SECRET']
DISCORD_WEBHOOK_URL = config['DISCORD_WEBHOOK_URL']

# API 설정
URL_BASE = "https://openapi.koreainvestment.com:9443"
ACCESS_TOKEN = None

# 종목 리스트
SYMBOLS = ["005930", "000660", "069500", "449450", "466920", "360750", "0053L0"]

# 종목 코드와 종목명 매핑
SYMBOL_NAMES = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "069500": "KODEX 200",
    "449450": "PLUS K방산",
    "466920": "SOL 조선 TOP3",
    "360750": "Tiger S&P",
    "0053L0": "Tiger 차이나휴머노이드로봇"
}

# RSI 계산 기간 및 분봉 설정
RSI_PERIOD = 14  # RSI 계산 기간
MINUTE_CANDLE = 30  # 분봉 (30분봉 사용)

def get_access_token():
    """토큰 발급"""
    global ACCESS_TOKEN
    try:
        headers = {"content-type": "application/json"}
        body = {
            "grant_type": "client_credentials",
            "appkey": APP_KEY,
            "appsecret": APP_SECRET
        }
        res = requests.post(f"{URL_BASE}/oauth2/tokenP", headers=headers, data=json.dumps(body), timeout=5)
        ACCESS_TOKEN = res.json()["access_token"]
        return ACCESS_TOKEN
    except Exception as e:
        print(f"토큰 발급 실패: {e}")
        return None

def get_minute_data(code, time_unit=MINUTE_CANDLE, period=336):
    """분봉 데이터 조회 (최근 1주일 = 336개, 30분봉 기준)"""
    global ACCESS_TOKEN
    
    if not ACCESS_TOKEN:
        ACCESS_TOKEN = get_access_token()
        if not ACCESS_TOKEN:
            print(f"❌ {code}: 토큰 발급 실패")
            return None
    
    PATH = "uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
    URL = f"{URL_BASE}/{PATH}"
    
    all_data = []
    next_key = ""
    
    try:
        # 페이지네이션을 통한 데이터 수집
        for page in range(10):  # 최대 10페이지까지 조회
            headers = {
                "Content-Type": "application/json",
                "authorization": f"Bearer {ACCESS_TOKEN}",
                "appKey": APP_KEY,
                "appSecret": APP_SECRET,
                "tr_id": "FHKST03010200",
                "custtype": "P"
            }
            
            params = {
                "FID_ETC_CLS_CODE": "",
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
                "FID_INPUT_HOUR_1": str(time_unit),
                "FID_PW_DATA_INCU_YN": "Y",
                "CTX_AREA_FK100": next_key,
                "CTX_AREA_NK100": ""
            }
            
            res = requests.get(URL, headers=headers, params=params, timeout=10)
            
            # 응답 코드가 만료된 토큰 오류인 경우
            if res.status_code == 401 or (res.status_code == 200 and 'access_token' in res.text.lower()):
                print(f"⚠️ {code}: 토큰이 만료되었습니다. 새 토큰을 발급합니다.")
                ACCESS_TOKEN = get_access_token()
                if ACCESS_TOKEN:
                    headers['authorization'] = f"Bearer {ACCESS_TOKEN}"
                    res = requests.get(URL, headers=headers, params=params, timeout=10)
                else:
                    print(f"❌ {code}: 토큰 재발급 실패")
                    if page == 0:
                        return None
                    break
            
            if res.status_code != 200:
                print(f"❌ {code}: API 호출 실패. 상태 코드: {res.status_code}")
                if page == 0:
                    return None
                break
            
            data = res.json()
            
            # 에러 체크
            if "rt_cd" in data and data["rt_cd"] != "0":
                error_msg = data.get("msg1", "알 수 없는 오류")
                print(f"❌ {code}: API 오류 - {error_msg} (rt_cd: {data['rt_cd']})")
                if page == 0:  # 첫 페이지에서 실패하면 종료
                    return None
                break
            
            if "output2" not in data or not data["output2"]:
                if page == 0:
                    print(f"❌ {code}: 분봉 데이터 없음")
                    return None
                break
            
            # 데이터 추가
            for item in data["output2"]:
                all_data.append({
                    'stck_prpr': item.get('stck_prpr', '0'),
                    'stck_stdg_prc': item.get('stck_stdg_prc', '0'),
                    'stck_oprc': item.get('stck_oprc', '0'),
                    'stck_hgpr': item.get('stck_hgpr', '0'),
                    'stck_lwpr': item.get('stck_lwpr', '0'),
                    'acml_vol': item.get('acml_vol', '0'),
                    'stck_prpr_strt_time': item.get('stck_prpr_strt_time', '')
                })
            
            # 필요한 데이터 수를 충족했거나 다음 페이지가 없으면 종료
            if len(all_data) >= period:
                all_data = all_data[:period]
                break
            
            # 다음 페이지 키 확인
            if "output1" in data and data["output1"]:
                next_key = data["output1"].get("CTX_AREA_FK100", "")
                if not next_key:
                    # ctx_area_fk100도 확인 (소문자 키)
                    next_key = data.get("ctx_area_fk100", "")
                    if not next_key:
                        break
            else:
                # output1이 없으면 ctx_area_fk100 확인 (소문자 키)
                next_key = data.get("ctx_area_fk100", "")
                if not next_key:
                    break
            
            time.sleep(0.2)  # API 호출 간격
        
        if not all_data:
            print(f"❌ {code}: 분봉 데이터가 없습니다")
            return None
        
        print(f"✅ {code}: 분봉 데이터 {len(all_data)}개 조회 완료")
        return {"output2": all_data}
        
    except requests.exceptions.RequestException as e:
        print(f"❌ {code}: 네트워크 오류 - {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ {code}: JSON 파싱 오류 - {e}")
        return None
    except Exception as e:
        print(f"❌ {code}: 분봉 데이터 조회 실패 - {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None

def calculate_rsi_series(data, periods=RSI_PERIOD):
    """RSI 시계열 데이터 계산 (최근 1주일)"""
    try:
        if "output2" not in data or not data["output2"]:
            print("RSI 계산을 위한 데이터가 부족합니다")
            return None, None
        
        df = pd.DataFrame(data["output2"])
        price_candidates = ['stck_prpr', 'close', 'last']
        price_col = next((col for col in price_candidates if col in df.columns), None)
        if not price_col:
            print("가격 데이터 컬럼을 찾을 수 없습니다:", df.columns)
            return None, None
        
        df['price'] = pd.to_numeric(df[price_col], errors='coerce')
        df = df.dropna(subset=['price'])
        
        if len(df) < periods + 1:
            print(f"RSI 데이터 부족 (필요: {periods + 1}, 현재: {len(df)})")
            return None, None
        
        # 시간 정보 추출 및 정렬
        if 'stck_prpr_strt_time' in df.columns:
            # 시간 문자열을 datetime으로 변환
            df['time'] = pd.to_datetime(df['stck_prpr_strt_time'], format='%Y%m%d%H%M%S', errors='coerce')
            # 시간이 파싱되지 않은 경우 처리
            if df['time'].isna().all():
                print(f"   ⚠️ 시간 파싱 실패, 인덱스 기반 시간 생성")
                # 시간 정보가 없으면 인덱스 기반으로 생성 (최신 데이터부터 역순)
                end_time = datetime.datetime.now(timezone('Asia/Seoul'))
                df['time'] = pd.date_range(end=end_time, periods=len(df), freq='30min')
            else:
                # 시간이 파싱된 경우, 시간순으로 정렬 (오래된 것부터)
                df = df.sort_values('time').reset_index(drop=True)
                
                # 실제 거래 시간만 필터링 (한국 주식 시장: 평일 09:30 ~ 15:30)
                # 9시 30분 이후, 15시 30분 이전 데이터만
                df = df[
                    ((df['time'].dt.hour == 9) & (df['time'].dt.minute >= 30)) |  # 9:30 이후
                    (df['time'].dt.hour.between(10, 14)) |  # 10:00 ~ 14:59
                    ((df['time'].dt.hour == 15) & (df['time'].dt.minute <= 30))  # 15:30 이전
                ]
                
                # 주말 데이터 제거 (월요일(0) ~ 금요일(4))
                df = df[df['time'].dt.weekday < 5]
                
                # 데이터가 실제로 있는지 확인
                if len(df) == 0:
                    print(f"   ⚠️ 거래 시간 데이터가 없습니다")
                else:
                    print(f"   ✅ 시간 파싱 성공: {df['time'].min()} ~ {df['time'].max()} (거래 시간만 필터링)")
                    print(f"      거래일: {sorted(df['time'].dt.date.unique())}")
        else:
            # 시간 정보가 없으면 인덱스 기반으로 생성
            print(f"   ⚠️ 시간 컬럼 없음, 인덱스 기반 시간 생성")
            end_time = datetime.datetime.now(timezone('Asia/Seoul'))
            df['time'] = pd.date_range(end=end_time, periods=len(df), freq='30min')
        
        # 가격 변화량 계산
        df['price_change'] = df['price'].diff()
        
        # 상승분과 하락분 분리
        df['gain'] = df['price_change'].where(df['price_change'] > 0, 0)
        df['loss'] = -df['price_change'].where(df['price_change'] < 0, 0)
        
        # 초기 평균 계산 (단순 평균) - Wilder's smoothing 방식
        df['avg_gain'] = 0.0
        df['avg_loss'] = 0.0
        
        # 첫 번째 EMA 계산 (periods 번째부터)
        if len(df) >= periods + 1:
            df.loc[periods, 'avg_gain'] = df['gain'].iloc[1:periods + 1].mean()
            df.loc[periods, 'avg_loss'] = df['loss'].iloc[1:periods + 1].mean()
        
        # 이후 EMA 계산 (Wilder's smoothing: alpha = 1/periods)
        alpha = 1.0 / periods
        for i in range(periods + 1, len(df)):
            df.loc[i, 'avg_gain'] = alpha * df['gain'].iloc[i] + (1 - alpha) * df['avg_gain'].iloc[i - 1]
            df.loc[i, 'avg_loss'] = alpha * df['loss'].iloc[i] + (1 - alpha) * df['avg_loss'].iloc[i - 1]
        
        # RSI 계산
        df['rs'] = df['avg_gain'] / df['avg_loss'].replace(0, np.nan)
        df['rsi'] = 100 - (100 / (1 + df['rs']))
        
        # 유효한 RSI 값만 필터링 (periods 이후부터)
        valid_df = df.iloc[periods:].copy()
        valid_df = valid_df[valid_df['rsi'].notna() & valid_df['time'].notna()]
        
        if len(valid_df) == 0:
            print("   ❌ 유효한 RSI 데이터가 없습니다")
            return None, None
        
        # 최근 3거래일 데이터만 필터링
        # 실제 거래 데이터가 있는 날짜만 고려
        if len(valid_df) > 0:
            # 데이터의 날짜 목록 추출
            valid_df['date'] = valid_df['time'].dt.date
            unique_dates = sorted(valid_df['date'].unique(), reverse=True)  # 최신순 정렬
            
            # 최근 3거래일만 선택
            if len(unique_dates) > 3:
                target_dates = set(unique_dates[:3])  # 최근 3일
                valid_df = valid_df[valid_df['date'].isin(target_dates)].copy()
            
            # date 컬럼 제거
            valid_df = valid_df.drop(columns=['date'])
            
            if len(valid_df) == 0:
                print("   ❌ 최근 3거래일 데이터가 없습니다")
                return None, None
            
            print(f"   📅 표시할 거래일: {sorted(set(valid_df['time'].dt.date.unique()))}")
        else:
            print("   ❌ 최근 3거래일 데이터가 없습니다")
            return None, None
        
        # 디버깅 정보
        if len(valid_df) > 0:
            print(f"   ✅ RSI 데이터: {len(valid_df)}개, 시간 범위: {valid_df['time'].min()} ~ {valid_df['time'].max()}")
            print(f"      RSI 범위: {valid_df['rsi'].min():.2f} ~ {valid_df['rsi'].max():.2f}")
            print(f"      가격 범위: {valid_df['price'].min():,.0f} ~ {valid_df['price'].max():,.0f}")
        
        return valid_df[['time', 'price', 'rsi']], valid_df['rsi'].iloc[-1]
        
    except Exception as e:
        print(f"RSI 시계열 계산 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return None, None

def calculate_rsi(data, periods=RSI_PERIOD):
    """표준 RSI 계산 공식 적용 (현재값만 반환)"""
    rsi_df, current_rsi = calculate_rsi_series(data, periods)
    return current_rsi

def get_current_price(code):
    """현재가 조회"""
    global ACCESS_TOKEN
    
    PATH = "uapi/domestic-stock/v1/quotations/inquire-price"
    URL = f"{URL_BASE}/{PATH}"
    
    if not ACCESS_TOKEN:
        ACCESS_TOKEN = get_access_token()
        if not ACCESS_TOKEN:
            return None
    
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "FHKST01010100"
    }
    
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": code
    }
    
    try:
        res = requests.get(URL, headers=headers, params=params, timeout=5)
        data = res.json()
        
        if "output" in data:
            return int(data["output"]["stck_prpr"])
        return None
    except Exception as e:
        print(f"현재가 조회 실패: {e}")
        return None

def get_moving_average(code, period=20):
    """이동평균 조회"""
    global ACCESS_TOKEN
    
    if not ACCESS_TOKEN:
        ACCESS_TOKEN = get_access_token()
        if not ACCESS_TOKEN:
            return None
    
    PATH = "uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    URL = f"{URL_BASE}/{PATH}"
    
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "FHKST03010100"
    }
    
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": code,
        "fid_org_adj_prc": "1",
        "fid_period_div_code": "D"
    }
    
    try:
        res = requests.get(URL, headers=headers, params=params, timeout=5)
        data = res.json()
        
        if "output2" not in data or not data["output2"]:
            return None
        
        prices = []
        for item in data["output2"][:period]:
            prices.append(float(item['stck_clpr']))
        
        if len(prices) < period:
            return None
        
        return sum(prices) / len(prices)
    except Exception as e:
        print(f"이동평균 조회 실패: {e}")
        return None

def plot_all_rsi_trends(all_rsi_data):
    """모든 종목의 RSI 추이를 한 페이지에 그래프로 표시"""
    if not all_rsi_data:
        print("❌ 그래프 데이터가 없습니다")
        return
    
    print(f"📊 그래프 생성: {len(all_rsi_data)}개 종목")
    
    # 종목 수에 따라 서브플롯 크기 결정 (2열 배치)
    num_symbols = len(all_rsi_data)
    cols = 2  # 2열 배치 (왼쪽 4개, 오른쪽 4개)
    rows = (num_symbols + cols - 1) // cols  # 올림 계산
    
    # 그래프 크기 조정 (가로를 줄이고 세로를 늘려서 추이가 잘 보이도록)
    fig = plt.figure(figsize=(16, 5 * rows))
    
    for idx, (symbol, symbol_name, rsi_df) in enumerate(all_rsi_data, 1):
        if rsi_df is None:
            print(f"⚠️ {symbol_name}({symbol}): rsi_df가 None입니다")
            continue
            
        if len(rsi_df) == 0:
            print(f"⚠️ {symbol_name}({symbol}): rsi_df가 비어있습니다")
            continue
        
        # 데이터 확인
        print(f"   📈 {symbol_name}({symbol}): {len(rsi_df)}개 데이터 포인트")
        print(f"      시간 범위: {rsi_df['time'].min()} ~ {rsi_df['time'].max()}")
        print(f"      RSI 범위: {rsi_df['rsi'].min():.2f} ~ {rsi_df['rsi'].max():.2f}")
        print(f"      가격 범위: {rsi_df['price'].min():,.0f} ~ {rsi_df['price'].max():,.0f}")
        
        # 서브플롯 인덱스 계산 (2열 배치)
        ax1 = plt.subplot(rows, cols, idx)
        try:
            # 현재가 그래프 (좌측 Y축)
            ax1.plot(rsi_df['time'], rsi_df['price'], label='현재가', color='black', linewidth=2, marker='o', markersize=2)
            ax1.set_ylabel('현재가 (원)', fontsize=10, fontweight='bold', color='black')
            ax1.tick_params(axis='y', labelcolor='black')
            ax1.grid(True, alpha=0.3)
            ax1.set_title(f'{symbol_name}({symbol}) - RSI & 현재가 추이', fontsize=11, fontweight='bold')
            
            # RSI 그래프 (우측 Y축)
            ax2 = ax1.twinx()  # 같은 x축을 공유하는 두 번째 y축 생성
            ax2.plot(rsi_df['time'], rsi_df['rsi'], label='RSI', color='blue', linewidth=2, marker='o', markersize=2)
            ax2.axhline(y=70, color='r', linestyle='--', alpha=0.7, label='과매수 (70)')
            ax2.axhline(y=50, color='gray', linestyle='--', alpha=0.5, label='중립 (50)')
            ax2.axhline(y=30, color='g', linestyle='--', alpha=0.7, label='과매도 (30)')
            ax2.fill_between(rsi_df['time'], 70, 100, alpha=0.2, color='red')
            ax2.fill_between(rsi_df['time'], 0, 30, alpha=0.2, color='green')
            ax2.set_ylabel('RSI', fontsize=10, fontweight='bold', color='blue')
            ax2.set_ylim(0, 100)
            ax2.tick_params(axis='y', labelcolor='blue')
            
            # 범례 통합 (좌측과 우측 모두 표시)
            lines1, labels1 = ax1.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=7)
            
            # x축 날짜 포맷 (마지막 행에만 x축 레이블 표시)
            if idx > (rows - 1) * cols:
                ax1.set_xlabel('시간', fontsize=10, fontweight='bold')
            
            # X축 최적화: 날짜 구분이 쉽도록
            # 주요 눈금: 3시간 간격 (09:00, 12:00, 15:00)
            ax1.xaxis.set_major_locator(mdates.HourLocator(interval=3))
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
            # 보조 눈금: 매일 00:00 (날짜 구분선)
            ax1.xaxis.set_minor_locator(mdates.DayLocator(interval=1))
            ax1.xaxis.set_minor_formatter(mdates.DateFormatter('\n%m/%d'))
            ax1.tick_params(axis='x', which='major', rotation=45, labelsize=7)
            ax1.tick_params(axis='x', which='minor', rotation=0, labelsize=7)
            ax1.grid(True, which='major', alpha=0.3)
            ax1.grid(True, which='minor', alpha=0.1, linestyle='--')
            
        except Exception as e:
            print(f"   ❌ {symbol_name}({symbol}) 그래프 오류: {e}")
            import traceback
            traceback.print_exc()
    
    print("✅ 그래프 생성 완료, 표시 중...")
    plt.tight_layout()
    plt.show()

def plot_rsi_trend(symbol, symbol_name, rsi_df):
    """RSI 추이 그래프 생성 (개별 종목용 - 사용 안 함)"""
    # 이 함수는 더 이상 사용하지 않음 (모든 종목을 한 페이지에 표시)
    pass

def check_rsi_for_all_symbols():
    """모든 종목의 RSI 추이 확인 및 그래프 표시"""
    print("=" * 80)
    print("한국 주식 RSI 추이 확인 (최근 3일)")
    print("=" * 80)
    
    # 토큰 발급
    if not ACCESS_TOKEN:
        get_access_token()
    
    current_time = datetime.datetime.now(timezone('Asia/Seoul'))
    print(f"조회 시간: {current_time.strftime('%Y-%m-%d %H:%M:%S')} (KST)\n")
    
    results = []
    all_rsi_data = []  # 모든 종목의 RSI 데이터 저장
    
    for symbol in SYMBOLS:
        symbol_name = SYMBOL_NAMES.get(symbol, symbol)
        print(f"\n[{symbol_name}({symbol})]")
        print("-" * 60)
        
        # 분봉 데이터 조회 (최근 1주일)
        data = get_minute_data(code=symbol, time_unit=MINUTE_CANDLE, period=336)
        if not data:
            print("❌ 분봉 데이터 조회 실패")
            results.append({
                'symbol': symbol,
                'symbol_name': symbol_name,
                'rsi': None,
                'current_price': None,
                'ma_20': None,
                'status': '데이터 조회 실패'
            })
            continue
        
        # RSI 시계열 계산
        print(f"📈 {symbol_name}({symbol}): RSI 계산 중...")
        rsi_df, current_rsi = calculate_rsi_series(data, periods=RSI_PERIOD)
        if rsi_df is None or current_rsi is None:
            print(f"❌ {symbol_name}({symbol}): RSI 계산 실패")
            results.append({
                'symbol': symbol,
                'symbol_name': symbol_name,
                'rsi': None,
                'current_price': None,
                'ma_20': None,
                'status': 'RSI 계산 실패'
            })
            continue
        
        # RSI 데이터가 있는지 확인
        if len(rsi_df) == 0:
            print(f"❌ {symbol_name}({symbol}): RSI 데이터가 비어있습니다")
            results.append({
                'symbol': symbol,
                'symbol_name': symbol_name,
                'rsi': None,
                'current_price': None,
                'ma_20': None,
                'status': 'RSI 데이터 없음'
            })
            continue
        
        # 현재가 조회 (실패해도 그래프는 표시)
        current_price = get_current_price(symbol)
        if current_price is None:
            print(f"⚠️ {symbol_name}({symbol}): 현재가 조회 실패 (과거 데이터로 그래프 표시)")
            # 그래프 데이터는 저장
            all_rsi_data.append((symbol, symbol_name, rsi_df))
            results.append({
                'symbol': symbol,
                'symbol_name': symbol_name,
                'rsi': current_rsi,
                'current_price': None,
                'ma_20': None,
                'status': '현재가 조회 실패'
            })
            continue
        
        # 이동평균 조회
        ma_20 = get_moving_average(symbol, period=20)
        
        # 결과 출력
        print(f"✅ {symbol_name}({symbol}): 분석 완료")
        print(f"   📊 현재 RSI ({RSI_PERIOD}일): {current_rsi:.2f}")
        print(f"   📊 RSI 범위: {rsi_df['rsi'].min():.2f} ~ {rsi_df['rsi'].max():.2f}")
        print(f"   💰 현재가: {current_price:,}원")
        if ma_20:
            price_diff = ((current_price - ma_20) / ma_20) * 100
            print(f"   📈 20일 이동평균: {ma_20:,.0f}원 (차이: {price_diff:+.2f}%)")
        
        # 매수/매도 조건 분석
        if current_rsi <= 28:
            print(f"   ✅ 매수 조건: RSI 과매도 구간")
        elif current_rsi >= 70:
            print(f"   🔴 매도 조건: RSI 과매수 구간")
        else:
            print(f"   ⚪ 중립 구간")
        
        # 그래프 데이터 저장
        all_rsi_data.append((symbol, symbol_name, rsi_df))
        
        results.append({
            'symbol': symbol,
            'symbol_name': symbol_name,
            'rsi': current_rsi,
            'rsi_min': rsi_df['rsi'].min(),
            'rsi_max': rsi_df['rsi'].max(),
            'current_price': current_price,
            'ma_20': ma_20,
            'price_diff_percent': ((current_price - ma_20) / ma_20) * 100 if (ma_20 and current_price) else None,
            'status': '정상'
        })
        
        time.sleep(0.5)  # API 호출 간격
    
    # 모든 종목의 그래프를 한 페이지에 표시
    if all_rsi_data:
        print(f"\n📈 전체 종목 RSI 추이 그래프 생성 중...")
        plot_all_rsi_trends(all_rsi_data)
    
    # 요약 출력
    print("\n" + "=" * 80)
    print("📊 전체 종목 RSI 요약")
    print("=" * 80)
    print(f"{'종목명':<15} {'종목코드':<10} {'RSI':<8} {'RSI범위':<15} {'현재가':<12} {'20일이평':<12} {'이평대비':<10} {'상태'}")
    print("-" * 100)
    
    for result in results:
        symbol_name = result['symbol_name']
        symbol = result['symbol']
        rsi = result['rsi']
        rsi_min = result.get('rsi_min')
        rsi_max = result.get('rsi_max')
        price = result['current_price']
        ma_20 = result['ma_20']
        price_diff = result.get('price_diff_percent')
        status = result['status']
        
        if rsi is not None:
            rsi_str = f"{rsi:.2f}"
        else:
            rsi_str = "N/A"
        
        if rsi_min is not None and rsi_max is not None:
            rsi_range_str = f"{rsi_min:.1f}~{rsi_max:.1f}"
        else:
            rsi_range_str = "N/A"
        
        if price is not None:
            price_str = f"{price:,}원"
        else:
            price_str = "N/A"
        
        if ma_20 is not None:
            ma_str = f"{ma_20:,.0f}원"
        else:
            ma_str = "N/A"
        
        if price_diff is not None:
            diff_str = f"{price_diff:+.2f}%"
        else:
            diff_str = "N/A"
        
        print(f"{symbol_name:<15} {symbol:<10} {rsi_str:<8} {rsi_range_str:<15} {price_str:<12} {ma_str:<12} {diff_str:<10} {status}")
    
    print("=" * 100)
    
    return results

if __name__ == "__main__":
    try:
        results = check_rsi_for_all_symbols()
    except KeyboardInterrupt:
        print("\n\n프로그램이 중단되었습니다.")
    except Exception as e:
        print(f"\n오류 발생: {e}")
        import traceback
        traceback.print_exc()
