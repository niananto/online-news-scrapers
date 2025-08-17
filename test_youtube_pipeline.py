# !/usr/bin/env python3
"""
YouTube Data Extraction Pipeline Test Script

This script demonstrates and tests the complete YouTube data extraction pipeline.
It shows how to:
1. Set up the database schema
2. Use the YouTube scraper directly
3. Test the API endpoints
4. Configure automated monitoring

Prerequisites:
- PostgreSQL database running
- YouTube Data API v3 key
- Required Python packages installed
"""

import os
import asyncio
import json
from datetime import datetime
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import our YouTube components
from youtube_scrapers.channel_scraper import YouTubeChannelScraper
from youtube_database_service import YouTubeDatabaseService


def test_environment():
    """Test that all required environment variables are set"""
    print("🔧 Testing environment setup...")
    
    required_vars = {
        'DB_HOST': os.getenv('DB_HOST', 'localhost'),
        'DB_DATABASE': 'shottify_db_new',
        'DB_USER': os.getenv('DB_USER', 'postgres'),
        'DB_PASSWORD': os.getenv('DB_PASSWORD'),
        'YOUTUBE_API_KEY': os.getenv('YOUTUBE_API_KEY')
    }
    
    missing = []
    for var, value in required_vars.items():
        if not value:
            missing.append(var)
        else:
            print(f"✅ {var}: {'*' * len(value[:8])}...")
    
    if missing:
        print(f"❌ Missing environment variables: {missing}")
        print("\nPlease set the following environment variables:")
        for var in missing:
            print(f"  export {var}=your_value_here")
        return False
    
    print("✅ Environment setup complete")
    return True


def test_database_setup():
    """Test database connection and create tables if needed"""
    print("\n📊 Testing database setup...")
    
    try:
        # Test database connection
        db_service = YouTubeDatabaseService()
        source_id = db_service.get_or_create_youtube_source()
        print(f"✅ Database connection successful, YouTube source ID: {source_id}")
        
        # Create YouTube tables if they don't exist
        import sys
        import os
        sys.path.append(os.path.join(os.path.dirname(__file__), 'create-database'))
        from youtube_videos_table import create_youtube_content_table
        print("🏗️  Ensuring YouTube tables exist...")
        create_youtube_content_table()
        print("✅ Database schema verified")
        
        return True
        
    except Exception as e:
        print(f"❌ Database setup failed: {e}")
        return False


async def test_youtube_scraper():
    """Test the YouTube scraper directly"""
    print("\n🎥 Testing YouTube scraper...")
    
    api_key = os.getenv('YOUTUBE_API_KEY')
    if not api_key:
        print("❌ YouTube API key not found")
        return False
    
    try:
        # Initialize scraper
        scraper = YouTubeChannelScraper(api_key)
        
        # Test with a small number of videos
        test_channel = "@WION"
        print(f"📺 Testing with channel: {test_channel}")
        
        videos = scraper.scrape_channel(
            channel_handle=test_channel,
            max_results=5,  # Small number for testing
            include_comments=True,
            include_transcripts=True,
            comments_limit=10
        )
        
        print(f"✅ Successfully scraped {len(videos)} videos")
        print(f"🔄 Quota used: {scraper.get_quota_usage()}")
        
        if videos:
            sample_video = videos[0]
            print(f"📹 Sample video: {sample_video.title}")
            print(f"   📝 Description: {sample_video.description[:100]}...")
            print(f"   👀 Views: {sample_video.view_count}")
            print(f"   💬 Comments: {len(sample_video.comments)}")
            print(f"   📜 Transcripts: {len(sample_video.transcript_languages)} languages")
        
        return videos
        
    except Exception as e:
        print(f"❌ YouTube scraper test failed: {e}")
        return False


