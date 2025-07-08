from news_scrapers import HindustanTimesScraper, BusinessStandardScraper, News18Scraper

scraper = News18Scraper()
articles = scraper.search("bangladesh", page=1, size=20)
for article in articles:
    print(f"{article.published_at} – {article.author} - {article.title}\n{article.url}\n{article.summary}\n"
          f"{article.media}\n{article.tags} - {article.section}\n")
print(f"{len(articles)} articles found")
