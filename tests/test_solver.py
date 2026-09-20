"""求解器单元测试：数值正确性 + 各类错误诊断。"""
import numpy as np
import pytest

from app.solver import NetworkError, analyze, validate_payload


def run(payload):
    return analyze(validate_payload(payload))


def volts(res):
    return {r["node"]: r["voltage"] for r in res["node_voltages"]}


# -------------------- 数值正确性 --------------------

def test_simple_voltage_source_with_resistor():
    """10V 电压源串联 5Ω 电阻：电流 2A，电源发出 20W，电阻耗散 20W。"""
    res = run({
        "node_count": 2, "ground": 1,
        "components": [
            {"id": "V1", "kind": "V", "a": 2, "b": 1, "value": 10},
            {"id": "R1", "kind": "R", "a": 2, "b": 1, "value": 5},
        ],
    })
    v = volts(res)
    assert v[1] == 0.0
    assert v[2] == pytest.approx(10.0)
    b = {x["id"]: x for x in res["branches"]}
    assert b["R1"]["current"] == pytest.approx(2.0)           # a->b (2->1)
    assert b["R1"]["power_absorbed"] == pytest.approx(20.0)
    assert b["V1"]["current"] == pytest.approx(-2.0)          # 实际 b->a，电源放电
    assert b["V1"]["power_absorbed"] == pytest.approx(-20.0)
    pb = res["power_balance"]
    assert pb["mismatch_w"] < 1e-9
    assert pb["relative_error"] < 1e-9
    assert pb["kcl_residual_a"] < 1e-9
    assert pb["total_generated"] == pytest.approx(20.0)
    assert pb["total_dissipated"] == pytest.approx(20.0)


def test_current_source_drives_resistor():
    """1A 电流源并联 4Ω：节点 2 电压 4V，电流源发出 4W。"""
    res = run({
        "node_count": 2, "ground": 1,
        "components": [
            {"id": "I1", "kind": "I", "a": 1, "b": 2, "value": 1},
            {"id": "R1", "kind": "R", "a": 2, "b": 1, "value": 4},
        ],
    })
    assert volts(res)[2] == pytest.approx(4.0)
    b = {x["id"]: x for x in res["branches"]}
    assert b["R1"]["current"] == pytest.approx(1.0)
    assert b["I1"]["power_absorbed"] == pytest.approx(-4.0)
    assert res["power_balance"]["mismatch_w"] < 1e-10


def test_two_source_bridge_example():
    """前端示例 1：与手算结果对比。"""
    res = run({
        "node_count": 4, "ground": 1,
        "components": [
            {"id": "V1", "kind": "V", "a": 2, "b": 1, "value": 12},
            {"id": "R1", "kind": "R", "a": 2, "b": 3, "value": 4},
            {"id": "R2", "kind": "R", "a": 3, "b": 1, "value": 6},
            {"id": "R3", "kind": "R", "a": 3, "b": 4, "value": 2},
            {"id": "R4", "kind": "R", "a": 4, "b": 1, "value": 3},
            {"id": "I1", "kind": "I", "a": 1, "b": 2, "value": 0.5},
        ],
    })
    v = volts(res)
    assert v[2] == pytest.approx(12.0)
    assert v[3] == pytest.approx(36 / 7.4)
    assert v[4] == pytest.approx(0.6 * (36 / 7.4))
    assert res["power_balance"]["relative_error"] < 1e-9
    assert res["power_balance"]["kcl_residual_a"] < 1e-9


def test_zero_volt_source_is_short_circuit():
    """0V 电压源相当于理想导线：两个节点等电位，5Ω 电阻电流 2A。"""
    res = run({
        "node_count": 3, "ground": 1,
        "components": [
            {"id": "V1", "kind": "V", "a": 2, "b": 1, "value": 10},
            {"id": "V0", "kind": "V", "a": 2, "b": 3, "value": 0},
            {"id": "R1", "kind": "R", "a": 3, "b": 1, "value": 5},
        ],
    })
    v = volts(res)
    assert v[2] == pytest.approx(10.0)
    assert v[3] == pytest.approx(10.0)
    b = {x["id"]: x for x in res["branches"]}
    assert b["R1"]["current"] == pytest.approx(2.0)


