#!/usr/bin/env python3
"""Debug script to check session creation."""

import os
import sys

# Add the backend directory to the path
backend_path = os.path.join(os.path.dirname(__file__), "backend")
sys.path.insert(0, backend_path)

from app.db.session import TestingSessionLocal

print(f"TestingSessionLocal: {TestingSessionLocal}")
print(f"Type: {type(TestingSessionLocal)}")

# Try to create a session
try:
    db = TestingSessionLocal()
    print(f"Created session: {db}")
    print(f"Session type: {type(db)}")
    db.close()
except Exception as e:
    print(f"Error creating session: {e}")
    import traceback
    traceback.print_exc()