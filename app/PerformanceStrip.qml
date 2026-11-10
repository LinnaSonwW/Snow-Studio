// PerformanceStrip.qml — 演奏谱横幅 (QML-2, 谱面化 2026-09-08): 白底黑网格,
// 车道/字母标签/网格/小节号行。只读渲染: 输入不进入本场景
// (QQuickWidget WA_TransparentForMouseEvents), 滚轮/写入 全部留在
// Python ScoreStrip 层。
// 规格: 节奏由字母水平间距表达 (lead sheet, 不锁死时值观感);
// (演奏谱重设计一期 2026-09-26) 时间刻度尺取消 → 顶部 20px 行 = 小节号行
// (只画小节线+小节号, 无拍线/速度标记; 速度编辑走卷帘标尺右键与 Tempo 车道);
// 蓝线/首尾圆点删除 → 音符时值改由亮起动效时长表达 (durMs 驱动);
// 演奏中方块点亮带外圈柔光复制层 + 蓝字 = 当前演奏; 红字 = 不可演奏;
// 全部经 bridge 属性绑定 (Scene Graph 增量, 无逐帧 Python)。
// (多排轮 2026-09-16) 渲染体抽成 StripRow 行组件: root 按 bridge.rows 纵向
// 堆叠 N 排, 第 r 排视野 = viewTick + r*pageTicks (同一份组件, 编辑器宿主
// rows=1 渲染结果与旧版逐像素等价; 悬浮窗 N 排 = 用户要的「全谱」)。
import QtQuick

