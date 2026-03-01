"""Integration test for tab completion against a live server."""

import pytest


@pytest.mark.skip(reason="Requires live server — implement when API client is ready")
def test_drive_path_completion():
    """Tab-completing a drive path should return folder/file names."""
    pass


@pytest.mark.skip(reason="Requires live server — implement when API client is ready")
def test_local_path_completion():
    """Tab-completing a ./ prefixed path should return local filesystem entries."""
    pass
