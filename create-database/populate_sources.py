import psycopg2
import os
import uuid
from datetime import datetime

def generate_uuid():
    """Generate a valid UUID string"""
    return str(uuid.uuid4())

def populate_sources_table():
    """
    Populates the sources table with 30 news sources from the news_source_list
    """
    
    # Database connection parameters
    db_config = {
        'host': os.getenv('DB_HOST', 'localhost'),
        'database': 'shottify_db_new',
        'user': os.getenv('DB_USER', 'postgres'),
        'password': os.getenv('DB_PASSWORD', 'shottify123'),
        'port': os.getenv('DB_PORT', '5432')
    }
    
    # Media outlets data from news_source_list.png (30 sources)
    media_outlets = [
        ('Indian Express', 'https://indianexpress.com/about/bangladesh/'),
        ('Hindustan Times', 'https://www.hindustantimes.com/search'),
        ('The Pioneer', 'https://www.dailypioneer.com/searchlist.php?searchword=bangladesh'),
        ('The Hindu', 'https://www.thehindu.com/search/#gsc.tab=0&gsc.q=bangladesh'),
        ('Millennium Post', 'https://www.millenniumpost.in/search?search=bangladesh'),
        ('Times of India', 'https://timesofindia.indiatimes.com/topic/Bangladesh'),
        ('The Tribune', 'https://www.tribuneindia.com/topic/bangladesh'),
        ('India.com', 'https://www.india.com/searchresult/?cx=partner-pub-...'),
        ('The Statesman', 'https://www.thestatesman.com/?s=bangladesh'),
        ('Business Standard', 'https://www.business-standard.com/search?q=bangladesh'),
        ('Economic Times', 'https://economictimes.indiatimes.com/topic/bangladesh'),
        ('Deccan Herald', 'https://www.deccanherald.com/search?q=bangladesh'),
        ('The Telegraph India', 'https://www.telegraphindia.com/search-results?q=bangladesh'),
        ('NDTV', 'https://www.ndtv.com/search?searchtext=bangladesh'),
        ('India Today', 'https://www.indiatoday.in/topic/bangladesh'),
        ('News18', 'https://www.news18.com/search/?search_text=bangladesh'),
        ('abplive', 'https://news.abplive.com/search?s=bangladesh'),
        ('Firstpost', 'https://www.firstpost.com/tag/bangladesh/'),
        ('republicworld', 'https://www.republicworld.com/search?query=bangladesh'),
        ('WION', 'https://www.wionews.com/search?page=1&title=bangladesh'),
        ('Quint', 'https://www.thequint.com/search?q=Bangladesh'),
        ('Aljazeera', 'https://aljazeera.com/search/bangladesh'),
        ('Reuters', 'https://www.reuters.com/site-search/?query=bangladesh'),
        ('The Guardian', 'https://www.theguardian.com/world/bangladesh'),
        ('BBC News', 'https://www.bbc.com/search?q=bangladesh'),
        ('CNN News', 'https://edition.cnn.com/search?q=bangladesh'),
        ('South Asia Monitor', 'https://southasiamonitor.org/search/node/bangladesh'),
        ('The Diplomat', 'https://thediplomat.com/search?gsc.q=bangladesh'),
        ('New York Times', 'https://www.nytimes.com/search?dropmab=false&query=bangladesh'),
        ('Washington Post', 'https://www.washingtonpost.com/search/?query=bangladesh')
    ]
    
    try:
        # Connect to PostgreSQL
        print("Connecting to PostgreSQL database...")
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()
        
        # Clear existing data first
        print("Clearing existing data...")
        cursor.execute("DELETE FROM sources;")
        
        # Insert media outlets data
        print("Inserting media outlets data...")
        
        insert_sql = """
        INSERT INTO sources (id, source_type, platform, url) 
        VALUES (%s, %s, %s, %s);
        """
        
        for platform, url in media_outlets:
            source_id = generate_uuid()
            cursor.execute(insert_sql, (source_id, 'news portal', platform, url))
        
        # Commit the changes
        conn.commit()
        print(f"Successfully inserted {len(media_outlets)} media outlets into sources table!")
        
        # Verification queries
        print("\n" + "="*50)
        print("DATA VERIFICATION")
        print("="*50)
        
        # Check total count
        cursor.execute("SELECT COUNT(*) FROM sources;")
        total_count = cursor.fetchone()[0]
        print(f"Total sources in database: {total_count}")
        
        # Show all data
        print("\n" + "="*50)
        print("ALL INSERTED DATA")
        print("="*50)
        cursor.execute("""
            SELECT id, source_type, platform, url, credibility_score, created_at 
            FROM sources 
            ORDER BY platform;
        """)
        
        for i, row in enumerate(cursor.fetchall(), 1):
            print(f"{i}. ID: {row[0]}")
            print(f"   Source Type: {row[1]}")
            print(f"   Platform: {row[2]}")
            print(f"   URL: {row[3]}")
            print(f"   Credibility Score: {row[4]}")
            print(f"   Created At: {row[5]}")
            print("-" * 50)
        
    except psycopg2.Error as e:
        print(f"Error populating sources table: {e}")
        if conn:
            conn.rollback()
    
    except Exception as e:
        print(f"Unexpected error: {e}")
        if conn:
            conn.rollback()
    
    finally:
        # Close database connection
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        print("Database connection closed.")

def main():
    """
    Main function to populate the sources table
    """
    print("Starting sources table population...")
    print("Note: credibility_score, created_by, and updated_at fields will be left empty for manual entry")
    print("="*70)
    populate_sources_table()
    print("="*70)
    print("Script completed.")

if __name__ == "__main__":
    main()