"""Tests for wikipedia module — response parsing with fixture data."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from city_guide.sources.wikipedia import WikiArticle, _fetch_page_details, _geosearch, fetch_nearby_articles
from city_guide.types import Language


def _make_geosearch_response() -> dict[str, Any]:
    return {
        "query": {
            "geosearch": [
                {"pageid": 100, "title": "Big Ben", "lat": 51.5007, "lon": -0.1246, "dist": 150.3},
                {"pageid": 200, "title": "Westminster Abbey", "lat": 51.4993, "lon": -0.1273, "dist": 300.5},
            ]
        }
    }


def _make_extracts_response() -> dict[str, Any]:
    return {
        "query": {
            "pages": {
                "100": {"pageid": 100, "title": "Big Ben", "extract": "Big Ben is a famous clock tower."},
                "200": {
                    "pageid": 200,
                    "title": "Westminster Abbey",
                    "extract": "Westminster Abbey is a large church.",
                },
            }
        }
    }


def _mock_httpx_response(data: dict[str, Any]) -> MagicMock:
    """Create a mock httpx response."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = data
    mock_resp.raise_for_status.return_value = None
    return mock_resp


async def test_geosearch_parses_results() -> None:
    mock_resp = _mock_httpx_response(_make_geosearch_response())
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("city_guide.sources.wikipedia.get_client", return_value=mock_client):
        results = await _geosearch(51.5, -0.1, 500, 5, Language.EN)
        assert len(results) == 2
        assert results[0]["title"] == "Big Ben"


async def test_fetch_page_details_parses_results() -> None:
    mock_resp = _mock_httpx_response(_make_extracts_response())
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("city_guide.sources.wikipedia.get_client", return_value=mock_client):
        details = await _fetch_page_details([100, 200], Language.EN)
        assert details[100].extract == "Big Ben is a famous clock tower."
        assert details[200].extract == "Westminster Abbey is a large church."
        assert details[100].thumbnail_url is None


async def test_fetch_page_details_empty_list() -> None:
    result = await _fetch_page_details([], Language.EN)
    assert result == {}


async def test_fetch_page_details_with_images() -> None:
    response: dict[str, Any] = {
        "query": {
            "pages": {
                "100": {
                    "pageid": 100,
                    "title": "Big Ben",
                    "extract": "Big Ben is a famous clock tower.",
                    "thumbnail": {
                        "source": "https://upload.wikimedia.org/thumb/BigBen.jpg",
                        "width": 300,
                        "height": 200,
                    },
                },
                "200": {
                    "pageid": 200,
                    "title": "Westminster Abbey",
                    "extract": "Westminster Abbey is a large church.",
                },
            }
        }
    }
    mock_resp = _mock_httpx_response(response)
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("city_guide.sources.wikipedia.get_client", return_value=mock_client):
        details = await _fetch_page_details([100, 200], Language.EN, with_images=True)
        assert details[100].thumbnail_url == "https://upload.wikimedia.org/thumb/BigBen.jpg"
        assert details[200].thumbnail_url is None


@patch("city_guide.sources.wikipedia._fetch_page_details", new_callable=AsyncMock)
@patch("city_guide.sources.wikipedia._geosearch", new_callable=AsyncMock)
async def test_fetch_nearby_articles(
    mock_geo: AsyncMock,
    mock_details: AsyncMock,
) -> None:
    from city_guide.sources.wikipedia import _PageDetails

    mock_geo.return_value = [
        {"pageid": 100, "title": "Big Ben", "lat": 51.5007, "lon": -0.1246, "dist": 150.3},
    ]
    mock_details.return_value = {100: _PageDetails(extract="Big Ben is a famous clock tower.")}

    articles = await fetch_nearby_articles(51.5, -0.1, radius=500, limit=5, language=Language.EN)
    assert len(articles) == 1
    assert isinstance(articles[0], WikiArticle)
    assert articles[0].title == "Big Ben"
    assert articles[0].extract == "Big Ben is a famous clock tower."
    assert articles[0].pageid == 100
    assert articles[0].thumbnail_url is None


@patch("city_guide.sources.wikipedia._fetch_page_details", new_callable=AsyncMock)
@patch("city_guide.sources.wikipedia._geosearch", new_callable=AsyncMock)
async def test_fetch_nearby_articles_with_images(
    mock_geo: AsyncMock,
    mock_details: AsyncMock,
) -> None:
    from city_guide.sources.wikipedia import _PageDetails

    mock_geo.return_value = [
        {"pageid": 100, "title": "Big Ben", "lat": 51.5007, "lon": -0.1246, "dist": 150.3},
    ]
    mock_details.return_value = {
        100: _PageDetails(extract="Big Ben is a famous clock tower.", thumbnail_url="https://example.com/bigben.jpg")
    }

    articles = await fetch_nearby_articles(51.5, -0.1, radius=500, limit=5, language=Language.EN, with_images=True)
    assert articles[0].thumbnail_url == "https://example.com/bigben.jpg"
    mock_details.assert_called_once_with([100], Language.EN, with_images=True)


@patch("city_guide.sources.wikipedia._geosearch", new_callable=AsyncMock, side_effect=Exception("network error"))
async def test_fetch_nearby_articles_handles_error(_mock_geo: AsyncMock) -> None:
    articles = await fetch_nearby_articles(51.5, -0.1, language=Language.EN)
    assert articles == []
