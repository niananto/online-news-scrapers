# YouTube Data Extraction Pipeline - Setup Guide

## 🎯 Overview

This guide will help you set up and use the production-ready YouTube data extraction pipeline that monitors YouTube channels, extracts video metadata with transcripts, and stores the data for content analysis to detect negativity/hatred.

## 📋 Prerequisites

### 1. System Requirements
- Python 3.10+ 
- PostgreSQL database
- YouTube Data API v3 key
- Chrome browser (for transcript extraction)

### 2. YouTube API Setup
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable YouTube Data API v3
4. Create credentials (API key)
5. Copy the API key for environment setup

### 3. Database Requirements
- PostgreSQL instance running
- Database named `shottify_db_new` (configurable)
- Required permissions for table creation

## 🚀 Quick Start

### Step 1: Environment Setup

Create `.env` file in the project root:

```bash
# Database Configuration
DB_HOST=localhost
DB_DATABASE=shottify_db_new
DB_USER=postgres
DB_PASSWORD=your_password
DB_PORT=5432

# YouTube API Configuration
YOUTUBE_API_KEY=your_youtube_api_key_here

# Optional Settings
LOG_LEVEL=INFO
```

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt
pip install -r requirements-youtube.txt
```

### Step 3: Initialize Database Schema

```bash
# Create database tables
python create-database/sources_table.py
python create-database/youtube_videos_table.py
```

### Step 4: Test the Pipeline

```bash
# Run comprehensive tests
python test_youtube_pipeline.py
```

### Step 5: Start the Server

```bash
# Start the unified server
python unified_server.py

# Server will be available at: http://localhost:8000
# API documentation at: http://localhost:8000/docs
```

## 📊 Database Schema

The pipeline creates a comprehensive `youtube_videos` table with the following structure:

### Core Video Metadata
- `video_id`: YouTube's unique identifier (primary key for deduplication)
- `title`, `description`: Video content
- `url`, `thumbnail_url`: Video links
- `channel_id`, `channel_title`, `channel_handle`: Channel information

### Engagement Metrics
- `view_count`, `like_count`, `comment_count`: Performance metrics
- `duration_seconds`, `duration_text`: Video length

### Content Analysis Fields
- `tags[]`: Video tags as PostgreSQL array
- `english_transcript`, `bengali_transcript`: Extracted transcripts
- `transcript_languages[]`: Available transcript languages
- `comments`: Comments as JSONB for analysis

### Processing & Analysis
- `sentiment_score`: For future sentiment analysis
- `content_category`: Content categorization
- `processing_status`: Pipeline status tracking
- `search_vector`: Full-text search capability

## 🔧 API Usage Examples

### 1. Basic Channel Scraping

```bash
curl -X POST "http://localhost:8000/youtube/scrape-channels" \
  -H "Content-Type: application/json" \
  -d '{
    "channels": ["@WION", "@BBC"],
    "max_results": 50,
    "include_transcripts": true,
    "include_comments": true,
    "comments_limit": 20
  }'
```

### 2. Advanced Filtering

```bash
curl -X POST "http://localhost:8000/youtube/scrape-channels" \
  -H "Content-Type: application/json" \
  -d '{
    "channels": ["@WION"],
    "max_results": 100,
    "keywords": ["bangladesh", "news", "politics"],
    "hashtags": ["breaking", "asia"],
    "published_after": "2025-08-08T00:00:00Z",
    "published_before": "2025-08-12T23:59:59Z",
    "include_transcripts": true,
    "include_comments": true
  }'
```

### 3. Retrieve Stored Videos

```bash
# Get videos by channel
curl "http://localhost:8000/youtube/videos?channel_handle=@WION&limit=100"

# Search videos by content
curl "http://localhost:8000/youtube/videos?search_term=bangladesh&limit=50"
```

### 4. Set Up Automated Monitoring

```bash
curl -X POST "http://localhost:8000/youtube/schedule" \
  -H "Content-Type: application/json" \
  -d '{
    "channels": ["@WION", "@BBC", "@CNN"],
    "max_results": 50,
    "keywords": ["bangladesh", "news"],
    "interval_minutes": 60,
    "enabled": true
  }'
