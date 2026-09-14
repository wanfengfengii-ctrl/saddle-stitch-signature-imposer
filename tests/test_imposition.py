"""编排核心逻辑的单元测试。"""

import itertools
import math

import pytest

from app.imposition import (
    ALLOWED_SHEETS_PER_SIGNATURE,
    BLANK,
    MAX_PAGE_COUNT,
    MAX_PAGE_NUMBER_START,
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


def test_right_binding_mirrors_left_and_right_positions() -> None:
    # 8 页、每帖 2 张、右装订：每张纸正反面的左右页位水平镜像，帖/张编号不变。
    result = impose(8, 2, binding_edge="right")
    (signature,) = result["signatures"]
    sheet1, sheet2 = signature["sheets"]

    assert sheet1["sheet"] == 1
    assert (sheet1["front"]["left"], sheet1["front"]["right"]) == (1, 8)
    assert (sheet1["back"]["left"], sheet1["back"]["right"]) == (7, 2)
    assert sheet2["sheet"] == 2
    assert (sheet2["front"]["left"], sheet2["front"]["right"]) == (3, 6)
    assert (sheet2["back"]["left"], sheet2["back"]["right"]) == (5, 4)


def test_right_binding_mirrors_blanks_in_last_signature() -> None:
    # 10 页、每帖 2 张、右装订：末帖含 6 个 BLANK，BLANK 页位同样参与镜像；
    # 正文分帖、末尾补白、帖张编号与总补白数均不改变。
    result = impose(10, 2, binding_edge="right")
    assert result["total_signatures"] == 2
    assert result["total_blanks"] == 6

    sig1, sig2 = result["signatures"]
    assert [sh["sheet"] for sh in sig1["sheets"]] == [1, 2]
    assert [
        (
            sh["front"]["left"],
            sh["front"]["right"],
            sh["back"]["left"],
            sh["back"]["right"],
        )
        for sh in sig1["sheets"]
    ] == [(1, 8, 7, 2), (3, 6, 5, 4)]
    # 末帖：承载正文末尾页 9、10，补白全部来自帖内末尾页位，镜像后仍在同一张。
    assert [sh["sheet"] for sh in sig2["sheets"]] == [1, 2]
    assert [
        (
            sh["front"]["left"],
            sh["front"]["right"],
            sh["back"]["left"],
            sh["back"]["right"],
        )
        for sh in sig2["sheets"]
    ] == [(9, BLANK, BLANK, 10), (BLANK, BLANK, BLANK, BLANK)]


def test_explicit_left_binding_equals_default() -> None:
    # 显式 "left" 与缺省（None）逐字段一致，且都与旧版本输出相同。
    for page_count, sheets in itertools.product(
        [1, 5, 8, 10, 17, 32], ALLOWED_SHEETS_PER_SIGNATURE
    ):
        default = impose(page_count, sheets)
        assert impose(page_count, sheets, binding_edge="left") == default
        assert impose(page_count, sheets, binding_edge=None) == default


def test_right_binding_is_exact_mirror_of_left() -> None:
    # 对多组参数：右装订结果 = 左装订结果逐面左右互换，其余字段完全一致。
    for page_count, sheets in itertools.product(
        range(1, 33), ALLOWED_SHEETS_PER_SIGNATURE
    ):
        left = impose(page_count, sheets)
        right = impose(page_count, sheets, binding_edge="right")
        assert right["page_count"] == left["page_count"]
        assert right["sheets_per_signature"] == left["sheets_per_signature"]
        assert right["total_signatures"] == left["total_signatures"]
        assert right["total_blanks"] == left["total_blanks"]
        assert len(right["signatures"]) == len(left["signatures"])
        for sig_l, sig_r in zip(left["signatures"], right["signatures"]):
            assert sig_l["signature"] == sig_r["signature"]
            for sh_l, sh_r in zip(sig_l["sheets"], sig_r["sheets"]):
                assert sh_l["sheet"] == sh_r["sheet"]
                assert sh_r["front"]["left"] == sh_l["front"]["right"]
                assert sh_r["front"]["right"] == sh_l["front"]["left"]
                assert sh_r["back"]["left"] == sh_l["back"]["right"]
                assert sh_r["back"]["right"] == sh_l["back"]["left"]


def test_each_content_page_appears_exactly_once_with_right_binding() -> None:
    for page_count in range(1, 49):
        for sheets in ALLOWED_SHEETS_PER_SIGNATURE:
            result = impose(page_count, sheets, binding_edge="right")
            flat = flatten_pages(result)
            content_pages = [p for p in flat if isinstance(p, int)]
            assert sorted(content_pages) == list(range(1, page_count + 1))
            assert len(content_pages) == len(set(content_pages)) == page_count
            assert flat.count(BLANK) == result["total_blanks"]


def test_right_binding_preserves_creep_sequence_and_reset() -> None:
    # 右装订 + 0.125mm、32 页两帖：creep 计算、舍入与跨帖归零保持原样。
    result = impose(32, 4, 0.125, binding_edge="right")
    expected = [0.0, 0.25, 0.5, 0.75]
    assert result["total_signatures"] == 2
    for signature in result["signatures"]:
        assert [sh["creep_mm"] for sh in signature["sheets"]] == expected
    # 首帖页位为左装订的镜像。
    first = result["signatures"][0]["sheets"]
    assert [
        (
            sh["front"]["left"],
            sh["front"]["right"],
            sh["back"]["left"],
            sh["back"]["right"],
        )
        for sh in first
    ] == [(1, 16, 15, 2), (3, 14, 13, 4), (5, 12, 11, 6), (7, 10, 9, 8)]


def test_right_binding_with_creep_keeps_pages_unique() -> None:
    # 右装订 + 补偿组合下，每个正文页仍恰好出现一次、补白数自洽。
    for page_count in range(1, 49):
        for sheets in ALLOWED_SHEETS_PER_SIGNATURE:
            result = impose(page_count, sheets, 0.125, binding_edge="right")
            flat = flatten_pages(result)
            content = [p for p in flat if isinstance(p, int)]
            assert sorted(content) == list(range(1, page_count + 1))
            assert len(content) == len(set(content)) == page_count
            assert flat.count(BLANK) == result["total_blanks"]


@pytest.mark.parametrize(
    "edge",
    ["LEFT", "Left", "middle", "", " left", "right ", 1, 0, 1.5, True, False, [], {}, ["left"]],
)
def test_invalid_binding_edge_raises_value_error(edge: object) -> None:
    with pytest.raises(ValueError):
        impose(8, 2, binding_edge=edge)


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


# ===== page_number_start（正文页码起点）=====


def test_page_number_start_37_per_side_pages_with_trailing_blanks() -> None:
    # 固定核对：起点 37、10 页、每帖 2 张：第一帖承载原文页 37..44，
    # 末帖承载 45、46 并含 6 个补白。逐面核对页码（BLANK 不受编号影响）。
    result = impose(10, 2, page_number_start=37)
    assert result["total_signatures"] == 2
    assert result["total_blanks"] == 6

    sig1, sig2 = result["signatures"]
    assert sig1["signature"] == 1 and sig2["signature"] == 2
    assert [sh["sheet"] for sh in sig1["sheets"]] == [1, 2]
    assert [
        (
            sh["front"]["left"],
            sh["front"]["right"],
            sh["back"]["left"],
            sh["back"]["right"],
        )
        for sh in sig1["sheets"]
    ] == [(44, 37, 38, 43), (42, 39, 40, 41)]
    assert [sh["sheet"] for sh in sig2["sheets"]] == [1, 2]
    assert [
        (
            sh["front"]["left"],
            sh["front"]["right"],
            sh["back"]["left"],
            sh["back"]["right"],
        )
        for sh in sig2["sheets"]
    ] == [
        (BLANK, 45, 46, BLANK),
        (BLANK, BLANK, BLANK, BLANK),
    ]
    # 响应不新增任何与起点相关的字段。
    assert set(result) == {
        "page_count",
        "sheets_per_signature",
        "total_signatures",
        "total_blanks",
        "signatures",
    }


def test_page_number_start_37_combined_with_right_binding_and_creep() -> None:
    # 三项功能组合：先完成编号映射，再执行既有镜像，creep 补偿量保持原样。
    result = impose(10, 2, 0.125, binding_edge="right", page_number_start=37)
    assert result["total_signatures"] == 2
    assert result["total_blanks"] == 6

    sig1, sig2 = result["signatures"]
    assert [
        (
            sh["front"]["left"],
            sh["front"]["right"],
            sh["back"]["left"],
            sh["back"]["right"],
            sh["creep_mm"],
        )
        for sh in sig1["sheets"]
    ] == [(37, 44, 43, 38, 0.0), (39, 42, 41, 40, 0.25)]
    assert [
        (
            sh["front"]["left"],
            sh["front"]["right"],
            sh["back"]["left"],
            sh["back"]["right"],
            sh["creep_mm"],
        )
        for sh in sig2["sheets"]
    ] == [
        (45, BLANK, BLANK, 46, 0.0),
        (BLANK, BLANK, BLANK, BLANK, 0.25),
    ]

    # 等价刻画：右装订 + 起点 = 同起点左装订逐面左右互换，creep 完全一致。
    left = impose(10, 2, 0.125, binding_edge="left", page_number_start=37)
    for sig_l, sig_r in zip(left["signatures"], result["signatures"]):
        assert sig_l["signature"] == sig_r["signature"]
        for sh_l, sh_r in zip(sig_l["sheets"], sig_r["sheets"]):
            assert sh_l["sheet"] == sh_r["sheet"]
            assert sh_l["creep_mm"] == sh_r["creep_mm"]
            assert sh_r["front"] == {
                "left": sh_l["front"]["right"],
                "right": sh_l["front"]["left"],
            }
            assert sh_r["back"] == {
                "left": sh_l["back"]["right"],
                "right": sh_l["back"]["left"],
            }


def test_page_number_start_defaults_to_one() -> None:
    # 缺省（None）与显式 1 都与旧版本输出逐字段一致。
    default = impose(10, 2)
    assert impose(10, 2, page_number_start=None) == default
    assert impose(10, 2, page_number_start=1) == default


def test_page_number_start_changes_only_content_numbers() -> None:
    # 分帖、补白数、帖/张编号完全按 page_count 计算，与起点无关；
    # 仅正文页编号被整体平移。
    for start in (1, 2, 37, 1000):
        baseline = impose(10, 2)
        shifted = impose(10, 2, page_number_start=start)
        assert shifted["page_count"] == baseline["page_count"] == 10
        assert shifted["sheets_per_signature"] == 2
        assert shifted["total_signatures"] == baseline["total_signatures"] == 2
        assert shifted["total_blanks"] == baseline["total_blanks"] == 6
        assert [s["signature"] for s in shifted["signatures"]] == [1, 2]
        assert shifted["signatures"][0]["sheets"][0]["sheet"] == 1
        assert flatten_pages(shifted).count(BLANK) == 6


def test_each_content_page_appears_exactly_once_with_start() -> None:
    for start in (1, 2, 37, 500, 999_900):
        for page_count in range(1, 49):
            if start + page_count > MAX_PAGE_NUMBER_START:
                continue
            for sheets in ALLOWED_SHEETS_PER_SIGNATURE:
                result = impose(page_count, sheets, page_number_start=start)
                flat = flatten_pages(result)
                content = [p for p in flat if isinstance(p, int)]
                assert sorted(content) == list(
                    range(start, start + page_count)
                ), (start, page_count, sheets)
                assert len(content) == len(set(content)) == page_count
                assert flat.count(BLANK) == result["total_blanks"]
                assert result["total_blanks"] == (-page_count) % (4 * sheets)


def test_page_number_start_preserves_blanks_and_signature_layout() -> None:
    # 把编号平移回 1 起始后，版面结构（BLANK 位置/帖张编号）必须与默认一致。
    for page_count in (1, 5, 9, 10, 17, 33):
        for sheets in ALLOWED_SHEETS_PER_SIGNATURE:
            shifted = impose(page_count, sheets, page_number_start=37)
            default = impose(page_count, sheets)
            offset = 36
            for sig_s, sig_d in zip(shifted["signatures"], default["signatures"]):
                assert sig_s["signature"] == sig_d["signature"]
                for sh_s, sh_d in zip(sig_s["sheets"], sig_d["sheets"]):
                    assert sh_s["sheet"] == sh_d["sheet"]
                    for side in ("front", "back"):
                        for pos in ("left", "right"):
                            got, want = sh_s[side][pos], sh_d[side][pos]
                            if want == BLANK:
                                assert got == BLANK
                            else:
                                assert got == want + offset


def test_page_number_start_with_creep_strips_to_renumbered_default() -> None:
    # 起点 + 补偿：剥除 creep_mm 后恰为仅指定起点的编排，补偿量本身不变。
    for page_count in (1, 8, 10, 32):
        compensated = impose(page_count, 4, 0.125, page_number_start=37)
        for sig in compensated["signatures"]:
            for sh in sig["sheets"]:
                assert sh.pop("creep_mm") == round(
                    0.25 * (sh["sheet"] - 1), 3
                )
        assert compensated == impose(page_count, 4, page_number_start=37)


@pytest.mark.parametrize(
    ("start", "page_count"),
    [
        (999_998, 1),          # 起点 + 页数恰为 999999，合法
        (999_989, 10),         # 999989 + 10 = 999999
        (997_999, MAX_PAGE_COUNT),
        (2, MAX_PAGE_COUNT),   # 2..2001
    ],
)
def test_page_number_start_upper_boundary_accepted(
    start: int, page_count: int
) -> None:
    result = impose(page_count, 4, page_number_start=start)
    flat = flatten_pages(result)
    content = sorted(p for p in flat if isinstance(p, int))
    assert content == list(range(start, start + page_count))
    assert start + page_count <= MAX_PAGE_NUMBER_START


@pytest.mark.parametrize(
    ("start", "page_count"),
    [
        (999_999, 1),                        # 起点 + 页数 = 1000000，越界
        (999_990, 10),                       # 同样为 1000000
        (MAX_PAGE_NUMBER_START, 2),
        (MAX_PAGE_NUMBER_START, MAX_PAGE_COUNT),
    ],
)
def test_page_number_start_plus_count_overflow_raises(
    start: int, page_count: int
) -> None:
    with pytest.raises(ValueError, match="page_number_start"):
        impose(page_count, 2, page_number_start=start)


@pytest.mark.parametrize("start", [0, -1, 1_000_000, 1_000_001])
def test_page_number_start_out_of_range_raises(start: int) -> None:
    with pytest.raises(ValueError):
        impose(8, 2, page_number_start=start)


@pytest.mark.parametrize("start", [True, False, "37", 37.0, 37.5, [37], {}, 1.0])
def test_non_integer_page_number_start_raises(start: object) -> None:
    with pytest.raises(ValueError):
        impose(8, 2, page_number_start=start)  # type: ignore[arg-type]
