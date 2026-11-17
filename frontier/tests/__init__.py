# SPDX-License-Identifier: Apache-2.0
"""Install the offline process guard before discovery imports any test module."""
import sys

sys.dont_write_bytecode = True

from . import sandbox

sandbox.install()
sandbox.install_test_guard()
