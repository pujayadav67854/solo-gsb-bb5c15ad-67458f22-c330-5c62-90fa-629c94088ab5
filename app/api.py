"""Flask 应用：输入管理、求解、方案查看与裁切单导出。"""

from __future__ import annotations

import hashlib
import json

from flask import Flask, jsonify, request, send_from_directory

from . import db as dbmod
from . import solver
from .validation import validate_inputs


def canonical_hash(clean):
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def enrich_sheets(sheets, kerf):
    """把求解器的刀线描述补充成渲染/导出所需的绝对坐标与文字标签。"""
    for sheet in sheets:
        for cut in sheet["cuts"]:
            if cut["orientation"] == "v":
                cut["from_x"] = cut["to_x"] = cut["pos"]
                cut["from_y"], cut["to_y"] = cut["from"], cut["to"]
                cut["from_label"] = f"({cut['pos']}, {cut['from']})"
                cut["to_label"] = f"({cut['pos']}, {cut['to']})"
            else:
                cut["from_y"] = cut["to_y"] = cut["pos"]
                cut["from_x"], cut["to_x"] = cut["from"], cut["to"]
                cut["from_label"] = f"({cut['from']}, {cut['pos']})"
                cut["to_label"] = f"({cut['to']}, {cut['pos']})"
            cut["label_x"] = (cut["from_x"] + cut["to_x"]) / 2
            cut["label_y"] = (cut["from_y"] + cut["to_y"]) / 2
            cut["kerf"] = kerf


def create_app(db_path=None):
    app = Flask(__name__, static_folder=None)
    dbmod.init_db(db_path)

    def db():
        return dbmod.connect(db_path)

    @app.get("/")
    def index():
        return send_from_directory("static", "index.html")

    @app.get("/static/<path:filename>")
    def static_files(filename):
        return send_from_directory("static", filename)

    @app.get("/api/state")
    def api_state():
        conn = db()
        try:
            return jsonify(dbmod.get_state(conn))
        finally:
            conn.close()

    @app.put("/api/inputs")
    def api_put_inputs():
        clean, errors = validate_inputs(request.get_json(silent=True))
        if errors:
            return jsonify({"ok": False, "errors": errors}), 400
        input_hash = canonical_hash(clean)
        conn = db()
        try:
            version = dbmod.save_inputs(conn, clean, input_hash)
            state = dbmod.get_state(conn)
        finally:
            conn.close()
        return jsonify(
            {
                "ok": True,
                "version": version,
                "input_hash": input_hash,
                "state": state,
            }
        )

    @app.post("/api/solve")
    def api_solve():
        conn = db()
        try:
            state = dbmod.get_state(conn)
            inputs = state["inputs"]
            if inputs is None:
                return jsonify({"ok": False, "error": "尚未保存有效输入，请先填写并保存输入。"}), 400
            version = inputs.pop("version")
            input_hash = inputs.pop("input_hash")

            result = solver.solve(
                master_w=inputs["master_w"],
                master_h=inputs["master_h"],
                kerf=inputs["kerf"],
                max_sheets=inputs["max_sheets"],
                max_states=inputs["max_states"],
                products=inputs["products"],
            )

            if result["status"] == "feasible":
                enrich_sheets(result["sheets"], inputs["kerf"])
                payload = {
                    "inputs": inputs,
                    "sheets": result["sheets"],
                    "actual": result["actual"],
                    "states_used": result["states_used"],
                }
                dbmod.save_solution(conn, version, input_hash, payload)
                state = dbmod.get_state(conn)
                return jsonify({"ok": True, "result_status": "feasible", "state": state})
            # infeasible / budget 均不保存方案；保留已有方案的话也必须已随输入保存失效
            return jsonify(
                {
                    "ok": True,
                    "result_status": result["status"],
                    "reason": result.get("reason"),
                    "states_used": result["states_used"],
                    "state": state,
                }
            )
        finally:
            conn.close()

    @app.get("/api/solution")
    def api_solution():
        conn = db()
        try:
            state = dbmod.get_state(conn)
        finally:
            conn.close()
        return jsonify(state["solution"])

    @app.get("/export")
    def export_html():
        conn = db()
        try:
            state = dbmod.get_state(conn)
            sol = state["solution"]
            if sol is None:
                return render_export_blocked("没有已保存的方案。请先在首页保存输入并搜索到可行方案。")
            if sol["stale"]:
                return render_export_blocked(
                    "方案已失效：方案生成后输入参数被修改过。请使用当前输入重新搜索并保存方案，"
                    "然后再导出裁切单。"
                )
        finally:
            conn.close()
        return render_cut_list(sol)

    return app


