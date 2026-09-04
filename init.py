#!/usr/bin/env python3
"""
Initialization script for TBX Finance Assistant
Verifies setup and initializes database
"""

import os
import sys
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def check_environment():
    """Check environment configuration"""
    logger.info("Checking environment configuration...")
    
    env_file = Path(".env")
    if not env_file.exists():
        logger.warning(".env file not found. Copying from .env.example...")
        env_example = Path(".env.example")
        if env_example.exists():
            env_file.write_text(env_example.read_text())
            logger.info("Created .env from .env.example - PLEASE EDIT WITH YOUR CREDENTIALS")
            return False
        else:
            logger.error(".env.example not found!")
            return False
    
    # Check required environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    required_vars = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "QWEN_7B_MODEL_ID"
    ]
    
    missing = []
    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)
    
    if missing:
        logger.error(f"Missing environment variables: {', '.join(missing)}")
        logger.error("Please update .env with your values")
        return False
    
    logger.info("✓ Environment configuration OK")
    return True

def check_data_files():
    """Check if data files exist"""
    logger.info("Checking data files...")
    
    data_dir = Path("./data")
    required_files = [
        "transactions.csv",
        "vendor_payouts.csv",
        "reconciliation_status.csv",
        "chart_of_accounts.csv",
        "vendor_list.csv"
    ]
    
    missing = []
    for file in required_files:
        filepath = data_dir / file
        if not filepath.exists():
            missing.append(file)
        else:
            size_mb = filepath.stat().st_size / (1024 * 1024)
            logger.info(f"  ✓ {file} ({size_mb:.2f} MB)")
    
    if missing:
        logger.error(f"Missing data files: {', '.join(missing)}")
        logger.error("Please generate data first using: python generate_dataset_v2.py")
        return False
    
    logger.info("✓ All data files present")
    return True

def check_dependencies():
    """Check if required Python packages are installed"""
    logger.info("Checking Python dependencies...")
    
    required_packages = [
        "fastapi",
        "uvicorn",
        "langgraph",
        "langchain",
        "boto3",
        "redis",
        "duckdb",
        "pydantic",
        "pandas",
        "numpy",
        "scikit-learn"
    ]
    
    missing = []
    for package in required_packages:
        try:
            __import__(package.replace("-", "_"))
            logger.info(f"  ✓ {package}")
        except ImportError:
            missing.append(package)
    
    if missing:
        logger.error(f"Missing packages: {', '.join(missing)}")
        logger.error("Please install: pip install -r backend/requirements.txt")
        return False
    
    logger.info("✓ All dependencies installed")
    return True

def check_redis_connection():
    """Check Redis connection"""
    logger.info("Checking Redis connection...")
    
    try:
        import redis
        r = redis.Redis(host="localhost", port=6379, decode_responses=True)
        r.ping()
        logger.info("✓ Redis connection OK")
        return True
    except Exception as e:
        logger.warning(f"Redis not available: {e}")
        logger.warning("Try: docker run -d -p 6379:6379 redis:latest")
        return False  # Non-fatal

def initialize_database():
    """Initialize DuckDB with data"""
    logger.info("Initializing database...")
    
    try:
        os.chdir("backend")
        from database import get_db
        
        db = get_db()
        
        # Verify tables loaded
        tables = ["transactions", "vendor_payouts", "reconciliation_status",
                 "chart_of_accounts", "vendor_list"]
        
        for table in tables:
            count = db.execute_scalar(f"SELECT COUNT(*) FROM {table}")
            logger.info(f"  ✓ {table}: {count} rows")
        
        logger.info("✓ Database initialized successfully")
        return True
    
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False
    finally:
        os.chdir("..")

def print_summary(results):
    """Print initialization summary"""
    logger.info("\n" + "=" * 60)
    logger.info("INITIALIZATION SUMMARY")
    logger.info("=" * 60)
    
    checks = {
        "Environment": results[0],
        "Data Files": results[1],
        "Dependencies": results[2],
        "Redis (optional)": results[3],
        "Database": results[4]
    }
    
    for check_name, passed in checks.items():
        status = "✓" if passed else "✗"
        logger.info(f"{status} {check_name}")
    
    if all(results[:4]):  # Redis is optional
        logger.info("\n✓ INITIALIZATION COMPLETE!")
        logger.info("\nNext steps:")
        logger.info("1. Backend:  cd backend && python main.py")
        logger.info("2. Frontend: cd frontend && npm run dev")
        logger.info("3. API Docs: http://localhost:8000/docs")
        logger.info("4. Chat UI:  http://localhost:3000")
        return True
    else:
        logger.error("\n✗ INITIALIZATION FAILED - Fix issues above")
        return False

if __name__ == "__main__":
    # Change to project root if needed
    if os.path.exists("./backend") and os.path.exists("./data"):
        # Already in project root
        pass
    elif os.path.exists("../backend"):
        os.chdir("..")
    
    # Run checks
    results = [
        check_environment(),
        check_data_files(),
        check_dependencies(),
        check_redis_connection(),
        False  # Database check done at end
    ]
    
    # Initialize database only if other checks pass
    if results[0] and results[1] and results[2]:
        results[4] = initialize_database()
    
    # Print summary
    success = print_summary(results)
    
    sys.exit(0 if success else 1)
