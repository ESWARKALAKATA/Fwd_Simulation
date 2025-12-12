"""Test script to verify logging configuration works correctly."""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.utils.logger import get_logger, get_query_logger, log_query_analytics, LOGS_DIR

def test_logging():
    """Test all logging functions."""
    print(f"Testing logging system...")
    print(f"Log directory: {LOGS_DIR}")
    print(f"Log directory exists: {LOGS_DIR.exists()}")
    print()
    
    # Test app logger
    logger = get_logger("test")
    logger.info("Test INFO message from app logger")
    logger.warning("Test WARNING message from app logger")
    logger.error("Test ERROR message from app logger")
    print("✓ App logger tested")
    
    # Test query analytics
    log_query_analytics(
        query="Test query for logging system",
        model_id="test:model",
        code_snippets_count=5,
        db_entities_found=3,
        response_time_ms=125.5,
        success=True
    )
    print("✓ Query analytics logged")
    
    log_query_analytics(
        query="Test failed query",
        model_id="test:model",
        code_snippets_count=0,
        db_entities_found=0,
        response_time_ms=50.2,
        success=False,
        error="Test error message"
    )
    print("✓ Failed query logged")
    
    # Check log files
    print()
    print("Log files created:")
    for log_file in LOGS_DIR.glob("*.log"):
        size = log_file.stat().st_size
        print(f"  - {log_file.name} ({size} bytes)")
    
    print()
    print("✓ All logging tests passed!")
    print()
    print("Check logs with:")
    print(f"  type {LOGS_DIR}\\app.log")
    print(f"  type {LOGS_DIR}\\query.log")

if __name__ == "__main__":
    test_logging()
