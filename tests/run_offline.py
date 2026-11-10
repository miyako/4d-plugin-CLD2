#!/usr/bin/env python3
"""Run the complete offline contract suite, forbidding skips and concurrent runs."""

import os
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).absolute().parent
lock = HERE / ".offline-suite.lock"
descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
try:
    os.write(descriptor, str(os.getpid()).encode())
    suite = unittest.defaultTestLoader.discover(str(HERE), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    leftovers = sorted(path.name for path in HERE.glob(".offline-*") if path != lock)
    print(f"OFFLINE: tests={result.testsRun} skips={len(result.skipped)} leftovers={leftovers}",
          flush=True)
    success = result.wasSuccessful() and not result.skipped and not leftovers
finally:
    os.close(descriptor)
    lock.unlink()
sys.exit(0 if success else 1)
