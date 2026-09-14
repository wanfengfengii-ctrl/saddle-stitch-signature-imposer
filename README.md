# 骑马订折帖编排 API

纯后端 HTTP 服务，解决短版骑马订手册制作中“把阅读页序当成印张页序”
导致的页码倒置、空白页落位错误问题。输入**正文页数**与**每帖张数**，
输出可直接交给双面印刷环节的折帖编排：帖号、张号、每张纸正反面
从左到右的页号，以及总补白数。

- Python 3.12
- FastAPI + Pydantic v2
- pytest（含 `httpx` 驱动的 TestClient 端到端测试）
- Docker / Docker Compose（含一次性 `verify` 验收服务）

---

## 1. 编排规则（与题面严格一致）

1. 每张纸固定承载 **4 页**：正面左/右、反面左/右。
2. 每帖张数 `sheets_per_signature` 仅允许 **1、2、3、4**，故每帖容量为
   `4 × sheets_per_signature` 页（4 / 8 / 12 / 16）。
3. 从正文起始处按每帖容量依次分帖，**帖间不插任何空页**。
4. 最后一帖不足帖容量时，**只在全文末尾**补 `BLANK`，把最后一帖补到
   4 的倍数（帖容量本身就是 4 的倍数）。补白数为
   `(-page_count) mod (4 × sheets_per_signature)`，整除时为 0。
5. 各帖独立套用“由外向内”取页规则。把一帖的页位序列记为 `seq`
   （长度 `L = 4k_max`），第 k 张纸（k 从 1 起）：
   - **正面**从左到右：`seq[L-2k+1]`、`seq[2k-2]`
   - **反面**从左到右：`seq[2k-1]`、`seq[L-2k]`
   - 取完后，序列两端各向内推进两页。

### 示例：8 页、每帖 2 张

| 帖 | 张 | 正面 左→右 | 反面 左→右 |
|---:|---:|:-----------|:-----------|
| 1 | 1 | 8, 1 | 2, 7 |
| 1 | 2 | 6, 3 | 4, 5 |

### 示例：10 页、每帖 2 张（末尾补 6 个 BLANK）

| 帖 | 张 | 正面 左→右 | 反面 左→右 |
|---:|---:|:-----------|:-----------|
| 1 | 1 | 8, 1 | 2, 7 |
| 1 | 2 | 6, 3 | 4, 5 |
| 2 | 1 | BLANK, 9 | 10, BLANK |
| 2 | 2 | BLANK, BLANK | BLANK, BLANK |

注意补白全部位于**最后一帖**（承载正文末尾页 9、10），第一帖没有 BLANK。

---

## 2. API

### `GET /healthz`

健康检查，返回 `{"status": "ok"}`。

### `POST /impose`

请求体（JSON）：

| 字段 | 类型 | 约束 |
|------|------|------|
| `page_count` | 整数 | 1 ≤ 值 ≤ 2000，必须是真正的整数（`1.0`、`"8"`、`true` 均拒绝） |
| `sheets_per_signature` | 整数 | 仅允许 `1`、`2`、`3`、`4` |

多余字段同样拒绝（`extra="forbid"`）。

响应：

```json
{
  "page_count": 8,
  "sheets_per_signature": 2,
  "total_signatures": 1,
  "total_blanks": 0,
  "signatures": [
    {
      "signature": 1,
      "sheets": [
        {
          "sheet": 1,
          "front": {"left": 8, "right": 1},
          "back": {"left": 2, "right": 7}
        },
        {
          "sheet": 2,
          "front": {"left": 6, "right": 3},
          "back": {"left": 4, "right": 5}
        }
      ]
    }
  ]
}
```

页位置的值为正文页码（整数）或字符串 `"BLANK"`。

### 错误响应

任何非法输入（页数越界、类型非整数、每帖张数不支持、缺字段、多字段、
非法 JSON）**整次请求返回 HTTP 422**，响应体为 FastAPI 标准的
`detail` 错误数组，并定位到出错字段，例如：

```json
{
  "detail": [
    {
      "type": "less_than_equal",
      "loc": ["body", "page_count"],
      "msg": "Input should be less than or equal to 2000",
      "input": 2001
    }
  ]
}
```

---

## 3. 快速开始

### 本地运行（Python 3.12）

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

交互文档：<http://localhost:8000/docs>

### Docker Compose

宿主端口由环境变量 `API_PORT` 覆盖（默认 `8000`）：

```bash
docker compose up --build api
API_PORT=9000 docker compose up --build api
```

### 调用示例

```bash
curl -s http://localhost:8000/healthz
curl -s -X POST http://localhost:8000/impose \
  -H 'content-type: application/json' \
  -d '{"page_count": 10, "sheets_per_signature": 2}'
```

---

## 4. 测试与验收

### 单元 + HTTP 测试（pytest）

```bash
pip install -r requirements.txt
python -m pytest
```

测试分三层：

- `tests/test_imposition.py`：编排核心逻辑
  - 1/2/3/4 张每帖的手工算例（逐张核对由外向内取页）；
  - 对 `page_count = 1..48` 与四种每帖张数做穷举，断言每个正文页
    **恰好出现一次**、总版面数、帖数、张号/帖号顺序、补白数全部自洽；
  - 补白只出现在最后一帖、帖间无空页；
  - 核心函数对非法参数与非整数（含 `bool`、字符串、浮点、`None`）抛错。
- `tests/test_api.py`：HTTP 层
  - 合法请求返回唯一页序；多组参数下每页恰好一次；
  - 非法页数、非整数、不支持的每帖张数、缺字段、多字段、非法 JSON、
    错误 Content-Type 一律 **422**，且携带具体错误定位；
  - 响应结构稳定、BLANK 只在末尾。
- `tests/conftest.py`：FastAPI `TestClient` 夹具。

### 一次性验收服务 `verify`

`scripts/verify.py` 对运行中的 API 发起**真实 HTTP 调用**（仅用标准库），
覆盖健康检查、10 种页数 × 4 种每帖张数的合法用例（逐页去重、补白自洽、
无帖间插空）与 12 种非法载荷（必须全部 422）。

Compose 将其建模为一次性服务（`restart: "no"`，跑完即退出）：

```bash
docker compose up --build verify
# 或
docker compose run --rm verify
```

`verify` 通过 `depends_on: condition: service_healthy` 等 API 就绪后
再执行；退出码 0 表示全部验收项通过。

> 镜像只在 `api` 服务声明一次 `build`，`verify` 用相同镜像名 +
> `pull_policy: never` 复用本地构建产物。这样 `up --build verify`
> 只会构建一次镜像，避免两个服务并行构建、对同一镜像标签重复打标签
> 导致的构建失败。

---

## 5. 项目结构

```
.
├── app/
│   ├── __init__.py
│   ├── imposition.py     # 纯函数编排核心（不依赖 FastAPI）
│   ├── schemas.py        # Pydantic 请求/响应模型与严格校验
│   └── main.py           # FastAPI 路由
├── scripts/
│   └── verify.py         # verify 一次性验收脚本（标准库 HTTP）
├── tests/
│   ├── conftest.py
│   ├── test_imposition.py
│   └── test_api.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pytest.ini
└── README.md
```
