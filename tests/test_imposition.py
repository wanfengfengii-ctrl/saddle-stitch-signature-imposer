"""编排核心逻辑的单元测试。"""

import itertools
import math

import pytest

from app.imposition import (
    ALLOWED_SHEETS_PER_SIGNATURE,
    BLANK,
    MAX_PAGE_COUNT,
    impose,
)


def flatten_pages(result: dict) -> list:
    """按“帖、张、正面左→右、反面左→右”的顺序取出全部版面位置。"""
    pages: list = []
    for signature in result["signatures"]:
        for sheet in signature["sheets"]:
            pages.append(sheet["front"]["left"])
            pages.append(sheet["front"]["right"])
            pages.append(sheet["back"]["left"])
            pages.append(sheet["back"]["right"])
    return pages


@pytest.mark.parametrize("sheets", ALLOWED_SHEETS_PER_SIGNATURE)
def test_exact_signature_no_blanks(sheets: int) -> None:
    capacity = 4 * sheets
    result = impose(capacity, sheets)

    assert result["total_signatures"] == 1
    assert result["total_blanks"] == 0
    assert flatten_pages(result).count(BLANK) == 0
    assert sorted(flatten_pages(result)) == list(range(1, capacity + 1))


def test_two_sheets_per_signature_known_layout() -> None:
    # 8 页一帖，由外向内的标准骑马订版式。
    result = impose(8, 2)
    (signature,) = result["signatures"]
    sheet1, sheet2 = signature["sheets"]

    assert sheet1["sheet"] == 1
    assert (sheet1["front"]["left"], sheet1["front"]["right"]) == (8, 1)
    assert (sheet1["back"]["left"], sheet1["back"]["right"]) == (2, 7)
    assert sheet2["sheet"] == 2
    assert (sheet2["front"]["left"], sheet2["front"]["right"]) == (6, 3)
    assert (sheet2["back"]["left"], sheet2["back"]["right"]) == (4, 5)


def test_one_sheet_per_signature_known_layout() -> None:
    # 4 页一帖：正面 4/1，反面 2/3。
    result = impose(4, 1)
    sheet = result["signatures"][0]["sheets"][0]
    assert (sheet["front"]["left"], sheet["front"]["right"]) == (4, 1)
    assert (sheet["back"]["left"], sheet["back"]["right"]) == (2, 3)


@pytest.mark.parametrize("sheets", ALLOWED_SHEETS_PER_SIGNATURE)
def test_blanks_only_at_end_of_last_signature(sheets: int) -> None:
    page_count = 4 * sheets + 1  # 最后一帖只有 1 个正文页
    result = impose(page_count, sheets)
    capacity = 4 * sheets
    expected_blanks = capacity - 1

    assert result["total_signatures"] == 2
    assert result["total_blanks"] == expected_blanks

    first_sig, last_sig = result["signatures"]
    # 中间帖不能有任何补白。
    assert BLANK not in flatten_pages({"signatures": [first_sig]})

    flat_last = flatten_pages({"signatures": [last_sig]})
    assert flat_last.count(BLANK) == expected_blanks
    # 补白在“由外向内”取页之后的物理表现：最后一帖最小正文页（首页）
    # 仍在第 1 张正面右侧，补白全部来自帖内末尾页位。
    assert last_sig["sheets"][0]["front"]["right"] == page_count
    # 帖内剩余页位全部为 BLANK。
    assert set(flat_last) - {page_count} == {BLANK}


def test_signatures_never_have_gaps_between_them() -> None:
    # 10 页、每帖 2 张（容量 8）：第一帖恰为 1..8，第二帖为 9,10 + 6 BLANK。
    result = impose(10, 2)
    sig1, sig2 = result["signatures"]
    assert sorted(p for p in flatten_pages({"signatures": [sig1]}) if p != BLANK) == list(
        range(1, 9)
    )
    assert sorted(
        p for p in flatten_pages({"signatures": [sig2]}) if p != BLANK
    ) == [9, 10]