def render_export_blocked(message):
    body = (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>无法导出裁切单</title>"
        "<style>body{font-family:sans-serif;max-width:640px;margin:48px auto;padding:0 16px}"
        ".box{border:1px solid #d33;border-left:6px solid #d33;background:#fff5f5;"
        "padding:16px 20px;border-radius:6px;line-height:1.7}</style></head>"
        "<body><h2>无法导出裁切单</h2><div class='box'>" + message +
        "</div><p><a href='/'>← 返回排样页</a></p></body></html>"
    )
    return body, 409


def render_cut_list(sol):
    payload = sol["payload"]
    inputs = payload["inputs"]
    products = inputs["products"]
    data_json = json.dumps(payload, ensure_ascii=False)
    # </script> 转义，防止产品名中的字符破坏内联 JSON
    data_json_safe = data_json.replace("</", "<\\/")

    rows = []
    for i, p in enumerate(products):
        got = payload["actual"][i]
        mark = "✓" if got == p["qty"] else "✗"
        rows.append(
            f"<tr><td>{esc(p['name'])}</td><td>{p['w']}×{p['h']}</td>"
            f"<td>{'可旋转' if p['rotatable'] else '不可旋转'}</td>"
            f"<td>{p['qty']}</td><td>{got}</td><td>{mark}</td></tr>"
        )

    sheet_count = len(payload["sheets"])
    cut_count = sum(len(s["cuts"]) for s in payload["sheets"])

    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>裁切单 v{sol['input_version']}</title>
