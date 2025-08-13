"""
YouTube Database Service

Database abstraction layer for YouTube video storage and retrieval.
Follows the same patterns as the existing database_service.py for news content.
"""

import psycopg2
import psycopg2.extras
from psycopg2 import sql
import json
import os
import uuid
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from youtube_scrapers.base import YouTubeVideo


class YouTubeDatabaseService:
    """
    Database service for YouTube video storage and retrieval operations.
    
    Features:
    - Video insertion with deduplication
    - Source management and platform mapping
    - Bulk operations with error handling
    - Statistics collection and reporting
    - Full-text search capabilities
    """
    
    def __init__(self):
        """Initialize the YouTube database service"""
        self.db_config = {
            'host': os.getenv('DB_HOST', 'localhost'),
            'database': os.getenv('DB_DATABASE', 'shottify_db_new'),
            'user': os.getenv('DB_USER', 'postgres'),
            'password': os.getenv('DB_PASSWORD', 'shottify123'),
            'port': os.getenv('DB_PORT', '5432')
        }
        
        # Cache for source IDs
        self._source_cache = {}
    
    def get_connection(self):
        """Get a database connection"""
        return psycopg2.connect(**self.db_config)
    
    def get_or_create_channel_source(self, channel_handle: str, channel_title: str = None) -> str:
        """
        Get or create a source entry for a specific YouTube channel
        
        Args:
            channel_handle (str): Channel handle like '@WION'
            channel_title (str): Channel title for display (optional)
            
        Returns:
            str: Source UUID for the YouTube channel
        """
        # Use channel handle as cache key
        cache_key = f"youtube_{channel_handle}"
        if cache_key in self._source_cache:
            return self._source_cache[cache_key]
        
        conn = None
        cursor = None
        
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Try to get existing channel source by URL
            channel_url = f"https://www.youtube.com/{channel_handle}"
            cursor.execute("""
                SELECT id FROM sources 
                WHERE platform = 'YouTube' AND source_type = 'social_media' AND url = %s
                LIMIT 1
            """, (channel_url,))
            
            result = cursor.fetchone()
            if result:
                source_id = str(result[0])
                self._source_cache[cache_key] = source_id
                return source_id
            
            # Create new source for this YouTube channel
            source_id = str(uuid.uuid4())
            
            cursor.execute("""
                INSERT INTO sources (id, source_type, platform, url, credibility_score) 
                VALUES (%s, %s, %s, %s, %s)
            """, (source_id, 'social_media', 'YouTube', channel_url, None))
            
            conn.commit()
            self._source_cache[cache_key] = source_id
            return source_id
            
        except Exception as e:
            if conn:
                conn.rollback()
            print(f"Error getting/creating YouTube channel source for {channel_handle}: {e}")
            raise
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    
    def insert_single_video(self, video: YouTubeVideo) -> Dict[str, Any]:
        """
        Insert a single YouTube video into the database
        
        Args:
            video (YouTubeVideo): Single video to insert
            
        Returns:
            Dict[str, Any]: Result with status and error info
        """
        conn = None
        cursor = None
        
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Prepare insert query
            insert_query = """
                INSERT INTO youtube_videos (
                    source_id, raw_data, video_id, title, description, url, thumbnail_url,
                    channel_id, channel_title, channel_handle, published_at,
                    duration_seconds, view_count, like_count, comment_count,
                    tags, video_language,
                    english_transcript, bengali_transcript, transcript_languages, comments,
                    processing_status
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s
                )
                ON CONFLICT (video_id) DO UPDATE SET
                    view_count = EXCLUDED.view_count,
                    like_count = EXCLUDED.like_count,
                    comment_count = EXCLUDED.comment_count,
                    english_transcript = EXCLUDED.english_transcript,
                    bengali_transcript = EXCLUDED.bengali_transcript,
                    transcript_languages = EXCLUDED.transcript_languages,
                    comments = EXCLUDED.comments,
                    processing_status = EXCLUDED.processing_status
            """
            
            # Get or create source for this channel
            source_id = self.get_or_create_channel_source(video.channel_handle, video.channel_title)
            
            # Transform video data
            video_data = self._transform_video_for_db(video, source_id)
            
            # Execute insert
            cursor.execute(insert_query, video_data)
            
            # Check if it was an insert or update
            if cursor.rowcount > 0:
                conn.commit()
                return {
                    'status': 'success',
                    'new_video': cursor.rowcount == 1,
                    'video_id': video.video_id,
                    'title': video.title
                }
            else:
                return {
                    'status': 'duplicate',
                    'new_video': False,
                    'video_id': video.video_id,
                    'title': video.title
                }
                
        except Exception as e:
            if conn:
                conn.rollback()
            return {
                'status': 'error',
                'error': str(e),
                'video_id': getattr(video, 'video_id', 'unknown'),
                'title': getattr(video, 'title', 'unknown')
            }
            
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    
    def insert_videos(self, videos: List[YouTubeVideo]) -> Dict[str, Any]:
        """
        Insert YouTube videos into the database with deduplication
        
        Args:
            videos (List[YouTubeVideo]): List of YouTube videos to insert
            
        Returns:
            Dict[str, Any]: Results summary with counts and statistics
        """
        if not videos:
            return {
                'total_videos': 0,
                'new_videos': 0,
                'duplicate_videos': 0,
                'failed_videos': 0,
                'errors': []
            }
        
        # We'll get source_id per video based on its channel
        
        conn = None
        cursor = None
        results = {
            'total_videos': len(videos),
            'new_videos': 0,
            'duplicate_videos': 0,
            'failed_videos': 0,
            'errors': []
        }
        
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Prepare insert query with ON CONFLICT for deduplication
            insert_query = """
                INSERT INTO youtube_videos (
                    source_id, raw_data, video_id, title, description, url, thumbnail_url,
                    channel_id, channel_title, channel_handle, published_at,
                    duration_seconds, view_count, like_count, comment_count,
                    tags, video_language,
                    english_transcript, bengali_transcript, transcript_languages, comments,
                    processing_status
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s
                )
                ON CONFLICT (video_id) DO UPDATE SET
                    view_count = EXCLUDED.view_count,
                    like_count = EXCLUDED.like_count,
                    comment_count = EXCLUDED.comment_count,
                    last_updated = NOW()
                RETURNING id, (xmax = 0) as is_new
            """
            
            for video in videos:
                try:
                    # Get channel-specific source_id
                    channel_handle = getattr(video, 'channel_handle', None)
                    channel_title = getattr(video, 'channel_title', None)
                    
                    if not channel_handle:
                        # Skip videos without channel handle
                        results['failed_videos'] += 1
                        results['errors'].append({
                            'video_id': getattr(video, 'video_id', 'unknown'),
                            'error': 'Missing channel_handle'
                        })
                        continue
                    
                    # Get or create source for this specific channel
                    source_id = self.get_or_create_channel_source(channel_handle, channel_title)
                    
                    # Transform video data for database
                    video_data = self._transform_video_for_db(video, source_id)
                    
                    cursor.execute(insert_query, video_data)
                    result = cursor.fetchone()
                    
                    if result:
                        is_new = result[1]  # xmax = 0 indicates INSERT, not UPDATE
                        if is_new:
                            results['new_videos'] += 1
                        else:
                            results['duplicate_videos'] += 1
                    
                except Exception as e:
                    results['failed_videos'] += 1
                    results['errors'].append({
                        'video_id': getattr(video, 'video_id', 'unknown'),
                        'error': str(e)
                    })
                    print(f"Error inserting video {getattr(video, 'video_id', 'unknown')}: {e}")
            
            conn.commit()
            print(f"YouTube videos insertion completed: {results['new_videos']} new, {results['duplicate_videos']} duplicates")
            
        except Exception as e:
            if conn:
                conn.rollback()
            print(f"Error in bulk video insertion: {e}")
            raise
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
        
        return results
    
    def _transform_video_for_db(self, video: YouTubeVideo, source_id: str) -> Tuple:
        """
        Transform a YouTubeVideo object into database-ready format
        
        Args:
            video (YouTubeVideo): YouTube video object
            source_id (str): Source UUID
            
        Returns:
            Tuple: Database values tuple
        """
        # Parse published_at to timestamp if possible
        published_at = None
        if video.published_at:
            try:
                published_at = datetime.fromisoformat(video.published_at.replace('Z', '+00:00'))
            except Exception:
                pass
        
        # Prepare raw_data with all available information
        raw_data = video.raw_data or {}
        raw_data.update({
            'video_id': video.video_id,
            'title': video.title,
            'description': video.description,
            'channel_info': {
                'id': video.channel_id,
                'title': video.channel_title,
                'handle': video.channel_handle
            },
            'metrics': {
                'view_count': video.view_count,
                'like_count': video.like_count,
                'comment_count': video.comment_count
            },
            'content': {
                'tags': video.tags,
                'duration': video.duration,
                'language': video.video_language
            }
        })
        
        return (
            source_id,  # source_id
            json.dumps(raw_data),  # raw_data
            video.video_id,  # video_id
            video.title,  # title
            video.description,  # description
            video.url,  # url
            video.thumbnail,  # thumbnail_url
            video.channel_id,  # channel_id
            video.channel_title,  # channel_title
            video.channel_handle,  # channel_handle
            published_at,  # published_at
            video.duration_seconds,  # duration_seconds
            video.view_count,  # view_count
            video.like_count,  # like_count
            video.comment_count,  # comment_count
            video.tags,  # tags (PostgreSQL array)
            video.video_language,  # video_language
            video.english_transcript,  # english_transcript
            video.bengali_transcript,  # bengali_transcript
            video.transcript_languages,  # transcript_languages (PostgreSQL array)
            json.dumps(video.comments) if video.comments else '[]',  # comments (JSONB)
            'pending'  # processing_status
        )
    
    def get_videos_by_channel(self, channel_handle: str, limit: int = 100, 
                             offset: int = 0) -> List[Dict[str, Any]]:
        """
        Get videos from a specific channel
        
        Args:
            channel_handle (str): Channel handle like '@WION'
            limit (int): Maximum number of videos to return
            offset (int): Number of videos to skip
            
        Returns:
            List[Dict[str, Any]]: List of video records
        """
        conn = None
        cursor = None
        
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            query = """
                SELECT * FROM youtube_videos 
                WHERE channel_handle = %s 
                ORDER BY published_at DESC 
                LIMIT %s OFFSET %s
            """
            
            cursor.execute(query, (channel_handle, limit, offset))
            return [dict(row) for row in cursor.fetchall()]
            
        except Exception as e:
            print(f"Error getting videos by channel: {e}")
            return []
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    
    def search_videos(self, search_term: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Full-text search for videos
        
        Args:
            search_term (str): Search term for title, description, or transcript
            limit (int): Maximum number of results
            
        Returns:
            List[Dict[str, Any]]: List of matching video records
        """
        conn = None
        cursor = None
        
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            query = """
                SELECT *, ts_rank(search_vector, plainto_tsquery('english', %s)) as rank
                FROM youtube_videos 
                WHERE search_vector @@ plainto_tsquery('english', %s)
                ORDER BY rank DESC, published_at DESC
                LIMIT %s
            """
            
            cursor.execute(query, (search_term, search_term, limit))
            return [dict(row) for row in cursor.fetchall()]
            
        except Exception as e:
            print(f"Error searching videos: {e}")
            return []
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    
    def get_database_stats(self) -> Dict[str, Any]:
        """
        Get YouTube database statistics
        
        Returns:
            Dict[str, Any]: Database statistics
        """
        conn = None
        cursor = None
        
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            stats = {}
            
            # Total videos count
            cursor.execute("SELECT COUNT(*) FROM youtube_videos")
            stats['total_videos'] = cursor.fetchone()[0]
            
            # Videos by channel
            cursor.execute("""
                SELECT channel_handle, COUNT(*) as video_count
                FROM youtube_videos 
                GROUP BY channel_handle 
                ORDER BY video_count DESC 
                LIMIT 10
            """)
            stats['top_channels'] = [{'channel': row[0], 'count': row[1]} 
                                   for row in cursor.fetchall()]
            
            # Recent videos count (last 7 days)
            cursor.execute("""
                SELECT COUNT(*) FROM youtube_videos 
                WHERE published_at > NOW() - INTERVAL '7 days'
            """)
            stats['recent_videos_7d'] = cursor.fetchone()[0]
            
            # Videos with transcripts
            cursor.execute("""
                SELECT COUNT(*) FROM youtube_videos 
                WHERE english_transcript IS NOT NULL OR bengali_transcript IS NOT NULL
            """)
            stats['videos_with_transcripts'] = cursor.fetchone()[0]
            
            # Language distribution
            cursor.execute("""
                SELECT video_language, COUNT(*) as count
                FROM youtube_videos 
                WHERE video_language IS NOT NULL
                GROUP BY video_language 
                ORDER BY count DESC 
                LIMIT 5
            """)
            stats['language_distribution'] = [{'language': row[0], 'count': row[1]} 
                                            for row in cursor.fetchall()]
            
            # Average engagement metrics
            cursor.execute("""
                SELECT 
                    AVG(view_count) as avg_views,
                    AVG(like_count) as avg_likes,
                    AVG(comment_count) as avg_comments
                FROM youtube_videos 
                WHERE view_count > 0
            """)
            metrics = cursor.fetchone()
            if metrics:
                stats['avg_engagement'] = {
                    'views': int(metrics[0] or 0),
                    'likes': int(metrics[1] or 0),
                    'comments': int(metrics[2] or 0)
                }
            
            return stats
            
        except Exception as e:
            print(f"Error getting database stats: {e}")
            return {}
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    
    def get_videos_for_analysis(self, limit: int = 100, 
                               processing_status: str = 'completed') -> List[Dict[str, Any]]:
        """
        Get videos that are ready for content analysis
        
        Args:
            limit (int): Maximum number of videos
            processing_status (str): Processing status filter
            
        Returns:
            List[Dict[str, Any]]: Videos ready for analysis
        """
        conn = None
        cursor = None
        
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            query = """
                SELECT * FROM youtube_videos 
                WHERE processing_status = %s 
                AND (english_transcript IS NOT NULL OR bengali_transcript IS NOT NULL)
                ORDER BY published_at DESC 
                LIMIT %s
            """
            
            cursor.execute(query, (processing_status, limit))
            return [dict(row) for row in cursor.fetchall()]
            
        except Exception as e:
            print(f"Error getting videos for analysis: {e}")
            return []
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()