import json
import os
import uuid
import psycopg2
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class DatabaseService:
    """Database service for inserting articles with deduplication"""
    
    def __init__(self):
        self.db_config = {
            'host': os.getenv('DB_HOST', 'localhost'),
            'database': os.getenv('DB_DATABASE', 'shottify_db'),
            'user': os.getenv('DB_USER', 'postgres'),
            'password': os.getenv('DB_PASSWORD', 'shottify123'),
            'port': os.getenv('DB_PORT', '5432')
        }
    
    def get_source_id_by_platform(self, platform_name: str, cursor) -> str:
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

    def transform_article_data(self, article: Dict[Any, Any]) -> Dict[Any, Any]:
        """Transform article data to match database schema"""
        transformed = {
            'title': article.get('title'),
            'published_at': article.get('published_at'),
            'url': article.get('url'),
            'content_text': article.get('content'),
            'summary': article.get('summary'),
            'author_name': article.get('author'),
            'media': article.get('media', []),
            'platform': article.get('outlet'),
            'tags': article.get('tags', []),
            'section': article.get('section')
        }
        
        # Remove None values to keep JSON clean
        return {k: v for k, v in transformed.items() if v is not None}

    def insert_articles_to_db(self, articles: List[Dict[Any, Any]], outlet: str) -> Dict[str, Any]:
        """Insert articles into content_items table with deduplication and return inserted IDs"""
        stats = {"inserted": 0, "duplicates_skipped": 0, "errors": 0, "inserted_ids": []}
        
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Get source_id for the outlet
            source_id = self.get_source_id_by_platform(outlet, cursor)
            
            # Transform and insert each article
            for article in articles:
                try:
                    # Transform the article data
                    transformed_article = self.transform_article_data(article)
                    
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
                    
                    # Insert with ON CONFLICT for deduplication and RETURNING id
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
                    ON CONFLICT (url) DO NOTHING
                    RETURNING id
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
                        'News article',
                        'English',
                        'Pending',
                        datetime.now()
                    ))
                    
                    # Check if row was actually inserted and get the ID
                    if cursor.rowcount > 0:
                        inserted_id = cursor.fetchone()[0]
                        stats["inserted"] += 1
                        stats["inserted_ids"].append(str(inserted_id))  # Convert UUID to string
                        logger.debug(f"✅ Inserted article: {url} with ID: {inserted_id}")
                    else:
                        stats["duplicates_skipped"] += 1
                        logger.debug(f"⏭️ Skipped duplicate: {url}")
                        
                except Exception as e:
                    stats["errors"] += 1
                    logger.error(f"Error inserting article: {e}")
                    continue
            
            # Commit all insertions
            conn.commit()
            logger.info(f"✅ {outlet}: {stats['inserted']} inserted, {stats['duplicates_skipped']} duplicates skipped, {stats['errors']} errors")
            
        except psycopg2.Error as e:
            logger.error(f"Database error: {e}")
            if 'conn' in locals():
                conn.rollback()
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            if 'conn' in locals():
                conn.rollback()
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals():
                conn.close()
                
        return stats

    def get_article_count_by_platform(self) -> Dict[str, int]:
        """Get article count by platform"""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT platform, COUNT(*) as count
                FROM content_items 
                WHERE platform IS NOT NULL
                GROUP BY platform
                ORDER BY count DESC
            """)
            
            results = cursor.fetchall()
            return {platform: count for platform, count in results}
            
        except Exception as e:
            logger.error(f"Error getting article counts: {e}")
            return {}
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals():
                conn.close()