from news_scrapers import (BaseNewsScraper,
                           HindustanTimesScraper,
                           BusinessStandardScraper,
                           News18Scraper,
                           FirstpostScraper,
                           RepublicWorldScraper,
                           IndiaDotComScraper,
                           StatesmanScraper,
                           DailyPioneerScraper,)

scraper: BaseNewsScraper = DailyPioneerScraper()
articles = scraper.search("bangladesh", page=1, size=50)
for article in articles:
    print(f"{article.published_at} – {article.outlet} - {article.author} - {article.title}\n"
          f"{article.url}\n"
          f"Summary: {article.summary}\n"
          f"Content: {article.content[:120] if article.content else ''} ...\n"
          f"{article.media}\n"
          f"{article.tags} - {article.section}\n")
print(f"{len(articles)} articles found")
