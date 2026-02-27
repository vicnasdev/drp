"""
Tests for cli.format — human_size, human_time.
Tests for cli.api.helpers — slug.
"""

import pytest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta

from cli.format import human_size, human_time
from cli.api.helpers import slug


# ── human_size ────────────────────────────────────────────────────────────────

class TestHumanSize:
    def test_zero_returns_dash(self):
        assert human_size(0) == '-'

    def test_none_returns_dash(self):
        assert human_size(None) == '-'

    def test_one_byte(self):
        assert human_size(1) == '1B'

    def test_bytes_no_decimal(self):
        assert human_size(512) == '512B'

    def test_kilobytes(self):
        result = human_size(2048)
        assert 'K' in result
        assert result.startswith('2')

    def test_megabytes(self):
        result = human_size(5 * 1024 * 1024)
        assert 'M' in result

    def test_gigabytes(self):
        result = human_size(3 * 1024 ** 3)
        assert 'G' in result

    def test_terabytes(self):
        result = human_size(2 * 1024 ** 4)
        assert 'T' in result

    def test_exact_1024_is_1k(self):
        assert human_size(1024) == '1.0K'


# ── human_time ────────────────────────────────────────────────────────────────

class TestHumanTime:
    def _iso(self, delta_seconds):
        """Return an ISO timestamp `delta_seconds` in the past."""
        dt = datetime.now(timezone.utc) - timedelta(seconds=delta_seconds)
        return dt.isoformat()

    def test_none_returns_dash(self):
        assert human_time(None) == '-'

    def test_empty_returns_dash(self):
        assert human_time('') == '-'

    def test_just_now(self):
        assert human_time(self._iso(5)) == 'just now'

    def test_minutes_ago(self):
        result = human_time(self._iso(300))
        assert 'm ago' in result

    def test_hours_ago(self):
        result = human_time(self._iso(7200))
        assert 'h ago' in result

    def test_days_ago(self):
        result = human_time(self._iso(86400 * 3))
        assert 'd ago' in result

    def test_old_date_shows_yyyy_mm_dd(self):
        result = human_time(self._iso(86400 * 30))
        assert '-' in result  # YYYY-MM-DD format
        assert len(result) == 10

    def test_invalid_string_returns_prefix(self):
        result = human_time('not-a-date-at-all')
        assert result == 'not-a-date'

    def test_z_suffix_handled(self):
        ts = datetime.now(timezone.utc) - timedelta(seconds=10)
        iso = ts.strftime('%Y-%m-%dT%H:%M:%SZ')
        assert human_time(iso) == 'just now'


# ── slug ──────────────────────────────────────────────────────────────────────

class TestSlug:
    def test_strips_extension(self):
        assert slug('notes.txt') == 'notes'

    def test_spaces_become_hyphens(self):
        assert slug('my cool file.pdf') == 'my-cool-file'

    def test_max_40_chars(self):
        assert len(slug('a' * 100 + '.txt')) <= 40

    def test_dotfile_nonempty(self):
        result = slug('.bashrc')
        assert len(result) > 0

    def test_no_leading_hyphens(self):
        assert not slug('  spaced.txt  ').startswith('-')

    def test_no_trailing_hyphens(self):
        assert not slug('  spaced.txt  ').endswith('-')

    def test_no_consecutive_hyphens(self):
        assert '--' not in slug('hello   world.txt')

    def test_only_safe_chars(self):
        result = slug('café & résumé (final).docx')
        assert all(c.isalnum() or c in '-_' for c in result)

    def test_numbers_preserved(self):
        assert slug('report2024.pdf') == 'report2024'

    def test_underscores_preserved(self):
        assert slug('my_file.txt') == 'my_file'

    def test_empty_stem_gets_random(self):
        # A file like ".." has an empty stem after stripping
        result = slug('...')
        assert len(result) > 0  # falls back to token_urlsafe