```

### 5. Check System Status

```bash
# YouTube database statistics
curl "http://localhost:8000/youtube/stats"

# Scheduler status
curl "http://localhost:8000/youtube/schedule/status"

# Monitored channels
curl "http://localhost:8000/youtube/channels"
```

## 📝 Python Usage Examples

### Direct Scraper Usage

```python
import os
from youtube_scrapers.channel_scraper import YouTubeChannelScraper
from youtube_database_service import YouTubeDatabaseService

# Initialize services
api_key = os.getenv('YOUTUBE_API_KEY')
scraper = YouTubeChannelScraper(api_key)
db_service = YouTubeDatabaseService()

# Scrape channel videos
videos = scraper.scrape_channel(
    channel_handle="@WION",
    max_results=50,
    keywords=["bangladesh", "news"],
    include_transcripts=True,
    include_comments=True
)

# Store in database
result = db_service.insert_videos(videos)
print(f"Stored {result['new_videos']} new videos")
```

### Database Queries

```python
from youtube_database_service import YouTubeDatabaseService

db_service = YouTubeDatabaseService()

# Get videos for analysis
videos = db_service.get_videos_for_analysis(limit=100)

# Search specific content
results = db_service.search_videos("hatred OR negative", limit=50)

# Channel statistics
stats = db_service.get_database_stats()
print(f"Total videos: {stats['total_videos']}")
```

## ⚙️ Configuration Options

### YouTube Channels to Monitor

Edit the `YOUTUBE_SCHEDULER_CONFIG` in `unified_server.py`:

```python
YOUTUBE_SCHEDULER_CONFIG = {
    'channels': [
        '@WION',           # Indian news
        '@BBC',            # International news  
        '@CNN',            # US news
        '@AlJazeeraEnglish', # Middle East news
        '@your_channel'    # Add your channels
    ],
    'max_results': 50,
    'keywords': ['bangladesh', 'news', 'politics'], # Filter keywords
    'hashtags': ['breaking', 'asia'],               # Filter hashtags
    'interval_minutes': 60,                         # Check every hour
    'enabled': True                                 # Enable automation
}
```

### Content Filtering

```python
# Keywords for content relevance
keywords = [
    'bangladesh', 'news', 'politics', 
    'breaking', 'analysis', 'report'
]

# Hashtags for social monitoring
hashtags = [
    'breaking', 'news', 'politics', 
    'asia', 'southasia', 'bangladesh'
]

# Date range filtering
published_after = "2025-08-01T00:00:00Z"
published_before = "2025-08-31T23:59:59Z"
```

## 🔍 Content Analysis Integration

### 1. Extract Videos for Analysis

```python
# Get videos with transcripts ready for sentiment analysis
videos = db_service.get_videos_for_analysis(
    limit=100,
    processing_status='completed'
)

for video in videos:
    # Analyze English transcript
    if video['english_transcript']:
        sentiment = analyze_sentiment(video['english_transcript'])
        # Update database with sentiment score
    
    # Analyze Bengali transcript  
    if video['bengali_transcript']:
        sentiment = analyze_bengali_sentiment(video['bengali_transcript'])
```

### 2. Comments Analysis

```python
# Analyze comments for negative content
for video in videos:
    comments = video.get('comments', [])
    if isinstance(comments, str):
        comments = json.loads(comments)
    
    for comment in comments:
        # Detect hate speech or negativity
        if detect_negative_content(comment):
            # Flag video for manual review
            flag_for_review(video['video_id'], 'negative_comments')
```

### 3. Full-Text Search for Negative Content

```python
# Search for potentially negative content
negative_keywords = [
    'hate', 'violence', 'discrimination', 
    'extremist', 'radical', 'terrorist'
]

for keyword in negative_keywords:
    results = db_service.search_videos(keyword, limit=100)
    for video in results:
        # Review and categorize
        categorize_content(video, keyword)
```

## 📊 Monitoring and Analytics

### Database Statistics Dashboard

```python
stats = db_service.get_database_stats()

