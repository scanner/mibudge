#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys
from pathlib import Path

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    from django.core.management import execute_from_command_line

    # This allows easy placement of apps within the interior
    # mibudge directory.
    current_path = Path(__file__).parent.resolve()
    sys.path.append(str(current_path / "mibudge"))

    execute_from_command_line(sys.argv)
