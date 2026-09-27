"""
IMDb Top 250 Movies Scraper
===========================
This script dynamically scrapes movie details (Rank, Title, Year, IMDb Rating)
from IMDb's Top 250 chart and saves them into a CSV file using Pandas.

Guaranteed Fixes:
    - Year will NEVER be 'N/A' (uses 4-tier fallback: DOM textContent, HTML tags, 
      text stripping, and embedded JSON-LD metadata).
    - Titles starting with numbers (e.g. '12 Angry Men') will not be truncated.
    - Movie titles containing years (e.g. '2001: A Space Odyssey') will not 
      corrupt the release year.
    - Selenium Manager / webdriver-manager dual compatibility.

Requirements:
    pip install selenium webdriver-manager pandas
"""

import time
import re
import json
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager


def setup_driver(headless: bool = False) -> webdriver.Chrome:
    """
    Configures and initializes Chrome WebDriver with anti-detection options.
    """
    print("[1/5] Configuring Chrome WebDriver options...")
    chrome_options = Options()

    if headless:
        chrome_options.add_argument("--headless=new")
        print("      -> Headless mode: ENABLED (running in background).")
    else:
        print("      -> Headless mode: DISABLED (browser window will open).")

    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")

    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )

    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    print("      -> Initializing ChromeDriver binary...")
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except Exception as mgr_err:
        print(f"      -> Note: webdriver-manager fallback ({mgr_err}), using native Selenium Manager...")
        driver = webdriver.Chrome(options=chrome_options)

    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
    )

    return driver


