"""贯通式（guillotine / slicing）矩形排样搜索器。

约束：
* 每一刀都沿直线贯穿当前所在的余料矩形；
* 刀缝（kerf）占用材料，相邻区域之间要扣除 kerf 毫米；
* 成品之间不得重叠、不得越界；
* 成品只有在 rotatable=True 时才可旋转 90 度。

算法：在每个矩形余料的左上角放入一块成品，先竖切或先横切把
L 形剩余区域切成两个矩形，递归填充；也允许整块余料留空
（仅用于子矩形，母纸不允许整张贴空）。该结构可枚举所有
slicing floorplan（可由贯通刀得到的排样），因此配合预算
可以区分“已穷尽的无解”与“预算耗尽”。

递归结果是一棵切分树；刀的执行顺序由树的前序遍历给出
（先在当前余料上下刀，再依次递归处理切出的各块余料）。

只要求找到可行方案，不做最优性保证。
"""

from __future__ import annotations

from dataclasses import dataclass


class BudgetExhausted(Exception):
    """搜索状态数超过预算时抛出。"""


@dataclass(frozen=True)
class Product:
    name: str
    w: int
    h: int
    qty: int
    rotatable: bool


def solve(master_w, master_h, kerf, max_sheets, max_states, products):
    """执行搜索。

    返回 dict：
      feasible:  {status, sheets, actual, states_used}
      infeasible:{status, reason, states_used}
      budget:    {status, states_used}
    """
    prods = sorted(
        (
            Product(
                name=str(p["name"]).strip(),
                w=int(p["w"]),
                h=int(p["h"]),
                qty=int(p["qty"]),
                rotatable=bool(p["rotatable"]),
            )
            for p in products
        ),
        key=lambda p: (-p.w * p.h, p.name),
    )
    n = len(prods)
    demand0 = tuple(p.qty for p in prods)

    # —— 廉价的必要条件检查 ——
    for p in prods:
        fits = (p.w <= master_w and p.h <= master_h) or (
            p.rotatable and p.h <= master_w and p.w <= master_h
        )
        if not fits:
            return {
                "status": "infeasible",
                "reason": f"成品「{p.name}」{p.w}×{p.h}mm 无论是否旋转都无法放入母纸 {master_w}×{master_h}mm",
                "states_used": 0,
            }

    total_area = sum(p.w * p.h * p.qty for p in prods)
    if total_area > max_sheets * master_w * master_h:
        return {
            "status": "infeasible",
            "reason": "成品总面积超过全部母纸可用面积上限（未计刀缝损耗，仍超过）",
            "states_used": 0,
        }

    states = [0]
    dead: set = set()  # 已证明无法填满的 (w,h,demand,allow_waste)

    def orientations(i):
        p = prods[i]
        if p.rotatable and p.w != p.h:
            return ((p.w, p.h, False), (p.h, p.w, True))
        return ((p.w, p.h, False),)

    def node(piece, cuts, children):
        """构造切分树节点。

        piece    左上角那块成品（dict）
        cuts     在当前余料上、按执行顺序的 0..2 刀（绝对坐标，尚未编号）
        children 切出的兄弟余料对应的子树（递归填充），按裁切先后排列
        """
        return {"piece": piece, "cuts": cuts, "children": children}

    def gen_fill(w, h, x0, y0, demand, allow_waste):
        """在 (x0,y0) 处 w×h 的矩形内填充。

        生成 (root_node, demand_after)；root_node 为 None 表示整块留空。
        """
        if not any(demand):
            yield (None, demand)
            return

        states[0] += 1
        if states[0] > max_states:
            raise BudgetExhausted()

        key = (w, h, demand, allow_waste)
        if key in dead:
            return

        yielded = [False]

        def emit(root, dem):
            yielded[0] = True
            return ((root, dem),)

        completed = False
        try:
            # 依次尝试每种成品的每个朝向（大块优先，不旋转优先）
            for i in range(n):
                if demand[i] <= 0:
                    continue
                for pw, ph, rotated in orientations(i):
                    if pw > w or ph > h:
                        continue
                    rem = list(demand)
                    rem[i] -= 1
                    rem = tuple(rem)
                    piece = {
                        "product_index": i,
                        "name": prods[i].name,
                        "x": x0,
                        "y": y0,
                        "w": pw,
                        "h": ph,
                        "rotated": rotated,
                    }

                    rw, rh = w - pw, h - ph  # 右侧/上方剩余（含刀缝位）

                    # 1) 残余两个方向都 <= 刀缝：无法再下刀，成品独占此格
                    if rw <= kerf and rh <= kerf:
                        yield from emit(node(piece, [], []), rem)
                        continue

                    # 2) 先竖切：竖刀 x=x0+pw 贯穿当前矩形全高。
                    #    仅当右侧存在可用余料（rw>kerf）时才需要这一刀；
                    #    rw==kerf（右条整条废料）时改走第 3 分支的全宽横刀。
                    if rw > kerf:
                        vcut = {
                            "orientation": "v",
                            "pos": x0 + pw,
                            "from": y0,
                            "to": y0 + h,
                        }
                        right_rect = (rw - kerf, h, x0 + pw + kerf, y0)
                        if rh > kerf:
                            # 第二刀在左列横切（仅跨左列），随后两块兄弟余料
                            hcut = {
                                "orientation": "h",
                                "pos": y0 + ph,
                                "from": x0,
                                "to": x0 + pw,
                            }
                            lower_rect = (pw, rh - kerf, x0, y0 + ph + kerf)
                            for rnode, d1 in gen_fill(*right_rect, rem, True):
                                for lnode, d2 in gen_fill(*lower_rect, d1, True):
                                    children = [c for c in (rnode, lnode) if c]
                                    yield from emit(
                                        node(piece, [vcut, hcut], children), d2
                                    )
                        else:
                            # 下方是 <= 刀缝的废料边：一刀竖切后只剩右侧兄弟
                            for rnode, d1 in gen_fill(*right_rect, rem, True):
                                children = [rnode] if rnode else []
                                yield from emit(
                                    node(piece, [vcut], children), d1
                                )

                    # 3) 先横切：横刀 y=y0+ph 贯穿当前矩形全宽
                    if rh > kerf:
                        hcut = {
                            "orientation": "h",
                            "pos": y0 + ph,
                            "from": x0,
                            "to": x0 + w,
                        }
                        top_rect = (w, rh - kerf, x0, y0 + ph + kerf)
                        if rw > kerf:
                            # 第二刀在底排竖切（仅跨底排），随后两块兄弟余料
                            vcut = {
                                "orientation": "v",
                                "pos": x0 + pw,
                                "from": y0,
                                "to": y0 + ph,
                            }
                            right_rect = (rw - kerf, ph, x0 + pw + kerf, y0)
                            for tnode, d1 in gen_fill(*top_rect, rem, True):
                                for rnode, d2 in gen_fill(*right_rect, d1, True):
                                    children = [c for c in (tnode, rnode) if c]
                                    yield from emit(
                                        node(piece, [hcut, vcut], children), d2
                                    )
                        else:
                            # 右方 <= 刀缝废料边：横刀已贯穿全宽一并切开
                            for tnode, d1 in gen_fill(*top_rect, rem, True):
                                children = [tnode] if tnode else []
                                yield from emit(
                                    node(piece, [hcut], children), d1
                                )
                    elif rw > kerf:
                        # 上余料高度恰好等于刀缝（整条废料）：不横切，
                        # 竖刀贯穿整个父矩形把成品与右侧可用余料分开
                        vcut = {
                            "orientation": "v",
                            "pos": x0 + pw,
                            "from": y0,
                            "to": y0 + h,
                        }
                        right_rect = (rw - kerf, ph, x0 + pw + kerf, y0)
                        for rnode, d2 in gen_fill(*right_rect, rem, True):
                            children = [rnode] if rnode else []
                            yield from emit(node(piece, [vcut], children), d2)

            # 4) 整块矩形留作废料（仅子矩形允许；用于消化不可避免的浪费）
            if allow_waste:
                yield from emit(None, demand)

            completed = True
        finally:
            # 只有自然枚举完毕且一无所获时才记入 dead；
            # 预算耗尽 / 外部提前关闭时不标记，以免漏判可行解。
            if completed and not yielded[0]:
                dead.add(key)

    def flatten(root, pieces, cuts):
        """前序遍历切分树：收集成品，并按真实下刀顺序导出刀。
        内部“只下刀”节点的 piece 为 None，用于挂多个兄弟子树。"""
        if root is None:
            return
        if root["piece"] is not None:
            pieces.append(root["piece"])
        cuts.extend(root["cuts"])
        for child in root["children"]:
            flatten(child, pieces, cuts)

    def best_fill(w, h, x0, y0, demand, prefer):
        """确定性单路填充：在当前矩形左上角放“面积最大的可放块”，
        切向优先选择与矩形长宽方向更匹配者；子区域填不下则留空。
        几何分支与 gen_fill 严格对称，因此产出的切分树/刀序天然合法。
        返回 (root_node|None, demand_after)。不消耗搜索状态预算。"""
        if not any(demand):
            return None, demand
        chosen = None  # (area, i, pw, ph, rotated)
        for i in range(n):
            if demand[i] <= 0:
                continue
            for pw, ph, rotated in orientations(i):
                if pw <= w and ph <= h:
                    cand = (pw * ph, i, pw, ph, rotated)
                    if chosen is None or cand[0] > chosen[0]:
                        chosen = cand
        if chosen is None:
            return None, demand  # 此整块留作废料

        _, i, pw, ph, rotated = chosen
        rem = list(demand)
        rem[i] -= 1
        rem = tuple(rem)
        piece = {
            "product_index": i,
            "name": prods[i].name,
            "x": x0,
            "y": y0,
            "w": pw,
            "h": ph,
            "rotated": rotated,
        }
        rw, rh = w - pw, h - ph

        if rw <= kerf and rh <= kerf:
            return node(piece, [], []), rem

        # 选择先竖切还是先横切：哪边的“主余料”更贴合选哪边
        can_v = rw > kerf
        can_h = rh > kerf
        if can_v and can_h:
            # 竖向余料更宽（适合继续横排）时优先竖切，由 prefer 决定同分时倾向
            v_fit = rw * h
            h_fit = rh * w
            go_v = (v_fit >= h_fit) if prefer == "v" else (v_fit > h_fit)
        else:
            go_v = can_v

        if go_v and can_v:
            vcut = {
                "orientation": "v",
                "pos": x0 + pw,
                "from": y0,
                "to": y0 + h,
            }
            rnode, d1 = best_fill(rw - kerf, h, x0 + pw + kerf, y0, rem, prefer)
            if rh > kerf:
                hcut = {
                    "orientation": "h",
                    "pos": y0 + ph,
                    "from": x0,
                    "to": x0 + pw,
                }
                lnode, d2 = best_fill(pw, rh - kerf, x0, y0 + ph + kerf, d1, prefer)
                children = [c for c in (rnode, lnode) if c]
                return node(piece, [vcut, hcut], children), d2
            children = [rnode] if rnode else []
            return node(piece, [vcut], children), d1

        if can_h:
            hcut = {
                "orientation": "h",
                "pos": y0 + ph,
                "from": x0,
                "to": x0 + w,
            }
            tnode, d1 = best_fill(w, rh - kerf, x0, y0 + ph + kerf, rem, prefer)
            if rw > kerf:
                vcut = {
                    "orientation": "v",
                    "pos": x0 + pw,
                    "from": y0,
                    "to": y0 + ph,
                }
                rnode, d2 = best_fill(rw - kerf, ph, x0 + pw + kerf, y0, d1, prefer)
                children = [c for c in (tnode, rnode) if c]
                return node(piece, [hcut, vcut], children), d2
            children = [tnode] if tnode else []
            return node(piece, [hcut], children), d1

        # rh<=kerf 但 rw>kerf：上方整条废料，竖刀贯穿全高
        vcut = {
            "orientation": "v",
            "pos": x0 + pw,
            "from": y0,
            "to": y0 + h,
        }
        rnode, d2 = best_fill(rw - kerf, ph, x0 + pw + kerf, y0, rem, prefer)
        children = [rnode] if rnode else []
        return node(piece, [vcut], children), d2

    def greedy_best(dem, prefer):
        """逐张母纸调用 best_fill，直到满足全部需求或超出张数上限。"""
        remaining = tuple(dem)
        roots = []
        while any(remaining):
            if len(roots) >= max_sheets:
                return None
            root, remaining = best_fill(master_w, master_h, 0, 0, remaining, prefer)
            if root is None:
                return None
            roots.append(root)
        return roots

    def _finalize_sheets(sheets):
        """给刀全局编号、统计实际成品数，组装 feasible 返回值。"""
        actual = [0] * n
        step = 0
        for si, sheet in enumerate(sheets):
            sheet.pop("_root", None)
            for cut in sheet["cuts"]:
                step += 1
                cut["step"] = step
                cut["sheet"] = si + 1
            for pc in sheet["pieces"]:
                actual[pc["product_index"]] += 1
            sheet["index"] = si + 1
        return {
            "status": "feasible",
            "sheets": sheets,
            "actual": actual,
            "states_used": states[0],
        }

    prod_area = [p.w * p.h for p in prods]
    master_area = master_w * master_h

    def remaining_area(dem):
        return sum(prod_area[i] * dem[i] for i in range(n))

    # —— 快速构造式启发：等高货架（shelf）排样 ——
    # 每张母纸按水平货架切分；同一货架内成品高度一致、横向阶梯排列。
    # 全部刀都是贯通刀（横刀贯穿母纸全宽，竖刀贯穿货架全高）。
    # 只是“先试一条容易命中的路”，失败仍回退到完整穷尽搜索。
    def heuristic(dem):
        """两种货架策略都尝试：按货架高度降序 / 按单块面积降序锚定。

        货架内每次选当前行放得下的最大宽度朝向，以减少横向浪费。
        任何一个策略在张数上限内满足全部需求即采用，否则返回 None
        交给完整穷尽搜索。
        """

        def run_strategy(mode):
            remaining = list(dem)
            roots = []

            def fits_orientations(i, avail_h):
                return [
                    (w0, h0, rot)
                    for w0, h0, rot in orientations(i)
                    if w0 <= master_w and h0 <= avail_h
                ]

            while any(remaining):
                if len(roots) >= max_sheets:
                    return None
                y = 0
                top_shelf = None
                avail_h = master_h
                made = False

                while any(remaining) and avail_h > 0:
                    # 锚定货架高度
                    choice = None  # (rank, width, height, i, rot)
                    for i in range(n):
                        if remaining[i] <= 0:
                            continue
                        for w0, h0, rot in fits_orientations(i, avail_h):
                            if mode == "height":
                                rank = h0
                            else:
                                rank = w0 * h0
                            cand = (rank, w0, h0, i, rot)
                            if choice is None or cand[0] > choice[0]:
                                choice = cand
                    if choice is None:
                        break
                    _, _, bh, _, _ = choice

                    # 横向填充货架：在高度恰为 bh 的前提下，逐格选最宽可放朝向
                    x = 0
                    band_pieces = []
                    while True:
                        best = None  # (width, index, rotated)
                        for i in range(n):
                            if remaining[i] <= 0:
                                continue
                            for w0, h0, rot in orientations(i):
                                if h0 == bh and w0 <= master_w - x:
                                    if best is None or w0 > best[0]:
                                        best = (w0, i, rot)
                        if best is None:
                            break
                        w0, i, rot = best
                        band_pieces.append((i, w0, bh, rot, x))
                        x += w0 + kerf
                        remaining[i] -= 1

                    if not band_pieces:
                        break

                    # 货架内阶梯（竖切）链
                    band_root = None
                    for i, w0, h0, rot, px in reversed(band_pieces):
                        pc = {
                            "product_index": i,
                            "name": prods[i].name,
                            "x": px,
                            "y": y,
                            "w": w0,
                            "h": h0,
                            "rotated": rot,
                        }
                        cuts = []
                        children = []
                        if band_root is not None:
                            cuts.append({
                                "orientation": "v",
                                "pos": px + w0,
                                "from": y,
                                "to": y + bh,
                            })
                            children.append(band_root)
                        band_root = {"piece": pc, "cuts": cuts, "children": children}

                    shelf_children = [band_root]
                    shelf_cuts = []
                    if top_shelf is not None or avail_h > bh:
                        shelf_cuts.append({
                            "orientation": "h",
                            "pos": y + bh,
                            "from": 0,
                            "to": master_w,
                        })
                        if top_shelf is not None:
                            shelf_children = [top_shelf, band_root]
                    top_shelf = {
                        "piece": None,
                        "cuts": shelf_cuts,
                        "children": shelf_children,
                    }
                    made = True

                    avail_h -= bh
                    if avail_h <= kerf:
                        avail_h = 0
                    else:
                        avail_h -= kerf
                    y += bh + kerf

                if not made:
                    return None
                roots.append(top_shelf)
                if any(remaining) and avail_h > 0:
                    return None  # 纸内还有高度却放不下，放弃此策略（避免漏需求）

            return roots if not any(remaining) else None

        for mode in ("height", "area"):
            result = run_strategy(mode)
            if result is not None:
                return result
        return None

    def _try_roots(quick_roots):
        if quick_roots is None:
            return None
        sheets = []
        for root in quick_roots:
            pieces, cuts = [], []
            flatten(root, pieces, cuts)
            sheets.append({"pieces": pieces, "cuts": cuts, "_root": root})
        if not _quick_layouts_valid(sheets):
            return None  # 快速路径自检不过：宁可不命中，也绝不返回错方案
        return _finalize_sheets(sheets)

    def _quick_layouts_valid(sheets):
        """快速构造方案的独立自检：成品不重叠/不越界/朝向合法，
        且每一刀在切分时刻都贯穿对应的当前余料矩形。"""
        for sheet in sheets:
            pieces, cuts = sheet["pieces"], sheet["cuts"]
            for pc in pieces:
                if pc["x"] < 0 or pc["y"] < 0:
                    return False
                if pc["x"] + pc["w"] > master_w or pc["y"] + pc["h"] > master_h:
                    return False
                p = prods[pc["product_index"]]
                if pc["rotated"]:
                    if not p.rotatable or (pc["w"], pc["h"]) != (p.h, p.w):
                        return False
                elif (pc["w"], pc["h"]) != (p.w, p.h):
                    return False
            for a in range(len(pieces)):
                for b in range(a + 1, len(pieces)):
                    pa, pb = pieces[a], pieces[b]
                    if (min(pa["x"] + pa["w"], pb["x"] + pb["w"]) - max(pa["x"], pb["x"]) > 0
                            and min(pa["y"] + pa["h"], pb["y"] + pb["h"]) - max(pa["y"], pb["y"]) > 0):
                        return False
            regions = [{"x": 0, "y": 0, "w": master_w, "h": master_h}]
            for cut in cuts:
                def spans(r):
                    if cut["orientation"] == "v":
                        return (r["x"] <= cut["pos"] <= r["x"] + r["w"]
                                and cut["from"] == r["y"] and cut["to"] == r["y"] + r["h"]
                                and cut["to"] - cut["from"] == r["h"])
                    return (r["y"] <= cut["pos"] <= r["y"] + r["h"]
                            and cut["from"] == r["x"] and cut["to"] == r["x"] + r["w"]
                            and cut["to"] - cut["from"] == r["w"])
                exact = [r for r in regions if spans(r)]
                if not exact:
                    return False
                r = sorted(exact, key=lambda z: (z["w"] * z["h"], z["y"], z["x"]))[0]
                regions.remove(r)
                if cut["orientation"] == "v":
                    regions.append({"x": r["x"], "y": r["y"], "w": cut["pos"] - r["x"], "h": r["h"]})
                    rw2 = r["x"] + r["w"] - (cut["pos"] + kerf)
                    if rw2 > 0:
                        regions.append({"x": cut["pos"] + kerf, "y": r["y"], "w": rw2, "h": r["h"]})
                else:
                    regions.append({"x": r["x"], "y": r["y"], "w": r["w"], "h": cut["pos"] - r["y"]})
                    bh2 = r["y"] + r["h"] - (cut["pos"] + kerf)
                    if bh2 > 0:
                        regions.append({"x": r["x"], "y": cut["pos"] + kerf, "w": r["w"], "h": bh2})
        return True

    # 快速可行解尝试（不消耗搜索状态预算，失败再走完整穷尽）：
    # 确定性 best-fill（竖切/横切两种偏好）+ 等高货架（高度/面积两种锚定）。
    # 每条都经 _quick_layouts_valid 独立自检，宁可不命中也不返回错方案。
    for quick in (
        lambda: greedy_best(demand0, "v"),
        lambda: greedy_best(demand0, "h"),
        lambda: heuristic(demand0),
    ):
        found = _try_roots(quick())
        if found is not None:
            return found

    # —— 逐张母纸驱动（完整穷尽） ——
    def fill_sheets(dem, used, sheets):
        if not any(dem):
            return sheets
        if used >= max_sheets:
            return None
        if remaining_area(dem) > (max_sheets - used) * master_area:
            return None
        for root, dem_after in gen_fill(master_w, master_h, 0, 0, dem, False):
            if root is None:
                continue  # 母纸不允许整张贴空
            pieces, cuts = [], []
            flatten(root, pieces, cuts)
            sheets.append({"pieces": pieces, "cuts": cuts, "_root": root})
            result = fill_sheets(dem_after, used + 1, sheets)
            if result is not None:
                return result
            sheets.pop()
        return None

    try:
        sheets = fill_sheets(demand0, 0, [])
    except BudgetExhausted:
        return {"status": "budget", "states_used": states[0]}

    if sheets is None:
        return {
            "status": "infeasible",
            "reason": f"已在 {states[0]} 个搜索状态内穷尽：{max_sheets} 张母纸内无法满足全部份数（含刀缝损耗）",
            "states_used": states[0],
        }

    return _finalize_sheets(sheets)
