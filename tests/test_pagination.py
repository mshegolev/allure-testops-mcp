"""Unit tests for :func:`allure_testops_mcp._mcp.pagination_from`."""

from __future__ import annotations

from allure_testops_mcp._mcp import pagination_from


def test_pagination_full_response():
    data = {"totalElements": 100, "size": 20, "number": 2, "totalPages": 5}
    result = pagination_from(data)
    assert result == {
        "page": 2,
        "size": 20,
        "total": 100,
        "total_pages": 5,
        "has_more": True,
        "next_page": 3,
    }


def test_pagination_last_page():
    data = {"totalElements": 100, "size": 20, "number": 4, "totalPages": 5}
    result = pagination_from(data)
    assert result["has_more"] is False
    assert result["next_page"] is None


def test_pagination_single_page():
    data = {"totalElements": 5, "size": 20, "number": 0, "totalPages": 1}
    result = pagination_from(data)
    assert result["has_more"] is False
    assert result["next_page"] is None


def test_pagination_missing_total_pages_inferred():
    data = {"totalElements": 50, "size": 10, "number": 1}
    result = pagination_from(data)
    assert result["total_pages"] == 5
    assert result["has_more"] is True
    assert result["next_page"] == 2


def test_pagination_empty_response():
    data = {}
    result = pagination_from(data)
    assert result == {
        "page": 0,
        "size": 0,
        "total": 0,
        "total_pages": 0,
        "has_more": False,
        "next_page": None,
    }


def test_pagination_zero_size_no_inference():
    data = {"totalElements": 100, "size": 0, "number": 0, "totalPages": 0}
    result = pagination_from(data)
    assert result["total_pages"] == 0
    assert result["has_more"] is False
    assert result["next_page"] is None
