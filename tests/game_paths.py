"""Where the tests look for your own copy of the game files.

Nothing from the games is in this repo. The tests that need real game files
read them from the folders named by these environment variables, and skip when
a variable is not set or the folder is missing:

  SR_TEST_NB1_DIR   the NB1 `lu` folder (the one with global.lu in it)
  SR_TEST_PIP_DIR   the PiP `lu` folder
  SR_TEST_NB1_ISO   an NB1 disc image (.iso), only for the disc extractor test

For example, in PowerShell:

  $env:SR_TEST_NB1_DIR = "D:\\games\\nb1\\lu"
  $env:SR_TEST_PIP_DIR = "D:\\games\\pip\\lu"
  python -m pytest tests
"""
import os
from pathlib import Path

_UNSET = "SR_TEST_PATH_NOT_SET"


def _path(*names):
    for n in names:
        v = os.environ.get(n)
        if v:
            return Path(v)
    return Path(_UNSET)                     # does not exist, so the test that needs it skips


NB1_DIR = _path("SR_TEST_NB1_DIR", "SR_TEST_NB1_GLOBAL_DIR")
PIP_DIR = _path("SR_TEST_PIP_DIR")
NB1_ISO = _path("SR_TEST_NB1_ISO")
