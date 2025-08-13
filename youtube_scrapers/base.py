"""
Base YouTube Scraper

Abstract base class for YouTube video extraction providing common functionality
for YouTube Data API v3 integration and transcript processing.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import time
import json
import re
from datetime import datetime
import yt_dlp
import xml.etree.ElementTree as ET


@dataclass
class YouTubeVideo:
    """Data class representing a YouTube video with all extracted metadata"""
    video_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    channel_title: Optional[str] = None
    channel_id: Optional[str] = None
    channel_handle: Optional[str] = None
    published_at: Optional[str] = None
    thumbnail: Optional[str] = None
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    duration: Optional[str] = None
    duration_seconds: Optional[int] = None
    tags: List[str] = None
    video_language: Optional[str] = None
    comments: List[str] = None
    english_transcript: Optional[str] = None
    bengali_transcript: Optional[str] = None
    transcript_languages: List[str] = None
    url: Optional[str] = None
    raw_data: Dict[str, Any] = None

    def __post_init__(self):
        """Initialize default values for mutable fields"""
        if self.tags is None:
            self.tags = []
        if self.comments is None:
            self.comments = []
        if self.transcript_languages is None:
            self.transcript_languages = []
        if self.raw_data is None:
            self.raw_data = {}
        if self.url is None:
            self.url = f"https://www.youtube.com/watch?v={self.video_id}"


class BaseYouTubeScraper(ABC):
    """
    Abstract base class for YouTube video extraction.
    
    Provides common functionality for:
    - YouTube Data API v3 integration
    - Rate limiting and quota management
    - Transcript extraction via yt-dlp
    - Error handling and retry logic
    """
    
    def __init__(self, api_key: str):
        """
        Initialize the YouTube scraper
        
        Args:
            api_key (str): YouTube Data API v3 key
        """
        self.api_key = api_key
        self.quota_used = 0
        self.rate_limit_delay = 0.5  # Default delay between requests
        
        # YouTube Data API v3 base URL
        self.base_url = "https://www.googleapis.com/youtube/v3"
        
    @abstractmethod
    def scrape_channel(self, channel_handle: str, **kwargs) -> List[YouTubeVideo]:
        """
        Extract videos from a YouTube channel
        
        Args:
            channel_handle (str): YouTube channel handle (e.g., '@WION')
            **kwargs: Additional parameters for filtering and pagination
            
        Returns:
            List[YouTubeVideo]: List of extracted video data
        """
        pass
    
    def get_channel_id_from_handle(self, channel_handle: str) -> Optional[str]:
        """
        Convert a channel handle to channel ID using YouTube API
        
        Args:
            channel_handle (str): Channel handle like '@WION'
            
        Returns:
            Optional[str]: Channel ID if found, None otherwise
        """
        # Remove @ if present
        if channel_handle.startswith('@'):
            handle_without_at = channel_handle[1:]
        else:
            handle_without_at = channel_handle
            channel_handle = f"@{channel_handle}"
        
        # Method 1: Try legacy username lookup
        try:
            import requests
            url = f"{self.base_url}/channels"
            params = {
                'part': 'id',
                'forUsername': handle_without_at,
                'key': self.api_key
            }
            
            response = requests.get(url, params=params)
            self.quota_used += 1
            
            if response.status_code == 200:
                data = response.json()
                if data.get('items'):
                    return data['items'][0]['id']
        except Exception as e:
            print(f"Error trying forUsername lookup: {e}")
        
        # Method 2: Search for the channel
        try:
            import requests
            url = f"{self.base_url}/search"
            params = {
                'part': 'snippet',
                'q': channel_handle,
                'type': 'channel',
                'maxResults': 10,
                'key': self.api_key
            }
            
            response = requests.get(url, params=params)
            self.quota_used += 100  # Search costs 100 units
            
            if response.status_code == 200:
                data = response.json()
                # Look for exact handle match in results
                for item in data.get('items', []):
                    snippet = item.get('snippet', {})
                    custom_url = snippet.get('customUrl', '').lower()
                    title = snippet.get('title', '').lower()
                    
                    # Check if this matches our target channel
                    if (custom_url == channel_handle.lower() or 
                        custom_url == handle_without_at.lower() or
                        channel_handle.lower().replace('@', '') in custom_url):
                        return item['id']['channelId']
                        
                # If no exact match, return first result as fallback
                if data.get('items'):
                    return data['items'][0]['id']['channelId']
                    
            else:
                print(f"Search API failed with status {response.status_code}")
                if response.status_code == 403:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get('error', {}).get('message', 'Unknown error')
                        print(f"API Error 403: {error_msg}")
                    except:
                        print("API Error 403: Likely quota exceeded or insufficient permissions")
                        
        except Exception as e:
            print(f"Error in channel search: {e}")
        
        return None
    
    
    def extract_transcript(self, video_id: str, save_to_file: bool = False, 
                          output_dir: str = 'transcripts') -> Dict[str, str]:
        """
        Extract transcripts in multiple languages using yt-dlp
        Matches the exact implementation from the working proof of concept
        
        Args:
            video_id (str): YouTube video ID
            save_to_file (bool): Whether to save transcript files
            output_dir (str): Directory for saved files
            
        Returns:
            Dict[str, str]: Dictionary with language codes as keys and transcript text as values
        """
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
                    return {}
                
                # Process each available target language
                found_languages = list(available_captions.keys())
                found_languages.sort(key=lambda x: target_languages.index(x) if x in target_languages else 999)
                
                print(f"Found captions in these target languages: {found_languages}")
                
                transcripts = {}
                for lang in found_languages:
                    caption_data = available_captions[lang]
                    caption_type = caption_data['type']
                    
                    print(f"Processing {caption_type} captions in {lang}...")
                    
                    transcript = self._process_subtitle_formats_exact(ydl, caption_data['formats'], lang)
                    if transcript:
                        # Convert transcript data to text
                        transcript_text = ' '.join(item['text'] for item in transcript)
                        transcripts[lang] = transcript_text
                
                return transcripts
        
        except Exception as e:
            print(f"Error retrieving captions: {e}")
        
        return {}
    
    def _process_subtitle_formats_exact(self, ydl, formats, lang: str) -> Optional[List]:
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

    def _process_subtitle_exact(self, ydl, subtitle, lang: str) -> Optional[List]:
        """Process a single subtitle format - EXACT from working code"""
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
                            start_time = self.parse_timestamp_exact(start_str)
                            end_time = self.parse_timestamp_exact(end_str)
                            
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
                        start_time = self.parse_timestamp_exact(begin)
                        end_time = self.parse_timestamp_exact(end)
                        
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

    def parse_timestamp_exact(self, timestamp):
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
    
    def _process_subtitle_formats(self, ydl, formats, lang: str) -> Optional[List]:
        """Process subtitle formats and extract text"""
        # Try JSON3 format first
        json_format = next((fmt for fmt in formats if fmt.get('ext') == 'json3'), None)
        if json_format and 'url' in json_format:
            transcript = self._process_subtitle(ydl, json_format, lang)
            if transcript:
                return transcript
        
        # Try other formats
        for fmt in formats:
            if 'url' in fmt:
                transcript = self._process_subtitle(ydl, fmt, lang)
                if transcript:
                    return transcript
        
        return None
    
    def _process_subtitle(self, ydl, subtitle, lang: str) -> Optional[List]:
        """Process a single subtitle format and extract text"""
        try:
            subtitle_url = subtitle.get('url')
            if not subtitle_url:
                return None
            
            response = ydl.urlopen(subtitle_url)
            subtitle_content = response.read().decode('utf-8')
            format_ext = subtitle.get('ext', '')
            
            if format_ext == 'json3':
                # Process JSON format (matching working script)
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
                # Process WebVTT or SRT formats (matching working script)
                transcript = []
                lines = subtitle_content.split('\n')
                
                for i, line in enumerate(lines):
                    # Skip headers and empty lines
                    if '-->' in line:
                        # This is a timestamp line
                        time_parts = line.split('-->')
                        if len(time_parts) == 2:
                            start_str = time_parts[0].strip()
                            end_str = time_parts[1].strip().split(' ')[0]  # Remove any styling info
                            
                            # Parse timestamps
                            start_time = self.parse_timestamp_helper(start_str)
                            end_time = self.parse_timestamp_helper(end_str)
                            
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
                # Basic TTML processing (matching working script structure)
                import xml.etree.ElementTree as ET
                root = ET.fromstring(subtitle_content)
                transcript = []
                
                # Find all text elements
                for elem in root.findall('.//{http://www.w3.org/ns/ttml}p'):
                    begin = elem.get('begin')
                    end = elem.get('end')
                    
                    if begin and end:
                        start_time = self.parse_timestamp_helper(begin)
                        end_time = self.parse_timestamp_helper(end)
                        
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
    
    def parse_timestamp_helper(self, timestamp):
        """Parse various timestamp formats to seconds (helper for transcript processing)"""
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

    def parse_duration(self, duration_str: str) -> Optional[int]:
        """
        Parse YouTube duration format (PT3M37S) to seconds
        
        Args:
            duration_str (str): Duration string in ISO 8601 format
            
        Returns:
            Optional[int]: Duration in seconds
        """
        if not duration_str:
            return None
            
        try:
            # Remove PT prefix
            duration_str = duration_str.replace('PT', '')
            
            # Extract hours, minutes, seconds
            hours = 0
            minutes = 0
            seconds = 0
            
            if 'H' in duration_str:
                hours_part, duration_str = duration_str.split('H')
                hours = int(hours_part)
            
            if 'M' in duration_str:
                minutes_part, duration_str = duration_str.split('M')
                minutes = int(minutes_part)
            
            if 'S' in duration_str:
                seconds_part = duration_str.replace('S', '')
                seconds = int(seconds_part)
            
            return hours * 3600 + minutes * 60 + seconds
            
        except Exception as e:
            print(f"Error parsing duration {duration_str}: {e}")
            return None
    
    def rate_limit(self):
        """Apply rate limiting to prevent API quota exhaustion"""
        if self.rate_limit_delay > 0:
            time.sleep(self.rate_limit_delay)
    
    def get_quota_usage(self) -> int:
        """Get current quota usage"""
        return self.quota_used