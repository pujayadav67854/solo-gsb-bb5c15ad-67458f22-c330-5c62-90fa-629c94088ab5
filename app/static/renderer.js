/* 排样图与裁切步骤渲染（首页与 /export 导出页共用）。
   依赖的 plan 结构：{inputs:{master_w,master_h,kerf,...}, sheets:[{index,pieces[],cuts[]}]} */
function renderPlans(host, plan, opts) {
  opts = opts || {};
  const inp = plan.inputs;
  const MARGIN = 36, LEGEND_H = 26, MAXPX = 560;
  const colors = ['#cfe3ff', '#d8f3d0', '#ffe7b8', '#f5d3e0', '#d9f0ef',
                  '#e6dcff', '#ffd9c2', '#dfe8c8', '#cfe8f3', '#f0d9e8'];

  function esc(s) {
    return String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  }

  host.innerHTML = '';
  plan.sheets.forEach(function (sheet) {
    const w = inp.master_w, h = inp.master_h;
    const scale = Math.min((MAXPX - 2 * MARGIN) / w, 3.0);
    const vw = Math.round(w * scale) + 2 * MARGIN;
    const vh = Math.round(h * scale) + 2 * MARGIN + LEGEND_H;
    let svg = '<svg viewBox="0 0 ' + vw + ' ' + vh + '" width="100%" ' +
      'style="max-width:' + vw + 'px;background:#fafafa;border:1px solid #ccc">' +
      '<rect x="' + MARGIN + '" y="' + MARGIN + '" width="' + Math.round(w * scale) +
      '" height="' + Math.round(h * scale) + '" fill="#fffef5" stroke="#333" stroke-width="2"/>';

    sheet.pieces.forEach(function (pc) {
      const x = MARGIN + pc.x * scale, y = MARGIN + pc.y * scale;
      const pw = Math.max(1, pc.w * scale - 1), ph = Math.max(1, pc.h * scale - 1);
      const c = colors[pc.product_index % colors.length];
      svg += '<rect x="' + x + '" y="' + y + '" width="' + pw + '" height="' + ph +
        '" fill="' + c + '" stroke="#555" stroke-width="1"/>';
      const label = esc(pc.name) + (pc.rotated ? ' ↻' : '');
      if (pw > 34 && ph > 16) {
        const fs = Math.min(13, Math.max(8, Math.min(pw / label.length * 1.7, ph / 2.4)));
        svg += '<text x="' + (x + pw / 2) + '" y="' + (y + ph / 2 + fs * 0.35) +
          '" text-anchor="middle" font-size="' + fs + '" fill="#222">' + label + '</text>';
      }
    });

    sheet.cuts.forEach(function (cut) {
      const x1 = MARGIN + cut.from_x * scale, y1 = MARGIN + cut.from_y * scale;
      const x2 = MARGIN + cut.to_x * scale, y2 = MARGIN + cut.to_y * scale;
      svg += '<line x1="' + x1 + '" y1="' + y1 + '" x2="' + x2 + '" y2="' + y2 +
        '" stroke="#d23" stroke-width="1.6" stroke-dasharray="6 3"/>';
      const lx = MARGIN + cut.label_x * scale, ly = MARGIN + cut.label_y * scale;
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
      sheet.cuts.forEach(function (cut) {
        const dir = cut.orientation === 'v' ? '竖切' : '横切';
        html += '<li>第 ' + cut.step + ' 刀（' + dir + '，刀线 ' + cut.pos +
          ' mm）：在当前余料上从 ' + cut.from_label + ' 贯通到 ' + cut.to_label +
          '，刀缝 ' + inp.kerf + ' mm</li>';
      });
      html += '</ol>';
    }
    html += '</div>';
    host.insertAdjacentHTML('beforeend', html);
  });
}
