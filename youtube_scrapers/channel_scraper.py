"""
YouTube Channel Scraper

Main implementation for extracting videos from YouTube channels using the YouTube Data API v3.
This single scraper works for all YouTube channels through configuration.
"""

import requests
import time
import random
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from .base import BaseYouTubeScraper, YouTubeVideo


class YouTubeChannelScraper(BaseYouTubeScraper):
    """
    YouTube channel scraper that works for all channels using YouTube Data API v3.
    
    Features:
    - Extract videos from any YouTube channel by handle or ID
    - Filter by date range, keywords, and hashtags
    - Extract detailed video metadata and statistics
    - Fetch comments and transcripts
    - Rate limiting and quota management
    """
    
    def __init__(self, api_key: str, rate_limit_delay: float = 2.0):
        """
        Initialize the YouTube channel scraper
        
        Args:
            api_key (str): YouTube Data API v3 key
            rate_limit_delay (float): Delay between API requests in seconds
        """
        super().__init__(api_key)
        self.rate_limit_delay = rate_limit_delay
        self.session = requests.Session()
        
        # Set up session headers
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
        })
    
    def scrape_channel(self, channel_handle: str, max_results: int = 100, 
                      published_after: Optional[str] = None, 
                      published_before: Optional[str] = None,
                      keywords: Optional[List[str]] = None,
                      hashtags: Optional[List[str]] = None,
                      include_comments: bool = True,
                      include_transcripts: bool = True,
                      comments_limit: int = 50) -> List[YouTubeVideo]:
        """
        Extract videos from a YouTube channel
        
        Args:
            channel_handle (str): Channel handle like '@WION' or channel ID
            max_results (int): Maximum number of videos to extract
            published_after (str): ISO format date for filtering (e.g., '2025-08-08T00:00:00Z')
            published_before (str): ISO format date for filtering
            keywords (List[str]): Keywords to filter videos by
            hashtags (List[str]): Hashtags to filter videos by
            include_comments (bool): Whether to fetch comments
            include_transcripts (bool): Whether to fetch transcripts
            comments_limit (int): Maximum comments per video
            
        Returns:
            List[YouTubeVideo]: List of extracted video data
        """
        print(f"Starting to scrape channel: {channel_handle}")
        
        # Get channel ID
        channel_id = self.get_channel_id_from_handle(channel_handle)
        if not channel_id:
            print(f"Could not find channel ID for {channel_handle}")
            return []
        
        print(f"Found channel ID: {channel_id}")
        
        # Get channel info
        channel_info = self._get_channel_info(channel_id)
        
        # Search for videos
        videos = self._search_videos(
            channel_id=channel_id,
            max_results=max_results,
            published_after=published_after,
            published_before=published_before,
            keywords=keywords,
            hashtags=hashtags
        )
        
        if not videos:
            print("No videos found matching criteria")
            return []
        
        print(f"Found {len(videos)} videos. Processing each video individually...")
        
        # Process each video individually and return immediately after processing
        processed_videos = []
        
        for i, video in enumerate(videos):
            try:
                print(f"[{i+1}/{len(videos)}] Processing video: {video.video_id}")
                
                # Add channel information
                if channel_info:
                    video.channel_title = channel_info.get('title', video.channel_title)
                    video.channel_handle = channel_handle
                
                # Get detailed statistics for this video
                video_stats = self._get_videos_statistics([video.video_id])
                if video.video_id in video_stats:
                    stats = video_stats[video.video_id]
                    video.view_count = int(stats.get('viewCount', 0))
                    video.like_count = int(stats.get('likeCount', 0))
                    video.comment_count = int(stats.get('commentCount', 0))
                    video.duration = stats.get('duration')
                    video.duration_seconds = self.parse_duration(stats.get('duration'))
                    video.tags = stats.get('tags', [])
                    video.video_language = stats.get('defaultAudioLanguage', 'unknown')
                    video.raw_data.update({'statistics': stats})
                
                # Get comments if requested
                if include_comments:
                    try:
                        comments = self._get_video_comments(video.video_id, comments_limit)
                        video.comments = comments
                        print(f"  Added {len(comments)} comments")
                    except Exception as e:
                        print(f"  Could not get comments: {e}")
                        video.comments = []
                
                # Get transcripts if requested
                if include_transcripts:
                    try:
                        transcript_results = self._get_youtube_captions_exact(video.video_id)
                        if transcript_results:
                            video.transcript_languages = []
                            video.bengali_transcript = ""
                            video.english_transcript = ""
                            
                            for result in transcript_results:
                                lang = result['language']
                                transcript_text = ' '.join(item['text'] for item in result['transcript'])
                                video.transcript_languages.append(lang)
                                
                                if lang.startswith('bn'):
                                    video.bengali_transcript = transcript_text
                                    print(f"  Added Bengali transcript ({lang})")
                                elif lang.startswith('en'):
                                    video.english_transcript = transcript_text
                                    print(f"  Added English transcript ({lang})")
                            
                            print(f"  Found {len(transcript_results)} transcript(s)")
                        else:
                            print(f"  No transcripts found")
                    except Exception as e:
                        print(f"  Could not get transcripts: {e}")
                        video.transcript_languages = []
                        video.bengali_transcript = ""
                        video.english_transcript = ""
                
                processed_videos.append(video)
                print(f"  ✅ Video {video.video_id} processed successfully")
                
            except Exception as e:
                print(f"  ❌ Error processing video {video.video_id}: {e}")
                continue
        
        print(f"Successfully processed {len(processed_videos)} videos from {channel_handle}")
        return processed_videos
    
    def _get_channel_info(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed channel information"""
        try:
            url = f"{self.base_url}/channels"
            params = {
                'part': 'snippet,statistics',
                'id': channel_id,
                'key': self.api_key
            }
            
            response = self.session.get(url, params=params)
            self.quota_used += 1
            self.rate_limit()
            
            if response.status_code == 200:
                data = response.json()
                if data.get('items'):
                    return data['items'][0]
            
        except Exception as e:
            print(f"Error getting channel info: {e}")
        
        return None
    
    def _search_videos(self, channel_id: str, max_results: int,
                      published_after: Optional[str] = None,
                      published_before: Optional[str] = None,
                      keywords: Optional[List[str]] = None,
                      hashtags: Optional[List[str]] = None) -> List[YouTubeVideo]:
        """Search for videos in a channel with optional filtering"""
        videos = []
        next_page_token = None
        
        # Build search query with OR logic for keywords
        search_query = ""
        if keywords:
            search_query += " OR ".join(keywords) + " "
        if hashtags:
            hashtag_parts = []
            for tag in hashtags:
                hashtag = tag if tag.startswith('#') else f"#{tag}"
                hashtag_parts.append(hashtag)
            if hashtag_parts:
                if search_query:
                    search_query += " OR "
                search_query += " OR ".join(hashtag_parts)
        
        while len(videos) < max_results:
            try:
                url = f"{self.base_url}/search"
                params = {
                    'part': 'snippet',
                    'channelId': channel_id,
                    'maxResults': min(50, max_results - len(videos)),
                    'order': 'date',
                    'type': 'video',
                    'key': self.api_key
                }
                
                if search_query.strip():
                    params['q'] = search_query.strip()
                
                if published_after:
                    params['publishedAfter'] = published_after
                
                if published_before:
                    params['publishedBefore'] = published_before
                
                if next_page_token:
                    params['pageToken'] = next_page_token
                
                response = self.session.get(url, params=params)
                self.quota_used += 100  # Search costs 100 units
                self.rate_limit()
                
                if response.status_code != 200:
                    print(f"API request failed with status {response.status_code}")
                    if response.status_code == 403:
                        try:
                            error_data = response.json()
                            error_msg = error_data.get('error', {}).get('message', 'Unknown error')
                            print(f"API Error 403: {error_msg}")
                        except:
                            print("API Error 403: Likely quota exceeded or insufficient permissions")
                    elif response.status_code == 400:
                        try:
                            error_data = response.json()
                            error_msg = error_data.get('error', {}).get('message', 'Unknown error')
                            print(f"API Error 400: {error_msg}")
                        except:
                            print("API Error 400: Bad request")
                    break
                
                data = response.json()
                items = data.get('items', [])
                
                if not items:
                    break
                
                # Convert API response to YouTubeVideo objects
                for item in items:
                    video = self._parse_search_result(item)
                    videos.append(video)
                
                next_page_token = data.get('nextPageToken')
                if not next_page_token:
                    break
                
            except Exception as e:
                print(f"Error searching videos: {e}")
                break
        
        return videos
    
    def _parse_search_result(self, item: Dict[str, Any]) -> YouTubeVideo:
        """Parse a search result item into a YouTubeVideo object"""
        snippet = item['snippet']
        
        return YouTubeVideo(
            video_id=item['id']['videoId'],
            title=snippet.get('title'),
            description=snippet.get('description', '')[:500],  # Truncate description
            channel_title=snippet.get('channelTitle'),
            channel_id=snippet.get('channelId'),
            published_at=snippet.get('publishedAt'),
            thumbnail=self._get_best_thumbnail(snippet.get('thumbnails', {})),
            raw_data={'search_result': item}
        )
    
    def _get_best_thumbnail(self, thumbnails: Dict[str, Any]) -> Optional[str]:
        """Extract the best quality thumbnail URL"""
        # Priority order: maxres, high, medium, default
        for quality in ['maxres', 'high', 'medium', 'default']:
            if quality in thumbnails:
                return thumbnails[quality]['url']
        return None
    
    def _enrich_videos_with_statistics(self, videos: List[YouTubeVideo], video_ids: List[str]):
        """Enrich videos with detailed statistics and metadata"""
        # Process in batches of 50 (API limit)
        for i in range(0, len(video_ids), 50):
            batch_ids = video_ids[i:i+50]
            stats_data = self._get_videos_statistics(batch_ids)
            
            # Match statistics with videos
            for video in videos:
                if video.video_id in stats_data:
                    stats = stats_data[video.video_id]
                    video.view_count = int(stats.get('viewCount', 0))
                    video.like_count = int(stats.get('likeCount', 0))
                    video.comment_count = int(stats.get('commentCount', 0))
                    video.duration = stats.get('duration')
                    video.duration_seconds = self.parse_duration(stats.get('duration'))
                    video.tags = stats.get('tags', [])
                    video.video_language = stats.get('defaultAudioLanguage', 'unknown')
                    
                    # Update raw_data
                    video.raw_data.update({'statistics': stats})
    
    def _get_videos_statistics(self, video_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Get detailed statistics for a batch of videos"""
        try:
            url = f"{self.base_url}/videos"
            params = {
                'part': 'statistics,contentDetails,snippet',
                'id': ','.join(video_ids),
                'key': self.api_key
            }
            
            response = self.session.get(url, params=params)
            self.quota_used += 1  # Videos.list costs 1 unit per video
            self.rate_limit()
            
            if response.status_code == 200:
                data = response.json()
                stats = {}
                
                for item in data.get('items', []):
                    video_id = item['id']
                    stats[video_id] = {
                        'viewCount': item['statistics'].get('viewCount', 0),
                        'likeCount': item['statistics'].get('likeCount', 0),
                        'commentCount': item['statistics'].get('commentCount', 0),
                        'duration': item['contentDetails']['duration'],
                        'tags': item['snippet'].get('tags', [])
                    }
                
                return stats
        
        except Exception as e:
            print(f"Error getting video statistics: {e}")
        
        return {}
    
    def _add_comments_to_videos(self, videos: List[YouTubeVideo], comments_limit: int):
        """Add comments to videos"""
        for video in videos:
            try:
                comments = self._get_video_comments(video.video_id, comments_limit)
                video.comments = comments
                time.sleep(1.0)  # Additional rate limiting for comments
                
            except Exception as e:
                print(f"Could not get comments for video {video.video_id}: {e}")
                video.comments = []
    
    def _get_video_comments(self, video_id: str, max_results: int) -> List[str]:
        """Extract comment text from a video"""
        try:
            url = f"{self.base_url}/commentThreads"
            params = {
                'part': 'snippet,replies',
                'videoId': video_id,
                'maxResults': min(max_results, 100),
                'order': 'relevance',
                'key': self.api_key
            }
            
            response = self.session.get(url, params=params)
            self.quota_used += 1  # CommentThreads.list costs 1 unit
            self.rate_limit()
            
            if response.status_code == 200:
                data = response.json()
                comments_text = []
                
                # Get top-level comments
                for item in data.get('items', []):
                    comment = item['snippet']['topLevelComment']['snippet']
                    comments_text.append(comment['textDisplay'])
                    
                    # Get replies if they exist
                    if 'replies' in item:
                        for reply in item['replies']['comments']:
                            reply_text = reply['snippet']['textDisplay']
                            comments_text.append(reply_text)
                
                return comments_text
        
        except Exception as e:
            print(f"Error getting comments for video {video_id}: {e}")
        
        return []
    
    def _add_transcripts_to_videos(self, videos: List[YouTubeVideo]):
        """Add transcripts to videos with enhanced rate limiting and retry logic"""
        for i, video in enumerate(videos):
            max_retries = 3
            base_delay = 3
            
            for attempt in range(max_retries):
                try:
                    print(f"[{i+1}/{len(videos)}] Getting transcript for video: {video.video_id} (attempt {attempt+1})")
                    
                    # Use EXACT working function from proof of concept
                    transcript_results = self._get_youtube_captions_exact(video.video_id)
                    
                    if transcript_results:
                        video.transcript_languages = []
                        video.bengali_transcript = ""
                        video.english_transcript = ""
                        
                        # Process each available transcript by language
                        for result in transcript_results:
                            lang = result['language']
                            transcript_text = ' '.join(item['text'] for item in result['transcript'])
                            video.transcript_languages.append(lang)
                            
                            # Store Bengali transcript
                            if lang.startswith('bn'):
                                video.bengali_transcript = transcript_text
                                print(f"  Added Bengali transcript ({lang})")
                            
                            # Store English transcript
                            elif lang.startswith('en'):
                                video.english_transcript = transcript_text
                                print(f"  Added English transcript ({lang})")
                        
                        print(f"  Found {len(transcript_results)} transcript(s)")
                        break  # Success, exit retry loop
                    else:
                        video.transcript_languages = []
                        video.bengali_transcript = ""
                        video.english_transcript = ""
                        print(f"  No transcripts found")
                        break  # No transcripts available, no need to retry
                    
                except Exception as e:
                    if "429" in str(e) or "too many requests" in str(e).lower():
                        if attempt < max_retries - 1:
                            # Exponential backoff for rate limiting
                            delay = base_delay * (2 ** attempt) + random.uniform(1, 5)
                            print(f"  Rate limited, retrying in {delay:.1f} seconds...")
                            time.sleep(delay)
                            continue
                    
                    print(f"Error getting transcript for video {video.video_id}: {e}")
                    video.transcript_languages = []
                    video.bengali_transcript = ""
                    video.english_transcript = ""
                    break
                
            # Add delay between videos (with jitter to avoid synchronized requests)
            delay = base_delay + random.uniform(0.5, 2.0)
            time.sleep(delay)
    
    def _get_youtube_captions_exact(self, video_id, save_to_file=False, output_dir='transcripts'):
        """
        EXACT COPY of working transcript extraction from proof of concept
        Get YouTube captions in multiple priority languages if available:
        - Bengali/Bangla (bn or bn-orig or bn-BD)
        - English (en, en-US, or en-GB)
        """
        import yt_dlp
        import json
        import re
        
        url = f"https://www.youtube.com/watch?v={video_id}"
        results = []
        
        # Target language codes
        bengali_codes = ['bn', 'bn-orig', 'bn-BD']
        english_codes = ['en', 'en-US', 'en-GB']
        target_languages = bengali_codes + english_codes
        
        # Configure yt-dlp options - EXACT COPY from working proof of concept
        ydl_opts = {
            'skip_download': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'listsubtitles': True,
            'subtitlesformat': 'json3/best',
            'quiet': True,
            'no_check_certificate': True,
            'cookies_from_browser': ('chrome', None, None, None),
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Get video info
                info = ydl.extract_info(url, download=False)
                video_title = info.get('title', video_id)
                safe_title = "".join([c if c.isalnum() or c in ' ._-' else '_' for c in video_title]).strip()
                
                # Collect available caption tracks for target languages
                available_captions = {}  # Use a dict to store best version of each language
                
                # Check manual subtitles first (preferred)
                if 'subtitles' in info and info['subtitles']:
                    for lang, formats in info['subtitles'].items():
                        if formats and lang in target_languages:
                            available_captions[lang] = {
                                'language': lang,
                                'type': 'manual',
                                'formats': formats
                            }
                
                # Add auto-generated captions if no manual ones exist for that language
                if 'automatic_captions' in info and info['automatic_captions']:
                    for lang, formats in info['automatic_captions'].items():
                        if formats and lang in target_languages and lang not in available_captions:
                            available_captions[lang] = {
                                'language': lang,
                                'type': 'auto',
                                'formats': formats
                            }
                
                if not available_captions:
                    print(f"No Bengali or English captions found for video {video_id}")
                    return results
                
                # Process each available target language
                found_languages = list(available_captions.keys())
                found_languages.sort(key=lambda x: target_languages.index(x) if x in target_languages else 999)
                
                print(f"Found captions in these target languages: {found_languages}")
                
                for lang in found_languages:
                    caption_data = available_captions[lang]
                    caption_type = caption_data['type']
                    
                    print(f"Processing {caption_type} captions in {lang}...")
                    
                    transcript = self._process_subtitle_formats_exact(ydl, caption_data['formats'], lang)
                    if transcript:
                        result = {
                            'transcript': transcript,
                            'language': lang,
                            'source': f"{caption_type.capitalize()} captions",
                            'files': []
                        }
                        results.append(result)
        
        except Exception as e:
            print(f"Error retrieving captions: {e}")
        
        return results
    
    def _process_subtitle_formats_exact(self, ydl, formats, lang):
        """Process a list of subtitle format options, trying each until successful - EXACT from working code"""
        # Try JSON3 format first if available
        json_format = next((fmt for fmt in formats if fmt.get('ext') == 'json3'), None)
        if json_format and 'url' in json_format:
            transcript = self._process_subtitle_exact(ydl, json_format, lang)
            if transcript:
                return transcript
        
        # Try other formats
        for fmt in formats:
            if 'url' in fmt:
                transcript = self._process_subtitle_exact(ydl, fmt, lang)
                if transcript:
                    return transcript
        
        return None
    
    def _process_subtitle_exact(self, ydl, subtitle, lang):
        """Process a single subtitle format - EXACT from working code"""
        import json
        import re
        import xml.etree.ElementTree as ET
        
        try:
            subtitle_url = subtitle.get('url')
            if not subtitle_url:
                return None
            
            response = ydl.urlopen(subtitle_url)
            subtitle_content = response.read().decode('utf-8')
            format_ext = subtitle.get('ext', '')
            
            if format_ext == 'json3':
                # Process JSON format
                subtitle_json = json.loads(subtitle_content)
                transcript = []
                for event in subtitle_json.get('events', []):
                    if 'segs' in event:
                        text = ' '.join(seg.get('utf8', '') for seg in event.get('segs', []) if 'utf8' in seg)
                        if text.strip():
                            transcript.append({
                                'text': text,
                                'start': event.get('tStartMs', 0) / 1000,
                                'duration': (event.get('dDurationMs', 0) / 1000)
                            })
                return transcript
            
            elif format_ext in ['vtt', 'srt']:
                # Process WebVTT or SRT formats
                transcript = []
                lines = subtitle_content.split('\n')
                current_text = ""
                current_start = 0
                current_duration = 0
                
                for i, line in enumerate(lines):
                    # Skip headers and empty lines
                    if '-->' in line:
                        # This is a timestamp line
                        time_parts = line.split('-->')
                        if len(time_parts) == 2:
                            start_str = time_parts[0].strip()
                            end_str = time_parts[1].strip().split(' ')[0]  # Remove any styling info
                            
                            # Parse timestamps
                            start_time = self._parse_timestamp_exact(start_str)
                            end_time = self._parse_timestamp_exact(end_str)
                            
                            if start_time is not None and end_time is not None:
                                current_start = start_time
                                current_duration = end_time - start_time
                                
                                # Get the text from the next line(s)
                                current_text = ""
                                j = i + 1
                                while j < len(lines) and lines[j].strip() and '-->' not in lines[j]:
                                    if current_text:
                                        current_text += " "
                                    # Remove HTML tags
                                    clean_line = re.sub(r'<[^>]+>', '', lines[j])
                                    current_text += clean_line.strip()
                                    j += 1
                                
                                if current_text:
                                    transcript.append({
                                        'text': current_text,
                                        'start': current_start,
                                        'duration': current_duration
                                    })
                
                return transcript
            
            elif format_ext == 'ttml':
                # Basic TTML processing
                root = ET.fromstring(subtitle_content)
                transcript = []
                
                # Find all text elements
                for elem in root.findall('.//{http://www.w3.org/ns/ttml}p'):
                    begin = elem.get('begin')
                    end = elem.get('end')
                    
                    if begin and end:
                        start_time = self._parse_timestamp_exact(begin)
                        end_time = self._parse_timestamp_exact(end)
                        
                        if start_time is not None and end_time is not None:
                            text = ''.join(elem.itertext()).strip()
                            if text:
                                transcript.append({
                                    'text': text,
                                    'start': start_time,
                                    'duration': end_time - start_time
                                })
                
                return transcript
        
        except Exception as e:
            print(f"Error processing {lang} subtitle: {e}")
        
        return None
    
    def _parse_timestamp_exact(self, timestamp):
        """Parse various timestamp formats to seconds - EXACT from working code"""
        try:
            # Handle HH:MM:SS.mmm format
            if ':' in timestamp:
                parts = timestamp.replace(',', '.').split(':')
                if len(parts) == 3:
                    hours, minutes, seconds = parts
                    seconds = float(seconds)
                    return int(hours) * 3600 + int(minutes) * 60 + seconds
                elif len(parts) == 2:
                    minutes, seconds = parts
                    seconds = float(seconds)
                    return int(minutes) * 60 + seconds
            
            # Handle seconds format
            elif '.' in timestamp or timestamp.isdigit():
                return float(timestamp)
            
            # Handle time with s, ms, or h suffix
            elif 's' in timestamp:
                if 'ms' in timestamp:
                    return float(timestamp.replace('ms', '')) / 1000
                else:
                    return float(timestamp.replace('s', ''))
            
            # Handle time with h suffix
            elif 'h' in timestamp:
                return float(timestamp.replace('h', '')) * 3600
        
        except Exception:
            pass
        
        return None
    
