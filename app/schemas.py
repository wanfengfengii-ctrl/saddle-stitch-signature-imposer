"""请求/响应 Pydantic 模型。

非法页数、非整数或不支持的每帖张数都在请求模型层被拒绝，FastAPI 统一
返回 HTTP 422（请求体为非法 JSON 时同样由 FastAPI 转为 422）。

``paper_thickness_mm`` 为可选字段：缺省时响应与旧版本完全一致（张对象不
携带 ``creep_mm``）；传入合法厚度后，每张纸才额外输出 ``creep_mm``。
"""

import math
from typing import Annotated, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
)

from .imposition import (
    ALLOWED_SHEETS_PER_SIGNATURE,
    MAX_PAGE_COUNT,
    MAX_PAPER_THICKNESS_MM,
    MIN_PAGE_COUNT,
    MIN_PAPER_THICKNESS_MM,
)

Page = int | Literal["BLANK"]
"""版面位置：正文页码（整数）或补白占位 ``BLANK``。"""


class ImpositionRequest(BaseModel):
    """折帖编排请求。

    整数字段使用 strict 整数校验：1.0、1.5、``"8"``、``true`` 等均不接受。
    ``paper_thickness_mm`` 使用 strict 数字校验：布尔值、字符串、显式
    ``null`` 均被拒绝，零、负数、超限值与非有限数由范围/有限性校验拒绝；
    只有**缺省该字段**才表示不做 creep 补偿。
    """

    model_config = ConfigDict(extra="forbid")

    page_count: Annotated[
        int,
        Field(
            strict=True,
            ge=MIN_PAGE_COUNT,
            le=MAX_PAGE_COUNT,
            description=f"正文页数，整数，范围 {MIN_PAGE_COUNT}–{MAX_PAGE_COUNT}。",
        ),
    ]
    sheets_per_signature: Annotated[
        int,
        Field(strict=True, description="每帖张数，仅允许 1、2、3、4。"),
    ]
    paper_thickness_mm: Optional[
        Annotated[
            float,
            Field(
                strict=True,
                gt=MIN_PAPER_THICKNESS_MM,
                le=MAX_PAPER_THICKNESS_MM,
                description=(
                    "可选纸张厚度（毫米），大于 0 且不超过 1 的有限小数；"
                    "缺省该字段时不做 creep 补偿，响应不包含 creep_mm。"
                    "显式传 null 视为无效，整次请求返回 422。"
                ),
            ),
        ]
    ] = None

    @field_validator("paper_thickness_mm")
    @classmethod
    def validate_thickness(cls, value: Optional[float]) -> Optional[float]:
        # 该校验器仅对显式提供的字段值触发（字段缺省时使用默认值，不进入
        # 校验器）：因此缺省 = 不补偿，而显式 null 必须拒绝整次请求。
        if value is None:
            raise ValueError(
                "paper_thickness_mm must not be null; omit the field to "
                "disable creep compensation"
            )
        if not math.isfinite(value):
            raise ValueError("paper_thickness_mm must be a finite number")
        return value

    @field_validator("sheets_per_signature")
    @classmethod
    def validate_sheets_per_signature(cls, value: int) -> int:
        if value not in ALLOWED_SHEETS_PER_SIGNATURE:
            allowed = ", ".join(str(n) for n in ALLOWED_SHEETS_PER_SIGNATURE)
            raise ValueError(
                f"sheets_per_signature must be one of {allowed}; got {value}"
            )
        return value


class SidePages(BaseModel):
    """一个印面（正面或反面）从左到右的两页。"""

    left: Page
    right: Page


class SheetLayout(BaseModel):
    """一张纸的双面编排。

    ``creep_mm`` 仅在请求传入 ``paper_thickness_mm`` 时出现；缺省调用的
    序列化结果中不包含该字段，保持旧版本响应快照不变。
    """

    sheet: int = Field(ge=1, description="帖内张号，从 1 开始。")
    front: SidePages = Field(description="正面，从左到右。")
    back: SidePages = Field(description="反面，从左到右。")
    creep_mm: Optional[float] = Field(
        default=None,
        ge=0,
        description=(
            "该张统一的 creep 补偿（毫米）：最外张为 0，每向内一张增加"
            "两倍纸厚；按帖独立计量。仅启用补偿时输出。"
        ),
    )

    @model_serializer(mode="wrap")
    def _omit_creep_when_disabled(self, handler, info):  # type: ignore[no-untyped-def]
        data = handler(self)
        if data.get("creep_mm") is None:
            data.pop("creep_mm", None)
        return data


class SignatureLayout(BaseModel):
    """一帖（一个骑马订书帖）的编排。"""

    signature: int = Field(ge=1, description="帖号，从 1 开始。")
    sheets: list[SheetLayout]


class ImpositionResponse(BaseModel):
    """折帖编排响应。"""

    page_count: int
    sheets_per_signature: int
    total_signatures: int = Field(description="总帖数。")
    total_blanks: int = Field(ge=0, description="全文末尾补白页总数。")
    signatures: list[SignatureLayout]


class HealthResponse(BaseModel):
    status: Literal["ok"]
