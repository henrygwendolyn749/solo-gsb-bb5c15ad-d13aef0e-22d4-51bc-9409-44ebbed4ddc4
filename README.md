# ⚡ 直流网络校核器（DC Network Checker）

一个基于 **Python FastAPI + NumPy + 原生 HTML/CSS/JS** 的直流电阻网络在线校核工具。
服务端使用**改进节点法（Modified Nodal Analysis, MNA）**组装并求解线性方程组，
返回各节点电压、各支路方向电流以及全网功率平衡误差。

## 功能特性

- 最多录入 **30 个节点**，任意数量的三类元件：
  - **R** 电阻（Ω，必须为正数）
  - **I** 独立电流源（A，定义电流方向为 `a → b`）
  - **V** 独立电压源（V，`a` 端为正极，允许 0&nbsp;V 理想导线）
- 可指定一个**接地节点**（电压参考零点）
- 求解结果：
  - 每个节点的对地电压（接地节点、未使用节点单独标注）
  - 每条支路的**实际方向电流**（`a→b` 或 `b→a`）、端电压、吸收功率
  - 电源总发出功率、总耗散功率、**功率平衡误差（绝对值与相对值）** 与 KCL 残差
- 鲁棒的错误诊断，服务端**绝不崩溃**，并区分、列出相关节点或元件：
  | 情形 | 诊断码 | 报告内容 |
  |---|---|---|
  | 未指定接地节点 | `no_ground` | 全部节点 |
  | 浮置子网（仅经电流源耦合 / 未连接） | `structural` | 浮置子网内所有节点 |
  | 互相矛盾的理想电压源（并联电压不等 / 环路电压不守恒） | `structural` | 冲突的电压源编号及相关节点 |
  | 方程组无解（如开路电流源） | `singular` | 残差最大的相关节点 |
  | 输入非法（零电阻、越界端点、重复编号等） | `validation_failed` | 出错字段与元件 |
- 前端：一键载入 4 个示例（含 3 类典型错误）、可编辑表格、客户端输入校验、结果高亮（高电位节点、大电流支路、发出功率的电源、平衡校核徽标）

## 快速开始（Docker Compose）

需要本机已安装 Docker 与 Docker Compose（`docker compose` v2）。

```bash
docker compose up --build
```

启动后在浏览器打开：

> **http://localhost:8000**

停止服务：在终端按 `Ctrl+C`，或执行 `docker compose down`。

## 配置

所有配置均在 `compose.yaml` 中，默认值开箱即用：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `ports` | `"8000:8000"` | 宿主机端口:容器端口。如 8000 被占用，可改为 `"8080:8000"`，然后访问 http://localhost:8080 |
| `environment.PORT` | `"8000"` | 容器内 uvicorn 监听端口，修改时需与映射右侧保持一致 |
| `restart` | `unless-stopped` | 容器退出自动重启（手动停止除外） |

## 本地开发运行（不使用 Docker）

需要 Python 3.11+：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## HTTP API

- `GET /api/health` — 健康检查
- `POST /api/analyze` — 求解/校核

请求体示例：

```json
{
  "node_count": 4,
  "ground": 1,
  "components": [
    {"id": "V1", "kind": "V", "a": 2, "b": 1, "value": 12},
    {"id": "R1", "kind": "R", "a": 2, "b": 3, "value": 4},
    {"id": "R2", "kind": "R", "a": 3, "b": 1, "value": 6},
    {"id": "I1", "kind": "I", "a": 1, "b": 2, "value": 0.5}
  ]
}
```

成功响应（节选）：

```json
{
  "ok": true,
  "node_voltages": [{"node": 1, "voltage": 0.0, "used": true, "is_ground": true}],
  "branches": [
    {"id": "R1", "kind": "R", "a": 2, "b": 3,
     "current": 1.2, "voltage": 4.8, "power_absorbed": 5.76,
     "direction_a_to_b": true}
  ],
  "power_balance": {
    "total_generated": 8.4,
    "total_dissipated": 8.4,
    "mismatch_w": 1.7e-14,
    "relative_error": 2.1e-15,
    "kcl_residual_a": 3.3e-16
  }
}
```

错误响应（HTTP 422）：

```json
{
  "ok": false,
  "error": {
    "code": "structural",
    "message": "网络结构存在问题，无法唯一求解",
    "items": [
      {"elements": ["V1", "V2"], "nodes": [1, 2], "message": "理想电压源约束矛盾：…"}
    ]
  }
}
```

## 求解原理简述

对每个非接地节点列 KCL，将理想电压源的支路电流增广为附加未知量，得到增广线性方程组：

```
[ G  B ] [ v ]   [ i ]
[ Bᵀ 0 ] [ j ] = [ e ]
```

- `G`：电阻电导节点导纳矩阵
- `B`：电压源关联矩阵（`+1 / −1`）
- `i`：电流源注入向量（电流 `a→b`，在 `a` 端抽出、`b` 端注入）
- `e`：电压源给定电压

结构诊断在矩阵组装前完成：接地检查、电压源约束图的一致性 BFS、
导电路径（电阻 + 电压源）连通分量检查；数值层再以
`numpy.linalg.solve` 求解，奇异时回退 `lstsq` 并用残差判别无解情况。

## 项目结构

```
.
├── app/
│   ├── __init__.py
│   ├── main.py        # FastAPI 路由、静态文件托管
│   └── solver.py      # 输入校验、结构诊断、MNA 组装求解、功率平衡
├── static/
│   ├── index.html     # 单页界面
│   ├── style.css
│   └── app.js         # 表格编辑、校验、示例、结果高亮
├── tests/
│   └── test_solver.py # NumPy 数值与错误场景单元测试
├── Dockerfile
├── compose.yaml
└── requirements.txt
```