def test_each_content_page_appears_exactly_once_across_all_cases() -> None:
    for page_count in range(1, 49):
        for sheets in ALLOWED_SHEETS_PER_SIGNATURE:
            result = impose(page_count, sheets)
            flat = flatten_pages(result)
            content_pages = [p for p in flat if isinstance(p, int)]
            assert sorted(content_pages) == list(range(1, page_count + 1))
            assert len(content_pages) == len(set(content_pages)) == page_count
            # 每张纸恰有 4 个版面，帖数/张数正确。
            assert all(
                len(sig["sheets"]) == sheets for sig in result["signatures"]
            )
            assert len(flat) == result["total_signatures"] * 4 * sheets
            assert flat.count(BLANK) == result["total_blanks"]


def test_sheet_indices_and_signature_indices_are_sequential() -> None:
    result = impose(27, 3)
    assert [s["signature"] for s in result["signatures"]] == list(
        range(1, result["total_signatures"] + 1)
    )
    for signature in result["signatures"]:
        assert [sh["sheet"] for sh in signature["sheets"]] == [1, 2, 3]


def test_max_page_count_accepted() -> None:
    result = impose(MAX_PAGE_COUNT, 4)
    assert result["total_signatures"] == MAX_PAGE_COUNT // 16
    assert result["total_blanks"] == 0
    flat = flatten_pages(result)
    assert sorted(flat) == list(range(1, MAX_PAGE_COUNT + 1))


def test_four_sheet_signature_outer_to_inner_order() -> None:
    # 16 页一帖：逐张核对两端各推进两页。
    result = impose(16, 4)
    sheets = result["signatures"][0]["sheets"]
    expected = [
        ((16, 1), (2, 15)),
        ((14, 3), (4, 13)),
        ((12, 5), (6, 11)),
        ((10, 7), (8, 9)),
    ]
    for sheet, (front, back) in zip(sheets, expected):
        assert (sheet["front"]["left"], sheet["front"]["right"]) == front
        assert (sheet["back"]["left"], sheet["back"]["right"]) == back


@pytest.mark.parametrize(
    ("page_count", "sheets"),
    [
        (0, 1),
        (-1, 2),
        (2001, 4),
        (8, 0),
        (8, 5),
        (8, -2),
    ],
)
def test_invalid_arguments_raise_value_error(page_count: int, sheets: int) -> None:
    with pytest.raises(ValueError):
        impose(page_count, sheets)


@pytest.mark.parametrize("page_count", [1.0, 1.5, "1", True, None, [1]])
def test_non_integer_page_count_raises(page_count: object) -> None:
    with pytest.raises(ValueError):
        impose(page_count, 1)


@pytest.mark.parametrize("sheets", [1.0, 2.5, "2", True, None, []])
def test_non_integer_sheets_raises(sheets: object) -> None:
    with pytest.raises(ValueError):
        impose(8, sheets)


def test_blank_count_padding_to_multiple_of_four() -> None:
    # 帖容量恒为 4 的倍数，补白后总版面数同样是 4 的倍数。
    for page_count, sheets in itertools.product(range(1, 33), ALLOWED_SHEETS_PER_SIGNATURE):
        result = impose(page_count, sheets)
        total_slots = result["total_signatures"] * 4 * sheets
        assert total_slots % 4 == 0
        assert total_slots - page_count == result["total_blanks"]


def test_default_response_carries_no_creep_field() -> None:
    # 不传厚度：任何张对象都不得出现 creep_mm 键（响应快照保持旧版本）。
    for page_count, sheets in itertools.product([1, 8, 17, 32], ALLOWED_SHEETS_PER_SIGNATURE):
        result = impose(page_count, sheets)
        assert all(
            "creep_mm" not in sh
            for sig in result["signatures"]
            for sh in sig["sheets"]
        )


def test_four_sheet_signature_creep_sequence_at_0_125() -> None:
    # 四张一帖、0.125mm：最外张为 0，每向内一张增加 0.250mm。
    result = impose(16, 4, 0.125)
    (signature,) = result["signatures"]
    assert [sh["creep_mm"] for sh in signature["sheets"]] == [0.0, 0.25, 0.5, 0.75]


