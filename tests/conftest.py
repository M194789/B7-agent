import os
import tempfile
import uuid
from pathlib import Path

import pytest

# Isolate test task files, secrets and checkpoints from the user's workspace.
os.environ['B7_DATA_DIR'] = tempfile.mkdtemp(prefix='b7-demo-tests-')
os.environ['B7_MODEL_CACHE'] = '0'  # tests that check the cache turn it on themselves
os.environ.pop('B7_LLM_BASE_URL', None)
os.environ.pop('B7_LLM_MODEL', None)
os.environ.pop('B7_LLM_API_KEY', None)


@pytest.fixture
def tmp_path():
    path = Path(os.environ['B7_DATA_DIR']) / 'fixtures' / uuid.uuid4().hex
    path.mkdir(parents=True)
    return path


@pytest.fixture(autouse=True)
def no_habits_from_other_tests():
    """Habits are remembered across tasks; each test starts without any left by another."""
    from app import habits, store
    store.init()
    for h in habits.listing():
        habits.forget(h['key'])
    yield
