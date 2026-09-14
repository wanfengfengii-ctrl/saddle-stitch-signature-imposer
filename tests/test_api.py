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


def test_default_response_snapshot_has_no_creep_anywhere(client) -> None:
    response = client.post(
        "/impose", json={"page_count": 8, "sheets_per_signature": 2}
    )
    assert response.status_code == 200
    assert response.json() == {
        "page_count": 8,
        "sheets_per_signature": 2,
        "total_signatures": 1,
        "total_blanks": 0,
        "signatures": [
            {
                "signature": 1,
                "sheets": [
                    {
                        "sheet": 1,
                        "front": {"left": 8, "right": 1},
                        "back": {"left": 2, "right": 7},
                    },
                    {
                        "sheet": 2,
                        "front": {"left": 6, "right": 3},
                        "back": {"left": 4, "right": 5},
                    },
                ],
            }
        ],
    }


def test_creep_sequence_four_sheets_0_125_and_cross_signature_reset(client) -> None:
    # 32 页、每帖 4 张（两帖）、0.125mm：
    # 各帖依次 0 / 0.250 / 0.500 / 0.750，跨帖重新从零计量。
    response = client.post(
        "/impose",
        json={
            "page_count": 32,
            "sheets_per_signature": 4,
            "paper_thickness_mm": 0.125,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_signatures"] == 2
    creeps = [
        [sh["creep_mm"] for sh in sig["sheets"]] for sig in body["signatures"]
    ]
    assert creeps == [[0.0, 0.25, 0.5, 0.75], [0.0, 0.25, 0.5, 0.75]]
    # 序列化为 JSON 后保留三位小数。
    for sig in body["signatures"]:
        for sh in sig["sheets"]:
            assert set(sh) == {"sheet", "front", "back", "creep_mm"}


def test_creep_compensation_preserves_layout_and_page_uniqueness(client) -> None:
    for page_count, sheets in itertools.product(
        [1, 2, 3, 7, 8, 9, 15, 16, 17, 100, 2000], [1, 2, 3, 4]
    ):
        base = client.post(
            "/impose",
            json={"page_count": page_count, "sheets_per_signature": sheets},
        ).json()
        response = client.post(
            "/impose",
            json={
                "page_count": page_count,
                "sheets_per_signature": sheets,
                "paper_thickness_mm": 0.125,
            },
        )
        assert response.status_code == 200, (page_count, sheets, response.text)
        body = response.json()
        # 每个正文页启用后仍恰好出现一次。
        flat = flatten_pages(body)
        content = [p for p in flat if isinstance(p, int)]
        assert sorted(content) == list(range(1, page_count + 1)), page_count
        assert len(set(content)) == page_count
        # 剥除 creep_mm 后与默认响应完全相同（页序/补白/帖张编号不变）。
        for sig in body["signatures"]:
            for sh in sig["sheets"]:
                del sh["creep_mm"]
        assert body == base, page_count


def test_integer_thickness_one_is_accepted(client) -> None:
    # JSON 数字 1（无小数）是合法的有限数字且不超过上界。
    response = client.post(
        "/impose",
        json={"page_count": 8, "sheets_per_signature": 2, "paper_thickness_mm": 1},
    )
    assert response.status_code == 200, response.text
    sheets = response.json()["signatures"][0]["sheets"]
    assert [sh["creep_mm"] for sh in sheets] == [0.0, 2.0]


def test_explicit_null_thickness_is_rejected(client) -> None:
    # 显式 null 与缺省不同：必须整次拒绝（422）并定位到厚度字段。
    response = client.post(
        "/impose",
        json={
            "page_count": 8,
            "sheets_per_signature": 2,
            "paper_thickness_mm": None,
        },
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert any(
        "".join(map(str, err["loc"])) == "bodypaper_thickness_mm"
        for err in detail
    ), detail


def test_omitted_thickness_succeeds_without_creep(client) -> None:
    # 缺省该字段才表示不补偿：200 且不输出 creep_mm。
    response = client.post(
        "/impose",
        json={"page_count": 8, "sheets_per_signature": 2},
    )
    assert response.status_code == 200, response.text
    assert all(
        "creep_mm" not in sh
        for sig in response.json()["signatures"]
        for sh in sig["sheets"]
    )


@pytest.mark.parametrize(
    "thickness",
    [0, 0.0, -0.1, -1.0, 1.0001, 2, True, False, "0.125", "1", None, [], {}],
)
def test_invalid_thickness_returns_422_with_field_location(
    client, thickness: object
) -> None:
    response = client.post(
        "/impose",
        json={
            "page_count": 8,
            "sheets_per_signature": 2,
            "paper_thickness_mm": thickness,
        },
    )
    assert response.status_code == 422, thickness
    detail = response.json()["detail"]
    assert any(
        "".join(map(str, err["loc"])) == "bodypaper_thickness_mm"
        for err in detail
    ), detail


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_thickness_token_returns_422(client, token: str) -> None:
    raw = (
        '{"page_count": 8, "sheets_per_signature": 2, '
        f'"paper_thickness_mm": {token}}}'
    )
    response = client.post(
        "/impose",
        content=raw,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422, response.text
