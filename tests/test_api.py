"""校验、持久化、版本失效与导出拒绝的端到端测试。"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api import create_app  # noqa: E402


VALID = {
    "master_w": 900,
    "master_h": 640,
    "kerf": 3,
    "max_sheets": 6,
    "max_states": 300000,
    "products": [
        {"name": "封面", "w": 210, "h": 297, "qty": 4, "rotatable": True},
        {"name": "插页", "w": 148, "h": 210, "qty": 6, "rotatable": False},
    ],
}


@pytest.fixture()
def client(tmp_path):
    db = str(tmp_path / "test.db")
    os.environ["CUTTER_DB"] = db
    app = create_app(db_path=db)
    app.testing = True
    return app.test_client()


def save(client, payload):
    return client.put("/api/inputs", data=json.dumps(payload),
                      content_type="application/json")


def test_invalid_inputs_rejected_not_saved(client):
    bad = dict(VALID)
    bad["master_w"] = 0  # 非正整数
    bad["products"] = [dict(VALID["products"][0]) for _ in range(1)]
    bad["products"][0]["qty"] = -2
    resp = save(client, bad)
    assert resp.status_code == 400
    errs = resp.get_json()["errors"]
    assert any("母纸长" in e for e in errs)
    assert any("份数" in e for e in errs)

    state = client.get("/api/state").get_json()
    assert state["inputs"] is None  # 非法输入没有保存


def test_bool_rejected_as_integer(client):
    bad = dict(VALID, kerf=True)
    resp = save(client, bad)
    assert resp.status_code == 400
    assert any("刀缝" in e for e in resp.get_json()["errors"])


def test_float_and_string_rejected(client):
    bad = dict(VALID, master_w=1200.5, max_sheets="3")
    resp = save(client, bad)
    assert resp.status_code == 400


def test_duplicate_names_and_empty_list_rejected(client):
    bad = dict(VALID)
    bad["products"] = [
        {"name": "A", "w": 100, "h": 100, "qty": 1, "rotatable": False},
        {"name": " a ", "w": 100, "h": 100, "qty": 1, "rotatable": False},
    ]
    assert save(client, bad).status_code == 400

    bad["products"] = []
    assert save(client, bad).status_code == 400


def test_save_solve_export_then_invalidate(client):
    resp = save(client, VALID)
    assert resp.status_code == 200
    v1 = resp.get_json()["version"]
    assert v1 == 1

    resp = client.post("/api/solve")
    data = resp.get_json()
    assert data["ok"] is True
    assert data["result_status"] == "feasible", data

    # 实际成品数满足全部份数
    sol = client.get("/api/solution").get_json()
    assert sol["stale"] is False
    assert sol["input_version"] == 1
    for i, p in enumerate(VALID["products"]):
        assert sol["payload"]["actual"][i] == p["qty"]

    # 导出成功且标明输入版本
    page = client.get("/export")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "输入版本号" in body and "v1" in body

    # 修改任一输入（哪怕是搜索预算）保存 → 版本自增、旧方案立即删除失效
    changed = dict(VALID, max_states=VALID["max_states"] + 1)
    resp = save(client, changed)
    assert resp.get_json()["version"] == 2
    state = client.get("/api/state").get_json()
    assert state["solution"] is None
    sol = client.get("/api/solution").get_json()
    assert sol is None

    # 导出被拒绝（409），不能导出失效/已清除的旧方案
    blocked = client.get("/export")
    assert blocked.status_code == 409
    assert "方案" in blocked.get_data(as_text=True)


def test_infeasible_returns_reason_and_no_solution(client):
    payload = dict(VALID, max_sheets=1)
    # 故意制造面积超过单张
    payload["products"] = [
        {"name": "大", "w": 800, "h": 600, "qty": 2, "rotatable": False}
    ]
    save(client, payload)
    resp = client.post("/api/solve").get_json()
    assert resp["result_status"] == "infeasible"
    assert resp["reason"]
    assert client.get("/api/solution").get_json() is None


def test_budget_status_not_infeasible(client):
    # 张数上限压到 2（总面积需要约 3 张，构造式启发放不下，于是进入穷尽搜索），
    # 状态预算 1 => budget；这不是无解，放宽张数与预算后能成功
    payload = dict(
        VALID,
        master_w=300, master_h=250, kerf=2,
        max_states=1, max_sheets=2,
    )
    payload["products"] = [
        {"name": "X", "w": 97, "h": 83, "qty": 12, "rotatable": True},
        {"name": "Y", "w": 61, "h": 47, "qty": 10, "rotatable": True},
    ]
    save(client, payload)
    resp = client.post("/api/solve").get_json()
    assert resp["result_status"] == "budget"
    # 预算耗尽不是无解：放大张数上限/预算重试可成功
    payload["max_states"] = 300000
    payload["max_sheets"] = 4
    save(client, payload)
    resp = client.post("/api/solve").get_json()
    assert resp["result_status"] == "feasible"


def test_cut_steps_ordered_and_sheet_diagram_data(client):
    save(client, VALID)
    client.post("/api/solve")
    sol = client.get("/api/solution").get_json()
    global_steps = []
    for sheet in sol["payload"]["sheets"]:
        steps = [c["step"] for c in sheet["cuts"]]
        assert steps == sorted(steps)
        global_steps.extend(steps)
        for c in sheet["cuts"]:
            # 渲染字段齐全
            assert {"from_x", "from_y", "to_x", "to_y", "label_x", "label_y",
                    "from_label", "to_label"} <= set(c)
    assert global_steps == list(range(1, len(global_steps) + 1))


def test_export_without_solution_409(client):
    resp = client.get("/export")
    assert resp.status_code == 409
