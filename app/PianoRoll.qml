// PianoRoll.qml — 卷帘画布 (QML 迁移步骤1): 行底色/音域框/网格/音符/播放头。
// 只读渲染: 输入事件不进入本场景 (QQuickWidget WA_TransparentForMouseEvents),
// 手势/编辑由外层 PianoRoll(QWidget) 捕获 → model API → 桥属性/模型增量刷新。
// 网格用独立 Canvas 层 (规格: 不与音符 delegate 混层); 音符经 content 容器
// 平移实现视口滚动 (平移=单属性, Scene Graph 增量), clip 裁剪屏外内容。
import QtQuick

Item {
    id: root
    clip: true
    // bridge/noteModel/blackClasses 为 Python rootContext 注入 (勿在根对象
    // 声明同名属性 —— 会遮蔽上下文属性, 全部绑定落默认值的教训)

    // ---- 桥注入 (Python 16ms 时钟推送; 值不变零代价) ----
    readonly property real vt: bridge ? bridge.viewTick : 0
    readonly property real ppt: bridge ? bridge.pxPerTick : 0.1
    readonly property real rowH: bridge ? bridge.rowH : 12
    readonly property real topF: bridge ? bridge.topPitch : 71
    readonly property real tpb: bridge ? bridge.tpb : 480
    readonly property real barT: bridge ? bridge.barTicks : 1920
    readonly property real subStep: bridge ? bridge.subStepTicks : 0
    readonly property real pptBase: bridge ? bridge.pptBase : root.ppt

    // ---- 1. 行底色 (C1~B8 全域 ≤100 行, 随 topF 相位平移) ----
    Repeater {
        model: 100
        Rectangle {
            x: 0; width: root.width
            property int pitchN: Math.floor(root.topF) + 1 - index
            y: (root.topF - pitchN) * root.rowH
            height: root.rowH + 0.6
            color: blackClasses.indexOf(((pitchN % 12) + 12) % 12) >= 0
                   ? '#222831' : '#2a313b'
            Rectangle {   // C 行底线
                anchors.bottom: parent.bottom
                width: parent.width; height: 1
                color: '#262c35'
                visible: ((parent.pitchN % 12) + 12) % 12 === 0
            }
        }
    }

    // ---- 2. 音域高亮框 (原 bgV 层迁移) ----
    Rectangle {
        visible: bridge ? bridge.rangeLo > -900 : false
        x: 1; width: root.width - 2
        y: (root.topF - bridge.rangeHi) * root.rowH
        height: (bridge.rangeHi - bridge.rangeLo + 1) * root.rowH
        color: 'transparent'
        border.color: Qt.rgba(80 / 255, 220 / 255, 120 / 255, 180 / 255)
        border.width: 2
        Text {
            property real yTop: (root.topF - bridge.rangeHi) * root.rowH
            x: 6
            y: yTop > 14 ? yTop - 13 : yTop + parent.height + 2
            visible: bridge && bridge.rangeLo > -900 && yTop > 14
            text: 'C' + (bridge.rangeLo / 12 - 1) + '~B' + (bridge.rangeHi / 12 - 1)
            color: Qt.rgba(120 / 255, 235 / 255, 150 / 255, 220 / 255)
            font.family: 'Segoe UI'; font.pointSize: 7
        }
    }

    // ---- 3. 网格层 (窗口坐标 Canvas; viewChanged/尺寸变化时重画) ----
    Canvas {
        id: grid
        anchors.fill: parent
        onPaint: {
            var ctx = getContext('2d')
            ctx.clearRect(0, 0, width, height)
            if (!bridge) return
            var vt = root.vt, ppt = root.ppt
            var t0 = Math.max(vt, 0), t1 = vt + width / ppt
            var t
            ctx.lineWidth = 1
            // 隔行小节底色
            t = Math.floor(t0 / root.barT) * root.barT
            for (; t <= t1; t += root.barT) {
                if (Math.round(t / root.barT) % 2 === 0) {
                    ctx.fillStyle = 'rgba(255, 255, 255, 0.02)'
                    ctx.fillRect((t - vt) * ppt, 0, root.barT * ppt, height)
                }
            }
            // 对齐细网格 (密度规则由 Python 折算进 subStep)
            if (root.subStep > 0) {
                ctx.strokeStyle = '#252b33'
                ctx.beginPath()
                t = Math.floor(t0 / root.subStep) * root.subStep
                for (; t <= t1; t += root.subStep) {
                    var xs = Math.round((t - vt) * ppt) + 0.5
                    ctx.moveTo(xs, 0); ctx.lineTo(xs, height)
                }
                ctx.stroke()
            }
            // 拍线
            ctx.strokeStyle = '#2b323c'
            ctx.beginPath()
            t = Math.floor(t0 / root.tpb) * root.tpb
            for (; t <= t1; t += root.tpb) {
                var xb = Math.round((t - vt) * ppt) + 0.5
                ctx.moveTo(xb, 0); ctx.lineTo(xb, height)
            }
            ctx.stroke()
            // 小节线 (画布段; 标尺段由 QWidget 瓦片层负责)
            ctx.strokeStyle = '#333b46'
            ctx.beginPath()
            t = Math.floor(t0 / root.barT) * root.barT
            for (; t <= t1; t += root.barT) {
                var xm = Math.round((t - vt) * ppt) + 0.5
                ctx.moveTo(xm, 0); ctx.lineTo(xm, height)
            }
            ctx.stroke()
        }
    }
    Connections {
        target: bridge
        function onViewChanged() { grid.requestPaint() }
    }
    onWidthChanged: grid.requestPaint()
    onHeightChanged: grid.requestPaint()
    Component.onCompleted: grid.requestPaint()

    // ---- 4. 音符层 (content 平移 = 视口滚动; delegate 行级增量) ----
    Item {
        id: content
        // (QML-1b) 横纵双向都是容器级单属性变换 —— 滚动/缩放帧零 delegate 重估:
        //   横向: x = -viewTick*ppt (随桥推送)
        //   纵向: y = topPitch*rowH (随桥推送); delegate.y = -pitch*rowH (静态)
        //   缩放: Scale.xScale = ppt/pptBase 顶帧 (防抖 220ms 后重算 pptBase)
        x: -root.vt * root.ppt
        y: root.topF * root.rowH
        width: root.width; height: root.height
        transform: Scale {
            xScale: root.pptBase > 0 ? root.ppt / root.pptBase : 1
            yScale: 1
            origin.x: 0; origin.y: 0
        }
        Repeater {
            model: noteModel
            delegate: Rectangle {
                x: model.startTick * root.pptBase
                y: -model.pitch * root.rowH + 1
                width: Math.max(model.duration * root.pptBase, 6)
                height: Math.max(root.rowH - 1, 2)
                radius: 3
                border.width: 1
                border.color: '#101318'
                color: model.state === 1 ? '#ffb020'
                     : model.state === 2 ? '#7c5158' : model.noteColor
                Text {
                    x: 3; width: Math.max(0, parent.width - 8)
                    height: parent.height
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                    visible: root.rowH >= 11 && text !== ''
                    text: model.label
                    font.family: 'Segoe UI'; font.pointSize: 7
                    style: Text.Outline; styleColor: '#101318'
                    color: '#eef3fa'
                }
            }
        }
    }
    // ---- 5. 播放头 (视口坐标系: 不随 content 容器平移/缩放, x 自带 vt 回减) ----
    Rectangle {
        visible: bridge ? bridge.playheadTick >= 0 : false
        x: (bridge.playheadTick - root.vt) * root.ppt
        y: 0; width: 2; height: root.height
        color: '#ff3b30'
        antialiasing: false
    }
}
