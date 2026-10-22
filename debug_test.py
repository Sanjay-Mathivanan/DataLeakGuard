import sys
sys.path.insert(0, './backend')

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import app.db.session
from app.db.base import Base
from app.main import app as fastapi_app
from app.db.session import get_db

SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///./test_test.db"
engine = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Override the dependency
def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.db.session.TestingSessionLocal = TestingSessionLocal
fastapi_app.dependency_overrides[get_db] = override_get_db
Base.metadata.create_all(bind=engine)

client = TestClient(fastapi_app)

try:
    csv_content = b'name,age,feature\nAlice,30,1\nBob,25,2\nCharlie,35,3\nDavid,40,4\n'
    response = client.post(
        '/api/v1/datasets',
        data={
            'name': 'preview test',
            'type': 'tabular',
            'format': 'CSV',
            'description': 'test'
        },
        files={'file': ('test.csv', csv_content, 'text/csv')}
    )
    print('Response status:', response.status_code)
    data = response.json()
    print('Response data:')
    for key, value in data.items():
        if key in ['preview_rows', 'columns', 'profile']:
            print(f'  {key}: {value}')
        else:
            print(f'  {key}: {value}')
finally:
    Base.metadata.drop_all(bind=engine)
    app.db.session.TestingSessionLocal = app.db.session.__dict__.get('TestingSessionLocal', None)  # restore? not important
    fastapi_app.dependency_overrides.clear()
