"""verify 一次性服务的端到端验收脚本。

对运行中的 API（地址由 ``API_BASE_URL`` 指定，默认
``http://api:8000``）做真实 HTTP 调用，验收：

1. 健康检查可用；
2. 多组合法参数返回的编排中，每个正文页恰好出现一次、补白数自洽、
   帖/张数量正确、不存在帖间插空；
3. 非法页数、非整数、不支持的每帖张数一律返回 422；
4. 不传 ``paper_thickness_mm`` 时响应快照与旧版本完全一致（不含
   ``creep_mm``）；传入后每张纸携带按帖独立计量的 ``creep_mm``，
   页序/补白/帖张编号不变；非法厚度整次请求 422 且字段定位到
   ``paper_thickness_mm``。
5. 可选 ``binding_edge``：右装订时每张纸正反面的左右页位水平镜像
   （末帖补白同样参与镜像，帖张编号与总补白数不变），与纸厚补偿组合时
   creep 计算/舍入/跨帖归零保持原样；缺省请求响应快照不出现新字段；
   无法识别或非字符串的装订侧整次请求 422 且字段定位到 ``binding_edge``；
   右装订下每个正文页仍恰好出现一次。

全部通过退出码为 0，任一失败退出码为 1。仅使用标准库，便于在
slim 镜像中直接运行。
"""

import copy
import json
import os
import sys
import urllib.error
import urllib.request
from itertools import product

API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000").rstrip("/")
TIMEOUT = 5

