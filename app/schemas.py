"""请求/响应 Pydantic 模型。

非法页数、非整数或不支持的每帖张数都在请求模型层被拒绝，FastAPI 统一
返回 HTTP 422（请求体为非法 JSON 时同样由 FastAPI 转为 422）。
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .imposition import (
    ALLOWED_SHEETS_PER_SIGNATURE,
    MAX_PAGE_COUNT,
    MIN_PAGE_COUNT,
)

Page = int | Literal["BLANK"]
"""版面位置：正文页码（整数）或补白占位 ``BLANK``。"""


class ImpositionRequest(BaseModel):
    """折帖编排请求。

    使用 strict 整数校验：1.0、1.5、``"8"``、``true`` 等均不接受。
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
    """一张纸的双面编排。"""

    sheet: int = Field(ge=1, description="帖内张号，从 1 开始。")
    front: SidePages = Field(description="正面，从左到右。")
    back: SidePages = Field(description="反面，从左到右。")


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
