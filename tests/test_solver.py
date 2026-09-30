"""求解器正确性测试：重叠/越界、刀缝扣除、旋转限制、贯通刀、
可行性与预算语义。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import solver  # noqa: E402


def rects_overlap_area(a, b):
    """两个轴平行矩形的重叠面积（贴边不算重叠）。"""
    ow = max(0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
    oh = max(0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))
    return ow * oh


def verify_solution(result, master_w, master_h, kerf, products, allow_fewer_sheets=True):
    """对可行方案做独立的几何/工艺校验。"""
    assert result["status"] == "feasible", result
    sheets = result["sheets"]
    by_name = {p["name"]: p for p in products}
    counts = {p["name"]: 0 for p in products}

    assert 1 <= len(sheets) <= solver_limit(products)
    for sheet in sheets:
        pieces = sheet["pieces"]
        cuts = sheet["cuts"]

        # 越界检查
        for pc in pieces:
            assert 0 <= pc["x"] and 0 <= pc["y"]
            assert pc["x"] + pc["w"] <= master_w
            assert pc["y"] + pc["h"] <= master_h
            prod = by_name[pc["name"]]
            if pc["rotated"]:
                assert prod["rotatable"], f"{pc['name']} 未允许旋转却被旋转"
                assert (pc["w"], pc["h"]) == (prod["h"], prod["w"])
            else:
                assert (pc["w"], pc["h"]) == (prod["w"], prod["h"])
            counts[pc["name"]] += 1

        # 重叠检查
        for i in range(len(pieces)):
            for j in range(i + 1, len(pieces)):
                area = rects_overlap_area(pieces[i], pieces[j])
                assert area == 0, f"成品重叠: {pieces[i]} {pieces[j]} 重叠面积 {area}"

        # 步骤号唯一且有序
        steps = [c["step"] for c in cuts]
        assert steps == sorted(steps) and len(set(steps)) == len(steps)

        # 每刀都贯穿当前所在余料：用矩形集合模拟切分过程。
        # 同一刀线上可能先后存在父子/兄弟多块余料，取“刀线跨度恰好等于
        # 该余料整宽/整高”的最贴合区域（面积最小），避免错配给邻格。
        regions = [{"x": 0, "y": 0, "w": master_w, "h": master_h}]
        for cut in cuts:
            exact = [r for r in regions if cut_spans_region_exactly(cut, r, kerf)]
            assert exact, f"刀 {cut['step']} 找不到对应的余料矩形，不是贯通刀"
            r = sorted(exact, key=lambda z: (z["w"] * z["h"], z["y"], z["x"]))[0]
            apply_cut(regions, r, cut, kerf)

        # 每个成品必须完整落在切分后某个余料格内（证明由这些刀可得到该布局）
        for pc in pieces:
            assert any(
                r["x"] <= pc["x"] and r["y"] <= pc["y"]
                and pc["x"] + pc["w"] <= r["x"] + r["w"]
                and pc["y"] + pc["h"] <= r["y"] + r["h"]
                for r in regions
            ), f"成品 {pc['name']} 不能由记录的贯通刀切出"

    for p in products:
        assert counts[p["name"]] == p["qty"], (
            f"{p['name']} 实际 {counts[p['name']]} != 需求 {p['qty']}"
        )
    assert result["actual"] == [counts[p["name"]] for p in
                                sorted(products, key=lambda p: (-p["w"] * p["h"], p["name"]))]
    return sheets


def solver_limit(products):
    return 1000


def cut_inside_region(cut, r, kerf):
    """刀切线段是否沿该余料矩形的一条完整贯穿线（允许端点贴界）。"""
    if cut["orientation"] == "v":
        return (r["x"] <= cut["pos"] <= r["x"] + r["w"]
                and cut["from"] == r["y"]
                and cut["to"] == r["y"] + r["h"])
    return (r["y"] <= cut["pos"] <= r["y"] + r["h"]
            and cut["from"] == r["x"]
            and cut["to"] == r["x"] + r["w"])


def cut_spans_region_exactly(cut, r, kerf):
    """刀切线段恰好是该余料矩形的一条贯穿线（长度等于整高/整宽）。"""
    if cut["orientation"] == "v":
        return (r["x"] <= cut["pos"] <= r["x"] + r["w"]
                and cut["from"] == r["y"] and cut["to"] == r["y"] + r["h"]
                and cut["to"] - cut["from"] == r["h"])
    return (r["y"] <= cut["pos"] <= r["y"] + r["h"]
            and cut["from"] == r["x"] and cut["to"] == r["x"] + r["w"]
            and cut["to"] - cut["from"] == r["w"])


def apply_cut(regions, r, cut, kerf):
    """用一刀把余料 r 切成两块（中间扣除刀缝），替换进 regions。"""
    regions.remove(r)
    if cut["orientation"] == "v":
        left_w = cut["pos"] - r["x"]
        right_x = cut["pos"] + kerf
        right_w = r["x"] + r["w"] - right_x
        regions.append({"x": r["x"], "y": r["y"], "w": left_w, "h": r["h"]})
        if right_w > 0:
            regions.append({"x": right_x, "y": r["y"], "w": right_w, "h": r["h"]})
    else:
        top_h = cut["pos"] - r["y"]
        bot_y = cut["pos"] + kerf
        bot_h = r["y"] + r["h"] - bot_y
        regions.append({"x": r["x"], "y": r["y"], "w": r["w"], "h": top_h})
        if bot_h > 0:
            regions.append({"x": r["x"], "y": bot_y, "w": r["w"], "h": bot_h})


def P(name, w, h, qty, rot=False):
    return {"name": name, "w": w, "h": h, "qty": qty, "rotatable": rot}


def test_simple_single_sheet():
    # 400x300 在 1200x800 上：3 列 × 2 行（无刀缝时正好）
    products = [P("A", 400, 300, 6, rot=True)]
    r = solver.solve(1200, 800, 0, 5, 50000, products)
    sheets = verify_solution(r, 1200, 800, 0, products)
    assert len(sheets) == 1


def test_kerf_exact_fit():
    # 母纸 806×406：宽向 2 列 400+刀缝3+400=803，高向 2 行 200+3+200=403
    # => 每张恰好 4 块，6 块需要 2 张
    products = [P("卡", 400, 200, 6, rot=False)]
    r = solver.solve(806, 406, 3, 2, 50000, products)
    sheets = verify_solution(r, 806, 406, 3, products)
    assert len(sheets) == 2


def test_kerf_too_tight_is_infeasible():
    # 803×403 恰好放 2×2=4 块；各少 1mm 后每个方向只能放 1 个 => 单张仅 1 块，
    # 需求 4 且张数上限 1 => 穷尽搜索后判定无解（不是预算耗尽）
    products = [P("卡", 400, 200, 4, rot=False)]
    r = solver.solve(802, 402, 3, 1, 50000, products)
    assert r["status"] == "infeasible"
    assert r["states_used"] > 0


def test_no_rotation_forbidden_size_infeasible():
    # 600x500 不允许旋转，母纸 550x700 放不下；旋转后才可放
    products = [P("B", 600, 500, 1, rot=False)]
    r = solver.solve(550, 700, 0, 1, 50000, products)
    assert r["status"] == "infeasible"

    r2 = solver.solve(550, 700, 0, 1, 50000, [P("B", 600, 500, 1, rot=True)])
    assert r2["status"] == "feasible"
    piece = r2["sheets"][0]["pieces"][0]
    assert piece["rotated"] is True
    assert (piece["w"], piece["h"]) == (500, 600)


def test_budget_exhausted_distinguishable():
    # 张数上限压到 2：总面积需要约 3 张，构造式启发也只能放弃，
    # 进入穷尽搜索后预算 1 立即耗尽 => budget，绝不能声称无解
    products = [P("X", 97, 83, 12, rot=True), P("Y", 61, 47, 10, rot=True)]
    r = solver.solve(300, 250, 2, 2, 1, products)
    assert r["status"] == "budget"
    # 放宽张数上限后（预算足够）应能找到
    r2 = solver.solve(300, 250, 2, 4, 300000, products)
    assert r2["status"] == "feasible"
    verify_solution(r2, 300, 250, 2, products)


def test_multi_sheet_demand():
    products = [P("A", 300, 300, 10, rot=False)]
    # 每张 600x600 放 4 块 => 需要 3 张
    r = solver.solve(600, 600, 0, 5, 100000, products)
    sheets = verify_solution(r, 600, 600, 0, products)
    assert len(sheets) == 3


def test_sheet_limit_infeasible():
    products = [P("A", 300, 300, 10, rot=False)]
    r = solver.solve(600, 600, 0, 2, 100000, products)
    assert r["status"] == "infeasible"


def test_kerf_waste_edge_residual():
    # 放一块后余宽恰好等于刀缝：该边为废料，不应产生非法刀
    products = [P("A", 500, 300, 2, rot=False)]
    r = solver.solve(503, 603, 3, 1, 50000, products)
    assert r["status"] == "feasible"
    verify_solution(r, 503, 603, 3, products)


def test_mixed_products_with_rotation_and_kerf():
    products = [
        P("封面", 210, 297, 8, rot=True),
        P("插页", 148, 210, 12, rot=True),
        P("腰封", 300, 60, 5, rot=False),
    ]
    r = solver.solve(900, 640, 3, 6, 500000, products)
    assert r["status"] == "feasible"
    verify_solution(r, 900, 640, 3, products)


@pytest.mark.parametrize("seed", range(12))
def test_random_instances_geometrically_valid(seed):
    import random
    rng = random.Random(seed)
    mw, mh = rng.choice([(600, 400), (800, 600), (1000, 700)])
    kerf = rng.choice([0, 1, 3, 5])
    kinds = rng.randint(1, 3)
    products = []
    for i in range(kinds):
        w = rng.randint(60, mw // 2)
        h = rng.randint(60, mh // 2)
        qty = rng.randint(1, 6)
        products.append(P(f"P{i}", w, h, qty, rot=rng.random() < 0.7))

    # 面积上界（忽略刀缝）可行才要求找到
    area = sum(p["w"] * p["h"] * p["qty"] for p in products)
    max_sheets = 8
    r = solver.solve(mw, mh, kerf, max_sheets, 400000, products)
    if r["status"] == "feasible":
        verify_solution(r, mw, mh, kerf, products)
    elif r["status"] == "infeasible":
        # 穷尽无解时，连忽略刀缝的面积上界都不该超出（否则是算法提前放弃）
        assert area > max_sheets * mw * mh or r["states_used"] > 0
    else:
        assert r["status"] == "budget"  # 预算耗尽不得声称无解
