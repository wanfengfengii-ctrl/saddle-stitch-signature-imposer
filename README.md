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

6. （可选）传入 **纸张厚度 `paper_thickness_mm`**（毫米，`0 < t ≤ 1` 的
   有限小数）时启用 **creep（订书沟位移）补偿**：厚纸手册折叠后内层纸张
   向外推移，裁切时需要按嵌套深度补偿。以帖内**最外张**（第 1 张）的
   嵌套深度为零，每向内一张深度加一，该张纸统一的补偿量为

   `creep_mm = 2 × paper_thickness_mm × (k − 1)`

   （外层每张纸的正反两层面板各贡献一个纸厚）。计量**按帖独立**，跨帖
   重新从零开始；结果按**十进制四舍五入保留三位小数**。补偿只在每张纸
   上**新增 `creep_mm` 字段**，不改变页序、补白位置与帖/张编号；不传
   `paper_thickness_mm` 时响应与旧版本完全一致（不出现该字段）。

   例如每帖 4 张、厚度 `0.125` 时，各帖的张依次得到
   `0 / 0.250 / 0.500 / 0.750` mm；下一帖重新从 `0` 开始。

7. （可选）传入 **装订侧 `binding_edge`**（仅 `"left"` 或 `"right"`，
   缺省等同 `"left"`）时，编排核心在既有帖、张、正反面对象上把每一面的
   **左右页位水平镜像**（含 `BLANK` 页位），用于从右向左翻阅的手册。
   正文分帖、末尾补白、帖张编号与总补白数均不改变。与
   `paper_thickness_mm` 同时传入时，先生成原有页序与逐张补偿量，再按
   装订侧镜像左右页位；`creep_mm` 的计算、舍入与跨帖归零保持原样。

   例如 8 页、每帖 2 张、右装订（`binding_edge="right"`）：

   | 帖 | 张 | 正面 左→右 | 反面 左→右 |
   |---:|---:|:-----------|:-----------|
   | 1 | 1 | 1, 8 | 7, 2 |
   | 1 | 2 | 3, 6 | 5, 4 |

8. （可选）传入 **正文页码起点 `page_number_start`**（1 至 999999 的
   **严格整数**，缺省为 1）时，从长文档中截取章节制作样册可保留原文页码：
   编排核心仍按 `page_count` 分帖、计算末尾补白，**只把正文页映射为从该
   起点连续递增的编号**（`start .. start+page_count-1`）；`BLANK`、帖号、
   张号与补白数均不受影响，响应结构不新增字段。**起点与正文页数相加**
   （`page_number_start + page_count`）**不得超过 999999**，超过即整次
   422（例如起点 999999 连 1 页也不允许；999989 配 10 页恰为上界）。与
   右装订及纸厚补偿组合时，**先完成编号映射**，再执行既有镜像，
   `creep_mm` 保持原补偿量。

   例如 10 页、每帖 2 张、`page_number_start: 37`（末帖含 6 个补白）：

   | 帖 | 张 | 正面 左→右 | 反面 左→右 |
   |---:|---:|:-----------|:-----------|
   | 1 | 1 | 44, 37 | 38, 43 |
   | 1 | 2 | 42, 39 | 40, 41 |
   | 2 | 1 | BLANK, 45 | 46, BLANK |
   | 2 | 2 | BLANK, BLANK | BLANK, BLANK |

   显式 `null`、布尔值（`true`/`false`）、字符串（`"37"`）、小数
   （`37.0`、`37.5`）一律 422。

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
| `paper_thickness_mm` | 小数 | 可选。大于 `0` 且不超过 `1` 的**有限小数**；布尔值（`true`/`false`）、字符串（`"0.5"`）、显式 `null`、`0`、负数、`> 1`、`NaN`/`Infinity` 一律 422。整数 `1` 作为 JSON 数字被接受。**只有缺省该字段**才表示不做补偿。 |
| `binding_edge` | 字符串 | 可选。仅接受 `"left"` 或 `"right"`；无法识别的值、非字符串（数字、布尔、数组、对象）与显式 `null` 一律 422。**只有缺省该字段**才表示左装订（与旧版本一致）。 |
| `page_number_start` | 整数 | 可选。`1` ≤ 值 ≤ `999999` 的严格整数，缺省为 `1`。布尔值（`true`/`false`）、字符串（`"37"`）、小数（`37.0`、`37.5`）、显式 `null` 一律 422。另要求 `page_number_start + page_count ≤ 999999`，超出同样 422 且定位到本字段。 |

多余字段同样拒绝（`extra="forbid"`）。

请求必须显式声明 `Content-Type: application/json`（允许携带 `charset`
等参数，如 `application/json; charset=utf-8`）：缺省该请求头或声明为
其他媒体类型（如 `text/plain`、`application/x-www-form-urlencoded`）
一律 **422** 拒绝，接口不会尝试按其他格式解释正文。

