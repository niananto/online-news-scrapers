import requests
import json
import psycopg2
import os
from typing import List, Dict, Any
import uuid
from datetime import datetime

# Configuration - Database config only
CONFIG = {
    'server_url': 'http://localhost:8000/scrape',
    'keyword': 'bangladesh',
    'db_config': {
        'host': os.getenv('DB_HOST', 'localhost'),
        'database': 'shottify_db',
        'user': os.getenv('DB_USER', 'postgres'),
        'password': os.getenv('DB_PASSWORD', 'shottify123'),
        'port': os.getenv('DB_PORT', '5432')
    }
}

# Mapping from display names to API outlet names
OUTLET_MAPPING = {

    "India.com": "india_dotcom",
    "The Statesman": "statesman",
    "South Asia Monitor": "south_asia_monitor",
    "News18": "news18",
    "Economic Times": "economic_times",
    "Firstpost": "firstpost",
    "Republic World": "republic_world",
    "India Today": "india_today",
    "Business Standard": "business_standard",
    "The Pioneer": "daily_pioneer",
    "Hindustan Times": "hindustan_times"
}

def get_source_id_by_platform(platform_name: str, cursor) -> str:
    """Get source_id from sources table by platform name"""
    cursor.execute("SELECT id FROM sources WHERE platform = %s LIMIT 1", (platform_name,))
    result = cursor.fetchone()
    if result:
        return result[0]
    else:
        # If not found, create a new source entry
        source_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO sources (id, source_type, platform, url) 
            VALUES (%s, %s, %s, %s)
        """, (source_id, 'news portal', platform_name, ''))
        return source_id

def get_user_input():
    """Get user input for outlets, limit, and page_size"""
    print("Available outlets:")
    for i, outlet in enumerate(sorted(OUTLET_MAPPING.keys()), 1):
        print(f"  {i}. {outlet}")
    
    print("\nEnter outlet names EXACTLY as shown above (case-sensitive)")
    
    # Get outlets
    outlets_input = input("\nEnter outlet names (comma-separated for multiple): ").strip()
    outlet_names = [name.strip() for name in outlets_input.split(',')]
    
    # Validate outlet names
    valid_outlets = []
    api_outlets = []
    for outlet in outlet_names:
        if outlet in OUTLET_MAPPING:
            valid_outlets.append(outlet)
            api_outlets.append(OUTLET_MAPPING[outlet])
            print(f"✓ '{outlet}' → API: '{OUTLET_MAPPING[outlet]}'")
        else:
            print(f"✗ '{outlet}' is not a valid outlet. Skipping...")
    
    if not valid_outlets:
        print("No valid outlets found. Exiting...")
        exit(1)
    
    # Get limit
    while True:
        try:
            limit = int(input("\nEnter limit (1-500): ").strip())
            if 1 <= limit <= 500:
                break
            else:
                print("Limit must be between 1 and 500")
        except ValueError:
            print("Please enter a valid number")
    
    # Get page_size
    while True:
        try:
            page_size = int(input("Enter page size (1-100): ").strip())
            if 1 <= page_size <= 100:
                break
            else:
                print("Page size must be between 1 and 100")
        except ValueError:
            print("Please enter a valid number")
    
    return valid_outlets, api_outlets, limit, page_size

def call_scraper_api(outlet: str, keyword: str, limit: int, page_size: int) -> List[Dict[Any, Any]]:
    """Call the FastAPI scraper endpoint"""
    payload = {
        'outlet': outlet,
        'keyword': keyword,
        'limit': limit,
        'page_size': page_size
    }
    
    try:
        print(f"Calling API for outlet: {outlet}")
        response = requests.post(CONFIG['server_url'], json=payload)
        response.raise_for_status()
        
        articles = response.json()
        print(f"Received {len(articles)} articles from {outlet}")
        return articles
        
    except requests.exceptions.RequestException as e:
        print(f"Error calling API for {outlet}: {e}")
        return []

def transform_article_data(article: Dict[Any, Any]) -> Dict[Any, Any]:
    """Transform article data to match database schema"""
    transformed = {
        'title': article.get('title'),
        'published_at': article.get('published_at'),
        'url': article.get('url'),
        'content_text': article.get('content'),  # Changed from 'content' to 'content_text'
        'summary': article.get('summary'),
        'author_name': article.get('author'),    # Changed from 'author' to 'author_name'
        'media': article.get('media', []),
        'platform': article.get('outlet'),       # Changed from 'outlet' to 'platform'
        'tags': article.get('tags', []),
        'section': article.get('section')
    }
    
    # Remove None values to keep JSON clean
    return {k: v for k, v in transformed.items() if v is not None}

def insert_articles_to_db(articles: List[Dict[Any, Any]], outlet: str):
    """Insert articles into content_items table"""
    try:
        # Connect to database
        conn = psycopg2.connect(**CONFIG['db_config'])
        cursor = conn.cursor()
        
        # Get source_id for the outlet
        source_id = get_source_id_by_platform(outlet, cursor)
        
        # Transform and insert each article
        inserted_count = 0
        for article in articles:
            try:
                # Transform the article data
                transformed_article = transform_article_data(article)
                
                # Prepare data for insertion
                raw_data = json.dumps(transformed_article)
                
                # Extract fields that match database columns
                title = transformed_article.get('title')
                content_text = transformed_article.get('content_text')
                url = transformed_article.get('url')
                author_name = transformed_article.get('author_name')
                published_at_text = transformed_article.get('published_at')
                platform = transformed_article.get('platform')
                
                # Convert author to string if it's a list
                if isinstance(author_name, list):
                    author_name = ', '.join(author_name) if author_name else None
                
                # Insert into database (excluding last_updated to keep it empty)
                insert_sql = """
                INSERT INTO content_items (
                    source_id, 
                    raw_data, 
                    title, 
                    content_text, 
                    url, 
                    author_name, 
                    published_at_text,
                    platform,
                    content_type,
                    language,
                    processing_status,
                    ingested_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                
                cursor.execute(insert_sql, (
                    source_id,
                    raw_data,
                    title,
                    content_text,
                    url,
                    author_name,
                    published_at_text,
                    platform,
                    'News article',      # default content_type
                    'English',      # default language
                    'Pending',      # default processing_status
                    datetime.now()  # explicitly set ingested_at, last_updated will remain empty
                ))
                
                inserted_count += 1
                
            except Exception as e:
                print(f"Error inserting article: {e}")
                continue
        
        # Commit all insertions
        conn.commit()
        print(f"Successfully inserted {inserted_count} articles from {outlet}")
        
    except psycopg2.Error as e:
        print(f"Database error: {e}")
        if conn:
            conn.rollback()
    
    except Exception as e:
        print(f"Unexpected error: {e}")
        if conn:
            conn.rollback()
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def main():
    """Main function to scrape and populate content"""
    print("=" * 60)
    print("           CONTENT POPULATION TOOL")
    print("=" * 60)
    
    # Get user input
    display_outlets, api_outlets, limit, page_size = get_user_input()
    
    print(f"\nConfiguration:")
    print(f"  Display Outlets: {display_outlets}")
    print(f"  API Outlets: {api_outlets}")
    print(f"  Keyword: {CONFIG['keyword']}")
    print(f"  Limit: {limit}")
    print(f"  Page Size: {page_size}")
    print("=" * 60)
    
    total_articles = 0
    
    for display_outlet, api_outlet in zip(display_outlets, api_outlets):
        print(f"\nProcessing outlet: {display_outlet} (API: {api_outlet})")
        
        # Call the scraper API using the API outlet name
        articles = call_scraper_api(
            outlet=api_outlet,
            keyword=CONFIG['keyword'],
            limit=limit,
            page_size=page_size
        )
        
        if articles:
            # Insert articles into database using the display outlet name for source lookup
            insert_articles_to_db(articles, display_outlet)
            total_articles += len(articles)
        else:
            print(f"No articles received from {display_outlet}")
    
    print("=" * 60)
    print(f"Content population completed!")
    print(f"Total articles processed: {total_articles}")
    print("=" * 60)

if __name__ == "__main__":
    main()