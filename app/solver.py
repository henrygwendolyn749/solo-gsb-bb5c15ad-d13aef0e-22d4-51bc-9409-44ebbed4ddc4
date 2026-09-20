"""直流网络校核器 —— 改进节点法（Modified Nodal Analysis）核心求解器。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

MAX_NODES = 30


class NetworkError(Exception):
    """网络结构性错误，携带可展示给前端的错误条目。"""

    def __init__(self, code: str, message: str, items: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.items = items or []


@dataclass
class Component:
    id: str
    kind: str  # 'R' | 'I' | 'V'
    a: int
    b: int
    value: float  # R: 欧姆；I: 安培（a->b 注入）；V: 伏特（a 端相对 b 端）


@dataclass
class Network:
    node_count: int
    ground: int | None
    components: list[Component] = field(default_factory=list)


# ---------------------------------------------------------------- 输入校验

def validate_payload(payload: dict[str, Any]) -> Network:
    """校验前端负载，返回 Network；错误时抛出 NetworkError('validation_failed')。"""
    errors: list[dict[str, Any]] = []

    try:
        node_count = int(payload.get("node_count", 0))
    except (TypeError, ValueError):
        node_count = -1
    if not 1 <= node_count <= MAX_NODES:
        errors.append({"field": "node_count",
                       "message": f"节点数必须为 1～{MAX_NODES} 之间的整数"})

    ground = payload.get("ground", None)
    if ground in (None, "", -1):
        ground_idx = None
    else:
        try:
            ground_idx = int(ground)
            if not (1 <= ground_idx <= node_count):
                errors.append({"field": "ground", "message": "接地节点编号超出范围"})
                ground_idx = None
        except (TypeError, ValueError):
            errors.append({"field": "ground", "message": "接地节点编号无效"})
            ground_idx = None

    raw_comps = payload.get("components", [])
    if not isinstance(raw_comps, list):
        raw_comps = []
        errors.append({"field": "components", "message": "元件列表格式错误"})

    components: list[Component] = []
    seen_ids: set[str] = set()
    for i, raw in enumerate(raw_comps):
        if not isinstance(raw, dict):
            continue
        cid = str(raw.get("id", "")).strip()
        if not cid:
            cid = f"#{i + 1}"
        prefix = f"components[{i}]"
        if cid in seen_ids:
            errors.append({"field": prefix, "element": cid,
                           "message": f"元件编号 {cid} 重复"})
        seen_ids.add(cid)

        kind = str(raw.get("kind", "")).upper()
        if kind not in ("R", "I", "V"):
            errors.append({"field": f"{prefix}.kind", "element": cid,
                           "message": f"元件 {cid} 类型无效（应为 R/I/V）"})
            continue

        endpoints_ok = True
        endpoints: list[int] = []
        for ep in ("a", "b"):
            try:
                n = int(raw.get(ep))
            except (TypeError, ValueError):
                errors.append({"field": f"{prefix}.{ep}", "element": cid,
                               "message": f"元件 {cid} 的端点 {ep} 不是有效节点编号"})
                endpoints_ok = False
                continue
            if not (1 <= n <= node_count):
                errors.append({"field": f"{prefix}.{ep}", "element": cid,
                               "message": f"元件 {cid} 引用了不存在的节点 {n}"})
                endpoints_ok = False
            endpoints.append(n)

        try:
            value = float(raw.get("value"))
            if not np.isfinite(value):
                raise ValueError
        except (TypeError, ValueError):
            errors.append({"field": f"{prefix}.value", "element": cid,
                           "message": f"元件 {cid} 的数值无效（必须为有限实数）"})
            continue

        if kind == "R" and value <= 0:
            errors.append({"field": f"{prefix}.value", "element": cid,
                           "message": f"电阻 {cid} 阻值必须为正数（如需理想导线请用 0V 电压源）"})
        if endpoints_ok:
            a, b = endpoints
            if a == b and kind == "R":
                errors.append({"field": prefix, "element": cid,
                               "message": f"电阻 {cid} 的两个端点不能为同一节点"})
            components.append(Component(id=cid, kind=kind, a=a, b=b, value=value))

    if errors:
        raise NetworkError("validation_failed", "输入数据校验未通过", errors)
    return Network(node_count=node_count, ground=ground_idx, components=components)


# ---------------------------------------------------------------- 结构诊断

def _used_nodes(net: Network) -> set[int]:
    used: set[int] = set()
    for c in net.components:
        used.add(c.a)
        used.add(c.b)
    return used


def _check_no_ground(net: Network) -> list[dict[str, Any]]:
    if net.ground is None:
        return [{"nodes": list(range(1, net.node_count + 1)),
                 "message": "未指定接地节点：全网电压缺少参考零点，方程矩阵奇异"}]
    return []


def _conductive_components(net: Network):
    """返回可导电元件（电阻与电压源；自环无意义，跳过）。"""
    return [c for c in net.components if c.kind in ("R", "V") and c.a != c.b]


def _check_floating_subnets(net: Network) -> list[dict[str, Any]]:
    """在「电阻 + 理想电压源」构成的无向图上寻找不包含地的连通分量。"""
    if net.ground is None:
        return []  # 已由 no_ground 覆盖

    used = _used_nodes(net)
    adj: dict[int, set[int]] = {n: set() for n in used}
    for c in _conductive_components(net):
        adj[c.a].add(c.b)
        adj[c.b].add(c.a)

    seen: set[int] = set()
    errors: list[dict[str, Any]] = []
    for start in sorted(used):
        if start in seen:
            continue
        stack = [start]
        comp_nodes: list[int] = []
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            comp_nodes.append(n)
            stack.extend(adj[n] - seen)
        if net.ground not in comp_nodes:
            only_sources = all(
                c.kind != "R" and c.kind != "V"
                for n in comp_nodes for c in net.components
                if n in (c.a, c.b)
            )
            if only_sources:
                msg = (f"纯电流源子网：节点 {', '.join(map(str, sorted(comp_nodes)))} "
                       f"所在连通分量没有任何电阻/电压源，理想电流源之间互相矛盾或开路，无唯一解")
            else:
                msg = (f"浮置子网：节点 {', '.join(map(str, sorted(comp_nodes)))} "
                       f"仅通过电流源（或未连接）与主网耦合，电位无法确定")
            errors.append({"nodes": sorted(comp_nodes), "message": msg})
    return errors


def _check_voltage_conflicts(net: Network) -> list[dict[str, Any]]:
    """沿理想电压源边做 BFS，检查并联/环路电压约束是否互相矛盾。"""
    if net.ground is None:
        return []

    # 无向图：节点 -> [(对端, 边id, 边方向下 u 相对 v 的电位升)]
    adj: dict[int, list[tuple[int, str, float]]] = {}
    for c in net.components:
        if c.kind != "V" or c.a == c.b:
            continue
        # 从 a 走到 b 时电位变化为 -value（Va - Vb = value）
        adj.setdefault(c.a, []).append((c.b, c.id, -c.value))
        adj.setdefault(c.b, []).append((c.a, c.id, +c.value))

    potential: dict[int, float] = {net.ground: 0.0}
    origin: dict[int, str] = {}  # 节点电位是由哪条电压源边建立的
    visited: set[int] = set()
    raw_errors: list[dict[str, Any]] = []

    # 先从接地节点（电位已知为 0）出发遍历，再处理与地无电压源路径的连通块
    roots = [net.ground] + [n for n in adj if n != net.ground]
    for root in roots:
        if root in visited:
            continue
        visited.add(root)
        if root not in potential:
            potential[root] = 0.0
        stack = [root]
        while stack:
            u = stack.pop()
            for v, eid, dv in adj.get(u, []):
                expect = potential[u] + dv
                if v not in visited:
                    visited.add(v)
                    potential[v] = expect
                    origin[v] = eid
                    stack.append(v)
                elif abs(potential[v] - expect) > 1e-7 * max(1.0, abs(expect)):
                    prior = origin.get(v)
                    # dv 是 u->v 的电位变化，即该电源强制 V{v}-V{u} = dv
                    required = dv
                    existing = potential[v] - potential[u]
                    raw_errors.append({
                        "elements": sorted({e for e in (eid, prior) if e}),
                        "nodes": sorted({u, v}),
                        "message": f"理想电压源约束矛盾：{eid} 要求 V{v}−V{u}"
                                   f"={required:g}V，但沿其他电压源推得 "
                                   f"V{v}−V{u}={existing:g}V"
                                   + (f"（约束由 {prior} 建立）" if prior else ""),
                    })

    # 同一对/同一组元件可能在环路遍历中重复触发，按元件集合去重
    errors: list[dict[str, Any]] = []
    seen_sets: list[set[str]] = []
    for e in raw_errors:
        s = set(e["elements"])
        if any(s <= t or t <= s for t in seen_sets):
            continue
        seen_sets.append(s)
        errors.append(e)
    return errors


# ---------------------------------------------------------------- MNA 求解

def _stamp_and_solve(net: Network):
    ground = net.ground
    assert ground is not None
    non_ground = [n for n in range(1, net.node_count + 1) if n != ground]
    used = _used_nodes(net)
    idx = {n: i for i, n in enumerate(n for n in non_ground if n in used)}
    v_sources = [c for c in net.components if c.kind == "V" and c.a != c.b]

    non_ground_used = sorted(idx)
    nv = len(non_ground_used)
    nvs = len(v_sources)
    size = nv + nvs
    A = np.zeros((size, size), dtype=np.float64)
    z = np.zeros(size, dtype=np.float64)

    # 电导（电阻）
    for c in net.components:
        if c.kind != "R":
            continue
        g = 1.0 / c.value
        ia = idx.get(c.a)
        ib = idx.get(c.b)
        if ia is not None:
            A[ia, ia] += g
        if ib is not None:
            A[ib, ib] += g
        if ia is not None and ib is not None:
            A[ia, ib] -= g
            A[ib, ia] -= g

    # 独立电流源：电流 I 从 a 流向 b（a 端抽出、b 端注入）
    for c in net.components:
        if c.kind != "I":
            continue
        ia = idx.get(c.a)
        ib = idx.get(c.b)
        if ia is not None:
            z[ia] -= c.value
        if ib is not None:
            z[ib] += c.value

    # 理想电压源附带支路电流变量，正方向 a -> b（从 + 端流入电源内部）
    for k, c in enumerate(v_sources):
        row = nv + k
        ia = idx.get(c.a)
        ib = idx.get(c.b)
        if ia is not None:
            A[ia, row] += 1.0
            A[row, ia] += 1.0
        if ib is not None:
            A[ib, row] -= 1.0
            A[row, ib] -= 1.0
        z[row] = c.value

    singular: dict[str, Any] | None = None
    try:
        x = np.linalg.solve(A, z)
    except np.linalg.LinAlgError:
        singular = {}
        x = None

    if singular is not None:
        x, *_ = np.linalg.lstsq(A, z, rcond=None)
        residual = float(np.max(np.abs(A @ x - z))) if size else 0.0
        if residual > 1e-6 * max(1.0, float(np.max(np.abs(z)))):
            # 尝试定位矛盾方程（KCL 残差最大的节点）
            res_nodes = []
            if nv:
                kcl_res = np.abs(A[:nv, :] @ x - z[:nv])
                for i in np.argsort(-kcl_res)[:3]:
                    if kcl_res[i] > 1e-6:
                        res_nodes.append(non_ground_used[int(i)])
            raise NetworkError(
                "singular",
                "线性方程组无解：通常由互相矛盾的理想电流源（如开路电流源、"
                "纯电流源串联割集）导致",
                [{"nodes": sorted(set(res_nodes)),
                  "message": f"方程残差 {residual:.3e}，相关节点："
                             + (", ".join(map(str, sorted(set(res_nodes)))) or "—")}],
            )

    voltages = {n: (0.0 if n == ground else None)
                for n in range(1, net.node_count + 1)}
    branch_currents: dict[str, float] = {}
    for n in non_ground:
        if n in idx:
            voltages[n] = float(x[idx[n]])
    for k, c in enumerate(v_sources):
        branch_currents[c.id] = float(x[nv + k])
    return voltages, branch_currents


# ---------------------------------------------------------------- 支路量与功率

def _branch_results(net: Network, voltages: dict[str, float],
                    v_source_currents: dict[str, float]) -> list[dict[str, Any]]:
    branches: list[dict[str, Any]] = []
    for c in net.components:
        va, vb = voltages[c.a], voltages[c.b]
        v_drop = va - vb  # a 相对 b 的压降
        if c.kind == "R":
            current = v_drop / c.value  # 正方向 a -> b
            p_absorbed = current * v_drop
            branches.append({
                "id": c.id, "kind": "R", "a": c.a, "b": c.b,
                "value": c.value, "current": current,
                "voltage": v_drop, "power_absorbed": p_absorbed,
                "direction_a_to_b": current >= 0,
            })
        elif c.kind == "I":
            current = c.value  # 定义正方向 a -> b
            p_absorbed = current * v_drop  # 无源惯例；负值表示发出功率
            branches.append({
                "id": c.id, "kind": "I", "a": c.a, "b": c.b,
                "value": c.value, "current": current,
                "voltage": v_drop, "power_absorbed": p_absorbed,
                "direction_a_to_b": True,
            })
        else:  # V
            current = v_source_currents.get(c.id, 0.0)
            p_absorbed = current * v_drop
            branches.append({
                "id": c.id, "kind": "V", "a": c.a, "b": c.b,
                "value": c.value, "current": current,
                "voltage": v_drop, "power_absorbed": p_absorbed,
                "direction_a_to_b": current >= 0,
            })
    return branches


def analyze(net: Network) -> dict[str, Any]:
    """完整校核流程：结构诊断 -> MNA 求解 -> 支路量与功率平衡。"""
    structural: list[dict[str, Any]] = []
    structural.extend(_check_no_ground(net))
    structural.extend(_check_voltage_conflicts(net))
    structural.extend(_check_floating_subnets(net))
    if structural:
        # 无接地是最高优先级的诊断；其余结构性问题统一为 structural
        has_no_ground = any("接地节点" in s.get("message", "") for s in structural)
        code = "no_ground" if has_no_ground else "structural"
        raise NetworkError(code, "网络结构存在问题，无法唯一求解", structural)

    voltages, vs_currents = _stamp_and_solve(net)
    branches = _branch_results(net, voltages, vs_currents)

    p_absorbed = sum(b["power_absorbed"] for b in branches)
    p_generated = -sum(min(0.0, b["power_absorbed"]) for b in branches)
    p_dissipated = sum(max(0.0, b["power_absorbed"]) for b in branches)
    scale = max(p_generated, p_dissipated, 1e-30)
    mismatch = abs(p_absorbed)
    relative_error = mismatch / scale

    # KCL 节点残差（独立校验，不依赖 MNA 矩阵）
    kcl_residual = 0.0
    for n in range(1, net.node_count + 1):
        leaving = 0.0
        for b in branches:
            if b["a"] == n:
                leaving += b["current"]
            if b["b"] == n:
                leaving -= b["current"]
        kcl_residual = max(kcl_residual, abs(leaving))

    return {
        "ok": True,
        "node_voltages": [
            {"node": n,
             "voltage": voltages.get(n),
             "used": n in _used_nodes(net),
             "is_ground": n == net.ground}
            for n in range(1, net.node_count + 1)
        ],
        "branches": branches,
        "power_balance": {
            "total_absorbed": p_absorbed,
            "total_generated": p_generated,
            "total_dissipated": p_dissipated,
            "mismatch_w": mismatch,
            "relative_error": relative_error,
            "kcl_residual_a": kcl_residual,
        },
    }
