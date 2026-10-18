"""Publish a completed static OOXML view without overwriting concurrent files."""
from pathlib import Path
import os
import tempfile

from static_ooxml_view_dev1 import create_view as build_private_view

VERSION = 'hybridguard-static-ooxml-analysis-view-dev2'


def create_view(source, destination):
    source, destination = Path(source), Path(destination)
    if destination.suffix.lower() != '.xlsx' or destination.exists() or source.resolve() == destination.resolve():
        raise ValueError('Destination must be a new, separate xlsx analysis file')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Build in a private directory, then atomically publish using a hard link.
    # EEXIST leaves the competing file untouched; never unlink its path.
    with tempfile.TemporaryDirectory(prefix='.hybridguard-static-', dir=destination.parent) as folder:
        private = Path(folder) / 'view.xlsx'
        receipt = build_private_view(source, private)
        os.link(private, destination)
    return {**receipt, 'version': VERSION, 'package_builder_version': receipt['version'],
            'publication': 'atomic hard link; destination must not exist'}