print(f"""
YouTube Pipeline Statistics:
============================
Total Videos: {stats['total_videos']}
Videos with Transcripts: {stats['videos_with_transcripts']} 
Recent Videos (7 days): {stats['recent_videos_7d']}

Top Channels:
{stats['top_channels']}

Language Distribution:
{stats['language_distribution']}

Average Engagement:
- Views: {stats['avg_engagement']['views']:,}
- Likes: {stats['avg_engagement']['likes']:,}
- Comments: {stats['avg_engagement']['comments']:,}
""")
```

### Automated Alerting

```python
# Set up alerts for specific content patterns
def check_for_alerts():
    # Check for high-negative content
    recent_videos = db_service.search_videos(
        "hate OR violence OR extremist", 
        limit=10
    )
    
    if len(recent_videos) > 5:  # Threshold
        send_alert("High negative content detected")
    
    # Check for unusual activity spikes
    stats = db_service.get_database_stats()
    if stats['recent_videos_7d'] > 1000:  # Threshold
        send_alert("Unusual content volume detected")
```

## 🚨 Error Handling and Troubleshooting

### Common Issues

1. **YouTube API Quota Exceeded**
```python
# Monitor quota usage
print(f"Current quota used: {scraper.get_quota_usage()}")

# Implement rate limiting
scraper.rate_limit_delay = 1.0  # 1 second between requests
```

2. **Transcript Extraction Failures**
```python
# Handle missing transcripts gracefully
try:
    videos = scraper.scrape_channel(
        channel_handle="@channel",
        include_transcripts=True
    )
except Exception as e:
    logger.error(f"Transcript extraction failed: {e}")
    # Continue without transcripts
```

3. **Database Connection Issues**
```python
# Test database connectivity
try:
    db_service = YouTubeDatabaseService()
    stats = db_service.get_database_stats()
    print("Database connection successful")
except Exception as e:
    logger.error(f"Database connection failed: {e}")
```

### Logging and Debugging

```python
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Monitor scraping progress
logger.info(f"Starting to scrape {channel_handle}")
logger.info(f"Found {len(videos)} videos")
logger.info(f"Quota used: {scraper.get_quota_usage()}")
```

## 🔐 Production Deployment

### Docker Configuration

```dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY requirements*.txt ./
RUN pip install -r requirements.txt
RUN pip install -r requirements-youtube.txt

COPY . .

ENV PYTHONPATH=/app

CMD ["uvicorn", "unified_server:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Environment Variables for Production

```bash
# Production .env
DB_HOST=prod-db-host
DB_DATABASE=prod_youtube_db
DB_USER=youtube_service
DB_PASSWORD=secure_password
DB_PORT=5432

YOUTUBE_API_KEY=prod_youtube_api_key

# Security
LOG_LEVEL=WARNING
API_RATE_LIMIT=100
MAX_CONCURRENT_REQUESTS=10

# Monitoring
ENABLE_METRICS=true
ALERT_WEBHOOK_URL=https://alerts.company.com/webhook
```

### Health Monitoring

```python
# Add health check endpoint
@app.get("/youtube/health")
async def youtube_health():
    try:
        # Test database
        db_service = YouTubeDatabaseService()
        stats = db_service.get_database_stats()
        
        # Test YouTube API (with minimal quota usage)
        api_key = os.getenv('YOUTUBE_API_KEY')
        if not api_key:
            raise Exception("YouTube API key not configured")
            
        return {
            "status": "healthy",
            "database": "connected",
            "youtube_api": "configured",
            "total_videos": stats.get('total_videos', 0)
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Health check failed: {e}")
```

## 📈 Next Steps

1. **Content Analysis Integration**: Use the stored data for sentiment analysis and hate speech detection
2. **Real-time Monitoring**: Set up automated alerts for concerning content
3. **Dashboard Creation**: Build a web interface for monitoring and analysis
4. **Multi-language Support**: Extend transcript analysis to more languages
5. **ML Model Integration**: Train models on the collected data for automated content classification

## 🆘 Support

For issues and questions:
1. Check the logs: `tail -f logs/youtube_pipeline.log`
2. Run the test suite: `python test_youtube_pipeline.py`
3. Check API documentation: `http://localhost:8000/docs`
4. Verify database connection: `psql -h localhost -U postgres -d shottify_db_new`

---

**Your production-ready YouTube data extraction pipeline is now ready to monitor channels and detect negative/harmful content! 🚀**