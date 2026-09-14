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


def test_body_with_invalid_utf8_bytes_returns_422(client) -> None:
    # 请求体含非法 UTF-8 编码字节：必须在解析阶段返回可解析的 422，
    # 而不是让解码异常冒泡成 5xx。
    response = client.post(
        "/impose",
        content=b'{"page_count": 8,\xff "sheets_per_signature": 2}',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], list) and body["detail"]
    assert any(err["loc"] == ["body"] for err in body["detail"]), body


def test_lone_surrogate_character_in_page_count_returns_field_level_422(
    client,
) -> None:
    # 页数字段中出现未配对代理字符（\uD800）：必须定位到 page_count
    # 返回 422，且错误响应体本身仍是合法 JSON（不发生编码异常）。
    response = client.post(
        "/impose",
        content=b'{"page_count": "\\uD800", "sheets_per_signature": 2}',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert any(
        "".join(err["loc"]) == "bodypage_count" for err in detail
    ), detail


@pytest.mark.parametrize(
    "raw",
    [
        b'{"page_count": 7, "page_count": 99, "sheets_per_signature": 2}',
        b'{"page_count": 8, "sheets_per_signature": 2, "sheets_per_signature": 2}',
    ],
)
def test_duplicate_json_fields_reject_entire_request(client, raw: bytes) -> None:
    # 同一对象内出现重复字段（无论两次取值是否相同）都必须整次拒绝，
    # 不能静默采用后值继续编排。
    response = client.post(
        "/impose",
        content=raw,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert isinstance(body["detail"], list) and body["detail"]


@pytest.mark.parametrize("content_type", [None, "text/plain", "application/x-www-form-urlencoded"])
def test_non_json_media_type_is_rejected(client, content_type: str | None) -> None:
    # 契约只接受 application/json：未声明 Content-Type 或声明为其他媒体
    # 类型都必须 422 拒绝，绝不尝试按其他格式解释正文。
    headers = {} if content_type is None else {"content-type": content_type}
    response = client.post(
        "/impose",
        content=b'{"page_count": 8, "sheets_per_signature": 2}',
        headers=headers,
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert isinstance(body["detail"], list) and body["detail"]


def test_json_content_type_with_charset_is_accepted(client) -> None:
    response = client.post(
        "/impose",
        content=b'{"page_count": 8, "sheets_per_signature": 2}',
        headers={"content-type": "application/json; charset=utf-8"},
    )
    assert response.status_code == 200, response.text


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


def test_right_binding_mirrors_layout_with_blanks_in_last_signature(client) -> None:
    # 固定场景一：右装订且末帖含补白。10 页、每帖 2 张（末帖 9、10 + 6 BLANK）：
    # 每张纸正反面的左右页位水平镜像，BLANK 页位同样参与镜像；正文分帖、
    # 末尾补白、帖张编号与总补白数均不改变。
    response = client.post(
        "/impose",
        json={"page_count": 10, "sheets_per_signature": 2, "binding_edge": "right"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["page_count"] == 10
    assert body["sheets_per_signature"] == 2
    assert body["total_signatures"] == 2
    assert body["total_blanks"] == 6
    assert [sig["signature"] for sig in body["signatures"]] == [1, 2]
    assert [
        (
            sh["front"]["left"],
            sh["front"]["right"],
            sh["back"]["left"],
            sh["back"]["right"],
        )
        for sig in body["signatures"]
        for sh in sig["sheets"]
    ] == [
        (1, 8, 7, 2),
        (3, 6, 5, 4),
        (9, "BLANK", "BLANK", 10),
        ("BLANK", "BLANK", "BLANK", "BLANK"),
    ]


def test_right_binding_combined_with_creep_compensation(client) -> None:
    # 固定场景二：右装订 + 纸厚补偿。先生成原有页序与逐张补偿量，再按装订侧
    # 镜像左右页位；creep_mm 的计算、舍入与跨帖归零保持原样。
    response = client.post(
        "/impose",
        json={
            "page_count": 32,
            "sheets_per_signature": 4,
            "paper_thickness_mm": 0.125,
            "binding_edge": "right",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_signatures"] == 2
    # creep 序列与跨帖归零与未镜像时完全一致。
    assert [
        [sh["creep_mm"] for sh in sig["sheets"]] for sig in body["signatures"]
    ] == [[0.0, 0.25, 0.5, 0.75], [0.0, 0.25, 0.5, 0.75]]
    # 首帖页位为左装订的镜像。
    assert [
        (
            sh["front"]["left"],
            sh["front"]["right"],
            sh["back"]["left"],
            sh["back"]["right"],
        )
        for sh in body["signatures"][0]["sheets"]
    ] == [(1, 16, 15, 2), (3, 14, 13, 4), (5, 12, 11, 6), (7, 10, 9, 8)]


def test_default_request_snapshot_has_no_binding_edge(client) -> None:
    # 固定场景三：缺省请求的完整响应快照不得出现新字段，与旧版本逐字段一致。
    response = client.post(
        "/impose", json={"page_count": 8, "sheets_per_signature": 2}
    )
    assert response.status_code == 200
    body = response.json()
    assert "binding_edge" not in body
    assert body == {
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


def test_explicit_left_binding_matches_default_response(client) -> None:
    # 显式 "left" 与缺省请求的响应逐字段一致（现有调用方无需调整解析）。
    default = client.post(
        "/impose", json={"page_count": 10, "sheets_per_signature": 2}
    ).json()
    response = client.post(
        "/impose",
        json={"page_count": 10, "sheets_per_signature": 2, "binding_edge": "left"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == default


@pytest.mark.parametrize(
    "edge",
    ["LEFT", "Left", "middle", "", " left", "right ", 1, 0, 1.5, True, False, None, [], {}],
)
def test_invalid_binding_edge_returns_422_with_field_location(client, edge) -> None:
    # 固定场景四：无法识别或非字符串的 binding_edge 一律 422，并定位到该字段。
    response = client.post(
        "/impose",
        json={"page_count": 8, "sheets_per_signature": 2, "binding_edge": edge},
    )
    assert response.status_code == 422, (edge, response.text)
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail
    assert any(
        "".join(map(str, err["loc"])) == "bodybinding_edge" for err in detail
    ), detail


def test_every_content_page_appears_exactly_once_with_right_binding(client) -> None:
    for page_count, sheets in itertools.product(
        [1, 2, 3, 7, 8, 9, 15, 16, 17, 100, 2000], [1, 2, 3, 4]
    ):
        response = client.post(
            "/impose",
            json={
                "page_count": page_count,
                "sheets_per_signature": sheets,
                "binding_edge": "right",
            },
        )
        assert response.status_code == 200, (page_count, sheets, response.text)
        body = response.json()
        flat = flatten_pages(body)
        content = [p for p in flat if isinstance(p, int)]
        assert sorted(content) == list(range(1, page_count + 1))
        assert len(content) == page_count
        assert flat.count("BLANK") == body["total_blanks"]


# ===== page_number_start（正文页码起点）=====


def test_page_number_start_37_per_side_pages_with_trailing_blanks(client) -> None:
    # 固定核对：起点 37、10 页、每帖 2 张，末帖含 6 个补白。逐面核对页码，
    # BLANK、帖/张编号与总补白数不受编号映射影响。
    response = client.post(
        "/impose",
        json={
            "page_count": 10,
            "sheets_per_signature": 2,
            "page_number_start": 37,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["page_count"] == 10
    assert body["total_signatures"] == 2
    assert body["total_blanks"] == 6
    assert [sig["signature"] for sig in body["signatures"]] == [1, 2]
    assert [
        (
            sh["front"]["left"],
            sh["front"]["right"],
            sh["back"]["left"],
            sh["back"]["right"],
        )
        for sig in body["signatures"]
        for sh in sig["sheets"]
    ] == [
        (44, 37, 38, 43),
        (42, 39, 40, 41),
        ("BLANK", 45, 46, "BLANK"),
        ("BLANK", "BLANK", "BLANK", "BLANK"),
    ]
    # 响应不新增与起点相关的字段，且不含 creep_mm。
    assert "page_number_start" not in body
    assert all(
        "creep_mm" not in sh
        for sig in body["signatures"]
        for sh in sig["sheets"]
    )


def test_page_number_start_37_with_right_binding_and_creep(client) -> None:
    # 三项功能组合：先完成编号映射，再执行既有镜像，creep 补偿量保持原样。
    response = client.post(
        "/impose",
        json={
            "page_count": 10,
            "sheets_per_signature": 2,
            "paper_thickness_mm": 0.125,
            "binding_edge": "right",
            "page_number_start": 37,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_signatures"] == 2
    assert body["total_blanks"] == 6
    assert [
        (
            sh["front"]["left"],
            sh["front"]["right"],
            sh["back"]["left"],
            sh["back"]["right"],
        )
        for sig in body["signatures"]
        for sh in sig["sheets"]
    ] == [
        (37, 44, 43, 38),
        (39, 42, 41, 40),
        (45, "BLANK", "BLANK", 46),
        ("BLANK", "BLANK", "BLANK", "BLANK"),
    ]
    assert [
        [sh["creep_mm"] for sh in sig["sheets"]] for sig in body["signatures"]
    ] == [[0.0, 0.25], [0.0, 0.25]]


def test_page_number_start_default_snapshot_unchanged(client) -> None:
    # 缺省该字段与显式 1 都与旧版本快照逐字节一致；响应不出现新字段。
    default = client.post(
        "/impose", json={"page_count": 8, "sheets_per_signature": 2}
    ).json()
    one = client.post(
        "/impose",
        json={"page_count": 8, "sheets_per_signature": 2, "page_number_start": 1},
    )
    assert one.status_code == 200
    assert "page_number_start" not in default
    assert one.json() == default
    assert default == {
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


def test_every_content_page_appears_exactly_once_with_start(client) -> None:
    for page_count, sheets in itertools.product(
        [1, 2, 3, 7, 8, 9, 15, 16, 17, 100, 2000], [1, 2, 3, 4]
    ):
        start = 37
        response = client.post(
            "/impose",
            json={
                "page_count": page_count,
                "sheets_per_signature": sheets,
                "page_number_start": start,
            },
        )
        assert response.status_code == 200, (page_count, sheets, response.text)
        body = response.json()
        flat = flatten_pages(body)
        content = [p for p in flat if isinstance(p, int)]
        # 指定范围内每个正文页（start..start+N-1）只出现一次。
        assert sorted(content) == list(
            range(start, start + page_count)
        ), page_count
        assert len(set(content)) == page_count
        assert flat.count("BLANK") == body["total_blanks"]
        # 补白、帖数仍只由 page_count 决定。
        assert body["total_blanks"] == (-page_count) % (4 * sheets)
        assert body["total_signatures"] == (
            page_count + 4 * sheets - 1
        ) // (4 * sheets)


def test_page_number_start_boundaries_accepted(client) -> None:
    # 起点 + 页数恰为 999999：接受；起点字段上界 999999 本身也可与 1 页组合
    # 之外的合法值出现（此处锁定 999989 + 10 = 999999）。
    response = client.post(
        "/impose",
        json={
            "page_count": 10,
            "sheets_per_signature": 2,
            "page_number_start": 999_989,
        },
    )
    assert response.status_code == 200, response.text
    content = [p for p in flatten_pages(response.json()) if isinstance(p, int)]
    assert sorted(content) == list(range(999_989, 999_999))


@pytest.mark.parametrize(
    ("page_count", "start"),
    [
        (10, 999_990),       # 999990 + 10 = 1000000
        (1, 999_999),        # 起点本身合法，但与 1 页相加越界
        (2000, 999_000),
    ],
)
def test_page_number_start_plus_count_overflow_returns_422(
    client, page_count: int, start: int
) -> None:
    response = client.post(
        "/impose",
        json={
            "page_count": page_count,
            "sheets_per_signature": 2,
            "page_number_start": start,
        },
    )
    assert response.status_code == 422, (start, response.text)
    detail = response.json()["detail"]
    assert any(
        "".join(map(str, err["loc"])) == "bodypage_number_start"
        for err in detail
    ), detail


@pytest.mark.parametrize(
    "start",
    [0, -1, 1_000_000, 1_000_001, None, True, False, "37", 37.0, 37.5, [], {}],
)
def test_invalid_page_number_start_returns_422_with_field_location(
    client, start: object
) -> None:
    response = client.post(
        "/impose",
        json={
            "page_count": 10,
            "sheets_per_signature": 2,
            "page_number_start": start,
        },
    )
    assert response.status_code == 422, (start, response.text)
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail
    assert any(
        "".join(map(str, err["loc"])) == "bodypage_number_start"
        for err in detail
    ), detail


def test_explicit_null_page_number_start_raw_json_returns_422(client) -> None:
    # 显式 null 与缺省不同：必须整次拒绝并定位到 page_number_start。
    response = client.post(
        "/impose",
        content=(
            b'{"page_count": 10, "sheets_per_signature": 2, '
            b'"page_number_start": null}'
        ),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert any(
        "".join(map(str, err["loc"])) == "bodypage_number_start"
        for err in detail
    ), detail


def test_page_number_start_with_invalid_page_count_still_field_located(client) -> None:
    # page_count 自身非法时优先报 page_count；组合上界检查不得产生
    # 定位到模型根（loc 仅为 body）的额外错误。
    response = client.post(
        "/impose",
        json={
            "page_count": 0,
            "sheets_per_signature": 2,
            "page_number_start": 999_999,
        },
    )
    assert response.status_code == 422
    locs = ["".join(map(str, e["loc"])) for e in response.json()["detail"]]
    assert "bodypage_count" in locs
    assert all(loc.startswith("body") for loc in locs)
