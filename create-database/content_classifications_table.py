import psycopg2
from psycopg2 import sql
import os
from datetime import datetime

def create_content_classifications_table():
    """
    Creates the content_classifications table in the shottify_db PostgreSQL database
    """
    
    # Database connection parameters
    db_config = {
        'host': os.getenv('DB_HOST', 'localhost'),
        'database': 'shottify_db',
        'user': os.getenv('DB_USER', 'postgres'),
        'password': os.getenv('DB_PASSWORD', 'shottify123'),
        'port': os.getenv('DB_PORT', '5432')
    }
    
    # SQL to create the content_classifications table
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS content_classifications (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        content_id UUID NOT NULL,
        ai_metadata TEXT,
        ai_response JSONB DEFAULT '{}'::jsonb,
        primary_topic VARCHAR(100),
        topic_confidence NUMERIC(3,2),
        content_classification VARCHAR(100),
        classification_confidence NUMERIC(3,2),
        sentiment VARCHAR(50),
        sentiment_confidence NUMERIC(3,2),
        urgency_level VARCHAR(50),
        urgency_confidence NUMERIC(3,2),
        political_bias VARCHAR(50),
        bias_confidence NUMERIC(3,2),
        credibility NUMERIC(3,1),
        manually_reviewed BOOLEAN DEFAULT false,
        reviewed_by UUID,
        reviewed_at TIMESTAMPTZ,
        review_notes TEXT,
        original_classification JSONB,
        small_analysis TEXT,
        medium_analysis TEXT,
        large_analysis TEXT,
        new_analysis_credibility_score INTEGER,
        new_analysis_misinformation_risk VARCHAR(10),
        new_analysis_narrative_tags TEXT[],
        
        -- Foreign key constraint
        CONSTRAINT fk_content_classifications_content_id FOREIGN KEY (content_id) REFERENCES content_items(id) ON DELETE CASCADE,
        
        -- Check constraints for confidence values
        CONSTRAINT check_topic_confidence CHECK (topic_confidence >= 0 AND topic_confidence <= 1),
        CONSTRAINT check_classification_confidence CHECK (classification_confidence >= 0 AND classification_confidence <= 1),
        CONSTRAINT check_sentiment_confidence CHECK (sentiment_confidence >= 0 AND sentiment_confidence <= 1),
        CONSTRAINT check_urgency_confidence CHECK (urgency_confidence >= 0 AND urgency_confidence <= 1),
        CONSTRAINT check_bias_confidence CHECK (bias_confidence >= 0 AND bias_confidence <= 1),
        CONSTRAINT check_credibility CHECK (credibility >= 0 AND credibility <= 10)
    );
    """
    
    # SQL to create indexes
    create_indexes_sql = [
        # Foreign key index
        "CREATE INDEX IF NOT EXISTS idx_content_classifications_content_id ON content_classifications(content_id);",
        
        # Classification indexes
        "CREATE INDEX IF NOT EXISTS idx_content_classifications_primary_topic ON content_classifications(primary_topic);",
        "CREATE INDEX IF NOT EXISTS idx_content_classifications_content_classification ON content_classifications(content_classification);",
        "CREATE INDEX IF NOT EXISTS idx_content_classifications_sentiment ON content_classifications(sentiment);",
        "CREATE INDEX IF NOT EXISTS idx_content_classifications_urgency_level ON content_classifications(urgency_level);",
        "CREATE INDEX IF NOT EXISTS idx_content_classifications_political_bias ON content_classifications(political_bias);",
        
        # Confidence indexes
        "CREATE INDEX IF NOT EXISTS idx_content_classifications_topic_confidence ON content_classifications(topic_confidence DESC);",
        "CREATE INDEX IF NOT EXISTS idx_content_classifications_classification_confidence ON content_classifications(classification_confidence DESC);",
        "CREATE INDEX IF NOT EXISTS idx_content_classifications_sentiment_confidence ON content_classifications(sentiment_confidence DESC);",
        "CREATE INDEX IF NOT EXISTS idx_content_classifications_urgency_confidence ON content_classifications(urgency_confidence DESC);",
        "CREATE INDEX IF NOT EXISTS idx_content_classifications_bias_confidence ON content_classifications(bias_confidence DESC);",
        "CREATE INDEX IF NOT EXISTS idx_content_classifications_credibility ON content_classifications(credibility DESC);",
        
        # Review indexes
        "CREATE INDEX IF NOT EXISTS idx_content_classifications_manually_reviewed ON content_classifications(manually_reviewed);",
        "CREATE INDEX IF NOT EXISTS idx_content_classifications_reviewed_by ON content_classifications(reviewed_by);",
        "CREATE INDEX IF NOT EXISTS idx_content_classifications_reviewed_at ON content_classifications(reviewed_at DESC);",
        
        # JSON indexes
        "CREATE INDEX IF NOT EXISTS idx_content_classifications_ai_response ON content_classifications USING gin(ai_response);",
        "CREATE INDEX IF NOT EXISTS idx_content_classifications_original_classification ON content_classifications USING gin(original_classification);",
        
        # New analysis indexes
        "CREATE INDEX IF NOT EXISTS idx_content_classifications_new_analysis_credibility ON content_classifications(new_analysis_credibility_score);",
        "CREATE INDEX IF NOT EXISTS idx_content_classifications_new_analysis_misinformation ON content_classifications(new_analysis_misinformation_risk);"
    ]
    
    # SQL to create trigger function for reviewed_at
    create_trigger_function_sql = """
    CREATE OR REPLACE FUNCTION update_content_classifications_reviewed_at()
    RETURNS TRIGGER AS $$
    BEGIN
        IF NEW.manually_reviewed = true AND OLD.manually_reviewed = false THEN
            NEW.reviewed_at = NOW();
        END IF;
        RETURN NEW;
    END;
    $$ language 'plpgsql';
    """
    
    # SQL to create trigger for reviewed_at
    create_trigger_sql = """
    DROP TRIGGER IF EXISTS update_content_classifications_reviewed_at_trigger ON content_classifications;
    CREATE TRIGGER update_content_classifications_reviewed_at_trigger 
        BEFORE UPDATE ON content_classifications
        FOR EACH ROW 
        EXECUTE FUNCTION update_content_classifications_reviewed_at();
    """
    
    try:
        # Connect to PostgreSQL
        print("Connecting to PostgreSQL database...")
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()
        
        # Create the table
        print("Creating content_classifications table...")
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
        print("Content_classifications table created successfully!")
        
        # Insert sample data
        # print("Inserting sample data...")
        # sample_data_sql = """
        # INSERT INTO content_classifications (
        #     content_id, 
        #     ai_metadata, 
        #     ai_response, 
        #     primary_topic, 
        #     topic_confidence,
        #     content_classification,
        #     classification_confidence,
        #     sentiment,
        #     sentiment_confidence,
        #     urgency_level,
        #     urgency_confidence,
        #     political_bias,
        #     bias_confidence,
        #     credibility,
        #     manually_reviewed,
        #     original_classification
        # ) 
        # SELECT 
        #     id as content_id,
        #     'Sample AI metadata for testing' as ai_metadata,
        #     '{"analysis": "sample", "confidence": 0.85}'::jsonb as ai_response,
        #     'Politics' as primary_topic,
        #     0.90 as topic_confidence,
        #     'News Article' as content_classification,
        #     0.85 as classification_confidence,
        #     'Neutral' as sentiment,
        #     0.75 as sentiment_confidence,
        #     'Medium' as urgency_level,
        #     0.80 as urgency_confidence,
        #     'Center' as political_bias,
        #     0.70 as bias_confidence,
        #     7.5 as credibility,
        #     false as manually_reviewed,
        #     '{"original": "sample_classification"}'::jsonb as original_classification
        # FROM content_items 
        # LIMIT 3
        # ON CONFLICT DO NOTHING;
        # """
        # cursor.execute(sample_data_sql)
        # conn.commit()
        # print("Sample data inserted successfully!")
        
        # Show table summary
        print("\n" + "="*50)
        print("TABLE SUMMARY")
        print("="*50)
        cursor.execute("SELECT COUNT(*) FROM content_classifications;")
        count = cursor.fetchone()[0]
        print(f"Total records: {count}")
        
        if count > 0:
            cursor.execute("""
                SELECT 
                    id, 
                    content_id, 
                    primary_topic, 
                    content_classification, 
                    sentiment, 
                    credibility,
                    manually_reviewed
                FROM content_classifications 
                LIMIT 3;
            """)
            
            print("\nSample records:")
            for row in cursor.fetchall():
                print(f"  ID: {row[0]}")
                print(f"  Content ID: {row[1]}")
                print(f"  Topic: {row[2]}")
                print(f"  Classification: {row[3]}")
                print(f"  Sentiment: {row[4]}")
                print(f"  Credibility: {row[5]}")
                print(f"  Reviewed: {row[6]}")
                print("-" * 30)
        
    except psycopg2.Error as e:
        print(f"Error creating content_classifications table: {e}")
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
    Main function to create the content_classifications table
    """
    print("Starting content_classifications table creation...")
    create_content_classifications_table()
    print("Script completed.")

if __name__ == "__main__":
    main()