def test_unused_node_is_not_floating():
    res = run({
        "node_count": 3, "ground": 1,
        "components": [
            {"id": "V1", "kind": "V", "a": 2, "b": 1, "value": 5},
            {"id": "R1", "kind": "R", "a": 2, "b": 1, "value": 10},
        ],
    })
    rows = {r["node"]: r for r in res["node_voltages"]}
    assert rows[3]["used"] is False
    assert rows[3]["voltage"] is None


def test_direction_flag_reverses():
    """电流实际从 b 流向 a 时 direction_a_to_b 为 False。"""
    res = run({
        "node_count": 3, "ground": 1,
        "components": [
            {"id": "V1", "kind": "V", "a": 2, "b": 1, "value": 10},
            {"id": "R1", "kind": "R", "a": 1, "b": 2, "value": 5},  # a=地, b=10V
        ],
    })
    r1 = next(b for b in res["branches"] if b["id"] == "R1")
    assert r1["current"] == pytest.approx(-2.0)
    assert r1["direction_a_to_b"] is False


# -------------------- 错误诊断 --------------------

def test_missing_ground():
    with pytest.raises(NetworkError) as ei:
        run({"node_count": 2, "ground": None,
             "components": [
                 {"id": "V1", "kind": "V", "a": 1, "b": 2, "value": 5},
                 {"id": "R1", "kind": "R", "a": 1, "b": 2, "value": 5}]})
    assert ei.value.code == "no_ground"
    assert set(ei.value.items[0]["nodes"]) == {1, 2}


def test_floating_subnet_reports_nodes():
    with pytest.raises(NetworkError) as ei:
        run({"node_count": 6, "ground": 1,
             "components": [
                 {"id": "V1", "kind": "V", "a": 2, "b": 1, "value": 9},
                 {"id": "R1", "kind": "R", "a": 2, "b": 3, "value": 3},
                 {"id": "R2", "kind": "R", "a": 3, "b": 1, "value": 6},
                 {"id": "R3", "kind": "R", "a": 5, "b": 6, "value": 2},
                 {"id": "R4", "kind": "R", "a": 6, "b": 5, "value": 4},
                 {"id": "I2", "kind": "I", "a": 3, "b": 5, "value": 1}]})
    assert ei.value.code == "structural"
    assert any(set(it.get("nodes", [])) == {5, 6} for it in ei.value.items)


def test_floating_single_node_via_current_source():
    """节点 2 只有电流源连接到地：无电导通路，电位不定。"""
    with pytest.raises(NetworkError) as ei:
        run({"node_count": 2, "ground": 1,
             "components": [{"id": "I1", "kind": "I", "a": 1, "b": 2, "value": 1}]})
    assert ei.value.code == "structural"
    assert 2 in ei.value.items[0]["nodes"]


def test_parallel_conflicting_voltage_sources():
    with pytest.raises(NetworkError) as ei:
        run({"node_count": 3, "ground": 1,
             "components": [
                 {"id": "V1", "kind": "V", "a": 2, "b": 1, "value": 12},
                 {"id": "V2", "kind": "V", "a": 2, "b": 1, "value": 5},
                 {"id": "R1", "kind": "R", "a": 2, "b": 3, "value": 10},
                 {"id": "R2", "kind": "R", "a": 3, "b": 1, "value": 10}]})
    assert ei.value.code == "structural"
    item = ei.value.items[0]
    assert set(item["elements"]) == {"V1", "V2"}
    assert set(item["nodes"]) == {1, 2}


def test_loop_voltage_conflict():
    """环路：5V + 5V 电压源与 8V 电压源反向构成回路，KVL 不满足。"""
    with pytest.raises(NetworkError):
        run({"node_count": 3, "ground": 1,
             "components": [
                 {"id": "V1", "kind": "V", "a": 1, "b": 2, "value": 5},
                 {"id": "V2", "kind": "V", "a": 2, "b": 3, "value": 5},
                 {"id": "V3", "kind": "V", "a": 1, "b": 3, "value": 8}]})


