import psycopg2
from psycopg2 import sql
import os
from datetime import datetime

def create_content_items_table():
    """
    Creates the content_items table in the shottify_db PostgreSQL database
    """
    
    # Database connection parameters
    db_config = {
        'host': os.getenv('DB_HOST', 'localhost'),
        'database': 'shottify_db_new',
        'user': os.getenv('DB_USER', 'postgres'),
        'password': os.getenv('DB_PASSWORD', 'shottify123'),
        'port': os.getenv('DB_PORT', '5432')
    }
    
    # SQL to create the content_items table
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS content_items (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        source_id UUID NOT NULL,
        parent_id UUID,
        raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
        title TEXT,
        content_text TEXT,
        url TEXT,
        author_name VARCHAR(255),
        author_handle VARCHAR(255),
        published_at_text TEXT,
        ingested_at TIMESTAMPTZ DEFAULT NOW(),
        last_updated TIMESTAMPTZ DEFAULT NOW(),
        content_type VARCHAR(50) NOT NULL,
        language VARCHAR(50) DEFAULT 'english',
        processing_status VARCHAR(50) DEFAULT 'pending',
        needs_manual_review BOOLEAN DEFAULT false,
        likes_count_text TEXT,
        shares_count_text TEXT,
        comments_count_text TEXT,
        views_count_text TEXT,
        platform VARCHAR(100),

        search_vector TSVECTOR,
        
        -- Foreign key constraint
        CONSTRAINT fk_content_items_source_id FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE,
        
        -- Unique constraint for URL
        CONSTRAINT uk_content_items_url UNIQUE (url)
    );
    """
    
    # SQL to create indexes
    create_indexes_sql = [
        # Primary search indexes
        "CREATE INDEX IF NOT EXISTS idx_content_items_source_id ON content_items(source_id);",
        "CREATE INDEX IF NOT EXISTS idx_content_items_parent_id ON content_items(parent_id);",
        "CREATE INDEX IF NOT EXISTS idx_content_items_content_type ON content_items(content_type);",
        "CREATE INDEX IF NOT EXISTS idx_content_items_language ON content_items(language);",
        "CREATE INDEX IF NOT EXISTS idx_content_items_processing_status ON content_items(processing_status);",
        "CREATE INDEX IF NOT EXISTS idx_content_items_platform ON content_items(platform);",
        
        # Time-based indexes
        "CREATE INDEX IF NOT EXISTS idx_content_items_ingested_at ON content_items(ingested_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_content_items_last_updated ON content_items(last_updated DESC);",
        "CREATE INDEX IF NOT EXISTS idx_content_items_published_at ON content_items(published_at_text);",
        
        # Search indexes
        "CREATE INDEX IF NOT EXISTS idx_content_items_title ON content_items USING gin(to_tsvector('english', title)) WHERE title IS NOT NULL;",
        "CREATE INDEX IF NOT EXISTS idx_content_items_content ON content_items USING gin(to_tsvector('english', content_text)) WHERE content_text IS NOT NULL;",
        "CREATE INDEX IF NOT EXISTS idx_content_items_search_vector ON content_items USING gin(search_vector) WHERE search_vector IS NOT NULL;",
        
        # JSON indexes for raw_data
        "CREATE INDEX IF NOT EXISTS idx_content_items_raw_data ON content_items USING gin(raw_data);",
        
        # URL and author indexes
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_content_items_url_unique ON content_items(url) WHERE url IS NOT NULL;",
        "CREATE INDEX IF NOT EXISTS idx_content_items_author_name ON content_items(author_name) WHERE author_name IS NOT NULL;",
        "CREATE INDEX IF NOT EXISTS idx_content_items_author_handle ON content_items(author_handle) WHERE author_handle IS NOT NULL;",
        
        # Review and status indexes
        "CREATE INDEX IF NOT EXISTS idx_content_items_needs_review ON content_items(needs_manual_review) WHERE needs_manual_review = true;"
    ]
    
    # SQL to create trigger function for updated_at
    create_trigger_function_sql = """
    CREATE OR REPLACE FUNCTION update_content_items_updated_at()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.last_updated = NOW();
        RETURN NEW;
    END;
    $$ language 'plpgsql';
    """
    
    # SQL to create trigger for updated_at
    create_trigger_sql = """
    DROP TRIGGER IF EXISTS update_content_items_updated_at_trigger ON content_items;
    CREATE TRIGGER update_content_items_updated_at_trigger 
        BEFORE UPDATE ON content_items
        FOR EACH ROW 
        EXECUTE FUNCTION update_content_items_updated_at();
    """
    
    # SQL to create trigger function for search_vector
    create_search_vector_function_sql = """
    CREATE OR REPLACE FUNCTION update_content_items_search_vector()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.search_vector = 
            setweight(to_tsvector('english', COALESCE(NEW.title, '')), 'A') ||
            setweight(to_tsvector('english', COALESCE(NEW.content_text, '')), 'B') ||
            setweight(to_tsvector('english', COALESCE(NEW.author_name, '')), 'C');
        RETURN NEW;
    END;
    $$ language 'plpgsql';
    """
    
    # SQL to create trigger for search_vector
    create_search_vector_trigger_sql = """
    DROP TRIGGER IF EXISTS update_content_items_search_vector_trigger ON content_items;
    CREATE TRIGGER update_content_items_search_vector_trigger 
        BEFORE INSERT OR UPDATE ON content_items
        FOR EACH ROW 
        EXECUTE FUNCTION update_content_items_search_vector();
    """
    
    try:
        # Connect to PostgreSQL
        print("Connecting to PostgreSQL database...")
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()
        
        # Create the table
        print("Creating content_items table...")
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
        print("Content_items table created successfully!")
        
        # Insert sample data
        print("Inserting sample data...")
        sample_data_sql = """
        INSERT INTO content_items (
            source_id, 
            raw_data, 
            title, 
            content_text, 
            url, 
            author_name, 
            content_type, 
            language
        ) 
        SELECT 
            id as source_id,
            '{"title": "Sample Article", "content": "This is sample content", "author": "Sample Author"}'::jsonb as raw_data,
            'Sample Article from ' || platform as title,
            'This is sample content for testing the content_items table structure.' as content_text,
            url as url,
            'Sample Author' as author_name,
            'article' as content_type,
            'english' as language
        FROM sources 
        LIMIT 3
        ON CONFLICT DO NOTHING;
        """
        cursor.execute(sample_data_sql)
        conn.commit()
        print("Sample data inserted successfully!")
        
    except psycopg2.Error as e:
        print(f"Error creating content_items table: {e}")
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
    Main function to create the content_items table
    """
    print("Starting content_items table creation...")
    create_content_items_table()
    print("Script completed.")

if __name__ == "__main__":
    main()