from news_scrapers import (HindustanTimesScraper,
                           BusinessStandardScraper,
                           News18Scraper,
                           FirstpostScraper,
                           RepublicWorldScraper,)

scraper = RepublicWorldScraper()
articles = scraper.search("bangladesh", page=1, size=50)
for article in articles:
    print(f"{article.published_at} – {article.outlet} - {article.author} - {article.title}\n"
          f"{article.url}\n"
          f"Summary: {article.summary}\n"
          f"Content: {article.content[:120]} ...\n"
          f"{article.media}\n"
          f"{article.tags} - {article.section}\n")
print(f"{len(articles)} articles found")