同一 JSON 对象内出现**重复字段**（如两个 `page_count`，无论两次取值
是否相同）一律 **422** 整次拒绝，不会静默采用后值；请求体含**非法
UTF-8 编码字节**时，同样在解析阶段返回 422。字段值中出现未配对代理
字符（如 `\uD800`）时，422 错误会定位到对应字段。

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

页位置的值为正文页码（整数）或字符串 `"BLANK"`。**不传厚度时，张对象
不包含 `creep_mm` 字段**（旧版本响应快照保持不变）。

### 启用 creep 补偿（`paper_thickness_mm`）

请求增加 `paper_thickness_mm` 后，**每张纸**额外携带 `creep_mm`（同样
保留页序、补白与编号）。每帖 4 张、厚度 `0.125`：

```json
{
  "page_count": 16,
  "sheets_per_signature": 4,
  "total_signatures": 1,
  "total_blanks": 0,
  "signatures": [
    {
      "signature": 1,
      "sheets": [
        {"sheet": 1, "front": {"left": 16, "right": 1}, "back": {"left": 2, "right": 15}, "creep_mm": 0.0},
        {"sheet": 2, "front": {"left": 14, "right": 3}, "back": {"left": 4, "right": 13}, "creep_mm": 0.25},
        {"sheet": 3, "front": {"left": 12, "right": 5}, "back": {"left": 6, "right": 11}, "creep_mm": 0.5},
        {"sheet": 4, "front": {"left": 10, "right": 7}, "back": {"left": 8, "right": 9}, "creep_mm": 0.75}
      ]
    }
  ]
}
```

> `creep_mm` 只在启用补偿时出现；最外张恒为 `0.0`，每向内一张增加
> `2 × 纸厚`，跨帖重新从零计量。

### 右装订（`binding_edge="right"`）

请求增加 `binding_edge: "right"` 后，每张纸正反面的**左右页位水平镜像**
（含 `BLANK` 页位），其余字段（帖/张编号、总补白数、`creep_mm`）不变；
响应结构不新增字段。10 页、每帖 2 张（末帖含补白）：

```json
{
  "page_count": 10,
  "sheets_per_signature": 2,
  "total_signatures": 2,
  "total_blanks": 6,
  "signatures": [
    {
      "signature": 1,
      "sheets": [
        {"sheet": 1, "front": {"left": 1, "right": 8}, "back": {"left": 7, "right": 2}},
        {"sheet": 2, "front": {"left": 3, "right": 6}, "back": {"left": 5, "right": 4}}
      ]
    },
    {
      "signature": 2,
      "sheets": [
        {"sheet": 1, "front": {"left": 9, "right": "BLANK"}, "back": {"left": "BLANK", "right": 10}},
        {"sheet": 2, "front": {"left": "BLANK", "right": "BLANK"}, "back": {"left": "BLANK", "right": "BLANK"}}
      ]
    }
  ]
}
```

> 缺省（或显式 `"left"`）时响应与旧版本完全一致，不出现 `binding_edge`
> 字段；现有调用方无需调整解析逻辑。

### 保留原文页码（`page_number_start`）

请求增加 `page_number_start` 后，正文页编号整体平移为
`start .. start+page_count-1`，分帖、补白、帖/张编号完全不变；响应结构
不新增字段。10 页、每帖 2 张、`page_number_start: 37`（末帖含补白）：

```json
{
  "page_count": 10,
  "sheets_per_signature": 2,
  "total_signatures": 2,
  "total_blanks": 6,
  "signatures": [
    {
      "signature": 1,
      "sheets": [
        {"sheet": 1, "front": {"left": 44, "right": 37}, "back": {"left": 38, "right": 43}},
        {"sheet": 2, "front": {"left": 42, "right": 39}, "back": {"left": 40, "right": 41}}
      ]
    },
    {
      "signature": 2,
      "sheets": [
        {"sheet": 1, "front": {"left": "BLANK", "right": 45}, "back": {"left": 46, "right": "BLANK"}},
        {"sheet": 2, "front": {"left": "BLANK", "right": "BLANK"}, "back": {"left": "BLANK", "right": "BLANK"}}
      ]
    }
  ]
}
```

> 缺省（或显式传 `1`）时响应与旧版本完全一致；与 `binding_edge: "right"`、
> `paper_thickness_mm` 同时使用时，先完成编号映射再镜像，补偿量不变。

### 错误响应

任何非法输入（页数越界、类型非整数、每帖张数不支持、纸张厚度为
布尔/字符串/显式 `null`/零/负数/超限/非有限数、装订侧无法识别或非
字符串、页码起点非严格整数/显式 `null`/越界或与正文页数相加上溢、
缺字段、多字段、非法 JSON、非法 UTF-8 编码、重复 JSON 字段、
未声明或声明错误的 `Content-Type`）**整次请求返回 HTTP 422**，响应体
为 FastAPI 标准的 `detail` 错误数组，并定位到出错字段，例如：

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
# 启用 creep 补偿（纸张厚度 0.125mm）：
curl -s -X POST http://localhost:8000/impose \
  -H 'content-type: application/json' \
  -d '{"page_count": 32, "sheets_per_signature": 4, "paper_thickness_mm": 0.125}'
