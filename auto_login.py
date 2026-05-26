import os
import time
import json
import pyotp
import logging
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv, set_key
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from NorenRestApiPy.NorenApi import NorenApi

load_dotenv()

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class NorenApiPy(NorenApi):
    def __init__(self):
        super().__init__(host='https://api.shoonya.com/NorenWClientAPI/', websocket='wss://api.shoonya.com/NorenWS/')

    def getOAuthURL(self, oauth_url, client_id):
        return f"{oauth_url}?api_key={client_id}"


class ShoonyaAuthenticator:
    def __init__(self):
        load_dotenv()
        self.user_id = os.getenv("USER_ID")
        self.password = os.getenv("PASSWORD")
        self.totp_secret = os.getenv("TOTP") 
        self.vendor_code = os.getenv("VENDOR_CODE")
        self.secret_code = os.getenv("SECRET_CODE")
        self.login_url = f"https://trade.shoonya.com/OAuthlogin/investor-entry-level/login?api_key={self.vendor_code}&route_to={self.user_id}"
        self.api = NorenApiPy()

    def get_totp(self):
        return pyotp.TOTP(self.totp_secret).now()

    def _init_driver(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--blink-settings=imagesEnabled=false")
        chrome_options.page_load_strategy = 'eager'
        chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=chrome_options)

    def automated_login(self):
        """Captures auth code using Selenium"""
        logger.info("Starting automated Selenium login flow...")
        driver = self._init_driver()
        wait = WebDriverWait(driver, 20)
        
        try:
            driver.get(self.login_url)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']")))
            
            all_inputs = driver.find_elements(By.CSS_SELECTOR, "input:not([type='hidden']):not([type='checkbox']):not([type='radio'])")
            visible_inputs = [inp for inp in all_inputs if inp.is_displayed()]
            
            if len(visible_inputs) < 3:
                visible_inputs = [
                    driver.find_element(By.ID, "lgnusrid"),
                    driver.find_element(By.ID, "lgnpwd"),
                    driver.find_element(By.ID, "lgnotp")
                ]

            logger.info("Filling credentials...")
            visible_inputs[0].send_keys(self.user_id)
            visible_inputs[1].send_keys(self.password)
            visible_inputs[2].send_keys(self.get_totp())
            
            try:
                driver.find_element(By.XPATH, "//button[normalize-space()='LOGIN']").click()
            except:
                driver.find_element(By.CLASS_NAME, "lgnBtnClss").click()
                
            start_time = time.time()
            while time.time() - start_time < 30:
                logs = driver.get_log("performance")
                for entry in logs:
                    try:
                        message = json.loads(entry["message"])["message"]
                        if message.get("method") == "Network.requestWillBeSent":
                            url = message.get("params", {}).get("request", {}).get("url", "")
                            if "code=" in url and "shoonya" in url.lower():
                                parsed = urlparse(url)
                                code = parse_qs(parsed.query).get("code", [None])[0]
                                if code:
                                    logger.info(f"Auth code captured: {code}")
                                    return code
                    except: continue
                time.sleep(0.1)
            raise Exception("Timeout: Auth code not found.")
        finally:
            driver.quit()

    def run(self):
        """Orchestrates the full flow for strategy.py"""
        auth_code = self.automated_login()
        if not auth_code:
            return None
            
        logger.info("Exchanging auth code for access token...")
        result = self.api.getAccessToken(
            auth_code, 
            self.secret_code, 
            f"{self.user_id}_U", 
            self.user_id
        )
        
        if result is not None:
            acc_tok, usrid, ref_tok, actid = result
            logger.info(f"Access token retrieved for user {usrid}")
            
            # Update .env
            set_key(".env", "ACCESS_TOKEN", acc_tok)
            logger.info("Updated ACCESS_TOKEN in .env")
            
            return acc_tok
        return None

if __name__ == "__main__":
    authenticator = ShoonyaAuthenticator()
    token = authenticator.run()
    if token:
        logger.info("Login Flow Completed successfully.")
    else:
        logger.error("Login failed.")