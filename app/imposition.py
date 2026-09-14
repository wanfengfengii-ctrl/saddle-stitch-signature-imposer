"""骑马订（saddle-stitched）折帖编排核心逻辑。

规则（题面约定）：

* 每张纸双面印刷，固定承载 4 个页面（正面左右、反面左右）。
* 每帖张数只能是 1、2、3、4，故每帖容量为 ``4 * sheets_per_signature`` 页。
* 从正文起始处按每帖容量依次分帖；帖间禁止插空。
* 最后一帖不足一个帖容量时，只在全文末尾追加 ``BLANK``，使最后一帖
  凑满 4 的倍数。
* 每帖独立按“由外向内”取页。帖内页位序列记为 ``seq``（长度为帖容量），
  对第 k 张纸（k 从 1 开始）：

      正面（front）从左到右：seq[L - 2k + 1]、seq[2k - 2]
      反面（back） 从左到右：seq[2k - 1]、     seq[L - 2k]

  取完一张后，序列两端各向内推进两页。

例如帖内为 1..8（每帖 2 张）：

    第 1 张：正面 (8, 1)，反面 (2, 7)
    第 2 张：正面 (6, 3)，反面 (4, 5)
"""

from typing import Any, Literal

MIN_PAGE_COUNT = 1
MAX_PAGE_COUNT = 2000
ALLOWED_SHEETS_PER_SIGNATURE: tuple[int, ...] = (1, 2, 3, 4)
PAGES_PER_SHEET = 4

BLANK: Literal["BLANK"] = "BLANK"
"""补白页在 API 输出中的标识。"""

Page = int | Literal["BLANK"]


def _is_real_int(value: object) -> bool:
    """严格判定：``bool`` 不是此处可接受的整数。"""
    return isinstance(value, int) and not isinstance(value, bool)


def _render_page(page: int | None) -> Page:
    return BLANK if page is None else page


def impose(page_count: Any, sheets_per_signature: Any) -> dict[str, Any]:
    """生成折帖编排。

    :param page_count: 正文页数，1 至 2000 的整数。
    :param sheets_per_signature: 每帖张数，仅允许 1、2、3、4。
    :return: 可直接序列化为 API 响应的字典。
    :raises ValueError: 参数不合法时抛出（HTTP 层由 Pydantic 先行拦截）。
    """
    if not _is_real_int(page_count):
        raise ValueError("page_count must be an integer")
    if not (MIN_PAGE_COUNT <= page_count <= MAX_PAGE_COUNT):
        raise ValueError(
            f"page_count must be between {MIN_PAGE_COUNT} and {MAX_PAGE_COUNT}"
        )
    if not _is_real_int(sheets_per_signature):
        raise ValueError("sheets_per_signature must be an integer")
    if sheets_per_signature not in ALLOWED_SHEETS_PER_SIGNATURE:
        raise ValueError(
            "sheets_per_signature must be one of "
            f"{', '.join(str(n) for n in ALLOWED_SHEETS_PER_SIGNATURE)}"
        )

    capacity = PAGES_PER_SHEET * sheets_per_signature
    total_signatures = (page_count + capacity - 1) // capacity
    # 只在全文末尾补白：帖容量减去“正文页数对帖容量的余数”，整除则为 0。
    total_blanks = (-page_count) % capacity

    # 正文页 1..N，末尾接全部补白；帖间不存在任何空页。
    padded: list[int | None] = list(range(1, page_count + 1)) + [None] * total_blanks

    signatures: list[dict[str, Any]] = []
    for sig_index in range(total_signatures):
        seq = padded[sig_index * capacity : (sig_index + 1) * capacity]
        sheets: list[dict[str, Any]] = []
        for k in range(1, sheets_per_signature + 1):
            front_left = seq[capacity - (2 * k - 1)]
            front_right = seq[2 * k - 2]
            back_left = seq[2 * k - 1]
            back_right = seq[capacity - 2 * k]
            sheets.append(
                {
                    "sheet": k,
                    "front": {
                        "left": _render_page(front_left),
                        "right": _render_page(front_right),
                    },
                    "back": {
                        "left": _render_page(back_left),
                        "right": _render_page(back_right),
                    },
                }
            )
        signatures.append(
            {
                "signature": sig_index + 1,
                "sheets": sheets,
            }
        )

    return {
        "page_count": page_count,
        "sheets_per_signature": sheets_per_signature,
        "total_signatures": total_signatures,
        "total_blanks": total_blanks,
        "signatures": signatures,
    }
