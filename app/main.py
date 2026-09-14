"""FastAPI 入口：骑马订折帖编排服务。"""

import json
import math
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

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


def _to_json_safe(value: Any) -> Any:
    """让 422 错误负载可序列化为严格合法的 JSON。

    在 ``_replace_non_finite_floats`` 之外，额外处理无法用 UTF-8 编码的
    字符串（典型为 ``\\uD800`` 这类未配对代理字符，可能原样出现在
    校验错误的 ``input`` 中）：用 ASCII ``\\uXXXX`` 转义表示，保证
    ``ensure_ascii=False`` 序列化也不会抛 ``UnicodeEncodeError``。
    """
    value = _replace_non_finite_floats(value)
    if isinstance(value, str):
        return value.encode("utf-8", "backslashreplace").decode("utf-8")
    if isinstance(value, dict):
        return {k: _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_json_safe(v) for v in value]
    return value


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    detail = jsonable_encoder(exc.errors())
    return JSONResponse(
        status_code=422,
        content={"detail": _to_json_safe(detail)},
    )


def _reject_parsing(message: str) -> RequestValidationError:
    """构造定位到整个请求体的 422 解析错误（与 FastAPI 原生 json_invalid 同形）。"""
    return RequestValidationError(
        [
            {
                "type": "json_invalid",
                "loc": ("body",),
                "msg": f"JSON decode error: {message}",
                "input": {},
                "ctx": {"error": message},
            }
        ]
    )


def _reject_constant(token: str) -> Any:
    """``parse_constant`` 回调：NaN/Infinity/-Infinity 不是合法 JSON 数值。"""
    raise ValueError(f"{token} is not a valid JSON value")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """``object_pairs_hook`` 回调：同一对象内重复字段整次拒绝。

    JSON 规范未规定重复键的取舍，静默采用后值会让操作员误以为前值
    生效，故任意重复字段（无论两次取值是否相同）都拒绝整次请求。
    """
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


@app.get("/healthz", response_model=HealthResponse, tags=["meta"])
def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post(
    "/impose",
    response_model=ImpositionResponse,
    summary="生成折帖编排",
    tags=["imposition"],
)
async def impose_signatures(request: Request) -> ImpositionResponse:
    # 契约要求请求体是 JSON：必须显式声明 application/json（允许携带
    # charset 等参数，如 application/json; charset=utf-8）。未声明或
    # 声明为其他媒体类型一律 422，绝不尝试按其他格式解释正文。
    content_type = request.headers.get("content-type")
    if content_type is None:
        raise RequestValidationError(
            [
                {
                    "type": "unsupported_media_type",
                    "loc": ("body",),
                    "msg": "Missing Content-Type header; expected application/json",
                    "input": None,
                }
            ]
        )
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise RequestValidationError(
            [
                {
                    "type": "unsupported_media_type",
                    "loc": ("body",),
                    "msg": (
                        f"Unsupported Content-Type {content_type!r}; "
                        "expected application/json"
                    ),
                    "input": None,
                }
            ]
        )

    raw_body = await request.body()
    if not raw_body:
        # 与 FastAPI 对缺省请求体的处理一致：422 且提示 body 缺失。
        raise RequestValidationError(
            [
                {
                    "type": "missing",
                    "loc": ("body",),
                    "msg": "Field required",
                    "input": None,
                }
            ]
        )

    try:
        text = raw_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        # 含非法 UTF-8 编码字节的请求体在 JSON 解析之前就必须给出
        # 可解析的 422 反馈，而不是让解码异常冒泡成 500。
        raise _reject_parsing(f"body is not valid UTF-8: {exc}") from exc

    try:
        payload = json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        # 语法非法、NaN/Infinity 标记、重复字段都在此拦截，整次请求 422。
        raise _reject_parsing(str(exc)) from exc

    try:
        model = ImpositionRequest.model_validate(payload)
    except ValidationError as exc:
        # 直接调用模型校验时错误定位缺少 FastAPI 注入的 "body" 前缀，
        # 这里统一补齐，保持 loc 与契约一致（如 ["body", "page_count"]）。
        errors: list[dict[str, Any]] = []
        for err in exc.errors():
            err = dict(err)
            err["loc"] = ("body", *err.get("loc", ()))
            errors.append(err)
        raise RequestValidationError(errors, body=payload) from exc

    result = impose(
        model.page_count,
        model.sheets_per_signature,
        model.paper_thickness_mm,
        model.binding_edge,
        model.page_number_start,
    )
    return ImpositionResponse.model_validate(result)