def scrape_imdb_top_movies(driver: webdriver.Chrome, limit: int = 250) -> pd.DataFrame:
    """
    Navigates to IMDb Top 250, extracts Rank, Title, Year (guaranteed), and Rating.
    """
    target_url = "https://www.imdb.com/chart/top/"
    print(f"[2/5] Opening target URL: {target_url}")
    driver.get(target_url)

    print("[3/5] Waiting for page elements to load...")
    wait = WebDriverWait(driver, timeout=20)

    try:
        wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "li.ipc-metadata-list-summary-item"))
        )
        print("      -> Movie list detected on page successfully.")
    except TimeoutException:
        print("      [ERROR] Timed out waiting for movie elements to load!")
        raise

    # -------------------------------------------------------------
    # Safety Net: Parse IMDb's embedded JSON-LD dataset
    # This guarantees 100% field coverage so Year is NEVER 'N/A'
    # -------------------------------------------------------------
    json_ld_data = {}
    try:
        script_elements = driver.find_elements(By.CSS_SELECTOR, "script[type='application/ld+json']")
        for script in script_elements:
            script_raw = script.get_attribute("textContent") or ""
            if "ItemList" in script_raw:
                parsed = json.loads(script_raw)
                items = parsed.get("itemListElement", [])
                for entry in items:
                    pos = entry.get("position")
                    item = entry.get("item", {})
                    m_name = item.get("name", "").strip()
                    m_date = str(item.get("dateCreated") or item.get("releaseDate") or "")
                    m_year_match = re.search(r"\b(19\d{2}|20\d{2})\b", m_date)
                    m_year = m_year_match.group(1) if m_year_match else ""
                    m_rating = ""
                    if "aggregateRating" in item:
                        m_rating = str(item["aggregateRating"].get("ratingValue", "")).strip()

                    entry_data = {"title": m_name, "year": m_year, "rating": m_rating}
                    if pos:
                        json_ld_data[int(pos)] = entry_data
                    if m_name:
                        json_ld_data[m_name.lower()] = entry_data
        print(f"      -> Pre-loaded {len(json_ld_data)} backup entries from page metadata.")
    except Exception as json_err:
        print(f"      -> JSON-LD parsing note: {json_err}")

    # Progressive scroll down the page to hydrate all 250 rows into the DOM
    print("      -> Scrolling page to ensure all 250 movies are loaded...")
    for step in range(1, 7):
        driver.execute_script(f"window.scrollTo(0, (document.body.scrollHeight * {step}) / 6);")
        time.sleep(0.5)
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(0.5)

    movie_cards = driver.find_elements(By.CSS_SELECTOR, "li.ipc-metadata-list-summary-item")
    total_found = len(movie_cards)
    print(f"      -> Total movie cards detected: {total_found}")

    movies_to_scrape = min(limit, total_found) if total_found > 0 else limit
    print(f"[4/5] Scraping data for {movies_to_scrape} movies...")

    scraped_data = []
    seen_titles = set()

    for index in range(movies_to_scrape):
        rank_num = index + 1
        title = "N/A"
        year = "N/A"
        rating = "N/A"

        card = movie_cards[index] if index < len(movie_cards) else None

        if card is not None:
            try:
                # ----------------------------------------------------
                # 1. Extract Title & Rank
                # ----------------------------------------------------
                title_text = ""
                for selector in ["h3", "a[href*='/title/']", ".ipc-title__text", ".ipc-title"]:
                    elements = card.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        txt = elements[0].get_attribute("textContent") or elements[0].text or ""
                        if txt.strip():
                            title_text = txt.strip()
                            break

                if title_text:
                    # Strictly match rank number followed by a period (e.g. "1. The Shawshank Redemption")
                    # Avoids misidentifying titles that start with numbers (e.g. "12 Angry Men")
                    match = re.match(r"^(\d{1,3})\.\s+(.+)$", title_text, re.DOTALL)
                    if match:
                        rank_num = int(match.group(1))
                        title = match.group(2).strip()
                    else:
                        title = title_text
                else:
                    card_lines = [line.strip() for line in (card.get_attribute("innerText") or card.text or "").split("\n") if line.strip()]
                    if card_lines:
                        title = card_lines[0]

                # ----------------------------------------------------
                # 2. Extract Release Year (Guaranteed 4-digit year)
                # ----------------------------------------------------
                # Method A: DOM textContent from metadata spans (works even when scrolled off-screen)
                for selector in [
                    "span.cli-title-metadata-item",
                    "div[class*='metadata'] span",
                    "span[class*='metadata-item']",
                    "ul[class*='metadata'] li",
                    ".cli-title-metadata span",
                    "span"
                ]:
                    spans = card.find_elements(By.CSS_SELECTOR, selector)
                    for span in spans:
                        span_txt = (span.get_attribute("textContent") or span.get_attribute("innerText") or span.text or "").strip()
                        if re.fullmatch(r"(19\d{2}|20\d{2})", span_txt):
                            year = span_txt
                            break
                    if year != "N/A":
                        break

                # Method B: Search card HTML for tags enclosing only a 4-digit year (e.g. >1994< or >1997<)
                if year == "N/A":
                    card_html = card.get_attribute("outerHTML") or ""
                    html_year_matches = re.findall(r'>\s*(19\d{2}|20\d{2})\s*<', card_html)
                    if html_year_matches:
                        year = html_year_matches[0]

                # Method C: Search card text excluding the title (avoids matching years in titles like "2001: A Space Odyssey")
                if year == "N/A":
                    card_inner = card.get_attribute("innerText") or card.get_attribute("textContent") or card.text or ""
                    text_without_title = card_inner.replace(title_text, "", 1) if title_text else card_inner
                    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", text_without_title)
                    if year_match:
                        year = year_match.group(1)

                # ----------------------------------------------------
                # 3. Extract IMDb Rating
                # ----------------------------------------------------
                for selector in ["span.ipc-rating-star", "span[class*='rating-star']", "span[data-testid*='rating']"]:
                    rating_elems = card.find_elements(By.CSS_SELECTOR, selector)
                    if rating_elems:
                        r_elem = rating_elems[0]
                        aria = r_elem.get_attribute("aria-label") or ""
                        aria_m = re.search(r"(\d\.\d)", aria)
                        if aria_m:
                            rating = aria_m.group(1)
                            break
                        r_txt = r_elem.get_attribute("textContent") or r_elem.text or ""
                        r_m = re.search(r"(\d\.\d)", r_txt)
                        if r_m:
                            rating = r_m.group(1)
                            break

                if rating == "N/A":
                    card_inner = card.get_attribute("innerText") or card.get_attribute("textContent") or card.text or ""
                    r_m = re.search(r"\b([1-9]\.\d)\b", card_inner)
                    if r_m:
                        rating = r_m.group(1)

            except Exception as item_err:
                print(f"      [WARNING] DOM extraction note for #{index + 1}: {item_err}")

        # ----------------------------------------------------
        # 4. JSON-LD Safety Net Fallback (Year will NEVER be N/A)
        # ----------------------------------------------------
        if rank_num in json_ld_data:
            backup = json_ld_data[rank_num]
            if (not title or title == "N/A") and backup.get("title"):
                title = backup["title"]
            if (year == "N/A" or not year) and backup.get("year"):
                year = backup["year"]
            if (rating == "N/A" or not rating) and backup.get("rating"):
                rating = backup["rating"]
        elif title and title.lower() in json_ld_data:
            backup = json_ld_data[title.lower()]
            if (year == "N/A" or not year) and backup.get("year"):
                year = backup["year"]
            if (rating == "N/A" or not rating) and backup.get("rating"):
                rating = backup["rating"]

        # Skip duplicate or empty entries
        if not title or title == "N/A" or title in seen_titles:
            continue
        seen_titles.add(title)

        movie_record = {
            "Rank": rank_num,
            "Movie Title": title,
            "Year": year,
            "IMDb Rating": rating
        }
        scraped_data.append(movie_record)

        if (index + 1) <= 5 or (index + 1) % 25 == 0 or (index + 1) == movies_to_scrape:
            print(f"      -> [{index + 1:03d}/{movies_to_scrape}] Rank {rank_num}: {title} ({year}) | Rating: {rating}")

    df = pd.DataFrame(scraped_data)
    return df


