"""FastAPI 入口：骑马订折帖编排服务。"""

import math
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__
from .imposition import impose
from .schemas import (
    HealthResponse,
    ImpositionRequest,
    ImpositionResponse,
)

app = FastAPI(
    title="骑马订折帖编排 API",
    description=(
        "接收正文页数与每帖张数，输出可直接交给双面印刷环节的"
        "折帖（帖/张/正反面/左右页）编排。"
    ),
    version=__version__,
)


def _replace_non_finite_floats(value: Any) -> Any:
    """把 NaN/Infinity 替换为字符串，保证 422 响应体能序列化为合法 JSON。

    非法厚度（如 ``NaN``、``Infinity``）的校验错误会在 ``input`` 中原样
    回显该值；Python 标准 JSON 默认拒绝输出这些标记，故在此清洗。
    """
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if isinstance(value, dict):
        return {k: _replace_non_finite_floats(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_non_finite_floats(v) for v in value]
    return value


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    detail = jsonable_encoder(exc.errors())
    return JSONResponse(
        status_code=422,
        content={"detail": _replace_non_finite_floats(detail)},
    )


@app.get("/healthz", response_model=HealthResponse, tags=["meta"])
def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post(
    "/impose",
    response_model=ImpositionResponse,
    summary="生成折帖编排",
    tags=["imposition"],
)
def impose_signatures(request: ImpositionRequest) -> ImpositionResponse:
    result = impose(
        request.page_count,
        request.sheets_per_signature,
        request.paper_thickness_mm,
    )
    return ImpositionResponse.model_validate(result)
