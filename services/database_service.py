"""
Unified Database Service

Combines news and YouTube database operations into a single service
with connection pooling and comprehensive error handling.
"""

import json
import uuid
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import psycopg2
import psycopg2.extras
from psycopg2 import sql

from config.database import get_db_connection
from core.logging import get_database_logger, log_performance
from core.exceptions import DatabaseError, retry_with_backoff

logger = get_database_logger()


class UnifiedDatabaseService:
    """
    Unified database service for both news and YouTube content operations
    """
    
    def __init__(self):
        self._source_cache = {}
    
    # =============================================================================
    # News Content Operations
    # =============================================================================
    
    def get_source_id_by_platform(self, platform_name: str) -> str:
        """Get or create source_id from sources table by platform name"""
        if platform_name in self._source_cache:
            return self._source_cache[platform_name]
        
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute("SELECT id FROM sources WHERE platform = %s LIMIT 1", (platform_name,))
                    result = cursor.fetchone()
                    
                    if result:
                        source_id = result[0]
                    else:
                        # Create new source entry
                        source_id = str(uuid.uuid4())
                        cursor.execute("""
                            INSERT INTO sources (id, source_type, platform, url) 
                            VALUES (%s, %s, %s, %s)
                        """, (source_id, 'news portal', platform_name, ''))
                        conn.commit()
                        logger.info(f"Created new source for platform: {platform_name}")
                    
                    # Cache the result
                    self._source_cache[platform_name] = source_id
                    return source_id
                    
                except Exception as e:
                    conn.rollback()
                    logger.error(f"Error getting/creating source for {platform_name}: {e}")
                    raise DatabaseError("get_source_id", str(e))
    
    def transform_article_data(self, article: Dict[Any, Any]) -> Dict[Any, Any]:
        """Transform article data to match content_items table schema"""
        return {
            'title': article.get('title'),
            'published_at': article.get('published_at'),
            'url': article.get('url'),
            'content_text': article.get('content'),
            'author_name': article.get('author'),
            'platform': article.get('outlet'),
            'raw_data': article  # Store complete original data as JSONB
        }
    
    @retry_with_backoff(max_retries=2)
    def insert_articles_to_db(self, articles: List[Dict[Any, Any]], platform: str) -> Dict[str, Any]:
        """
        Insert multiple articles with deduplication and comprehensive error handling
        
        Args:
            articles: List of article dictionaries
            platform: Platform name for source identification
            
        Returns:
            Dictionary with insertion statistics
        """
        if not articles:
            return {"inserted": 0, "duplicates_skipped": 0, "errors": 0, "inserted_ids": []}
        
        with log_performance(logger, f"inserting {len(articles)} articles for {platform}"):
            try:
                source_id = self.get_source_id_by_platform(platform)
                
                inserted = 0
                duplicates_skipped = 0
                errors = 0
                inserted_ids = []
                
                with get_db_connection() as conn:
                    with conn.cursor() as cursor:
                        for article in articles:
                            try:
                                transformed = self.transform_article_data(article)
                                
                                # Check for duplicate URL
                                if transformed['url']:
                                    cursor.execute(
                                        "SELECT id FROM content_items WHERE url = %s LIMIT 1",
                                        (transformed['url'],)
                                    )
                                    if cursor.fetchone():
                                        duplicates_skipped += 1
                                        continue
                                
                                # Generate content ID
                                content_id = str(uuid.uuid4())
                                
                                # Insert article
                                cursor.execute("""
                                    INSERT INTO content_items (
                                        id, source_id, raw_data, title, published_at_text, url, content_text,
                                        author_name, platform, content_type, ingested_at, last_updated
                                    ) VALUES (
                                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                                    )
                                """, (
                                    content_id, source_id, json.dumps(transformed['raw_data']),
                                    transformed['title'], transformed['published_at'], transformed['url'],
                                    transformed['content_text'], transformed['author_name'],
                                    transformed['platform'], 'article'
                                ))
                                
                                inserted += 1
                                inserted_ids.append(content_id)
                                
                            except Exception as e:
                                logger.error(f"[ERROR] Database insertion failed for URL: {article.get('url', 'unknown')} | Error: {e}")
                                errors += 1
                                continue
                        
                        # Commit all changes
                        conn.commit()
                        
                        logger.info(f"[LIST] News insertion complete: {inserted} inserted, {duplicates_skipped} duplicates, {errors} errors")
                        
                        return {
                            "inserted": inserted,
                            "duplicates_skipped": duplicates_skipped,
                            "errors": errors,
                            "inserted_ids": inserted_ids
                        }
                        
            except Exception as e:
                logger.error(f"Database insertion failed for {platform}: {e}")
                raise DatabaseError("insert_articles", str(e))
    
    def get_article_count_by_platform(self) -> Dict[str, int]:
        """Get article counts grouped by platform"""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT platform, COUNT(*) 
                        FROM content_items 
                        WHERE platform IS NOT NULL
                        GROUP BY platform
                        ORDER BY COUNT(*) DESC
                    """)
                    
                    return dict(cursor.fetchall())
                    
        except Exception as e:
            logger.error(f"Error getting article counts: {e}")
            raise DatabaseError("get_article_count", str(e))
    
    # =============================================================================
    # YouTube Content Operations  
    # =============================================================================
    
    def get_or_create_channel_source(self, channel_handle: str, channel_title: str = None) -> str:
        """Get or create a source entry for a specific YouTube channel"""
        cache_key = f"youtube_{channel_handle}"
        if cache_key in self._source_cache:
            return self._source_cache[cache_key]
        
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    # Check if source exists
                    cursor.execute("""
                        SELECT id FROM sources 
                        WHERE source_type = 'youtube' AND platform = %s 
                        LIMIT 1
                    """, (channel_handle,))
                    
                    result = cursor.fetchone()
                    
                    if result:
                        source_id = result[0]
                    else:
                        # Create new YouTube channel source
                        source_id = str(uuid.uuid4())
                        cursor.execute("""
                            INSERT INTO sources (id, source_type, platform, url)
                            VALUES (%s, %s, %s, %s)
                        """, (
                            source_id, 'youtube', channel_handle,
                            f"https://www.youtube.com/{channel_handle}"
                        ))
                        conn.commit()
                        logger.info(f"Created new YouTube source for: {channel_handle}")
                    
                    # Cache the result
                    self._source_cache[cache_key] = source_id
                    return source_id
                    
                except Exception as e:
                    conn.rollback()
                    logger.error(f"Error getting/creating YouTube source for {channel_handle}: {e}")
                    raise DatabaseError("get_channel_source", str(e))
    
    @retry_with_backoff(max_retries=2)
    def insert_single_video(self, video) -> Dict[str, Any]:
        """
        Insert a single YouTube video with comprehensive error handling
        
        Args:
            video: YouTubeVideo object
            
        Returns:
            Dictionary with insertion result
        """
        try:
            source_id = self.get_or_create_channel_source(
                video.channel_handle or video.channel_id,
                video.channel_title
            )
            
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Check for duplicate video  
                    cursor.execute(
                        "SELECT video_id FROM youtube_content WHERE video_id = %s LIMIT 1",
                        (video.video_id,)
                    )
                    
                    if cursor.fetchone():
                        return {"status": "skipped", "reason": "duplicate"}
                    
                    # Insert video
                    cursor.execute("""
                        INSERT INTO youtube_content (
                            source_id, raw_data, video_id, title, description, url, thumbnail_url,
                            channel_id, channel_title, channel_handle, published_at,
                            duration_seconds, view_count, like_count, comment_count,
                            tags, video_language,
                            english_transcript, bengali_transcript, transcript_languages, comments,
                            processing_status
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s
                        ) ON CONFLICT (video_id) DO NOTHING RETURNING id
                    """, (
                        source_id, json.dumps(video.raw_data or {}), video.video_id, 
                        video.title, video.description, video.url, video.thumbnail,
                        video.channel_id, video.channel_title, video.channel_handle, 
                        video.published_at, video.duration_seconds, video.view_count,
                        video.like_count, video.comment_count, video.tags or [],
                        video.video_language, video.english_transcript, video.bengali_transcript,
                        video.transcript_languages or [], json.dumps(video.comments or []),
                        'pending'
                    ))
                    
                    # Check if video was inserted
                    result = cursor.fetchone()
                    if result:
                        conn.commit()
                        return {
                            "status": "success", 
                            "content_id": result[0],
                            "video_id": video.video_id
                        }
                    else:
                        return {"status": "skipped", "reason": "duplicate via conflict"}
                    
        except Exception as e:
            logger.error(f"Error inserting YouTube video {video.video_id}: {e}")
            return {
                "status": "error",
                "error": str(e),
                "video_id": video.video_id
            }
    
    def get_youtube_database_stats(self) -> Dict[str, Any]:
        """Get comprehensive YouTube database statistics"""
        try:
            with get_db_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                    stats = {}
                    
                    # Total videos
                    cursor.execute("SELECT COUNT(*) FROM youtube_content")
                    stats['total_videos'] = cursor.fetchone()[0]
                    
                    # Videos by channel
                    cursor.execute("""
                        SELECT channel_handle, COUNT(*) as video_count
                        FROM youtube_content 
                        WHERE channel_handle IS NOT NULL
                        GROUP BY channel_handle 
                        ORDER BY video_count DESC
                        LIMIT 10
                    """)
                    stats['top_channels'] = [dict(row) for row in cursor.fetchall()]
                    
                    # Recent activity
                    cursor.execute("""
                        SELECT DATE(created_at) as date, COUNT(*) as videos_added
                        FROM youtube_content 
                        WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
                        GROUP BY DATE(created_at)
                        ORDER BY date DESC
                    """)
                    stats['recent_activity'] = [dict(row) for row in cursor.fetchall()]
                    
                    # Language distribution
                    cursor.execute("""
                        SELECT video_language, COUNT(*) as count
                        FROM youtube_content 
                        WHERE video_language IS NOT NULL
                        GROUP BY video_language 
                        ORDER BY count DESC
                        LIMIT 5
                    """)
                    stats['language_distribution'] = [dict(row) for row in cursor.fetchall()]
                    
                    return stats
                    
        except Exception as e:
            logger.error(f"Error getting YouTube database stats: {e}")
            raise DatabaseError("get_youtube_stats", str(e))
    
    # =============================================================================
    # Common Operations
    # =============================================================================
    
    def get_database_health(self) -> Dict[str, Any]:
        """Get overall database health information"""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    health_info = {}
                    
                    # Connection test
                    cursor.execute("SELECT 1")
                    health_info['connection'] = 'healthy'
                    
                    # Table counts
                    tables = ['content_items', 'youtube_content', 'sources']
                    for table in tables:
                        cursor.execute(f"SELECT COUNT(*) FROM {table}")
                        health_info[f'{table}_count'] = cursor.fetchone()[0]
                    
                    # Database size
                    cursor.execute("""
                        SELECT pg_size_pretty(pg_database_size(current_database())) as size
                    """)
                    health_info['database_size'] = cursor.fetchone()[0]
                    
                    return health_info
                    
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return {
                'connection': 'unhealthy',
                'error': str(e)
            }
    
    def search_content(self, query: str, content_type: str = 'both', limit: int = 50) -> List[Dict[str, Any]]:
        """
        Search across news and YouTube content
        
        Args:
            query: Search query
            content_type: 'news', 'youtube', or 'both'
            limit: Maximum results to return
            
        Returns:
            List of matching content items
        """
        try:
            results = []
            
            with get_db_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                    
                    # Search news content
                    if content_type in ['news', 'both']:
                        cursor.execute("""
                            SELECT 'news' as content_type, id, title, url, platform, 
                                   created_at, summary
                            FROM content_items 
                            WHERE title ILIKE %s OR content_text ILIKE %s OR summary ILIKE %s
                            ORDER BY created_at DESC 
                            LIMIT %s
                        """, (f'%{query}%', f'%{query}%', f'%{query}%', limit // 2))
                        
                        results.extend([dict(row) for row in cursor.fetchall()])
                    
                    # Search YouTube content  
                    if content_type in ['youtube', 'both']:
                        cursor.execute("""
                            SELECT 'youtube' as content_type, id, title, url, 
                                   channel_handle as platform, created_at, description as summary
                            FROM youtube_content 
                            WHERE title ILIKE %s OR description ILIKE %s 
                                  OR english_transcript ILIKE %s
                            ORDER BY created_at DESC 
                            LIMIT %s
                        """, (f'%{query}%', f'%{query}%', f'%{query}%', limit // 2))
                        
                        results.extend([dict(row) for row in cursor.fetchall()])
            
            # Sort combined results by creation date
            results.sort(key=lambda x: x['created_at'], reverse=True)
            return results[:limit]
            
        except Exception as e:
            logger.error(f"Content search failed: {e}")
            raise DatabaseError("search_content", str(e))
    
    def cleanup_old_content(self, days_to_keep: int = 30) -> Dict[str, int]:
        """
        Clean up content older than specified days
        
        Args:
            days_to_keep: Number of days of content to retain
            
        Returns:
            Dictionary with cleanup statistics
        """
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cutoff_date = f"CURRENT_DATE - INTERVAL '{days_to_keep} days'"
                    
                    # Clean up old news content
                    cursor.execute(f"""
                        DELETE FROM content_items 
                        WHERE created_at < {cutoff_date}
                    """)
                    news_deleted = cursor.rowcount
                    
                    # Clean up old YouTube content
                    cursor.execute(f"""
                        DELETE FROM youtube_content 
                        WHERE created_at < {cutoff_date}
                    """)
                    youtube_deleted = cursor.rowcount
                    
                    conn.commit()
                    
                    logger.info(f"Content cleanup complete: {news_deleted} news articles, "
                              f"{youtube_deleted} YouTube videos deleted")
                    
                    return {
                        "news_deleted": news_deleted,
                        "youtube_deleted": youtube_deleted,
                        "total_deleted": news_deleted + youtube_deleted
                    }
                    
        except Exception as e:
            logger.error(f"Content cleanup failed: {e}")
            raise DatabaseError("cleanup_content", str(e))