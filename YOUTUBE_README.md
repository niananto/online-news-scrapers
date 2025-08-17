# YouTube Data Extraction Pipeline

A production-ready YouTube video monitoring and analysis system built on top of the existing news scraping infrastructure. This system extracts comprehensive video data including metadata, comments, and transcripts from specified YouTube channels for content analysis and monitoring.

## 🚀 Features

### Core Capabilities
- **Multi-Channel Monitoring**: Monitor multiple YouTube channels simultaneously
- **Comprehensive Data Extraction**: Video metadata, engagement metrics, comments, and transcripts
- **Multi-Language Support**: Automatic transcript extraction in English and Bengali
- **Database Integration**: Structured storage with deduplication and full-text search
- **RESTful API**: Complete API interface for all operations
- **Automated Scheduling**: Configurable automated monitoring with interval-based execution
- **Production Ready**: Error handling, rate limiting, and quota management

### Data Extracted Per Video
- **Metadata**: Title, description, channel info, publish date, duration
- **Engagement**: View count, like count, comment count
- **Content**: Tags, language detection, thumbnail URL
- **Comments**: Configurable number of top comments
- **Transcripts**: Multi-language transcript extraction (English, Bengali)
- **Raw Data**: Complete YouTube API response preserved in JSONB

## 📋 Prerequisites

### Required Services
- **PostgreSQL Database**: For structured data storage
- **YouTube Data API v3 Key**: For accessing YouTube data
- **Python 3.10+**: Runtime environment

### API Keys Setup
```bash
# Get YouTube Data API v3 key from Google Cloud Console
export YOUTUBE_API_KEY="your_youtube_api_key_here"

# Database configuration
export DB_HOST="localhost"
export DB_DATABASE="shottify_db_new"
export DB_USER="postgres"
export DB_PASSWORD="your_password"
export DB_PORT="5432"
```

## 🛠️ Installation

### 1. Install Dependencies
```bash
# Install Python dependencies
pip install -r requirements.txt

# Key new dependencies for YouTube:
# - google-api-python-client: YouTube Data API v3
# - yt-dlp: Transcript extraction
# - google-auth: Authentication libraries
```

### 2. Database Setup
```bash
# Create YouTube tables
python create-database/youtube_content_table.py

# This creates:
# - youtube_content table with comprehensive schema
# - Indexes for optimal query performance
# - Full-text search capabilities
# - Automatic timestamp triggers
```

### 3. Test Installation
```bash
# Run the test pipeline
python test_youtube_pipeline.py

# This will:
# ✅ Verify environment setup
# ✅ Test database connection
# ✅ Test YouTube scraper with sample data
# ✅ Test database operations
# ✅ Test API endpoints (if server is running)
```

## 🌐 API Usage

### Start the Server
```bash
python unified_server.py
# Server runs on http://localhost:8000
# API documentation available at http://localhost:8000/docs
```

### Core Endpoints

#### 1. Scrape YouTube Channels
Extract videos from specified channels and store in database.

```bash
POST /youtube/scrape-channels
Content-Type: application/json

{
  "channels": ["@WION", "@BBC", "@CNN"],
  "max_results": 100,
  "published_after": "2025-08-01T00:00:00Z",
  "published_before": "2025-08-12T23:59:59Z",
  "keywords": ["bangladesh", "news"],
  "hashtags": ["politics", "asia"],
  "include_comments": true,
  "include_transcripts": true,
  "comments_limit": 50
}
```

**Response:**
```json
{
  "summary": {
    "channels_processed": 3,
    "successful_channels": 3,
    "failed_channels": 0,
    "total_scraped": 247,
    "total_stored": 198,
    "total_duplicates": 49,
    "quota_used": 1250
  },
  "database_result": {
    "new_videos": 198,
    "duplicate_videos": 49,
    "failed_videos": 0
  },
  "timestamp": "2025-08-12T10:30:00Z"
}
```