<style>
  body{{font-family:"PingFang SC","Microsoft YaHei",sans-serif;margin:24px;color:#222}}
  .wrap{{max-width:960px;margin:0 auto}}
  .badge{{display:inline-block;background:#eef3ff;border:1px solid #9db4f0;border-radius:6px;
    padding:8px 14px;margin:4px 8px 4px 0;font-size:14px}}
  .stale{{color:#b00;font-weight:bold}}
  h2{{border-bottom:2px solid #333;padding-bottom:6px}}
  h3{{margin-top:32px}}
  table{{border-collapse:collapse;width:100%;margin:12px 0;font-size:14px}}
  th,td{{border:1px solid #999;padding:6px 10px;text-align:left}}
  th{{background:#f0f0f0}}
  .sheet{{page-break-inside:avoid;margin-bottom:28px}}
  .cuts li{{margin:4px 0;font-size:14px;line-height:1.6}}
  @media print {{.noprint{{display:none}}}}
</style></head>
<body><div class="wrap">
  <div class="noprint"><a href="/">← 返回排样页</a>　<button onclick="window.print()">打印 / 另存为 PDF</button></div>
  <h2>裁切单</h2>
  <div>
    <span class="badge">输入版本号：<b>v{sol['input_version']}</b></span>
    <span class="badge">输入指纹：<code>{esc(sol['input_hash'])}</code></span>
    <span class="badge">方案生成时间：{esc(sol['created_at'])} UTC</span>
  </div>
  <h3>输入参数（版本 v{sol['input_version']}）</h3>
  <table><tr>
    <th>母纸长 (mm)</th><th>母纸宽 (mm)</th><th>刀缝 (mm)</th>
    <th>张数上限</th><th>搜索状态上限</th>
  </tr><tr>
    <td>{inputs['master_w']}</td><td>{inputs['master_h']}</td><td>{inputs['kerf']}</td>
    <td>{inputs['max_sheets']}</td><td>{inputs['max_states']}</td>
  </tr></table>
  <h3>成品需求与实际数量</h3>
  <table><tr>
    <th>成品</th><th>尺寸 (mm)</th><th>旋转</th><th>需求份数</th><th>实际成品数</th><th></th>
  </tr>{''.join(rows)}</table>
  <p>实际用纸 <b>{sheet_count}</b> 张，贯通刀共 <b>{cut_count}</b> 刀，
     搜索状态数 <b>{payload['states_used']}</b>。</p>
  <h3>逐张排样图与裁切步骤</h3>
  <div id="diagrams"></div>
  <script>
  const PLAN = {data_json_safe};
  {RENDERER_JS}
  renderPlans(document.getElementById('diagrams'), PLAN, {{steps: true}});
  </script>
</div></body></html>"""
    return html


def esc(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


RENDERER_JS = r"""
function esc(s) {
  return String(s).replace(/[&<>"]/g, function (c) {
    return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c];
  });
}
function renderPlans(host, plan, opts) {
  opts = opts || {};
  const inp = plan.inputs;
  const MARGIN = 36, LEGEND_H = 26, MAXPX = 560;
  const colors = ['#cfe3ff','#d8f3d0','#ffe7b8','#f5d3e0','#d9f0ef',
                  '#e6dcff','#ffd9c2','#dfe8c8','#cfe8f3','#f0d9e8'];
  host.innerHTML = '';
  plan.sheets.forEach(function(sheet) {
    const w = inp.master_w, h = inp.master_h;
    const scale = Math.min((MAXPX - 2*MARGIN)/w, 3.0);
    const vw = Math.round(w*scale) + 2*MARGIN;
    const vh = Math.round(h*scale) + 2*MARGIN + LEGEND_H;
    let svg = '<svg viewBox="0 0 ' + vw + ' ' + vh + '" width="100%" ' +
      'style="max-width:' + vw + 'px;background:#fafafa;border:1px solid #ccc">' +
      '<rect x="' + MARGIN + '" y="' + MARGIN + '" width="' + Math.round(w*scale) +
      '" height="' + Math.round(h*scale) + '" fill="#fffef5" stroke="#333" stroke-width="2"/>';
    sheet.pieces.forEach(function(pc) {
      const x = MARGIN + pc.x*scale, y = MARGIN + pc.y*scale;
      const pw = Math.max(1, pc.w*scale - 1), ph = Math.max(1, pc.h*scale - 1);
      const c = colors[pc.product_index % colors.length];
      svg += '<rect x="' + x + '" y="' + y + '" width="' + pw + '" height="' + ph +
        '" fill="' + c + '" stroke="#555" stroke-width="1"/>';
      const label = esc(pc.name + (pc.rotated ? ' ↻' : ''));
      if (pw > 34 && ph > 16) {
        const fs = Math.min(13, Math.max(8, Math.min(pw/label.length*1.7, ph/2.2)));
        svg += '<text x="' + (x + pw/2) + '" y="' + (y + ph/2 + fs*0.35) +
          '" text-anchor="middle" font-size="' + fs + '" fill="#222">' + label + '</text>';
      }
    });
    sheet.cuts.forEach(function(cut) {
      const x1 = MARGIN + cut.from_x*scale, y1 = MARGIN + cut.from_y*scale;
      const x2 = MARGIN + cut.to_x*scale, y2 = MARGIN + cut.to_y*scale;
      svg += '<line x1="' + x1 + '" y1="' + y1 + '" x2="' + x2 + '" y2="' + y2 +
        '" stroke="#d23" stroke-width="1.6" stroke-dasharray="6 3"/>';
      const lx = MARGIN + cut.label_x*scale, ly = MARGIN + cut.label_y*scale;
      svg += '<text x="' + lx + '" y="' + ly + '" font-size="10" fill="#d23" ' +
        'text-anchor="middle" font-weight="bold" stroke="#fff" stroke-width="3" ' +
        'paint-order="stroke">' + cut.step + '</text>';
    });
    svg += '<text x="' + MARGIN + '" y="' + (vh - 8) + '" font-size="11" fill="#666">' +
      '第 ' + sheet.index + ' 张　' + w + '×' + h + 'mm　红虚线为贯通刀，数字为全局下刀顺序</text>';
    svg += '</svg>';

    let html = '<div class="sheet"><h4>第 ' + sheet.index + ' 张母纸</h4>' + svg;
    if (opts.steps && sheet.cuts.length) {
      html += '<ol class="cuts">';
      sheet.cuts.forEach(function(cut) {
        const dir = cut.orientation === 'v' ? '竖切' : '横切';
        html += '<li>第 ' + cut.step + ' 刀（' + dir +
          '，刀线 ' + cut.pos + ' mm）：在当前余料上从 ' +
          cut.from_label + ' 贯通到 ' + cut.to_label + '，刀缝 ' + inp.kerf + ' mm</li>';
      });
      html += '</ol>';
    }
    html += '</div>';
    host.insertAdjacentHTML('beforeend', html);
  });
}
"""
