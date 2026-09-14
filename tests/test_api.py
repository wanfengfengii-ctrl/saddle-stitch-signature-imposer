"""HTTP 层测试：合法请求、422 校验错误、错误响应结构。"""

import itertools

import pytest

from tests.test_imposition import flatten_pages


def test_healthz(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_valid_request_returns_unique_page_order(client) -> None:
    response = client.post("/impose", json={"page_count": 8, "sheets_per_signature": 2})
    assert response.status_code == 200
    body = response.json()

    assert body["page_count"] == 8
    assert body["sheets_per_signature"] == 2
    assert body["total_signatures"] == 1
    assert body["total_blanks"] == 0

    sheets = body["signatures"][0]["sheets"]
    assert [
        (
            s["front"]["left"],
            s["front"]["right"],
            s["back"]["left"],
            s["back"]["right"],
        )
        for s in sheets
    ] == [(8, 1, 2, 7), (6, 3, 4, 5)]


def test_every_content_page_appears_exactly_once_over_http(client) -> None:
    for page_count, sheets in itertools.product(
        [1, 2, 3, 7, 8, 9, 15, 16, 17, 100, 2000], [1, 2, 3, 4]
    ):
        response = client.post(
            "/impose",
            json={"page_count": page_count, "sheets_per_signature": sheets},
        )
        assert response.status_code == 200, (page_count, sheets, response.text)
        body = response.json()
        flat = flatten_pages(body)
        content = [p for p in flat if isinstance(p, int)]
        assert sorted(content) == list(range(1, page_count + 1))
        assert len(content) == page_count
        assert flat.count("BLANK") == body["total_blanks"]


@pytest.mark.parametrize("page_count", [0, -5, 2001, 10_000])
def test_invalid_page_count_returns_422(client, page_count: int) -> None:
    response = client.post(
        "/impose", json={"page_count": page_count, "sheets_per_signature": 2}
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(
        "".join(err["loc"]) == "bodypage_count" for err in detail
    ), detail


@pytest.mark.parametrize("sheets", [0, 5, -1, 8])
def test_unsupported_sheets_returns_422(client, sheets: int) -> None:
    response = client.post(
        "/impose", json={"page_count": 12, "sheets_per_signature": sheets}
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(
        "".join(err["loc"]) == "bodysheets_per_signature" for err in detail
    ), detail


@pytest.mark.parametrize(
    "payload",
    [
        {"page_count": 1.0, "sheets_per_signature": 1},
        {"page_count": 8.5, "sheets_per_signature": 2},
        {"page_count": "8", "sheets_per_signature": 2},
        {"page_count": True, "sheets_per_signature": 2},
        {"page_count": None, "sheets_per_signature": 2},
        {"page_count": 8, "sheets_per_signature": 1.0},
        {"page_count": 8, "sheets_per_signature": "2"},
        {"page_count": 8, "sheets_per_signature": True},
        {"page_count": 8},
        {"sheets_per_signature": 2},
        {},
        {"page_count": 8, "sheets_per_signature": 2, "extra": 1},
    ],
)
def test_bad_payloads_return_422(client, payload: dict) -> None:
    response = client.post("/impose", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert "detail" in body
    assert isinstance(body["detail"], list)
    assert body["detail"], "422 必须携带具体校验错误"


def test_malformed_json_returns_422(client) -> None:
    response = client.post(
        "/impose",
        content="{not valid json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422


def test_wrong_content_type_does_not_create_work(client) -> None:
    # 非 JSON 请求体同样在解析阶段被拒，不会落到编排逻辑。
    response = client.post(
        "/impose",
        content="page_count=8&sheets_per_signature=2",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 422


def test_response_shape_is_stable(client) -> None:
    response = client.post("/impose", json={"page_count": 5, "sheets_per_signature": 1})
    assert response.status_code == 200
    signature = response.json()["signatures"][0]
    sheet = signature["sheets"][0]
    assert set(sheet) == {"sheet", "front", "back"}
    assert set(sheet["front"]) == {"left", "right"}
    assert set(sheet["back"]) == {"left", "right"}


def test_blank_only_appended_at_end(client) -> None:
    # 9 页、每帖 1 张：前两帖为完整正文帖（1-4、5-8），无 BLANK；
    # 末帖只有第 9 页，补 3 个 BLANK。
    response = client.post("/impose", json={"page_count": 9, "sheets_per_signature": 1})
    body = response.json()
    assert body["total_signatures"] == 3
    assert body["total_blanks"] == 3
    sig1, sig2, sig3 = body["signatures"]
    assert "BLANK" not in flatten_pages({"signatures": [sig1, sig2]})
    assert flatten_pages({"signatures": [sig3]}).count("BLANK") == 3
