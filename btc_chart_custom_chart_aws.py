from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, NoSuchElementException
import time
import logging
import os

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('upbit_chart.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# XPath 상수 정의 (이전과 동일)
XPATHS = {
    'time_menu': "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[1]/span/cq-clickable",
    'one_hour': "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[1]/cq-menu-dropdown/cq-item[8]",
    'indicator_menu': "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]",
    'bollinger_bands': "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]/cq-menu-dropdown/cq-scroll/cq-studies/cq-studies-content/cq-item[15]",
    'rsi': "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]/cq-menu-dropdown/cq-scroll/cq-studies/cq-studies-content/cq-item[81]",
    'stochastic': "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]/cq-menu-dropdown/cq-scroll/cq-studies/cq-studies-content/cq-item[92]",
    'volume_osc': "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]/cq-menu-dropdown/cq-scroll/cq-studies/cq-studies-content/cq-item[108]",
    'atr': "/html/body/div[1]/div[2]/div[3]/div/section/article/span[2]/div[1]/span[2]",
    'menu_close_area': "/html/body/div[1]/div[2]/div[3]/div/section/article/span[2]/div[1]/span[2]"
}

def setup_chrome_options():
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    chrome_options.binary_location = '/usr/bin/google-chrome'  # EC2의 Chrome 위치
    return chrome_options

def create_driver():
    logger.info("ChromeDriver 설정 중...")
    try:
        chrome_options = setup_chrome_options()
        service = Service(executable_path='/usr/local/bin/chromedriver')  # EC2의 ChromeDriver 위치
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except Exception as e:
        logger.error(f"ChromeDriver 설정 중 오류 발생: {e}")
        raise

# 스크린샷 저장 디렉토리 생성
def ensure_screenshot_dir():
    screenshot_dir = 'screenshots'
    if not os.path.exists(screenshot_dir):
        os.makedirs(screenshot_dir)
    return screenshot_dir

def click_element_by_xpath(driver, xpath, element_name, wait_time=10):
    try:
        # 요소가 보일 때까지 스크롤
        element = WebDriverWait(driver, wait_time).until(
            EC.presence_of_element_located((By.XPATH, xpath))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", element)
        
        # 요소가 클릭 가능할 때까지 대기
        element = WebDriverWait(driver, wait_time).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        )
        element.click()
        logger.info(f"{element_name} 클릭 완료")
        time.sleep(0.5)  # 클릭 후 최소 대기
    except TimeoutException:
        logger.error(f"{element_name} 요소를 찾는 데 시간이 초과되었습니다.")
        raise
    except ElementClickInterceptedException:
        logger.error(f"{element_name} 요소를 클릭할 수 없습니다. 다른 요소에 가려져 있을 수 있습니다.")
        raise
    except NoSuchElementException:
        logger.error(f"{element_name} 요소를 찾을 수 없습니다.")
        raise
    except Exception as e:
        logger.error(f"{element_name} 클릭 중 오류 발생: {e}")
        raise

def setup_chart_timeframe(driver):
    logger.info("차트 시간 단위 설정 시작")
    try:
        # 시간 메뉴 클릭
        click_element_by_xpath(driver, XPATHS['time_menu'], "시간 메뉴")
        # 1시간 옵션 선택
        click_element_by_xpath(driver, XPATHS['one_hour'], "1시간 옵션")
        logger.info("차트 시간 단위 설정 완료")
    except Exception as e:
        logger.error(f"차트 시간 단위 설정 중 오류 발생: {e}")
        raise

def add_technical_indicators(driver):
    logger.info("기술적 지표 추가 시작")
    try:
        # 지표 메뉴 클릭
        click_element_by_xpath(driver, XPATHS['indicator_menu'], "지표 메뉴")
        
        # 각 지표 추가
        indicators = {
            'bollinger_bands': '볼린저 밴드',
            'rsi': 'RSI',
            'stochastic': '스토캐스틱',
            'volume_osc': 'Volume OSC',
            'atr': 'ATR'
        }
        
        for i, (xpath_key, indicator_name) in enumerate(indicators.items()):
            click_element_by_xpath(driver, XPATHS[xpath_key], indicator_name)
            # 마지막 지표가 아닐 경우에만 지표 메뉴 다시 클릭
            if i < len(indicators) - 1:
                click_element_by_xpath(driver, XPATHS['indicator_menu'], "지표 메뉴")
        
        # 마지막에 빈 영역 클릭해서 메뉴 닫기
        time.sleep(0.5)  # 마지막 지표가 적용될 때까지 최소 대기
        click_element_by_xpath(driver, XPATHS['menu_close_area'], "메뉴 닫기를 위한 빈 영역")
        
        logger.info("기술적 지표 추가 완료")
    except Exception as e:
        logger.error(f"기술적 지표 추가 중 오류 발생: {e}")
        raise

def capture_full_page_screenshot(driver, filename):
    try:
        logger.info("전체 페이지 스크린샷 촬영 준비 중...")
        time.sleep(2)  # 최종 차트 로딩을 위한 대기
        
        screenshot_dir = ensure_screenshot_dir()
        screenshot_path = os.path.join(screenshot_dir, filename)
        
        logger.info("전체 페이지 스크린샷 촬영 중...")
        driver.save_screenshot(screenshot_path)
        logger.info(f"스크린샷이 성공적으로 저장되었습니다: {screenshot_path}")
    except Exception as e:
        logger.error(f"스크린샷 촬영 중 오류 발생: {e}")
        raise

def setup_upbit_chart(url, screenshot_filename="Upbit.png"):
    driver = None
    try:
        driver = create_driver()
        logger.info(f"업비트 차트 페이지 로딩 중: {url}")
        driver.get(url)
        
        # 초기 페이지 로딩 대기
        logger.info("페이지 로딩 대기 중...")
        time.sleep(10)  # 페이지 로딩을 위해 10초 대기
        
        # 차트 시간 단위 설정
        setup_chart_timeframe(driver)
        
        # 기술적 지표 추가
        add_technical_indicators(driver)
        
        # 최종 스크린샷 촬영
        capture_full_page_screenshot(driver, screenshot_filename)
        
        logger.info("모든 작업이 완료되었습니다.")
        
    except Exception as e:
        logger.error(f"차트 설정 중 오류 발생: {e}")
        raise
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    try:
        upbit_url = "https://upbit.com/full_chart?code=CRIX.UPBIT.KRW-BTC"
        setup_upbit_chart(upbit_url)
    except Exception as e:
        logger.error(f"프로그램 실행 중 오류 발생: {e}")