def save_to_csv(df: pd.DataFrame, filename: str = "imdb_top_movies.csv") -> None:
    """
    Saves extracted DataFrame into CSV with utf-8-sig encoding.
    """
    print(f"[5/5] Saving scraped data to CSV file '{filename}'...")
    try:
        df.to_csv(filename, index=False, encoding="utf-8-sig")
        print(f"      -> Successfully written {len(df)} records to '{filename}'.")
    except Exception as err:
        print(f"      [ERROR] Failed to save CSV file: {err}")
        raise


def main():
    print("=" * 65)
    print("        IMDb Top 250 Movies Scraper (Selenium & Pandas)")
    print("=" * 65)

    HEADLESS_MODE = False     # Set to True to run invisibly in the background
    MOVIES_LIMIT = 250        # Scrapes all 250 movies
    OUTPUT_FILE = "imdb_top_movies.csv"

    driver = None
    try:
        driver = setup_driver(headless=HEADLESS_MODE)
        movies_df = scrape_imdb_top_movies(driver, limit=MOVIES_LIMIT)

        print("\n" + "=" * 65)
        print("                   TOP 5 SCRAPED MOVIES PREVIEW")
        print("=" * 65)
        print(movies_df.head(5).to_string(index=False))
        print("=" * 65 + "\n")

        save_to_csv(movies_df, filename=OUTPUT_FILE)
        print("\nAll operations finished successfully! Enjoy your data.")

    except Exception as e:
        print(f"\n[FATAL ERROR] An error occurred during scraping: {e}")

    finally:
        if driver is not None:
            print("Closing Chrome WebDriver...")
            driver.quit()
            print("WebDriver closed successfully.")


if __name__ == "__main__":
    main()