def test_consistent_parallel_voltage_sources_solve():
    """同值理想电压源并联不报错（电流由 MNA 自动分配）。"""
    res = run({"node_count": 2, "ground": 1,
               "components": [
                   {"id": "V1", "kind": "V", "a": 2, "b": 1, "value": 5},
                   {"id": "V2", "kind": "V", "a": 2, "b": 1, "value": 5},
                   {"id": "R1", "kind": "R", "a": 2, "b": 1, "value": 10}]})
    assert volts(res)[2] == pytest.approx(5.0)


def test_pure_current_source_subnet_is_structural():
    """两个不同电流的理想电流源构成无导电路径的子网：结构诊断即可发现。"""
    with pytest.raises(NetworkError) as ei:
        run({"node_count": 2, "ground": 1,
             "components": [
                 {"id": "I1", "kind": "I", "a": 1, "b": 2, "value": 1},
                 {"id": "I2", "kind": "I", "a": 2, "b": 1, "value": 2}]})
    assert ei.value.code == "structural"
    assert 2 in ei.value.items[0]["nodes"]


def test_mna_singular_fallback_directly():
    """深度防线：绕过结构检查，直接验证 MNA 对无解方程组的 lstsq 残差判别。

    地 - 1A 电流源 - 节点2 - 2A 电流源 - 节点3 - 0V 导线 - 地，
    节点 2 的 KCL 要求 1==2，增广方程组无解。
    """
    from app.solver import Component, Network, _stamp_and_solve

    net = Network(node_count=3, ground=1, components=[
        Component(id="I1", kind="I", a=1, b=2, value=1.0),
        Component(id="I2", kind="I", a=2, b=3, value=2.0),
        Component(id="V0", kind="V", a=3, b=1, value=0.0),
    ])
    with pytest.raises(NetworkError) as ei:
        _stamp_and_solve(net)
    assert ei.value.code == "singular"
    assert ei.value.items[0]["nodes"]  # 定位到了相关节点


# -------------------- 输入校验 --------------------

def test_reject_zero_resistance():
    with pytest.raises(NetworkError) as ei:
        run({"node_count": 2, "ground": 1,
             "components": [{"id": "R1", "kind": "R", "a": 1, "b": 2, "value": 0}]})
    assert ei.value.code == "validation_failed"


def test_reject_out_of_range_endpoint():
    with pytest.raises(NetworkError) as ei:
        run({"node_count": 2, "ground": 1,
             "components": [{"id": "R1", "kind": "R", "a": 1, "b": 9, "value": 5}]})
    assert ei.value.code == "validation_failed"


def test_reject_too_many_nodes():
    with pytest.raises(NetworkError) as ei:
        run({"node_count": 31, "ground": 1, "components": []})
    assert ei.value.code == "validation_failed"


def test_reject_duplicate_ids():
    with pytest.raises(NetworkError) as ei:
        run({"node_count": 2, "ground": 1,
             "components": [
                 {"id": "X", "kind": "R", "a": 1, "b": 2, "value": 1},
                 {"id": "X", "kind": "R", "a": 1, "b": 2, "value": 2}]})
    assert ei.value.code == "validation_failed"


def test_wheatstone_balance():
    """经典惠斯通电桥：平衡时桥臂无电流。"""
    res = run({"node_count": 4, "ground": 1,
               "components": [
                   {"id": "V1", "kind": "V", "a": 2, "b": 1, "value": 10},
                   {"id": "R1", "kind": "R", "a": 2, "b": 3, "value": 10},
                   {"id": "R2", "kind": "R", "a": 2, "b": 4, "value": 20},
                   {"id": "R3", "kind": "R", "a": 3, "b": 1, "value": 10},
                   {"id": "R4", "kind": "R", "a": 4, "b": 1, "value": 20},
                   {"id": "Rb", "kind": "R", "a": 3, "b": 4, "value": 100}]})
    v = volts(res)
    assert v[3] == pytest.approx(v[4])
    rb = next(b for b in res["branches"] if b["id"] == "Rb")
    assert abs(rb["current"]) < 1e-12
    assert res["power_balance"]["relative_error"] < 1e-9
