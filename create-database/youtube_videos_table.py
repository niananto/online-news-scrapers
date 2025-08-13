import psycopg2
from psycopg2 import sql
import os
from datetime import datetime

def create_youtube_videos_table():
    """
    Creates the youtube_videos table in the shottify_db PostgreSQL database
    Based on the existing content_items pattern but optimized for YouTube video data
    """
    
    # Database connection parameters
    db_config = {
        'host': os.getenv('DB_HOST', 'localhost'),
        'database': 'shottify_db_new',
        'user': os.getenv('DB_USER', 'postgres'),
        'password': os.getenv('DB_PASSWORD', 'shottify123'),
        'port': os.getenv('DB_PORT', '5432')
    }
    
    # SQL to create the youtube_videos table
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS youtube_videos (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        source_id UUID NOT NULL,
        raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
        
        -- Core video metadata
        video_id VARCHAR(20) NOT NULL,
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
        published_at_text TEXT,
        duration_seconds INTEGER,
        duration_text VARCHAR(20),
        
        -- Engagement metrics
        view_count BIGINT DEFAULT 0,
        like_count INTEGER DEFAULT 0,
        comment_count INTEGER DEFAULT 0,
        
        -- Content metadata
        tags TEXT[], -- Array of tags
        default_audio_language VARCHAR(10),
        default_language VARCHAR(10),
        video_language VARCHAR(10),
        
        -- Transcript data
        english_transcript TEXT,
        bengali_transcript TEXT,
        transcript_languages VARCHAR(50)[], -- Available transcript languages
        
        -- Comments (JSON array of comment text)
        comments JSONB DEFAULT '[]'::jsonb,
        
        -- Processing metadata
        ingested_at TIMESTAMPTZ DEFAULT NOW(),
        last_updated TIMESTAMPTZ DEFAULT NOW(),
        processing_status VARCHAR(50) DEFAULT 'pending',
        needs_manual_review BOOLEAN DEFAULT false,
        
        -- Analysis fields for future use
        sentiment_score DECIMAL(3,2),
        content_category VARCHAR(100),
        language_detection_confidence DECIMAL(3,2),
        
        -- Search vector for full-text search
        search_vector TSVECTOR,
        
        -- Foreign key constraint
        CONSTRAINT fk_youtube_videos_source_id FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE,
        
        -- Unique constraint for video_id (YouTube's unique identifier)
        CONSTRAINT uk_youtube_videos_video_id UNIQUE (video_id)
    );
    """
    
    # SQL to create indexes
    create_indexes_sql = [
        # Primary search indexes
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_source_id ON youtube_videos(source_id);",
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_video_id ON youtube_videos(video_id);",
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_channel_id ON youtube_videos(channel_id);",
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_channel_handle ON youtube_videos(channel_handle);",
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_processing_status ON youtube_videos(processing_status);",
        
        # Time-based indexes
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_published_at ON youtube_videos(published_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_ingested_at ON youtube_videos(ingested_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_last_updated ON youtube_videos(last_updated DESC);",
        
        # Engagement metrics indexes
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_view_count ON youtube_videos(view_count DESC);",
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_like_count ON youtube_videos(like_count DESC);",
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_comment_count ON youtube_videos(comment_count DESC);",
        
        # Content search indexes
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_title ON youtube_videos USING gin(to_tsvector('english', title)) WHERE title IS NOT NULL;",
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_description ON youtube_videos USING gin(to_tsvector('english', description)) WHERE description IS NOT NULL;",
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_english_transcript ON youtube_videos USING gin(to_tsvector('english', english_transcript)) WHERE english_transcript IS NOT NULL;",
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_search_vector ON youtube_videos USING gin(search_vector) WHERE search_vector IS NOT NULL;",
        
        # Array and JSON indexes
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_tags ON youtube_videos USING gin(tags) WHERE tags IS NOT NULL;",
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_transcript_languages ON youtube_videos USING gin(transcript_languages) WHERE transcript_languages IS NOT NULL;",
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_comments ON youtube_videos USING gin(comments) WHERE comments IS NOT NULL;",
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_raw_data ON youtube_videos USING gin(raw_data);",
        
        # Language and content indexes
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_video_language ON youtube_videos(video_language) WHERE video_language IS NOT NULL;",
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_content_category ON youtube_videos(content_category) WHERE content_category IS NOT NULL;",
        
        # Analysis indexes
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_sentiment_score ON youtube_videos(sentiment_score) WHERE sentiment_score IS NOT NULL;",
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_needs_review ON youtube_videos(needs_manual_review) WHERE needs_manual_review = true;",
        
        # Composite indexes for common queries
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_channel_published ON youtube_videos(channel_id, published_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_youtube_videos_status_updated ON youtube_videos(processing_status, last_updated DESC);"
    ]
    
    # SQL to create trigger function for updated_at
    create_trigger_function_sql = """
    CREATE OR REPLACE FUNCTION update_youtube_videos_updated_at()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.last_updated = NOW();
        RETURN NEW;
    END;
    $$ language 'plpgsql';
    """
    
    # SQL to create trigger for updated_at
    create_trigger_sql = """
    DROP TRIGGER IF EXISTS update_youtube_videos_updated_at_trigger ON youtube_videos;
    CREATE TRIGGER update_youtube_videos_updated_at_trigger 
        BEFORE UPDATE ON youtube_videos
        FOR EACH ROW 
        EXECUTE FUNCTION update_youtube_videos_updated_at();
    """
    
    # SQL to create trigger function for search_vector
    create_search_vector_function_sql = """
    CREATE OR REPLACE FUNCTION update_youtube_videos_search_vector()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.search_vector = 
            setweight(to_tsvector('english', COALESCE(NEW.title, '')), 'A') ||
            setweight(to_tsvector('english', COALESCE(NEW.description, '')), 'B') ||
            setweight(to_tsvector('english', COALESCE(NEW.english_transcript, '')), 'B') ||
            setweight(to_tsvector('english', COALESCE(NEW.channel_title, '')), 'C') ||
            setweight(to_tsvector('english', COALESCE(array_to_string(NEW.tags, ' '), '')), 'D');
        RETURN NEW;
    END;
    $$ language 'plpgsql';
    """
    
    # SQL to create trigger for search_vector
    create_search_vector_trigger_sql = """
    DROP TRIGGER IF EXISTS update_youtube_videos_search_vector_trigger ON youtube_videos;
    CREATE TRIGGER update_youtube_videos_search_vector_trigger 
        BEFORE INSERT OR UPDATE ON youtube_videos
        FOR EACH ROW 
        EXECUTE FUNCTION update_youtube_videos_search_vector();
    """
    
    try:
        # Connect to PostgreSQL
        print("Connecting to PostgreSQL database...")
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()
        
        # Create the table
        print("Creating youtube_videos table...")
        cursor.execute(create_table_sql)
        
        # Create indexes
        print("Creating indexes...")
        for index_sql in create_indexes_sql:
            cursor.execute(index_sql)
        
        # Create trigger functions
        print("Creating trigger functions...")
        cursor.execute(create_trigger_function_sql)
        cursor.execute(create_search_vector_function_sql)
        
        # Create triggers
        print("Creating triggers...")
        cursor.execute(create_trigger_sql)
        cursor.execute(create_search_vector_trigger_sql)
        
        # Commit the changes
        conn.commit()
        print("YouTube videos table created successfully!")
        
        # Insert a YouTube source entry if it doesn't exist
        print("Ensuring YouTube source exists...")
        youtube_source_sql = """
        INSERT INTO sources (
            source_type, 
            platform, 
            url, 
            credibility_score
        ) 
        VALUES (
            'social_media',
            'YouTube',
            'https://www.youtube.com',
            0.75
        )
        ON CONFLICT DO NOTHING;
        """
        cursor.execute(youtube_source_sql)
        conn.commit()
        print("YouTube source entry ensured!")
        
    except psycopg2.Error as e:
        print(f"Error creating youtube_videos table: {e}")
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
    Main function to create the youtube_videos table
    """
    print("Starting youtube_videos table creation...")
    create_youtube_videos_table()
    print("Script completed.")

if __name__ == "__main__":
    main()