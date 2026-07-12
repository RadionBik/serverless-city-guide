"""Global test configuration — prevent tests from writing to production files."""

import os

os.environ["LOG_FILE"] = ""
