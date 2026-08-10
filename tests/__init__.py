"""Test bootstrap: isolate jmem from the real install BEFORE jmem.core is
imported anywhere. jmem.core computes ROOT/DB_PATH at import time from
JMEM_HOME, so this must run first (unittest imports the tests package before
any test module)."""
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="jmem-test-")
os.environ["JMEM_HOME"] = _TMP
os.environ["JMEM_PROJECTS_ROOT"] = os.path.join(_TMP, "projects")
os.environ["JMEM_CONFIG_NO_CACHE"] = "1"
os.makedirs(os.environ["JMEM_PROJECTS_ROOT"], exist_ok=True)
