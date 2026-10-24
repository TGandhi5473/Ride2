import sys
import os
import requests
from sqlalchemy import text

# Ensure core is accessible
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import Config, get_neon_engine, setup_logger

logger = setup_logger("SmokeTest")

def test_db_readiness():
    """Checks connection, pgvector extension, and medallion schema."""
    logger.info("--- 🗄️ Testing Database & pgvector Readiness ---")
    try:
        engine = get_neon_engine()
        with engine.connect() as conn:
            # 1. Check pgvector (Crucial for Gold Layer embeddings)
            vector_check = conn.execute(text(
                "SELECT extname FROM pg_extension WHERE extname = 'vector';"
            )).fetchone()
            
            if vector_check:
                logger.info("✅ pgvector extension is enabled.")
            else:
                logger.warning("⚠️ pgvector NOT found. Run 'CREATE EXTENSION vector;' in Neon.")

            # 2. Check for Medallion Table existence
            # Using your specific table name from the old script
            table_check = conn.execute(text(
                "SELECT to_regclass('public.bronze_social_posts');"
            )).fetchone()
            
            if table_check[0]:
                logger.info("✅ Medallion schema (Bronze) detected.")
            else:
                logger.error("❌ Table 'bronze_social_posts' missing. Run 3_gold/schema.sql.")
                return False
        
        logger.info("✅ Database Connectivity: SUCCESS")
        return True
    except Exception as e:
        logger.error(f"❌ DB Connection Failed: {e}")
        return False

def test_external_apis():
    """Checks if API keys are valid by performing minimal no-cost requests."""
    logger.info("\n--- 🌐 Testing API Authentication ---")
    success = True
    
    # YouTube Check: Minimalist request for a known video
    if Config.YOUTUBE_API_KEY:
        yt_url = "https://www.googleapis.com/youtube/v3/videos"
        yt_res = requests.get(
            yt_url,
            params={"part": "id", "id": "Ks-_Mh1QhMc", "key": Config.YOUTUBE_API_KEY},
            timeout=5,
        )
        if yt_res.status_code == 200:
            logger.info("✅ YouTube API: Authorized.")
        else:
            logger.error(f"❌ YouTube API Failed: {yt_res.status_code}")
            success = False
    else:
        logger.error("❌ YouTube API Key missing from environment.")
        success = False

    # Bluesky Check: Resolving handle to prove existence
    if Config.BSKY_HANDLE:
        bsky_url = "https://bsky.social/xrpc/com.atproto.identity.resolveHandle"
        bsky_res = requests.get(bsky_url, params={"handle": Config.BSKY_HANDLE}, timeout=5)
        if bsky_res.status_code == 200:
            logger.info(f"✅ Bluesky: Handle '{Config.BSKY_HANDLE}' resolved.")
        else:
            logger.error(f"❌ Bluesky: Could not resolve handle.")
            success = False
    else:
        logger.error("❌ Bluesky credentials missing from environment.")
        success = False

    return success

if __name__ == "__main__":
    db_ok = test_db_readiness()
    api_ok = test_external_apis()
    
    if not db_ok or not api_ok:
        logger.error("\n💀 Smoke Test Failed. Environment is NOT production-ready.")
        sys.exit(1)
        
    logger.info("\n🚀 ALL SYSTEMS GO: Environment verified for production run.")