#### 2. Retrieve Videos
Query stored videos with filtering and search.

```bash
# Get videos by channel
GET /youtube/videos?channel_handle=@WION&limit=100&offset=0

# Full-text search
GET /youtube/videos?search_term=bangladesh politics&limit=50

# Get recent videos
GET /youtube/videos?limit=100
```

#### 3. YouTube Statistics
Get comprehensive analytics and statistics.

```bash
GET /youtube/stats
```

**Response:**
```json
{
  "youtube_statistics": {
    "total_videos": 1247,
    "top_channels": [
      {"channel": "@WION", "count": 523},
      {"channel": "@BBC", "count": 398}
    ],
    "recent_videos_7d": 89,
    "videos_with_transcripts": 1156,
    "language_distribution": [
      {"language": "en-GB", "count": 892},
      {"language": "en-US", "count": 245}
    ],
    "avg_engagement": {
      "views": 45623,
      "likes": 1234,
      "comments": 87
    }
  }
}
```

#### 4. Automated Monitoring

**Configure Monitoring:**
```bash
POST /youtube/schedule
Content-Type: application/json

{
  "channels": ["@WION", "@BBC", "@AlJazeeraEnglish"],
  "max_results_per_channel": 50,
  "keywords": ["bangladesh", "news"],
  "hashtags": ["politics"],
  "include_comments": true,
  "include_transcripts": true,
  "interval_minutes": 60,
  "enabled": true
}
```

**Check Status:**
```bash
GET /youtube/schedule/status
```

**Manual Trigger:**
```bash
POST /youtube/schedule/trigger
```

## 🗄️ Database Schema

### YouTube Videos Table
```sql
CREATE TABLE youtube_content (
    id UUID PRIMARY KEY,
    source_id UUID NOT NULL,
    raw_data JSONB NOT NULL,
    
    -- Core video metadata
    video_id VARCHAR(20) NOT NULL UNIQUE,
    title TEXT,
    description TEXT,
    url TEXT,
    thumbnail_url TEXT,
    
    -- Channel information
    channel_id VARCHAR(50) NOT NULL,
    channel_title VARCHAR(255),
    channel_handle VARCHAR(100),
    
    -- Publishing and timing
    published_at TIMESTAMPTZ,
    duration_seconds INTEGER,
    
    -- Engagement metrics
    view_count BIGINT DEFAULT 0,
    like_count INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    
    -- Content metadata
    tags TEXT[],
    video_language VARCHAR(10),
    
    -- Transcript data
    english_transcript TEXT,
    bengali_transcript TEXT,
    transcript_languages VARCHAR(50)[],
    
    -- Comments and processing
    comments JSONB DEFAULT '[]'::jsonb,
    processing_status VARCHAR(50) DEFAULT 'pending',
    
    -- Search vector for full-text search
    search_vector TSVECTOR,
    
    -- Timestamps
    ingested_at TIMESTAMPTZ DEFAULT NOW(),
    last_updated TIMESTAMPTZ DEFAULT NOW()
);
```

### Key Features
- **Deduplication**: Automatic duplicate prevention by video_id
- **Full-Text Search**: GIN indexes on title, description, and transcripts
- **JSONB Storage**: Raw API data preserved for flexibility
- **Comprehensive Indexing**: 25+ indexes for optimal query performance
- **Automatic Triggers**: Search vector and timestamp maintenance

## 🔧 Configuration

### Environment Variables
```bash
# Required
YOUTUBE_API_KEY="your_api_key"
DB_HOST="localhost"
DB_DATABASE="shottify_db_new"
DB_USER="postgres"
DB_PASSWORD="your_password"

# Optional
DB_PORT="5432"
LOG_LEVEL="INFO"
```

### Scheduler Configuration
```python
YOUTUBE_SCHEDULER_CONFIG = {
    'channels': ['@WION', '@BBC', '@CNN'],
    'max_results_per_channel': 50,
    'keywords': ['bangladesh', 'news'],
    'interval_minutes': 60,
    'enabled': False  # Enable via API
}
```

