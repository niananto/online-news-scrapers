"""
Create YouTube API Quota Tracking Table

Optional table for persistent quota tracking across application restarts.
This enables quota state to survive container restarts in production.
"""

import psycopg2
from psycopg2 import sql
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_DATABASE', 'shottify_db_new'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', 'shottify123'),
    'port': os.getenv('DB_PORT', '5432')
}


def create_youtube_quota_table():
    """
    Create table for YouTube API quota tracking
    """
    
    create_table_query = """
    -- YouTube API Quota Tracking Table
    CREATE TABLE IF NOT EXISTS youtube_api_quota (
        -- Primary key
        id SERIAL PRIMARY KEY,
        
        -- API key identification (hashed for security)
        key_hash VARCHAR(32) NOT NULL,
        key_index INTEGER NOT NULL,  -- 1, 2, or 3 for easy identification
        
        -- Quota tracking
        units_used INTEGER DEFAULT 0,
        requests_count INTEGER DEFAULT 0,
        last_used_at TIMESTAMP,
        
        -- Daily reset tracking
        quota_date DATE DEFAULT CURRENT_DATE,
        last_reset TIMESTAMP DEFAULT NOW(),
        
        -- Status tracking
        is_exhausted BOOLEAN DEFAULT FALSE,
        last_error TEXT,
        
        -- Metadata
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        
        -- Ensure one entry per key per day
        UNIQUE(key_hash, quota_date)
    );
    
    -- Index for fast lookups
    CREATE INDEX IF NOT EXISTS idx_youtube_quota_key_date 
    ON youtube_api_quota(key_hash, quota_date);
    
    -- Index for current date queries
    CREATE INDEX IF NOT EXISTS idx_youtube_quota_date 
    ON youtube_api_quota(quota_date);
    """
    
    # Optional: Create a summary view
    create_view_query = """
    CREATE OR REPLACE VIEW youtube_quota_summary AS
    SELECT 
        key_index,
        key_hash,
        quota_date,
        units_used,
        requests_count,
        10000 - units_used as units_remaining,
        ROUND((units_used::numeric / 10000) * 100, 2) as usage_percentage,
        is_exhausted,
        last_used_at,
        last_error
    FROM youtube_api_quota
    WHERE quota_date = CURRENT_DATE
    ORDER BY key_index;
    """
    
    # Optional: Function to auto-reset quotas at midnight
    create_function_query = """
    CREATE OR REPLACE FUNCTION reset_youtube_quotas()
    RETURNS void AS $$
    BEGIN
        -- Mark yesterday's records as historical
        UPDATE youtube_api_quota 
        SET is_exhausted = FALSE 
        WHERE quota_date < CURRENT_DATE;
        
        -- Log the reset
        RAISE NOTICE 'YouTube API quotas reset for new day: %', CURRENT_DATE;
    END;
    $$ LANGUAGE plpgsql;
    """
    
    try:
        # Connect to database
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        print("Creating YouTube API quota tracking table...")
        
        # Create table
        cursor.execute(create_table_query)
        print("✓ Table 'youtube_api_quota' created successfully")
        
        # Create view
        cursor.execute(create_view_query)
        print("✓ View 'youtube_quota_summary' created successfully")
        
        # Create function
        cursor.execute(create_function_query)
        print("✓ Function 'reset_youtube_quotas' created successfully")
        
        # Commit changes
        conn.commit()
        
        # Show table structure
        cursor.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'youtube_api_quota'
            ORDER BY ordinal_position;
        """)
        
        print("\nTable structure:")
        print("-" * 80)
        print(f"{'Column':<20} {'Type':<20} {'Nullable':<10} {'Default':<30}")
        print("-" * 80)
        
        for column in cursor.fetchall():
            col_name, data_type, nullable, default = column
            default_str = str(default)[:28] if default else 'NULL'
            print(f"{col_name:<20} {data_type:<20} {nullable:<10} {default_str:<30}")
        
        print("-" * 80)
        print("\n✅ YouTube quota tracking table setup complete!")
        print("\nUsage:")
        print("1. The table will automatically track API usage")
        print("2. View current usage: SELECT * FROM youtube_quota_summary;")
        print("3. Reset quotas manually: SELECT reset_youtube_quotas();")
        print("4. The table supports up to 3 API keys (key_index: 1, 2, 3)")
        
    except psycopg2.Error as e:
        print(f"❌ Database error: {e}")
        if conn:
            conn.rollback()
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    print("=" * 80)
    print("YouTube API Quota Tracking Table Setup")
    print("=" * 80)
    print(f"Database: {DB_CONFIG['database']}")
    print(f"Host: {DB_CONFIG['host']}")
    print(f"Port: {DB_CONFIG['port']}")
    print("=" * 80)
    
    create_youtube_quota_table()