def test_database_operations(videos):
    """Test database storage and retrieval"""
    print("\n💾 Testing database operations...")
    
    if not videos:
        print("⚠️  No videos to test with")
        return False
    
    try:
        db_service = YouTubeDatabaseService()
        
        # Test insertion
        print("📥 Testing video insertion...")
        result = db_service.insert_videos(videos)
        print(f"✅ Insertion result: {result['new_videos']} new, {result['duplicate_videos']} duplicates")
        
        # Test retrieval by channel
        print("📤 Testing video retrieval...")
        channel_handle = videos[0].channel_handle
        stored_videos = db_service.get_videos_by_channel(channel_handle, limit=10)
        print(f"✅ Retrieved {len(stored_videos)} videos for channel {channel_handle}")
        
        # Test search
        if stored_videos:
            search_results = db_service.search_videos("news", limit=5)
            print(f"✅ Search found {len(search_results)} videos matching 'news'")
        
        # Test statistics
        stats = db_service.get_database_stats()
        print(f"✅ Database stats: {stats.get('total_videos', 0)} total videos")
        
        return True
        
    except Exception as e:
        print(f"❌ Database operations test failed: {e}")
        return False


def test_api_endpoints():
    """Test the FastAPI endpoints"""
    print("\n🌐 Testing API endpoints...")
    
    base_url = "http://localhost:8000"  # Adjust if your server runs on different port
    
    try:
        # Test health check
        response = requests.get(f"{base_url}/health")
        if response.status_code == 200:
            print("✅ Health check passed")
        else:
            print("⚠️  Health check failed - is the server running?")
            return False
        
        # Test YouTube stats endpoint
        response = requests.get(f"{base_url}/youtube/stats")
        if response.status_code == 200:
            stats = response.json()
            print(f"✅ YouTube stats: {stats}")
        else:
            print(f"⚠️  YouTube stats endpoint failed: {response.status_code}")
        
        # Test YouTube channels endpoint
        response = requests.get(f"{base_url}/youtube/channels")
        if response.status_code == 200:
            channels = response.json()
            print(f"✅ Found {channels.get('total_channels', 0)} monitored channels")
        else:
            print(f"⚠️  YouTube channels endpoint failed: {response.status_code}")
        
        return True
        
    except requests.exceptions.ConnectionError:
        print("⚠️  Could not connect to API server. Please start the server with:")
        print("   python unified_server.py")
        return False
    except Exception as e:
        print(f"❌ API endpoint test failed: {e}")
        return False


def demonstrate_api_usage():
    """Demonstrate how to use the API for YouTube scraping"""
    print("\n📖 API Usage Examples:")
    print("\n1. Scrape YouTube channels:")
    print("   POST /youtube/scrape-channels")
    print("   {")
    print('     "channels": ["@WION", "@BBC"],')
    print('     "max_results": 50,')
    print('     "keywords": ["bangladesh", "news"],')
    print('     "include_transcripts": true')
    print("   }")
    
    print("\n2. Get videos from database:")
    print("   GET /youtube/videos?channel_handle=@WION&limit=100")
    
    print("\n3. Search videos:")
    print("   GET /youtube/videos?search_term=politics&limit=50")
    
    print("\n4. Configure automated monitoring:")
    print("   POST /youtube/schedule")
    print("   {")
    print('     "channels": ["@WION", "@BBC"],')
    print('     "interval_minutes": 60,')
    print('     "enabled": true')
    print("   }")
    
    print("\n5. Check monitoring status:")
    print("   GET /youtube/schedule/status")
    
    print("\n6. Manually trigger monitoring:")
    print("   POST /youtube/schedule/trigger")


async def main():
    """Run all tests"""
    print("🚀 YouTube Data Extraction Pipeline Test")
    print("=" * 50)
    
    # Test environment
    if not test_environment():
        return
    
    # Test database setup
    if not test_database_setup():
        return
    
    # Test YouTube scraper
    videos = await test_youtube_scraper()
    if not videos:
        return
    
    # Test database operations
    if not test_database_operations(videos):
        return
    
    # Test API endpoints
    test_api_endpoints()
    
    # Show API usage examples
    demonstrate_api_usage()
    
    print("\n🎉 All tests completed!")
    print("\nNext steps:")
    print("1. Start the unified server: python unified_server.py")
    print("2. Visit http://localhost:8000 for API documentation")
    print("3. Use the API endpoints to scrape and monitor YouTube channels")
    print("4. Set up automated monitoring for your target channels")


if __name__ == "__main__":
    asyncio.run(main())