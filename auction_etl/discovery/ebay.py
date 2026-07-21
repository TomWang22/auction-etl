from bs4 import BeautifulSoup


def extract_listing_urls(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")

    urls = []

    for a in soup.select("a.s-item__link"):
        href = a.get("href")

        if href and href.startswith("https://www.ebay."):
            urls.append(href.split("?")[0])

    return sorted(set(urls))
