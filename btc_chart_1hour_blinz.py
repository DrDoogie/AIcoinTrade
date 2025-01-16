from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException
from webdriver_manager.chrome import ChromeDriverManager
import time
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def setup_chrome_options():
    chrome_options = Options()
    chrome_options.add_argument("--window-size=1920,1080")  # 창 크기 설정
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--ignore-ssl-errors")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-web-security")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    return chrome_options

def create_driver():
    logger.info("ChromeDriver 설정 중...")
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=setup_chrome_options())
        driver.execute_cdp_cmd('Network.setUserAgentOverride', {"userAgent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        return driver
    except Exception as e:
        logger.error(f"드라이버 생성 중 오류: {e}")
        raise

def wait_and_click(driver, xpath, element_name, timeout=10):
    try:
        logger.info(f"{element_name} 대기 중...")
        element = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.XPATH, xpath))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", element)
        time.sleep(2)
        WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        ).click()
        logger.info(f"{element_name} 클릭 완료")
        time.sleep(2)
        return True
    except Exception as e:
        logger.error(f"{element_name} 클릭 실패: {e}")
        return False

def perform_chart_actions(driver):
    try:
        logger.info("차트 설정 시작")
        
        # 기본 페이지 로딩 대기
        time.sleep(10)
        
        # 팝업이나 알림창 처리 (필요한 경우)
        try:
            popup_close = driver.find_element(By.XPATH, "//button[contains(@class, 'close')]")
            if popup_close:
                popup_close.click()
        except:
            pass

        # 차트 영역이 로드될 때까지 대기
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "cq-chart-title"))
        )
        
        # 시간 설정
        success = wait_and_click(
            driver,
            "//cq-menu[contains(@class, 'period-menu')]",
            "시간 메뉴"
        )
        if success:
            wait_and_click(
                driver,
                "//cq-item[contains(text(), '1시간')]",
                "1시간 옵션"
            )

        # 지표 설정
        success = wait_and_click(
            driver,
            "//cq-menu[contains(@class, 'studies-menu')]",
            "지표 메뉴"
        )
        if success:
            wait_and_click(
                driver,
                "//cq-item[contains(text(), '볼린저 밴드')]",
                "볼린저 밴드"
            )

        logger.info("차트 설정 완료")
        time.sleep(5)  # 최종 설정 적용 대기
        
    except Exception as e:
        logger.error(f"차트 설정 중 오류: {e}")
        raise

def capture_screenshot(driver, filename):
    try:
        logger.info("스크린샷 촬영 준비 중...")
        
        # 페이지 전체 높이 구하기
        total_height = driver.execute_script("return Math.max( document.body.scrollHeight, document.body.offsetHeight, document.documentElement.clientHeight, document.documentElement.scrollHeight, document.documentElement.offsetHeight );")
        
        # 창 크기 설정
        driver.set_window_size(1920, total_height)
        time.sleep(2)
        
        # 스크린샷 촬영
        logger.info("스크린샷 촬영 중...")
        driver.save_screenshot(filename)
        logger.info(f"스크린샷 저장 완료: {filename}")
        
    except Exception as e:
        logger.error(f"스크린샷 촬영 중 오류: {e}")
        raise

def main():
    driver = None
    try:
        driver = create_driver()
        
        # 페이지 로드
        logger.info("업비트 차트 페이지 로딩 중...")
        driver.get("https://upbit.com/full_chart?code=CRIX.UPBIT.KRW-BTC")
        
        # 초기 로딩 대기
        time.sleep(15)
        
        # 차트 설정
        perform_chart_actions(driver)
        
        # 스크린샷 촬영
        capture_screenshot(driver, "upbit_btc_1hour_chart.png")
        
    except Exception as e:
        logger.error(f"오류 발생: {e}")
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    main()