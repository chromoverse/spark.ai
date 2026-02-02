async def fetch_web_results_with_selenium(query, limit=5):
    """
    Fetch Google search results using Selenium with headless Chrome.
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from webdriver_manager.chrome import ChromeDriverManager
    import time
    
    options = Options()
    # options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_argument("--lang=en")  # Force English results
    
    driver = None
    results = []
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        
        # Navigate to Google search
        search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}&hl=en"
        driver.get(search_url)
        
        time.sleep(3)  # Wait for page to fully load
        
        # Find all search result containers
        result_elements = driver.find_elements(By.CSS_SELECTOR, "div.g")
        print(f"[DEBUG] Found {len(result_elements)} result elements")
        
        if not result_elements:
            # Try alternative selector
            result_elements = driver.find_elements(By.XPATH, "//div[@class='g' or contains(@class, 'tF2Cxc')]")
            print(f"[DEBUG] Alternative selector found {len(result_elements)} elements")
        
        # Extract information from each result
        for idx, element in enumerate(result_elements[:limit * 2]):  # Get extra to filter later
            try:
                title = None
                url = None
                snippet = None
                
                # Method 1: Try standard structure
                try:
                    # Get the link element first (most reliable)
                    link = element.find_element(By.XPATH, ".//a[@href]")
                    url = link.get_attribute("href")
                    
                    # Skip non-http URLs (like javascript:)
                    if not url or not url.startswith("http"):
                        continue
                    
                    # Get title from h3 within the link or nearby
                    try:
                        title_elem = element.find_element(By.XPATH, ".//h3")
                        title = title_elem.text.strip()
                    except:
                        # Try getting from the link text
                        title = link.text.strip()
                    
                    # Get snippet
                    try:
                        snippet_elem = element.find_element(By.XPATH, ".//div[contains(@class, 'VwiC3b') or contains(@data-sncf, '1')]")
                        snippet = snippet_elem.text.strip()
                    except:
                        try:
                            # Alternative snippet location
                            snippet_elem = element.find_element(By.XPATH, ".//span[contains(@class, 'aCOpRe')]")
                            snippet = snippet_elem.text.strip()
                        except:
                            snippet = ""
                    
                except Exception as e:
                    print(f"[DEBUG] Method 1 failed for element {idx}: {str(e)}")
                    continue
                
                # Validate and add result
                if title and url and len(title) > 0:
                    results.append({
                        "title": title,
                        "url": url,
                        "snippet": snippet or "No description available"
                    })
                    print(f"[DEBUG] ✓ Result {len(results)}: {title[:60]}...")
                    
                    if len(results) >= limit:
                        break
                else:
                    print(f"[DEBUG] ✗ Skipped element {idx}: title='{title}', url='{url}'")
                
            except Exception as e:
                print(f"[DEBUG] Error processing element {idx}: {str(e)}")
                continue
        
        # If no results, try to debug
        if not results:
            print("[DEBUG] No valid results extracted")
            print(f"[DEBUG] Page title: {driver.title}")
            
            # Try to find ANY links on the page for debugging
            all_links = driver.find_elements(By.XPATH, "//a[@href]")
            print(f"[DEBUG] Total links found on page: {len(all_links)}")
            
            # Sample first few search results manually
            try:
                sample_results = driver.find_elements(By.XPATH, "//h3")
                print(f"[DEBUG] H3 elements found: {len(sample_results)}")
                for i, h3 in enumerate(sample_results[:3]):
                    print(f"[DEBUG] H3 #{i}: {h3.text[:100]}")
            except:
                pass
        
    except Exception as e:
        print(f"[ERROR] Selenium search failed: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        if driver:
            driver.quit()
    
    return results

async def fetch_bing_results_with_selenium(query, limit=5):
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    import time

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    driver.get(f"https://www.bing.com/search?q={query.replace(' ', '+')}")
    time.sleep(4)

    results = []
    items = driver.find_elements(By.CSS_SELECTOR, "li.b_algo")

    for item in items[:limit]:
        try:
            title = item.find_element(By.TAG_NAME, "h2").text
            url = item.find_element(By.TAG_NAME, "a").get_attribute("href")
            snippet = item.find_element(By.CLASS_NAME, "b_caption").text
            results.append({"title": title, "url": url, "snippet": snippet})
        except:
            continue

    driver.quit()
    return results