import psycopg2
from psycopg2 import sql
import os
from datetime import datetime

def create_sources_table():
    """
    Creates the sources table in the shottify_db PostgreSQL database
    """
    
    # Database connection parameters
    db_config = {
        'host': os.getenv('DB_HOST', 'localhost'),
        'database': 'shottify_db_new',
        'user': os.getenv('DB_USER', 'postgres'),
        'password': os.getenv('DB_PASSWORD', 'shottify123'),
        'port': os.getenv('DB_PORT', '5432')
    }
    
    # SQL to create the sources table
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS sources (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        source_type VARCHAR(100),
        platform VARCHAR(255),
        url TEXT,
        credibility_score DECIMAL(3,2),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        created_by UUID,
        
        CONSTRAINT valid_credibility_score CHECK (credibility_score >= 0 AND credibility_score <= 10)
    );
    """
    
    # SQL to create indexes
    create_indexes_sql = [
        "CREATE INDEX IF NOT EXISTS idx_sources_source_type ON sources(source_type);",
        "CREATE INDEX IF NOT EXISTS idx_sources_platform ON sources(platform);",
        "CREATE INDEX IF NOT EXISTS idx_sources_credibility ON sources(credibility_score DESC NULLS LAST);",
        "CREATE INDEX IF NOT EXISTS idx_sources_url ON sources(url) WHERE url IS NOT NULL;",
        "CREATE INDEX IF NOT EXISTS idx_sources_created_at ON sources(created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_sources_updated_at ON sources(updated_at DESC);"
    ]
    
    # SQL to create trigger function
    create_trigger_function_sql = """
    CREATE OR REPLACE FUNCTION update_sources_updated_at()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = NOW();
        RETURN NEW;
    END;
    $$ language 'plpgsql';
    """
    
    # SQL to create trigger
    create_trigger_sql = """
    DROP TRIGGER IF EXISTS update_sources_updated_at_trigger ON sources;
    CREATE TRIGGER update_sources_updated_at_trigger 
        BEFORE UPDATE ON sources
        FOR EACH ROW 
        EXECUTE FUNCTION update_sources_updated_at();
    """
    
    try:
        # Connect to PostgreSQL
        print("Connecting to PostgreSQL database...")
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()
        
        # Create the table
        print("Creating sources table...")
        cursor.execute(create_table_sql)
        
        # Create indexes
        print("Creating indexes...")
        for index_sql in create_indexes_sql:
            cursor.execute(index_sql)
        
        # Create trigger function
        print("Creating trigger function...")
        cursor.execute(create_trigger_function_sql)
        
        # Create trigger
        print("Creating trigger...")
        cursor.execute(create_trigger_sql)
        
        # Commit the changes
        conn.commit()
        print("Sources table created successfully!")
        
        # Insert sample data
        print("Inserting sample data...")
        sample_data_sql = """
        INSERT INTO sources (source_type, platform, url, credibility_score) 
        VALUES 
            ('news', 'BBC News', 'https://www.bbc.com/news', 8.5),
            ('social_media', 'Twitter', 'https://twitter.com/Reuters', 9.0),
            ('video', 'YouTube', 'https://www.youtube.com/c/CNN', 7.5)
        ON CONFLICT DO NOTHING;
        """
        cursor.execute(sample_data_sql)
        conn.commit()
        print("Sample data inserted successfully!")
        
    except psycopg2.Error as e:
        print(f"Error creating sources table: {e}")
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
    Main function to create the sources table
    """
    print("Starting sources table creation...")
    create_sources_table()
    print("Script completed.")

if __name__ == "__main__":
    main()