Item {
    id: root
    clip: true

    // ---- 桥注入 (ScoreStrip.update → bridge.push; 值不变零代价) ----
    readonly property real vt: bridge ? bridge.viewTick : 0
    readonly property real ppt: bridge ? bridge.pxPerTick : 0.1
    readonly property int kbW: bridge ? bridge.kbW : 64
    // 透明皮肤: 背景/小节号行/轨名列底透明, 音符与轨名照常不透明
    readonly property bool clear: bridge ? bridge.skinClear : false
    readonly property int rulerH: 20
    readonly property int rows: bridge ? Math.max(1, bridge.rows) : 1
    readonly property real pageTicks: bridge ? bridge.pageTicks : 3840
    readonly property real rowH: height / rows
    // 测试可观测性: 外层 Repeater 实际实例化的排数 / 第 i 排视野首
    readonly property alias rowsCount: rep.count
    property real lastRowVt: -1
    function rowVtAt(i) {
        var it = rep.itemAt(i)
        lastRowVt = it ? it.rowVt : -1
        return lastRowVt
    }

    // ---- 帧级平滑播放时钟 phs: Python 每 40ms 推一次 playheadTick (25Hz 阶梯),
    // 逐帧按实测 tick/ms 速率外推 (≤90ms 防过冲), 单调不回跳; 跳播/停止直接吸附。
    // 帧动画不推进 (离屏测试) 时 phs 恒等于 playheadTick
    property real phs: -1
    property real _anchor: -1
    property real _anchorMs: 0
    property real _rate: 0
    property bool _ticked: false
    readonly property real _rawPh: bridge ? bridge.playheadTick : -1
    on_RawPhChanged: {
        var now = Date.now(), t = _rawPh
        if (t < 0) { _anchor = t; _rate = 0; phs = t; return }
        var dt = now - _anchorMs, dTk = t - _anchor
        if (_anchor >= 0 && dt > 5 && dt < 400 && dTk > 0) {
            var inst = dTk / dt
            // 跳播/拖动 ≠ 播放速度: 离群采样 (>4× 现速或 >20 tick/ms) 不入估计并停外推
            if (inst <= 20 && (_rate <= 0 || inst <= _rate * 4))
                _rate = _rate > 0 ? _rate * 0.7 + inst * 0.3 : inst
            else
                _rate = 0
        } else if (dTk < 0 || dt >= 400) {
            _rate = 0                        // 回跳/长停顿: 重新测速
        }
        // 外推领先量上限 = 本次采样间隔内应走的量 (再宽 50%), 超出即视为跳播直接吸附
        var keep = _ticked && _rate > 0 && t <= phs
            && phs - t <= _rate * Math.min(90, Math.max(0, dt)) * 1.5
        _anchor = t; _anchorMs = now; _ticked = false
        if (!keep) phs = t
    }
    FrameAnimation {
        running: root._anchor >= 0 && root._rate > 0
        onTriggered: {
            var el = Math.min(90, Date.now() - root._anchorMs)
            var tgt = root._anchor + root._rate * el
            if (tgt > root.phs) root.phs = tgt
            root._ticked = true
        }
    }

    Rectangle { anchors.fill: parent; color: root.clear ? "transparent" : pal.bg }

    // ---- 每排渲染 (一行 = 迷你刻度行 + 车道 + 排内播放头, 时间窗按排偏移) ----
    component StripRow: Item {
        id: row
        objectName: 'stripRow'
        clip: true
        property int rowIndex: 0
        // 本排时间窗首 (tick): 跟随/翻页模式 = 页首对齐; 手动模式连续排页
        readonly property real rowVt: root.vt + rowIndex * root.pageTicks
        readonly property real laneH:
            (height - root.rulerH) / Math.max(1, bridge ? bridge.laneCount : 1)
        readonly property bool first: rowIndex === 0

        // ---- 1. 网格 + 刻度行 (Canvas; 视图/速度/车道变化时重画) ----
        Canvas {
            id: grid
            anchors.fill: parent
            onPaint: {
                var ctx = getContext('2d')
                ctx.clearRect(0, 0, width, height)
                if (!bridge) return
                var vt = row.rowVt, ppt = root.ppt
                var bt = bridge.barTicks
                var RH = root.rulerH, KB = root.kbW
                var t0 = Math.max(vt, 0), t1 = vt + (width - KB) / ppt
                // 小节号行底 (演奏谱重设计一期: 刻度行 → 小节号行)
                if (!root.clear) {
                    ctx.fillStyle = pal.rulerFill
                    ctx.fillRect(0, 0, width, RH)
                }
                ctx.strokeStyle = pal.sep
                ctx.beginPath(); ctx.moveTo(0, RH + 0.5); ctx.lineTo(width, RH + 0.5); ctx.stroke()
                // (小节谱轮) 列布局: 小节线/小节号按 Python 页表逐小节画
                // (x 为列数×列宽的累计像素, 非 tick×ppt; 无拍线)
                if (bridge.colMode === true) {
                    var brr = bridge.barsByRow
                    var bars = (brr && brr.length > rowIndex) ? brr[rowIndex] : null
                    ctx.lineWidth = 1
                    ctx.strokeStyle = pal.bar
                    ctx.beginPath()
                    if (bars) for (var g1 = 0; g1 < bars.length; g1++) {
                        var xg = Math.round(KB + bars[g1][0]) + 0.5
                        if (xg >= KB - 1 && xg <= width + 1)
                            { ctx.moveTo(xg, RH + 0.5); ctx.lineTo(xg, height) }
                    }
                    ctx.stroke()
                    ctx.fillStyle = pal.barNo
                    ctx.font = '8pt "Segoe UI"'
                    ctx.textBaseline = 'middle'
                    if (bars) for (var g2 = 0; g2 < bars.length; g2++) {
                        var xn4 = KB + bars[g2][0]
                        if (xn4 >= KB - 20 && xn4 <= width)
                            ctx.fillText(String(bars[g2][1]), xn4 + 3, RH / 2)
                    }
                    return
                }
                // 小节线 (车道段) + 小节号
                // (二期) 多段拍号: 小节线按 barStarts 表逐段绘制 (段边界=小节线)
                var segStarts = (bridge.barStarts && bridge.barStarts.length > 0)
                    ? bridge.barStarts : null
                var barPx = bt * ppt
                ctx.lineWidth = 1
                ctx.strokeStyle = pal.bar
                ctx.beginPath()
                if (segStarts) {
                    for (var si = 0; si < segStarts.length; si++) {
                        var xm2 = Math.round(KB + (segStarts[si][0] - vt) * ppt) + 0.5
                        if (xm2 >= KB - 1 && xm2 <= width + 1)
                            { ctx.moveTo(xm2, RH + 0.5); ctx.lineTo(xm2, height) }
                    }
                } else {
                    var t = Math.floor(t0 / bt) * bt
                    while (t <= t1 + bt) {
                        var xm1 = Math.round(KB + (t - vt) * ppt) + 0.5
                        if (xm1 >= KB) { ctx.moveTo(xm1, RH + 0.5); ctx.lineTo(xm1, height) }
                        t += bt
                    }
                }
                ctx.stroke()
                // 小节号 (bar_px >= 40)
                if (barPx >= 40) {
                    ctx.fillStyle = pal.barNo
                    ctx.font = '8pt "Segoe UI"'
                    ctx.textBaseline = 'middle'
                    if (segStarts) {
                        for (var sj = 0; sj < segStarts.length; sj++) {
                            var xn2 = Math.round(KB + (segStarts[sj][0] - vt) * ppt) + 0.5
                            if (xn2 >= KB - 20 && xn2 <= width)
                                ctx.fillText(String(segStarts[sj][1]), xn2 + 3, RH / 2)
                        }
                    } else {
                        var t2 = Math.floor(t0 / bt) * bt
                        while (t2 <= t1 + bt) {
                            var xn1 = KB + (t2 - vt) * ppt
                            if (xn1 >= KB) ctx.fillText(String(Math.round(t2 / bt) + 1), xn1 + 3, RH / 2)
                            t2 += bt
                        }
                    }
                }
            }
        }
        Connections {
            target: bridge
            function onViewChanged() { grid.requestPaint() }
            function onLanesChanged() { grid.requestPaint() }
        }
        onWidthChanged: grid.requestPaint()
        Component.onCompleted: grid.requestPaint()

        // ---- 2. 车道 (字母标签层在标签列之下 [左外侧条目被标签列遮住] + 空轨提示) ----
        Repeater {
            model: bridge ? bridge.laneCount : 0
            Item {
                required property int index
                y: root.rulerH + index * row.laneH
                width: row.width; height: row.laneH
                // 演奏事件 (谱面化 2026-09-08: 色块取消 → 字母标签 + 演奏中蓝线段)
                // (显示修复保留) 先画事件后画标签列: 负 x 的条目从画布外延伸进来,
                // 由标签列 (后画, 不透明) 遮住 0..kbW 段
                Repeater {
                    model: bridge.laneModels[index]
                    Item {
                        id: ev
                        // (小节谱轮) 列布局分流: bars = 消费 Python 预计算 xPx/rowIdx
                        // (小节=列数×列宽, 等距列), follow/beat = tick×ppt 原路径
                        property bool colMode: bridge ? bridge.colMode === true : false
                        // (琶音轮) 合并块: arpSeq 非空 = 琶音块 (顺序亮起)
                        property var arpSeq: model.arpSeq || []
                        readonly property bool isArp: arpSeq.length > 0
                        // 琶音块: 只有「正在演奏」的起点组亮起 (蓝填 + 白字放大),
                        // 已演奏过的组回到常态, 不再累积成整块蓝色
                        function subOn(ni) {
                            if (!isArp) return playing || tail
                            return (playing || tail) && curGroup >= 0
                                && groupOf(ni) === curGroup
                        }
                        function groupOf(ni) {
                            for (var j = 0; j < groups.length; j++)
                                if (ni >= groups[j][0] && ni <= groups[j][1]) return j
                            return -1
                        }
                        // 当前组 (不受 playing 门控: 释放期随亮度包络淡出)
                        readonly property int curGroup: hitAll < 0 ? -1 : groupOf(hitAll)
                        // (音游轮) 已击中的最后一个标签序号 (-1 = 未开始): 驱动分段填充
                        // hitAll 不受 playing 门控 (释放期保留末状态, 供填充渐隐)
                        readonly property int hitAll: {
                            if (!isArp || relMs < 0) return -1
                            var rel = root.phs - startTick, k = -1
                            for (var i = 0; i < arpSeq.length; i++)
                                if (arpSeq[i][0] <= rel) k = i
                            return k
                        }
                        readonly property int hitIdx: playing ? hitAll : -1
                        // (判定格) 起点组表 [首标签序号, 末标签序号, 组内偏移 tick]
                        readonly property var groups: {
                            var g = []
                            for (var i = 0; i < arpSeq.length; i++) {
                                if (i === 0 || arpSeq[i][0] !== arpSeq[i - 1][0])
                                    g.push([i, i, arpSeq[i][0]])
                                else g[g.length - 1][1] = i
                            }
                            return g
                        }
                        readonly property int hitGroup: {
                            if (hitIdx < 0) return -1
                            for (var j = 0; j < groups.length; j++)
                                if (hitIdx >= groups[j][0] && hitIdx <= groups[j][1]) return j
                            return -1
                        }
                        // 起点锚 (负值 = 画布左外侧); 线段跨度 = 音符时值
                        property real nx: colMode
                            ? root.kbW + (model.xPx || 0)
                            : root.kbW + (startTick - row.rowVt) * root.ppt
                        property real lw: colMode
                            ? Math.max(model.wPx || bridge.colW, 2)
                            : Math.max(duration * root.ppt, 2)
                        property bool playing: model.state !== 2 && root.phs >= 0
                            && root.phs >= startTick
                            && root.phs < startTick + duration
                        // (点轮) 行角色捕获: 逐音符标签 / 简谱八度点 [上加, 下加]
                        property var nlabels: model.noteLabels
                        property var ndots: model.noteDots
                        property int st: model.state
                        // (三轮) 音符方块矩形: 常态 = 浅灰细描边圆角框; 演奏中 =
                        // 放大 + 蓝色填充亮起 + 字母放大变白; 结束后经 Behavior
                        // 渐缩回常态大小 (有下限, 不消失)、蓝色渐隐
                        // (六轮定稿) 方框随演奏进度渐缩: 起始 1.18× → 结束位置
                        // 恰好回常态 1.0× (指针驱动, 落地无跳变; Behavior 移除)
                        // (音游轮) 帧级包络 (phs 驱动, 无 Behavior 滞后):
                        //  击打 = 70ms easeOutBack 弹到 1.18× (微过冲) →
                        //  衰减 = smoothstep 随进度回落, 结束位置恰好 1.0× (落地无跳变);
                        //  琶音块每击中一组叠加 110ms 小冲击 (+5%) = 顿挫感
                        // (统一动画模组) 单音/和弦/琶音共用一条毫秒制包络:
                        //  击打 80ms easeOutBack → 1.18× (微过冲);
                        //  持续 = 随进度 smoothstep 回落到 1.05× (时值仍由渐缩表达);
                        //  释放 = 音符结束后 240ms (1-t)³ 余晖回 1.0×, 全程连续无跳变
                        readonly property real noteMs: Math.max(1, model.durMs)
                        readonly property real msPerTk: noteMs / Math.max(1, duration)
                        readonly property real relMs: root.phs < 0 ? -1
                            : (root.phs - startTick) * msPerTk
                        readonly property int releaseMs: 240
                        readonly property bool live: model.state !== 2 && relMs >= 0
                            && relMs < noteMs + releaseMs
                        function level(ms) {
                            var a = Math.min(1, ms / 80) - 1
                            var atk = 1 + 2.70158 * a * a * a + 1.70158 * a * a
                            var p = Math.max(0, Math.min(1, ms / noteMs))
                            return atk * (0.05 + 0.13 * (1 - p * p * (3 - 2 * p)))
                        }
                        readonly property real relT: live && relMs >= noteMs
                            ? (relMs - noteMs) / releaseMs : 0
                        // 亮度包络: 持续期满亮, 释放期 (1-t)² 渐隐 (与缩放余晖同步)
                        readonly property real fillEnv: !live ? 0
                            : (relMs < noteMs ? 1 : (1 - relT) * (1 - relT))
                        // 击中白闪 (与琶音判定格同参): 0.5 → 180ms 平方衰减
                        readonly property real hitFlash: {
                            if (!live) return 0
                            var f = Math.max(0, 1 - relMs / 180)
                            return f * f
                        }
                        // 释放余晖期标签保持白字 (蓝底未褪尽前不翻回深色)
                        readonly property bool tail: live && !playing && fillEnv > 0.45
                        property real boxScale: {
                            if (!live) return 1.0
                            if (relMs >= noteMs) {
                                var r = 1 - relT
                                return 1.0 + level(noteMs) * r * r * r
                            }
                            var s = 1.0 + level(relMs)
                            if (hitIdx >= 0 && arpSeq[hitIdx][0] > 0) {
                                var h = Math.max(0, 1 - (relMs - arpSeq[hitIdx][0]
                                                 * msPerTk) / 110)
                                s += 0.05 * h * h
                            }
                            return s
                        }
                        // (动画轮) 动效时长由音符时值决定 (毫秒, 变速曲按位置换算)
                        property real durMs: Math.max(60, model.durMs)
                        x: nx; y: 0
                        width: Math.max(lw, 24); height: parent.height
                        // 视口剔除: 列布局只渲染本排条目 (rowIdx 过滤;
                        // StripRow 的排号属性是 rowIndex, 不是 Repeater 的 index);
                        // 完全在画布区 (kbW..width) 外的条目零绘制
                        visible: (!colMode || model.rowIdx === row.rowIndex)
                            && nx + lw > root.kbW && nx < row.width
                        // (演奏谱重设计一期) 蓝线/首尾圆点已删除:
                        // 时值改由亮起动效时长表达 (durMs 驱动, 见下方 Behavior)
                        // (三轮) 音符方块: 包住字母; 演奏中蓝填白字放大, 结束渐缩回常态
                        // (琶音轮) 同格和弦保持单行拼接; 琶音窄块按音高轻微上下
                        // 偏移 (subY, 数据层钳 ±6px): 高音稍高、低音稍低 → 阶梯可辨
                        Item {
                            id: bx
                            // (点轮二改) 方块 = 数字 + 八度点的紧凑包裹, 方向性增长:
                            //  上加点只扩上缘 / 下加点只扩下缘 (贴合"刚好包含");
                            //  底缘不压蓝线 —— 压线时整体上移 (数字随方框上浮)
                            readonly property real lblPt: bridge ? bridge.labelPt : 8
                            readonly property real dotD: Math.max(2.6, lblPt * 0.38)
                            readonly property real st: dotD + 1.5
                            readonly property real textH: lblPt * 1.75
                            readonly property int maxUp: {
                                var m = 0
                                for (var i = 0; i < ev.ndots.length; i++)
                                    if (ev.ndots[i][0] > m) m = ev.ndots[i][0]
                                return m
                            }
                            readonly property int maxDn: {
                                var m = 0
                                for (var i = 0; i < ev.ndots.length; i++)
                                    if (ev.ndots[i][1] > m) m = ev.ndots[i][1]
                                return m
                            }
                            readonly property real upPart: maxUp > 0
                                ? 2.5 + maxUp * dotD + (maxUp - 1) * 1.5 : 0
                            readonly property real dnPart: maxDn > 0
                                ? 2.5 + maxDn * dotD + (maxDn - 1) * 1.5 : 0
                            readonly property real textCY: 2 + upPart + textH / 2
                            property real boxH: Math.max(14,
                                4 + textH + upPart + dnPart)
                            // 蓝线锚定 (槽位轮) y = Python 槽位表给的绝对位置:
                            // 线上 3 槽 / 线下 2 槽互不重叠且不跨蓝线, QML 不再钳制
                            x: 0
                            y: model.subY
                            // (小节谱 v2) 列布局盒宽恒 = 列距 (wPx) —— 一音一列
                            // 等距永不重叠; 跟弹/节拍保持内容自适应宽
                            width: Math.max(ev.colMode ? model.wPx
                                             : (nrow.visible ? nrow.implicitWidth : 0) + 8,
                                            12)
                            height: boxH
                            // (音游轮) 帧级包络直驱, 不再挂 Behavior (滞后 + 与包络打架)
                            scale: ev.boxScale
                            transformOrigin: Item.Left   // 左缘原点: 放大不推走字母 (字母贴左缘)
                            // (五轮) 复制层: 外圈柔光 — 尺寸比方块大 4px、低不透明度,
                            // 与方块同随缩放动画, 点亮由内向外过渡更细腻 (熄灭同步淡出)
                            Rectangle {
                                anchors.fill: parent; anchors.margins: -4
                                radius: 6
                                color: pal.blue
                                // (统一动画模组) 柔光 = 亮度包络 + 击中闪, 帧级直驱;
                                // 琶音块不做整块柔光 (柔光只给当前组, 见判定格)
                                opacity: ev.isArp ? 0
                                    : 0.28 * ev.fillEnv + 0.14 * ev.hitFlash
                                visible: opacity > 0.003
                            }
                            // 音符块白底: 透明皮肤下画布透明, 方块仍用白底突出字体
                            Rectangle {
                                anchors.fill: parent; radius: 4
                                color: "#ffffff"
                                visible: root.clear
                            }
                            // (统一动画模组) 常态灰描边恒在; 蓝填充/蓝描边按亮度包络
                            // 叠加 (释放期连续渐隐, 不再二值切换 + Behavior 追赶)
                            Rectangle {
                                anchors.fill: parent; radius: 4
                                color: "transparent"
                                border.width: 1; border.color: pal.sub
                                opacity: 0.55
                            }
                            Rectangle {
                                anchors.fill: parent; radius: 4
                                color: ev.isArp ? "transparent" : pal.blue
                                border.width: 1; border.color: pal.blue
                                opacity: ev.fillEnv
                                visible: opacity > 0.003
                            }
                            // 单音/和弦击中白闪 (与琶音判定格同参: 0.5 × 180ms 平方衰减)
                            Rectangle {
                                anchors.fill: parent; radius: 4
                                color: "#ffffff"
                                opacity: ev.isArp ? 0 : 0.5 * ev.hitFlash
                                visible: opacity > 0.003
                            }
                            // (判定格) 每个起点组 = 一格, 满高、横跨到两侧分割线中点
                            // (首/末格贴方块圆角); 不随标签缩放。当前组: 击中白闪
                            // 0.68 → 180ms 平方衰减 → 常亮 0.18 (hold); 下一组: 底部
                            // 接近条按距下次击中的进度增长 (音游 approach 提示)
                            Repeater {
                                model: ev.isArp ? ev.groups.length : 0
                                Item {
                                    id: cell
                                    readonly property var gr: ev.groups[index]
                                    readonly property bool last: index === ev.groups.length - 1
                                    function edge(k) {
                                        var it = nrep.count > k ? nrep.itemAt(k) : null
                                        return it ? nrow.x + it.x + it.width - it.breath
                                            + (it.breath + nrow.spacing) / 2 : 0
                                    }
                                    readonly property real x0: index === 0 ? 0
                                        : edge(ev.groups[index - 1][1])
                                    readonly property real x1: last ? bx.width : edge(gr[1])
                                    x: x0; width: Math.max(0, x1 - x0); height: bx.height
                                    readonly property real rel: root.phs - startTick
                                    readonly property bool cur: ev.playing && ev.hitGroup === index
                                    readonly property bool nxt: ev.playing
                                        && ev.hitGroup === index - 1
                                    readonly property real flash: {
                                        if (!cur) return 0
                                        var ms = (rel - gr[2]) * ev.durMs / Math.max(1, duration)
                                        var f = Math.max(0, 1 - ms / 180)
                                        return f * f
                                    }
                                    // 当前组 = 只给这一格蓝色填充 (释放期随亮度包络淡出)
                                    readonly property bool lit: ev.live && ev.curGroup === index
                                    Rectangle {
                                        anchors.fill: parent
                                        topLeftRadius: index === 0 ? 4 : 0
                                        bottomLeftRadius: index === 0 ? 4 : 0
                                        topRightRadius: cell.last ? 4 : 0
                                        bottomRightRadius: cell.last ? 4 : 0
                                        color: pal.blue
                                        opacity: cell.lit ? ev.fillEnv : 0
                                        visible: opacity > 0.003
                                    }
                                    Rectangle {
                                        anchors.fill: parent
                                        topLeftRadius: index === 0 ? 4 : 0
                                        bottomLeftRadius: index === 0 ? 4 : 0
                                        topRightRadius: cell.last ? 4 : 0
                                        bottomRightRadius: cell.last ? 4 : 0
                                        color: "#ffffff"
                                        opacity: cell.cur ? 0.35 * cell.flash : 0
                                    }
                                    Rectangle {
                                        visible: cell.nxt
                                        readonly property real prevOff: index > 0
                                            ? ev.groups[index - 1][2] : 0
                                        readonly property real prog: Math.max(0, Math.min(1,
                                            (cell.rel - prevOff)
                                            / Math.max(1, cell.gr[2] - prevOff)))
                                        x: 2; y: parent.height - 4
                                        width: Math.max(0, (parent.width - 4) * prog)
                                        height: 2; radius: 1
                                        color: pal.blue; opacity: 0.85   // 下一组接近条 (白底上可见)
                                    }
                                }
                            }
                            // 字母标签 (点轮) 逐音符项: 简谱八度点 = 独立几何圆点
                            // (数字正上/正下方, 直径随字号), 取代组合符 (Segoe UI
                            // 对数字组合点整形偏右且过小); 键位/音名模式无点。
                            // 字号/颜色/演奏中加粗逻辑与旧单 Text 一致
                            Row {
                                id: nrow
                                x: 3; height: parent.height
                                spacing: Math.max(4, (bridge ? bridge.labelPt : 8) * 0.7)
                                visible: ev.nlabels.length > 0
                                // (小节谱 v3) 不缩字: 节距已拉长适应最宽盒
                                // (盒宽=内容宽, 节内等距由 Python pitch 保证)
                                Repeater {
                                    id: nrep
                                    model: ev.nlabels.length
                                    Item {
                                        readonly property int ni: index
                                        readonly property bool on_i:
                                            ev.subOn(ni)     // (琶音轮) 逐音顺序亮起
                                        // (琶音轮) 逐音放大: 琶音块内标签随播放
                                        // 依次放大 (未到 0.9× / 到达 1.3×, 和弦同刻同放)
                                        readonly property bool arpRow:
                                            ev.arpSeq.length > 0
                                        // (负空间分组) 同起点 = 一个微胶囊 (组内紧排);
                                        // 不同起点组之间留呼吸间距, 间距正中画悬浮细线 (见 nrow 外层)
                                        readonly property bool groupStart:
                                            arpRow && (ni === 0
                                            || ev.arpSeq[ni][0] !== ev.arpSeq[ni - 1][0])
                                        readonly property bool groupEnd:
                                            arpRow && (ni >= ev.arpSeq.length - 1
                                            || ev.arpSeq[ni][0] !== ev.arpSeq[ni + 1][0])
                                        readonly property real breath:
                                            (groupEnd && ni < ev.arpSeq.length - 1)
                                            ? Math.max(9, (bridge ? bridge.labelPt : 8) * 1.0)
                                            : 0
                                        scale: arpRow ? (on_i ? 1.3 : 0.9) : 1.0
                                        transformOrigin: Item.Center
                                        // (音游轮) 击中 = 110ms easeOutBack 弹出 (微过冲后落定);
                                        // 未击中/释放 = 140ms easeOutCubic 平滑回收
                                        Behavior on scale {
                                            NumberAnimation {
                                                duration: on_i ? 110 : 140
                                                easing.type: on_i ? Easing.OutBack
                                                                  : Easing.OutCubic
                                                easing.overshoot: 2.2
                                            }
                                        }
                                        readonly property int dotsUp:
                                            ev.ndots.length > ni ? ev.ndots[ni][0] : 0
                                        readonly property int dotsDn:
                                            ev.ndots.length > ni ? ev.ndots[ni][1] : 0
                                        readonly property color dotCol:
                                            ev.st === 2 ? pal.red
                                                : (on_i ? "#ffffff" : pal.text)
                                        // (负空间分组) 组尾右侧追加呼吸间距 (Python _arp_width 镜像)
                                        width: txt.implicitWidth + 1 + breath
                                        height: nrow.height
                                        Text {
                                            id: txt
                                            anchors.verticalCenter: parent.verticalCenter
                                            anchors.verticalCenterOffset:
                                                bx.textCY - bx.height / 2
                                            text: ev.nlabels[ni]
                                            font.family: 'Segoe UI'
                                            font.pointSize: bridge ? bridge.labelPt : 8
                                            font.bold: parent.on_i
                                            color: ev.st === 2 ? pal.red
                                                   : (parent.on_i ? "#ffffff" : pal.text)
                                        }
                                        Repeater {              // 上加八度点 (数字上方, 向上叠)
                                            model: dotsUp
                                            Rectangle {
                                                property int k: index
                                                anchors.horizontalCenter: parent.horizontalCenter
                                                y: 2 + bx.upPart - 2.5
                                                   - bx.dotD - k * bx.st
                                                width: bx.dotD; height: bx.dotD
                                                radius: bx.dotD / 2
                                                color: dotCol
                                            }
                                        }
                                        Repeater {              // 下加八度点 (数字下方, 向下叠)
                                            model: dotsDn
                                            Rectangle {
                                                property int k: index
                                                anchors.horizontalCenter: parent.horizontalCenter
                                                y: bx.textCY + bx.textH / 2 + 2.5
                                                   + k * bx.st
                                                width: bx.dotD; height: bx.dotD
                                                radius: bx.dotD / 2
                                                color: dotCol
                                            }
                                        }
                                    }
                                }
                            }
                            // (悬浮细线) 琶音起点组分割线: 几何图元, 不随音符缩放
                            // (位于 nrow 缩放项之外); 高 = 文字高 85%, 垂直居中于字心,
                            // 落在组间空隙 (breath + Row spacing) 正中, 不占额外宽度
                            Repeater {
                                model: ev.arpSeq.length > 0 ? ev.nlabels.length : 0
                                Rectangle {
                                    readonly property Item it: nrep.count > index
                                        ? nrep.itemAt(index) : null
                                    visible: it !== null && it.groupEnd
                                        && index < ev.arpSeq.length - 1
                                    width: 1
                                    height: Math.round(bx.textH * 0.85)
                                    radius: 0.5
                                    x: it ? Math.round(nrow.x + it.x + it.width - it.breath
                                        + (it.breath + nrow.spacing) / 2) : 0
                                    y: bx.textCY - height / 2
                                    antialiasing: true
                                    // 只有当前组那一格是蓝底: 分割线恒为灰线
                                    color: pal.bar
                                    opacity: 0.6
                                }
                            }
                        }
                    }
                }
                // 左列: 轨道色块 + 轨名 (与卷帘键盘列对齐; 盖在事件层之上)
                // (多排二轮) 不透明底列保留在所有排 (遮负 x 入场条目);
                // 轨色条/轨名/空轨提示只第 0 排画, 其余排不再重复 (用户裁定)
                // 透明皮肤: 只有画布透明, 轨名区保持白底突出字体
                Rectangle { x: 0; width: root.kbW; height: parent.height + 0.5
                            color: root.clear ? "#ffffff" : pal.laneCol }
                readonly property bool blank: bridge.laneBlank[index] === true
                Rectangle { visible: row.first && !parent.blank
                            x: 4; y: 3; width: 5; height: Math.max(3, parent.height - 6)
                            color: bridge.laneColors[index] }
                Text { visible: row.first && !parent.blank
                       x: 11; width: root.kbW - 13; height: parent.height
                       verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
                       text: bridge.laneNames[index]
                       font.family: 'Segoe UI'
                       font.pointSize: bridge ? bridge.namePt : 7
                       color: pal.name }
                // 空白乐谱排: 「+」交互块 (点击由 Python ScoreStrip.lane_at 命中)
                Rectangle { visible: row.first && parent.blank && bridge.laneEditable
                            x: 8; y: 6; width: root.kbW - 16
                            height: Math.max(12, parent.height - 12)
                            radius: 6; color: "transparent"
                            border.width: 1; border.color: pal.bar; opacity: 0.7
                            Text { anchors.centerIn: parent; text: "+"
                                   font.family: 'Segoe UI'; font.pointSize: 16
                                   color: pal.bar } }
                Text { visible: row.first && parent.blank && bridge.laneEditable
                       x: root.kbW; width: parent.width - root.kbW; height: parent.height
                       horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                       text: blankHint; font.family: 'Segoe UI'; font.pointSize: 8; color: pal.empty }
                Text { visible: row.first && !parent.blank && bridge.laneCounts[index] === 0
                       x: root.kbW; width: parent.width - root.kbW; height: parent.height
                       horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                       text: emptyHint; font.family: 'Segoe UI'; font.pointSize: 8; color: pal.empty }
                Rectangle { visible: index > 0; x: root.kbW; y: 0.5
                            width: parent.width - root.kbW; height: 1; color: pal.sep }
            }
        }
        // (指针删除轮 2026-09-26) 演奏谱红色指针已移除 —— 播放位置由音符
        // 点亮动画自身表达 (方框放大/蓝填/顺播), 不再画独立指针线
    }

    Repeater {
        id: rep
        model: root.rows
        StripRow {
            rowIndex: index
            y: index * root.rowH
            width: root.width
            height: root.rowH
        }
    }

    // ---- (仿冰与火之舞小球轮) 每车道一颗小球沿半圆弧在音符框之间飞行 +
    // 当前段轨迹弧。置于 rows Repeater 之后 = z 序最上, 跨排飞行不被单排
    // clip 裁掉; 进度由平滑时钟 phs 驱动 (不新建定时器); 段表按 t0 升序,
    // 当前段 = t0 ≤ phs 的最后一段, 段内参数位 = 角度匀速转 180° (仿游戏
    // 每拍匀速) + 端点 y 线性插值: x = x0+(x1-x0)p,
    // y = y0+(y1-y0)p - side·ry·sin(πp)。轨迹 Canvas 只在段切换/几何变化
    // 时 requestPaint (不逐帧重绘), 小球本体是逐帧移动的 Rectangle。
    // 未出发 (播放头 < 0 或 < 首段 t0) 隐藏; 到达 (p≥1) 停在本段终点
    // (上方段框顶边 / 下方段框底边中点) 直到下一段出发; 颜色到达时切换
    // (120ms 过渡): 飞行中保持前一目标色, 进入琶音子音 = 亮红, 普通音 = 蓝。
    Item {
        visible: bridge ? bridge.colMode === true : false
        anchors.fill: parent
        Repeater {
            model: bridge ? bridge.laneCount : 0
            Item {
                id: bl
                required property int index
                readonly property real laneH:
                    (root.rowH - root.rulerH)
                    / Math.max(1, bridge ? bridge.laneCount : 1)
                readonly property var segs: {
                    var all = bridge ? bridge.ballSegs : null
                    var out = []
                    if (all) for (var i = 0; i < all.length; i++)
                        if (all[i].lane === index) out.push(all[i])
                    return out
                }
                readonly property int curIdx: {
                    var j = -1
                    for (var i = 0; i < segs.length; i++)
                        if (segs[i].t0 <= root.phs) j = i
                    return j
                }
                readonly property var cur: curIdx >= 0 ? segs[curIdx] : null
                readonly property real prog: {
                    if (!cur) return 1
                    var d = Math.max(1e-9, cur.t1 - cur.t0)
                    return Math.max(0, Math.min(1, (root.phs - cur.t0) / d))
                }
                // 段内参数位 (p) → 全局坐标 (排 y + 小节号行 + 车道 y + 局部 y)
                function pos(seg, p) {
                    var ly = seg.y0 + (seg.y1 - seg.y0) * p
                        - seg.side * seg.ry * Math.sin(Math.PI * p)
                    return Qt.point(root.kbW + seg.x0 + (seg.x1 - seg.x0) * p,
                                    root.rulerH + index * laneH
                                    + seg.row0 * root.rowH + ly)
                }
                readonly property var ballPos:
                    cur ? pos(cur, prog) : Qt.point(-99, -99)
                readonly property bool ballArp:
                    cur ? (prog >= 1 ? cur.arp === true
                                     : cur.prevArp === true) : false
                Canvas {                         // 轨迹线: 只画当前段整条弧
                    id: trace
                    // (轨迹弧修复轮) bl 是无尺寸挂点 (小球按 x/y 直接定位,
                    // 不依赖父尺寸), anchors.fill: parent 会把画布钉成 0×0
                    // → onPaint 无可画区域, 弧恒不可见; bl 恒在层原点, 直接
                    // 铺满 root 与 pos() 的全局坐标系一致
                    x: 0
                    y: 0
                    width: root.width
                    height: root.height
                    onPaint: {
                        var ctx = getContext('2d')
                        ctx.clearRect(0, 0, width, height)
                        if (!bl.cur || root.phs < 0) return
                        ctx.strokeStyle = '#8a9099'
                        ctx.globalAlpha = 0.55
                        ctx.lineWidth = 1.5
                        ctx.lineCap = 'round'
                        ctx.beginPath()
                        var N = 24
                        for (var i = 0; i <= N; i++) {
                            var pt = bl.pos(bl.cur, i / N)
                            if (i === 0) ctx.moveTo(pt.x, pt.y)
                            else ctx.lineTo(pt.x, pt.y)
                        }
                        ctx.stroke()
                    }
                }
                onCurIdxChanged: trace.requestPaint()   // 段切换才重绘
                onSegsChanged: trace.requestPaint()     // 段表重赋值 = 段坐标
                onLaneHChanged: trace.requestPaint()    //   变化 (滚动平移/换页) 同步重绘;
                                                        //   不逐帧重绘; 画布自身 resize
                                                        //   (root 尺寸/车道数变化) 自动重绘
                Rectangle {                      // 小球本体 (逐帧移动)
                    visible: bl.cur !== null && root.phs >= 0
                    readonly property real d:
                        Math.max(7, (bridge ? bridge.labelPt : 8) * 1.1)
                    x: bl.ballPos.x - d / 2
                    y: bl.ballPos.y - d / 2
                    width: d; height: d; radius: d / 2
                    color: bl.ballArp ? pal.ballRed : pal.blue
                    Behavior on color { ColorAnimation { duration: 120 } }
                    border.width: 1.5
                    border.color: '#1a1d22'
                }
            }
        }
    }
}