# 8 页、每帖 2 张、不传纸张厚度时的完整响应快照（旧版本契约，逐字节锁定）。
SNAPSHOT_8_PAGES_2_SHEETS = {
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


def request(method: str, path: str, payload: object | None = None) -> tuple[int, object]:
    data = None
    headers = {"accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["content-type"] = "application/json"
    req = urllib.request.Request(
        f"{API_BASE_URL}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def request_raw(method: str, path: str, raw_body: str) -> tuple[int, object]:
    """发送未经 json.dumps 处理的原始请求体（用于 NaN/Infinity 等非法 JSON）。"""
    req = urllib.request.Request(
        f"{API_BASE_URL}{path}",
        data=raw_body.encode("utf-8"),
        headers={"accept": "application/json", "content-type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return exc.code, {}


def request_raw_with_headers(
    method: str, path: str, raw_body: bytes, headers: dict
) -> tuple[int, object]:
    """发送原始字节请求体并自定义请求头。

    用于覆盖含非法 UTF-8 字节的正文，以及未声明 / 声明错误
    Content-Type 的场景。
    """
    req = urllib.request.Request(
        f"{API_BASE_URL}{path}",
        data=raw_body,
        headers={"accept": "application/json", **headers},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return exc.code, {}


def flatten(body: dict) -> list:
    pages: list = []
    for signature in body["signatures"]:
        for sheet in signature["sheets"]:
            for side in ("front", "back"):
                pages.append(sheet[side]["left"])
                pages.append(sheet[side]["right"])
    return pages


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"验收失败：{name}" + (f"（{detail}）" if detail else ""))
    print(f"  ✓ {name}")


def main() -> int:
    print(f"验收目标：{API_BASE_URL}")

    status, body = request("GET", "/healthz")
    check("健康检查返回 200", status == 200, str(body))
    check("健康检查负载正确", body == {"status": "ok"})

    valid_cases = list(product([1, 2, 3, 7, 8, 9, 16, 17, 100, 2000], [1, 2, 3, 4]))
    for page_count, sheets in valid_cases:
        status, body = request(
            "POST",
            "/impose",
            {"page_count": page_count, "sheets_per_signature": sheets},
        )
        check(
            f"合法请求 {page_count} 页 / 每帖 {sheets} 张返回 200",
            status == 200,
            str(body),
        )
        flat = flatten(body)
        content = [p for p in flat if isinstance(p, int)]
        check(
            f"{page_count} 页：每个正文页恰好出现一次",
            sorted(content) == list(range(1, page_count + 1))
            and len(set(content)) == page_count,
        )
        capacity = 4 * sheets
        check(
            f"{page_count} 页：补白只在末尾且数量自洽",
            body["total_blanks"] == (-page_count) % capacity
            and flat.count("BLANK") == body["total_blanks"],
        )
        check(
            f"{page_count} 页：帖数与每帖张数正确、无帖间插空",
            body["total_signatures"]
            == (page_count + capacity - 1) // capacity
            and all(len(s["sheets"]) == sheets for s in body["signatures"]),
        )
        check(
            f"{page_count} 页：默认响应任何纸张都不含 creep_mm",
            all("creep_mm" not in sh for s in body["signatures"] for sh in s["sheets"]),
        )

    # 默认响应快照：8 页 / 每帖 2 张的整份负载与旧版本逐字段一致。
    status, body = request(
        "POST",
        "/impose",
        {"page_count": 8, "sheets_per_signature": 2},
    )
    check("默认响应快照（8 页 / 每帖 2 张）不变", status == 200 and body == SNAPSHOT_8_PAGES_2_SHEETS, str(body))

    # creep 补偿：四张一帖、厚度 0.125mm 时，最外张为 0，每向内一张
    # 增加 0.250mm；用 32 页（两帖）验证跨帖重新从零计量。
    status, body = request(
        "POST",
        "/impose",
        {"page_count": 32, "sheets_per_signature": 4, "paper_thickness_mm": 0.125},
    )
    check("启用补偿返回 200", status == 200, str(body))
    expected_creeps = [0.0, 0.25, 0.5, 0.75]
    got_creeps = [
        [sh["creep_mm"] for sh in sig["sheets"]] for sig in body["signatures"]
    ]
    check(
        "四张一帖 0.125mm：各帖依次 0/0.250/0.500/0.750，跨帖重新从零",
        body["total_signatures"] == 2 and got_creeps == [expected_creeps, expected_creeps],
        str(got_creeps),
    )
    check(
        "creep 按十进制四舍五入保留三位小数",
        [f"{v:.3f}" for sig in body["signatures"] for sh in sig["sheets"] for v in [sh["creep_mm"]]]
        == ["0.000", "0.250", "0.500", "0.750"] * 2,
    )

    # 启用前后：对全部页数 × 每帖张数组合，页序/补白/帖张编号完全一致，
    # 且启用补偿后每个正文页仍恰好出现一次、每张纸都携带 creep_mm。
    for page_count, sheets in valid_cases:
        payload = {"page_count": page_count, "sheets_per_signature": sheets}
        status0, body0 = request("POST", "/impose", payload)
        status1, body1 = request("POST", "/impose", {**payload, "paper_thickness_mm": 0.125})
        check(
            f"{page_count} 页 / 每帖 {sheets} 张：启用补偿返回 200",
            status0 == 200 and status1 == 200,
            str(body1),
        )
        flat1 = flatten(body1)
        content1 = [p for p in flat1 if isinstance(p, int)]
        check(
            f"{page_count} 页：启用补偿后每个正文页仍恰好出现一次",
            sorted(content1) == list(range(1, page_count + 1))
            and len(set(content1)) == page_count,
        )
        check(
            f"{page_count} 页：启用后每张纸均携带 creep_mm，且按帖从 0 计量",
            all(
                [sh["creep_mm"] for sh in sig["sheets"]]
                == [round(0.25 * i, 3) for i in range(sheets)]
                for sig in body1["signatures"]
            ),
        )
        stripped = copy.deepcopy(body1)
        for sig in stripped["signatures"]:
            for sh in sig["sheets"]:
                sh.pop("creep_mm", None)
        check(
            f"{page_count} 页：补偿不改变页序、补白位置与帖张编号",
            stripped == body0,
        )

    # ===== binding_edge（装订侧）验收 =====

    # 固定场景一：右装订且末帖含补白。10 页、每帖 2 张（末帖 9、10 + 6
    # BLANK）：每张纸正反面的左右页位水平镜像，BLANK 页位同样参与镜像；
    # 正文分帖、末尾补白、帖张编号与总补白数均不改变。
    status, body = request(
        "POST",
        "/impose",
        {"page_count": 10, "sheets_per_signature": 2, "binding_edge": "right"},
    )
    check("右装订（10 页 / 每帖 2 张）返回 200", status == 200, str(body))
    check(
        "右装订：末帖补白参与镜像，帖/张编号与总补白数不变",
        body["total_signatures"] == 2
        and body["total_blanks"] == 6
        and [sig["signature"] for sig in body["signatures"]] == [1, 2]
        and [
            (
                sh["front"]["left"],
                sh["front"]["right"],
                sh["back"]["left"],
                sh["back"]["right"],
            )
            for sig in body["signatures"]
            for sh in sig["sheets"]
        ]
        == [
            (1, 8, 7, 2),
            (3, 6, 5, 4),
            (9, "BLANK", "BLANK", 10),
            ("BLANK", "BLANK", "BLANK", "BLANK"),
        ],
        str(body),
    )

    # 固定场景二：右装订 + 纸厚补偿。先生成原有页序与逐张补偿量，再按装订侧
    # 镜像左右页位；creep_mm 的计算、舍入与跨帖归零保持原样。
    status, body = request(
        "POST",
        "/impose",
        {
            "page_count": 32,
            "sheets_per_signature": 4,
            "paper_thickness_mm": 0.125,
            "binding_edge": "right",
        },
    )
    check("右装订 + 补偿（32 页 / 每帖 4 张）返回 200", status == 200, str(body))
    check(
        "右装订 + 补偿：creep 跨帖归零不变",
        [
            [sh["creep_mm"] for sh in sig["sheets"]]
            for sig in body["signatures"]
        ]
        == [[0.0, 0.25, 0.5, 0.75], [0.0, 0.25, 0.5, 0.75]],
        str(body),
    )
    check(
        "右装订 + 补偿：首帖左右页位镜像",
        [
            (
                sh["front"]["left"],
                sh["front"]["right"],
                sh["back"]["left"],
                sh["back"]["right"],
            )
            for sh in body["signatures"][0]["sheets"]
        ]
        == [(1, 16, 15, 2), (3, 14, 13, 4), (5, 12, 11, 6), (7, 10, 9, 8)],
        str(body),
    )

    # 固定场景三：缺省请求的完整响应快照不得出现新字段（与旧版本逐字段一致）。
    status, body = request(
        "POST",
        "/impose",
        {"page_count": 8, "sheets_per_signature": 2},
    )
    check(
        "缺省请求响应不含 binding_edge 且快照不变",
        status == 200
        and "binding_edge" not in body
        and body == SNAPSHOT_8_PAGES_2_SHEETS,
        str(body),
    )
    # 显式 "left" 与缺省请求的响应逐字段一致（现有调用方无需调整解析）。
    status, body_left = request(
        "POST",
        "/impose",
        {"page_count": 8, "sheets_per_signature": 2, "binding_edge": "left"},
    )
    check(
        "显式 left 与缺省响应一致",
        status == 200 and body_left == SNAPSHOT_8_PAGES_2_SHEETS,
        str(body_left),
    )

    # 右装订下每个正文页仍恰好出现一次、补白数自洽。
    for page_count, sheets in valid_cases:
        status, body = request(
            "POST",
            "/impose",
            {
                "page_count": page_count,
                "sheets_per_signature": sheets,
                "binding_edge": "right",
            },
        )
        check(
            f"右装订 {page_count} 页 / 每帖 {sheets} 张返回 200",
            status == 200,
            str(body),
        )
        flat = flatten(body)
        content = [p for p in flat if isinstance(p, int)]
        check(
            f"右装订 {page_count} 页：每个正文页恰好出现一次",
            sorted(content) == list(range(1, page_count + 1))
            and len(set(content)) == page_count,
        )
        check(
            f"右装订 {page_count} 页：补白数自洽",
            flat.count("BLANK") == body["total_blanks"],
        )

    # 固定场景四：无法识别或非字符串的 binding_edge 一律 422，并定位到该字段。
    invalid_edges = [
        "LEFT",
        "Left",
        "middle",
        "",
        " left",
        "right ",
        1,
        0,
        1.5,
        True,
        False,
        None,
        [],
        {},
    ]
    for edge in invalid_edges:
        status, body = request(
            "POST",
            "/impose",
            {"page_count": 8, "sheets_per_signature": 2, "binding_edge": edge},
        )
        check(f"非法装订侧 {edge!r} 返回 422", status == 422, f"got {status}")
        check(
            f"非法装订侧 {edge!r} 定位到 binding_edge",
            isinstance(body.get("detail"), list)
            and any(
                "".join(map(str, err.get("loc", []))) == "bodybinding_edge"
                for err in body["detail"]
            ),
            str(body),
        )

    # 非法纸张厚度：整次请求 422。这些可被 JSON 表达的非法值还必须把错误
    # 定位到 body.paper_thickness_mm（布尔、字符串、零、负数、超限、
    # 显式 null；只有字段缺省才表示不补偿）。
    invalid_thickness = [
        (True, True),
        (False, True),
        ("0.5", True),
        ("0", True),
        (0, True),
        (0.0, True),
        (-0.1, True),
        (-1.0, True),
        (1.0001, True),
        (2, True),
        (None, True),
    ]
    for thickness, expect_loc in invalid_thickness:
        status, body = request(
            "POST",
            "/impose",
            {"page_count": 8, "sheets_per_signature": 2, "paper_thickness_mm": thickness},
        )
        check(f"非法厚度 {thickness!r} 返回 422", status == 422, f"got {status}")
        check("422 响应携带 detail 列表", isinstance(body.get("detail"), list) and bool(body["detail"]))
        if expect_loc:
            check(
                f"非法厚度 {thickness!r} 定位到 paper_thickness_mm",
                any(
                    "".join(map(str, err.get("loc", []))) == "bodypaper_thickness_mm"
                    for err in body["detail"]
                ),
                str(body["detail"]),
            )

    # NaN / Infinity 不是合法 JSON 数值：请求体在 JSON 解析阶段即被拒（422）。
    for token in ("NaN", "Infinity", "-Infinity"):
        raw = (
            '{"page_count": 8, "sheets_per_signature": 2, '
            f'"paper_thickness_mm": {token}}}'
        )
        status, body = request_raw("POST", "/impose", raw)
        check(f"非有限数 {token} 返回 422", status == 422, f"got {status}")

    # 非法 UTF-8 编码字节：解析阶段必须返回可解析的 422，而非 5xx。
    status, body = request_raw_with_headers(
        "POST",
        "/impose",
        b'{"page_count": 8,\xff "sheets_per_signature": 2}',
        {"content-type": "application/json"},
    )
    check("含非法编码字节的正文返回 422", status == 422, f"got {status}")
    check(
        "非法编码 422 携带 detail 列表并定位 body",
        isinstance(body.get("detail"), list)
        and any("".join(map(str, err.get("loc", []))) == "body" for err in body["detail"]),
        str(body),
    )

    # 未配对代理字符：定位到 page_count 返回 422，响应体仍为合法 JSON。
    status, body = request_raw(
        "POST",
        "/impose",
        r'{"page_count": "\uD800", "sheets_per_signature": 2}',
    )
    check("页数字段含未配对代理字符返回 422", status == 422, f"got {status}")
    check(
        "未配对代理错误定位到 page_count",
        isinstance(body.get("detail"), list)
        and any(
            "".join(map(str, err.get("loc", []))) == "bodypage_count"
            for err in body["detail"]
        ),
        str(body),
    )

    # 同一对象内重复字段：无论两次取值是否相同，整次请求 422。
    for raw in (
        '{"page_count": 7, "page_count": 99, "sheets_per_signature": 2}',
        '{"page_count": 8, "sheets_per_signature": 2, "sheets_per_signature": 2}',
    ):
        status, body = request_raw("POST", "/impose", raw)
        check(f"重复字段整次拒绝：{raw}", status == 422, f"got {status}")
        check(
            "重复字段 422 携带 detail 列表",
            isinstance(body.get("detail"), list) and bool(body["detail"]),
            str(body),
        )

    # 未声明 / 声明错误的 Content-Type：即使正文是合法 JSON 也必须 422。
    valid_json_body = b'{"page_count": 8, "sheets_per_signature": 2}'
    status, body = request_raw_with_headers(
        "POST", "/impose", valid_json_body, headers={}
    )
    check("未声明 Content-Type 返回 422", status == 422, f"got {status}")
    for content_type in ("text/plain", "application/x-www-form-urlencoded"):
        status, body = request_raw_with_headers(
            "POST",
            "/impose",
            valid_json_body,
            headers={"content-type": content_type},
        )
        check(
            f"非 JSON 媒体类型 {content_type} 返回 422",
            status == 422,
            f"got {status}",
        )
        check(
            f"{content_type} 的 422 携带 detail 列表",
            isinstance(body.get("detail"), list) and bool(body["detail"]),
            str(body),
        )
    # 带 charset 参数的 application/json 仍应被接受。
    status, body = request_raw_with_headers(
        "POST",
        "/impose",
        valid_json_body,
        headers={"content-type": "application/json; charset=utf-8"},
    )
    check("application/json; charset=utf-8 正常受理", status == 200, str(body))

    invalid_payloads = [
        {"page_count": 0, "sheets_per_signature": 2},
        {"page_count": -1, "sheets_per_signature": 2},
        {"page_count": 2001, "sheets_per_signature": 4},
        {"page_count": 8, "sheets_per_signature": 0},
        {"page_count": 8, "sheets_per_signature": 5},
        {"page_count": 1.5, "sheets_per_signature": 2},
        {"page_count": "8", "sheets_per_signature": 2},
        {"page_count": 8, "sheets_per_signature": 2.0},
        {"page_count": True, "sheets_per_signature": 2},
        {"page_count": 8},
        {"sheets_per_signature": 2},
        {},
    ]
    for payload in invalid_payloads:
        status, body = request("POST", "/impose", payload)
        check(f"非法载荷 {payload} 返回 422", status == 422, f"got {status}")
        check("422 响应携带 detail 列表", isinstance(body.get("detail"), list) and bool(body["detail"]))

    print("\n全部验收项通过。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - 验收脚本需要在顶层统一转非零退出
        print(str(exc), file=sys.stderr)
        sys.exit(1)
