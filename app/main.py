"""FastAPI 入口：骑马订折帖编排服务。"""

from fastapi import FastAPI

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
    result = impose(request.page_count, request.sheets_per_signature)
    return ImpositionResponse.model_validate(result)
