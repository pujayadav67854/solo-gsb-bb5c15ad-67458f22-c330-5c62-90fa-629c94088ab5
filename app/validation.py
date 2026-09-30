"""输入校验。所有非法输入在此被拒绝，不进入持久化层。"""

from __future__ import annotations

# 合理的服务端上限，防止滥用（单位均为毫米 / 个）
MAX_DIM = 10000
MAX_KERF = 1000
MAX_QTY = 1_000_000
MAX_SHEETS = 1000
MAX_STATES = 100_000_000
MAX_NAME = 40
MAX_PRODUCT_KINDS = 200


def _is_plain_int(v):
    """bool 是 int 的子类，必须明确拒绝。"""
    return isinstance(v, int) and not isinstance(v, bool)


def validate_inputs(data):
    """返回 (clean, errors)。成功时 errors 为空列表。"""
    errors = []

    if not isinstance(data, dict):
        return None, ["请求体必须是 JSON 对象"]

    scalar_fields = {
        "master_w": ("母纸长", 1, MAX_DIM),
        "master_h": ("母纸宽", 1, MAX_DIM),
        "kerf": ("刀缝宽度", 0, MAX_KERF),
        "max_sheets": ("张数上限", 1, MAX_SHEETS),
        "max_states": ("搜索状态数上限", 1, MAX_STATES),
    }
    clean = {}
    for key, (label, lo, hi) in scalar_fields.items():
        v = data.get(key)
        if not _is_plain_int(v):
            kind = "非负整数" if key == "kerf" else "正整数"
            errors.append(f"{label}（{key}）必须是{kind}")
        elif v < lo or v > hi:
            errors.append(f"{label}（{key}）必须在 {lo} 到 {hi} 之间")
        else:
            clean[key] = v

    raw_products = data.get("products")
    if not isinstance(raw_products, list) or len(raw_products) == 0:
        errors.append("成品列表 products 至少要包含一类成品")
        return (clean if not errors else None), errors
    if len(raw_products) > MAX_PRODUCT_KINDS:
        errors.append(f"成品种类最多 {MAX_PRODUCT_KINDS} 种")

    products = []
    seen_names = set()
    for idx, p in enumerate(raw_products):
        where = f"products[{idx + 1}]"
        if not isinstance(p, dict):
            errors.append(f"{where} 必须是对象")
            continue
        name = p.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{where}.name 必须是非空字符串")
        elif len(name.strip()) > MAX_NAME:
            errors.append(f"{where}.name 长度不能超过 {MAX_NAME} 个字符")
        elif name.strip().lower() in seen_names:
            errors.append(f"成品名称重复：{name.strip()}")
        else:
            seen_names.add(name.strip().lower())

        pc = {"name": name.strip() if isinstance(name, str) else ""}
        for key, label in (("w", "长"), ("h", "宽")):
            v = p.get(key)
            if not _is_plain_int(v):
                errors.append(f"{where}.{key}（{label}）必须是正整数")
            elif not (1 <= v <= MAX_DIM):
                errors.append(f"{where}.{key}（{label}）必须在 1 到 {MAX_DIM} 之间")
            else:
                pc[key] = v

        qty = p.get("qty")
        if not _is_plain_int(qty):
            errors.append(f"{where}.qty（份数）必须是正整数")
        elif not (1 <= qty <= MAX_QTY):
            errors.append(f"{where}.qty（份数）必须在 1 到 {MAX_QTY} 之间")
        else:
            pc["qty"] = qty

        rot = p.get("rotatable")
        if not isinstance(rot, bool):
            errors.append(f"{where}.rotatable 必须是 true 或 false")
        else:
            pc["rotatable"] = rot

        if len(pc) == 5:
            products.append(pc)

    if errors:
        return None, errors
    clean["products"] = products
    return clean, []