## 📊 Monitoring and Analytics

### Real-Time Monitoring
- **API Quota Usage**: Track YouTube API consumption
- **Processing Statistics**: Success/failure rates per channel
- **Database Growth**: Video count and storage metrics
- **Scheduler Status**: Automated job monitoring

### Content Analysis Integration
The extracted data is optimized for content analysis:
- **Transcript Analysis**: Full-text content available for sentiment analysis
- **Engagement Metrics**: Views, likes, comments for trend analysis
- **Multi-Language Support**: Bengali and English content handling
- **Temporal Analysis**: Time-series data for trend detection

## 🚨 Error Handling

### Robust Error Management
- **YouTube API Errors**: Graceful handling of quota limits and rate limiting
- **Network Failures**: Automatic retry with exponential backoff
- **Database Constraints**: Proper handling of duplicates and conflicts
- **Transcript Failures**: Fallback mechanisms when transcripts unavailable

### Logging and Monitoring
- **Structured Logging**: JSON-formatted logs with context
- **Performance Metrics**: Request latency and success rates
- **Quota Tracking**: YouTube API usage monitoring
- **Error Alerting**: Failed operations tracking

## 🔒 Security and Best Practices

### API Security
- **Environment Variables**: Secure credential management
- **Rate Limiting**: Respect YouTube API quotas and limits
- **Input Validation**: Pydantic models for request validation
- **Error Sanitization**: No sensitive data in error responses

### Database Security
- **Connection Pooling**: Efficient database connection management
- **SQL Injection Prevention**: Parameterized queries throughout
- **Access Control**: Database user permissions properly configured

## 📈 Performance Optimization

### Efficient Operations
- **Batch Processing**: Multiple videos processed together
- **Database Indexing**: Optimized queries for all common operations
- **Async Processing**: Non-blocking I/O for improved throughput
- **Caching**: Source ID caching to reduce database calls

### Scalability Features
- **Concurrent Scraping**: Multiple channels processed in parallel
- **Pagination Support**: Handle large result sets efficiently
- **Memory Management**: Streaming data processing to minimize memory usage

## 🎯 Use Cases

### Content Monitoring
- **News Monitoring**: Track news channels for specific topics
- **Brand Monitoring**: Monitor mentions and discussions
- **Competitor Analysis**: Track competitor channel activity
- **Trend Analysis**: Identify trending topics and hashtags

### Research Applications
- **Media Studies**: Analyze video content and engagement patterns
- **Sentiment Analysis**: Process transcripts for opinion mining
- **Language Processing**: Multi-language content analysis
- **Social Media Research**: Study video-based communication patterns

## 🚀 Getting Started Example

```python
# 1. Set up environment
export YOUTUBE_API_KEY="your_key"
export DB_PASSWORD="your_password"

# 2. Create database tables
python create-database/youtube_content_table.py

# 3. Test the pipeline
python test_youtube_pipeline.py

# 4. Start the server
python unified_server.py

# 5. Make your first API call
curl -X POST "http://localhost:8000/youtube/scrape-channels" \
     -H "Content-Type: application/json" \
     -d '{
       "channels": ["@WION"],
       "max_results": 10,
       "include_transcripts": true
     }'
```

## 📞 Support

### Documentation
- **API Docs**: http://localhost:8000/docs (when server is running)
- **Database Schema**: See `create-database/youtube_content_table.py`
- **Test Examples**: See `test_youtube_pipeline.py`

### Architecture Integration
This YouTube pipeline seamlessly integrates with the existing news scraping system:
- **Shared Database**: Uses same PostgreSQL instance and patterns
- **Unified API**: Extends existing FastAPI server
- **Common Patterns**: Follows same architectural principles
- **Monitoring**: Integrated with existing scheduler and monitoring

The system is designed to scale and can be extended for additional video platforms following the same patterns.