def test_creep_restarts_from_zero_for_each_signature() -> None:
    # 32 页、每帖 4 张（两帖）：跨帖重新从零计量。
    result = impose(32, 4, 0.125)
    sig1, sig2 = result["signatures"]
    expected = [0.0, 0.25, 0.5, 0.75]
    assert [sh["creep_mm"] for sh in sig1["sheets"]] == expected
    assert [sh["creep_mm"] for sh in sig2["sheets"]] == expected


@pytest.mark.parametrize("sheets", ALLOWED_SHEETS_PER_SIGNATURE)
def test_creep_zero_on_outermost_sheet_of_every_signature(sheets: int) -> None:
    capacity = 4 * sheets
    result = impose(capacity * 3, sheets, 0.3)
    for signature in result["signatures"]:
        assert signature["sheets"][0]["creep_mm"] == 0.0
        assert [sh["creep_mm"] for sh in signature["sheets"]] == [
            round(0.6 * i, 3) for i in range(sheets)
        ]


def test_creep_uses_decimal_half_up_rounding_to_three_places() -> None:
    # 厚度 0.00125mm 时最内张 creep = 0.0075mm：十进制四舍五入应进位为
    # 0.008（Python 内置 round 是银行家舍入，对该值得到 0.007），借此
    # 锁定“按十进制四舍五入保留三位”的规则。
    result = impose(16, 4, 0.00125)
    creeps = [sh["creep_mm"] for sh in result["signatures"][0]["sheets"]]
    assert creeps == [0.0, 0.003, 0.005, 0.008]
    assert round(0.0075, 3) == 0.007  # 对照：内置 round 不进位


def test_creep_compensation_preserves_pages_blanks_and_numbering() -> None:
    # 启用补偿仅新增 creep_mm：剥除后与默认编排逐字段相等。
    for page_count in [1, 5, 8, 17, 32, 49]:
        for sheets in ALLOWED_SHEETS_PER_SIGNATURE:
            baseline = impose(page_count, sheets)
            compensated = impose(page_count, sheets, 0.125)
            for signature in compensated["signatures"]:
                for sh in signature["sheets"]:
                    sh.pop("creep_mm")
            assert compensated == baseline


def test_content_pages_appear_once_with_compensation_enabled() -> None:
    for page_count in range(1, 49):
        for sheets in ALLOWED_SHEETS_PER_SIGNATURE:
            result = impose(page_count, sheets, 0.125)
            flat = flatten_pages(result)
            content = [p for p in flat if isinstance(p, int)]
            assert sorted(content) == list(range(1, page_count + 1))
            assert len(content) == len(set(content)) == page_count
            assert flat.count(BLANK) == result["total_blanks"]


def test_thickness_boundaries_accepted_by_core() -> None:
    # 1.0mm / 整数 1（上界）与极小正数均合法；creep 可以大于 1（只有厚度受限）。
    for thickness in (1.0, 1):
        result = impose(16, 4, thickness)
        assert [sh["creep_mm"] for sh in result["signatures"][0]["sheets"]] == [
            0.0,
            2.0,
            4.0,
            6.0,
        ]
    result = impose(16, 4, 1e-9)
    assert result["signatures"][0]["sheets"][-1]["creep_mm"] == 0.0


@pytest.mark.parametrize(
    "thickness",
    [0, 0.0, -0.001, -1, -1.0, 1.0000001, 2.0, 2, True, False, "0.5"],
)
def test_invalid_thickness_raises_value_error(thickness: object) -> None:
    with pytest.raises(ValueError):
        impose(8, 2, thickness)  # type: ignore[arg-type]


@pytest.mark.parametrize("thickness", [math.nan, math.inf, -math.inf])
def test_non_finite_thickness_raises_value_error(thickness: float) -> None:
    with pytest.raises(ValueError):
        impose(8, 2, thickness)
