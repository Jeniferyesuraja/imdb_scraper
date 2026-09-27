from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import pandas as pd
import time


options = webdriver.ChromeOptions()
options.add_argument("--start-maximized")

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=options
)


url = "https://www.coingecko.com/en"
print("Opening CoinGecko...")
driver.get(url)


wait = WebDriverWait(driver, 15)
rows = wait.until(
    EC.presence_of_all_elements_located((By.CSS_SELECTOR, "table tbody tr"))
)

print("Rows found:", len(rows))

data = []


for row in rows[:10]:
    try:
        cells = row.find_elements(By.TAG_NAME, "td")

        coin_name = cells[2].text
        price = cells[3].text
        change_24h = cells[4].text
        market_cap = cells[7].text

        print("\n-----------------------------")
        print("Coin:", coin_name)
        print("Price:", price)
        print("24h Change:", change_24h)
        print("Market Cap:", market_cap)

        data.append({
            "Coin Name": coin_name,
            "Price": price,
            "24h Change": change_24h,
            "Market Cap": market_cap
        })

    except Exception as e:
        print("Error:", e)


print("\n===================================")
print("TOP 10 CRYPTOCURRENCY DATA")
print("===================================")

if len(data) == 0:
    print("No data found")
else:
    df = pd.DataFrame(data)
    print(df)

    file_name = "crypto_prices.csv"
    df.to_csv(file_name, index=False, encoding="utf-8")

    print("\nCSV FILE CREATED SUCCESSFULLY!")
    print("File:", file_name)


time.sleep(5)
driver.quit()

print("\nProgram completed.")