import sys
import os
sys.path.insert(0, 'backend')

from tests.test_train_test_contamination import test_train_test_contamination_with_time_column
from fastapi.testclient import TestClient
from app.main import app
from app.db.base import Base
from app.db import leakage_models
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

# Create test database
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///./test_test.db"
engine = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create test client
client = TestClient(app)

# Get a test db session
def get_test_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

# Override the dependencies
from app.db.session import get_db
from app.db import session as db_session
original_testing_session_local = db_session.TestingSessionLocal
db_session.TestingSessionLocal = TestingSessionLocal
app.dependency_overrides[get_db] = get_test_db

# Create the tables
print("Creating tables...")
Base.metadata.create_all(bind=engine)
print("Tables created:", list(Base.metadata.tables.keys()))

try:
    test_db = next(get_test_db())
    test_train_test_contamination_with_time_column(client, test_db)
    print("TEST PASSED")
except Exception as e:
    print(f"TEST FAILED: {e}")
    import traceback
    traceback.print_exc()
finally:
    # Clean up
    app.dependency_overrides.clear()
    db_session.TestingSessionLocal = original_testing_session_local
    # Drop tables
    Base.metadata.drop_all(bind=engine)
    try:
        test_db.close()
    except:
        pass