# 右装订（从右向左翻阅，左右页位水平镜像）：
curl -s -X POST http://localhost:8000/impose \
  -H 'content-type: application/json' \
  -d '{"page_count": 10, "sheets_per_signature": 2, "binding_edge": "right"}'
# 保留原文页码（章节从原书第 37 页开始）：
curl -s -X POST http://localhost:8000/impose \
  -H 'content-type: application/json' \
  -d '{"page_count": 10, "sheets_per_signature": 2, "page_number_start": 37}'
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
  - creep 补偿：默认响应不含 `creep_mm`；四张一帖 `0.125` 依次
    `0/0.250/0.500/0.750`、跨帖重置、十进制四舍五入三位、启用前后
    编排一致且每页仍恰好一次；非法厚度（含 `bool`、字符串、零、负数、
    超限、`NaN`/`Infinity`）抛错；
  - 装订侧：右装订逐面镜像左右页位（含 `BLANK` 页位）、显式 `left`
    与缺省一致、右装订与补偿组合时 creep 不变、右装订下每页仍恰好一次；
    非法装订侧（无法识别的字符串、非字符串）抛错；
  - 页码起点：起点 37 且末帖含补白的逐面页码、与右装订及补偿三项组合
    （先映射再镜像、补偿量不变）、缺省/显式 1 与旧版本一致、平移后每个
    正文页恰好一次且补白/帖张编号不变、边界 999999 与上溢、非严格整数
    （含 `bool`、字符串、小数、`None`）抛错；
  - 核心函数对非法参数与非整数（含 `bool`、字符串、浮点、`None`）抛错。
- `tests/test_api.py`：HTTP 层
  - 合法请求返回唯一页序；多组参数下每页恰好一次；
  - 非法页数、非整数、不支持的每帖张数、缺字段、多字段、非法 JSON、
    非法 UTF-8 编码字节、页数字段含未配对代理字符、重复 JSON 字段、
    未声明或非 JSON 的错误 Content-Type 一律 **422**，且携带具体错误定位；
  - 默认响应**整份快照锁定**（不含 `creep_mm`）；启用补偿后的 creep
    序列、跨帖重置、整数 `1` 被接受、显式 `null` 被 422 拒绝（仅缺省
    才不补偿）；非法厚度 422 且定位到 `body.paper_thickness_mm`；
    `NaN`/`Infinity` token 返回合法 JSON 的 422；
  - 装订侧：右装订且末帖含补白的镜像结果、右装订与纸厚补偿组合、
    缺省请求快照不出现 `binding_edge`、显式 `left` 与缺省一致、
    非法装订侧 422 且定位到 `body.binding_edge`、右装订下每页仍恰好一次；
  - 页码起点：起点 37 且末帖含补白的逐面页码、与右装订及补偿三项组合、
    缺省/显式 1 的默认快照不变、多组组合下 `start..start+N-1` 每页恰好
    一次、边界（999989+10=999999）与上溢（999990+10、999999+1）422 并
    定位到 `body.page_number_start`、显式 null/布尔/字符串/小数 422 且
    字段定位正确；
  - 响应结构稳定、BLANK 只在末尾。
- `tests/conftest.py`：FastAPI `TestClient` 夹具。

### 一次性验收服务 `verify`

`scripts/verify.py` 对运行中的 API 发起**真实 HTTP 调用**（仅用标准库），
覆盖健康检查、10 种页数 × 4 种每帖张数的合法用例（逐页去重、补白自洽、
无帖间插空）、12 种非法载荷（必须全部 422），非法 UTF-8 编码字节、
字段内未配对代理字符、重复 JSON 字段、未声明或非 JSON 的 Content-Type
专项（同样必须 422），creep 补偿专项：
默认响应整份快照不变（无 `creep_mm`）、四张一帖 `0.125` 依次
`0/0.250/0.500/0.750` 且跨帖重置、对全部合法组合验证启用前后页序一致、
每页仍恰好一次、非法厚度 422 并定位到 `paper_thickness_mm`（含
`NaN`/`Infinity` token），以及装订侧专项：
右装订且末帖含补白的镜像结果、右装订与纸厚补偿组合（creep 不变）、
缺省请求快照不出现 `binding_edge`、显式 `left` 与缺省一致、
右装订下每页仍恰好一次、非法装订侧 422 并定位到 `binding_edge`，以及
页码起点专项：起点 37 且末帖含补白的逐面页码、与右装订及补偿三项组合
（先映射再镜像、补偿量不变）、缺省/显式 1 快照不变、边界 999999 与
多组组合下每个正文页恰好一次、非法起点（含显式 null、布尔、字符串、
小数、上溢）422 并定位到 `page_number_start`。

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
