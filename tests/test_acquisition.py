"""Tests for STAC API queries and band loading.

These tests verify the query logic without making real HTTP requests.
Integration tests that hit actual STAC APIs should be run separately.
"""

from unittest.mock import MagicMock, patch

import pytest

from config.settings import AOI_BBOX, ELEMENT84_URL, SENTINEL2_COLLECTION
from src.acquisition.stac_client import (
    _build_datetime_range,
    search_element84,
    search_sentinel2_with_fallback,
)


class TestDatetimeRange:
    def test_explicit_range(self):
        result = _build_datetime_range("2024-01-01", "2024-06-30")
        assert result == "2024-01-01/2024-06-30"

    def test_default_range(self):
        result = _build_datetime_range()
        parts = result.split("/")
        assert len(parts) == 2
        # Both parts should be valid date strings
        assert len(parts[0]) == 10
        assert len(parts[1]) == 10


class TestSearchElement84:
    @patch("src.acquisition.stac_client.Client")
    def test_returns_items(self, mock_client_class):
        mock_catalog = MagicMock()
        mock_client_class.open.return_value = mock_catalog

        mock_search = MagicMock()
        mock_items = MagicMock()
        mock_items.__len__ = MagicMock(return_value=5)
        mock_search.item_collection.return_value = mock_items
        mock_catalog.search.return_value = mock_search

        result = search_element84(
            bbox=AOI_BBOX,
            datetime_range="2024-01-01/2024-06-30",
        )

        mock_client_class.open.assert_called_once_with(ELEMENT84_URL)
        mock_catalog.search.assert_called_once()
        assert result == mock_items

    @patch("src.acquisition.stac_client.Client")
    def test_passes_cloud_filter(self, mock_client_class):
        mock_catalog = MagicMock()
        mock_client_class.open.return_value = mock_catalog

        mock_search = MagicMock()
        mock_search.item_collection.return_value = MagicMock(__len__=MagicMock(return_value=0))
        mock_catalog.search.return_value = mock_search

        search_element84(
            bbox=AOI_BBOX,
            datetime_range="2024-01-01/2024-06-30",
            max_cloud_cover=15,
        )

        call_kwargs = mock_catalog.search.call_args[1]
        assert call_kwargs["query"]["eo:cloud_cover"]["lt"] == 15


class TestFallback:
    @patch("src.acquisition.stac_client.search_planetary_computer")
    @patch("src.acquisition.stac_client.search_element84")
    def test_falls_back_when_empty(self, mock_e84, mock_pc):
        mock_e84_items = MagicMock()
        mock_e84_items.__len__ = MagicMock(return_value=0)
        mock_e84.return_value = mock_e84_items

        mock_pc_items = MagicMock()
        mock_pc_items.__len__ = MagicMock(return_value=3)
        mock_pc.return_value = mock_pc_items

        result = search_sentinel2_with_fallback()

        mock_e84.assert_called_once()
        mock_pc.assert_called_once()
        assert result == mock_pc_items

    @patch("src.acquisition.stac_client.search_planetary_computer")
    @patch("src.acquisition.stac_client.search_element84")
    def test_no_fallback_when_has_results(self, mock_e84, mock_pc):
        mock_e84_items = MagicMock()
        mock_e84_items.__len__ = MagicMock(return_value=5)
        mock_e84.return_value = mock_e84_items

        result = search_sentinel2_with_fallback()

        mock_e84.assert_called_once()
        mock_pc.assert_not_called()
        assert result == mock_e84_items
