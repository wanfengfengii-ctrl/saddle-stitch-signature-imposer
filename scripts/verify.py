"""verify 一次性服务的端到端验收脚本。

对运行中的 API（地址由 ``API_BASE_URL`` 指定，默认
``http://api:8000``）做真实 HTTP 调用，验收：

1. 健康检查可用；
2. 多组合法参数返回的编排中，每个正文页恰好出现一次、补白数自洽、
   帖/张数量正确、不存在帖间插空；
3. 非法页数、非整数、不支持的每帖张数一律返回 422。

全部通过退出码为 0，任一失败退出码为 1。仅使用标准库，便于在
slim 镜像中直接运行。
"""

import json
import os
import sys
import urllib.error
import urllib.request
from itertools import product

API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000").rstrip("/")
TIMEOUT = 5


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
