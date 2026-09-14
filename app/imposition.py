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

* 传入 ``paper_thickness_mm``（毫米，0 < t ≤ 1）时启用 creep（订书沟位移）
  补偿：以帖内最外张（k=1）嵌套深度为零，每向内一张深度加一，该张统一的
  ``creep_mm = 2 * t * (k - 1)``（外层每张纸的正反两层面板各贡献一个纸厚）。
  计量按帖独立，跨帖重新从零开始；结果按十进制四舍五入保留三位小数。
  补偿只新增 ``creep_mm`` 字段，不改变页序、补白位置与帖/张编号；不传时
  输出与旧版本完全一致（不出现该字段）。

* 可选 ``binding_edge``（仅 ``"left"`` 或 ``"right"``，缺省等同
  ``"left"``）：选择 ``"right"`` 时，在既有帖、张、正反面对象上把每一面
  的左右页位水平镜像（含 ``BLANK`` 页位）；正文分帖、末尾补白、帖张
  编号与总补白数均不改变。与 ``paper_thickness_mm`` 同时传入时，先生成
  原有页序与逐张补偿量，再按装订侧镜像左右页位；``creep_mm`` 的计算、
  舍入与跨帖归零保持原样。

例如帖内为 1..8（每帖 2 张）：

    第 1 张：正面 (8, 1)，反面 (2, 7)
    第 2 张：正面 (6, 3)，反面 (4, 5)

右装订（``binding_edge="right"``）时同一帖镜像为：

    第 1 张：正面 (1, 8)，反面 (7, 2)
    第 2 张：正面 (3, 6)，反面 (5, 4)
"""

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal

MIN_PAGE_COUNT = 1
MAX_PAGE_COUNT = 2000
MIN_PAPER_THICKNESS_MM = 0.0
MAX_PAPER_THICKNESS_MM = 1.0
ALLOWED_SHEETS_PER_SIGNATURE: tuple[int, ...] = (1, 2, 3, 4)
ALLOWED_BINDING_EDGES: tuple[str, ...] = ("left", "right")
DEFAULT_BINDING_EDGE: str = "left"
PAGES_PER_SHEET = 4
_CREEP_QUANTUM = Decimal("0.001")

BLANK: Literal["BLANK"] = "BLANK"
"""补白页在 API 输出中的标识。"""

Page = int | Literal["BLANK"]


def _is_real_int(value: object) -> bool:
    """严格判定：``bool`` 不是此处可接受的整数。"""
    return isinstance(value, int) and not isinstance(value, bool)


def _render_page(page: int | None) -> Page:
    return BLANK if page is None else page


def _is_real_number(value: object) -> bool:
    """严格判定：``bool`` 不是此处可接受的有限小数。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _round_creep(value: Decimal) -> float:
    """按十进制四舍五入（ROUND_HALF_UP）保留三位小数。"""
    return float(value.quantize(_CREEP_QUANTUM, rounding=ROUND_HALF_UP))


def impose(
    page_count: Any,
    sheets_per_signature: Any,
    paper_thickness_mm: Any = None,
    binding_edge: Any = None,
) -> dict[str, Any]:
    """生成折帖编排。

    :param page_count: 正文页数，1 至 2000 的整数。
    :param sheets_per_signature: 每帖张数，仅允许 1、2、3、4。
    :param paper_thickness_mm: 可选纸张厚度（毫米），大于 0 且不超过 1 的
        有限小数。传入后每张纸输出 ``creep_mm``（仅当启用补偿时存在）。
    :param binding_edge: 可选装订侧，仅 ``"left"`` 或 ``"right"``；缺省
        （``None``）等同 ``"left"``。选择 ``"right"`` 时，每张纸正反面的
        左右页位水平镜像（含 ``BLANK`` 页位），正文分帖、末尾补白、帖张
        编号与总补白数不变。
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

    if binding_edge is None:
        binding_edge = DEFAULT_BINDING_EDGE
    if binding_edge not in ALLOWED_BINDING_EDGES:
        raise ValueError(
            "binding_edge must be one of "
            f"{', '.join(ALLOWED_BINDING_EDGES)}"
        )

    if paper_thickness_mm is None:
        thickness: Decimal | None = None
    else:
        if not _is_real_number(paper_thickness_mm):
            raise ValueError("paper_thickness_mm must be a finite number")
        thickness_value = paper_thickness_mm
        if not math.isfinite(thickness_value):
            raise ValueError("paper_thickness_mm must be a finite number")
        if not (
            MIN_PAPER_THICKNESS_MM < thickness_value <= MAX_PAPER_THICKNESS_MM
        ):
            raise ValueError(
                "paper_thickness_mm must be greater than 0 and at most "
                f"{MAX_PAPER_THICKNESS_MM:g}"
            )
        thickness = Decimal(str(thickness_value))

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
            sheet_layout: dict[str, Any] = {
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
            if thickness is not None:
                # 嵌套深度以最外张为零，每向内一张增加两倍纸厚。
                sheet_layout["creep_mm"] = _round_creep(
                    Decimal(2) * thickness * Decimal(k - 1)
                )
            sheets.append(sheet_layout)
        signatures.append(
            {
                "signature": sig_index + 1,
                "sheets": sheets,
            }
        )

    if binding_edge == "right":
        # 右装订：在既有帖/张/正反面对象上水平镜像每一面的左右页位。
        # 页序、补白位置、帖张编号与 creep 均已按原装订侧生成，此处仅互换
        # 左右页位（含 BLANK 页位），不触碰其他任何字段。
        for signature in signatures:
            for sheet in signature["sheets"]:
                for side in ("front", "back"):
                    sheet[side]["left"], sheet[side]["right"] = (
                        sheet[side]["right"],
                        sheet[side]["left"],
                    )

    return {
        "page_count": page_count,
        "sheets_per_signature": sheets_per_signature,
        "total_signatures": total_signatures,
        "total_blanks": total_blanks,
        "signatures": signatures,
    }
