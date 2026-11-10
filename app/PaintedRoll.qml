// PaintedRoll.qml — MuseScore 路线画布 (QML-3 / ROLL_QML=2):
// NotesPaintedItem(QQuickPaintedItem) 以 QPainter 复用 roll_tiles 已验证绘制
// 函数全量重绘画布 (行底色/音域框/网格/音符)。播放头由 Python paint() 直绘,
// 编辑覆盖层由外层 _QmlOverlay QWidget 承担, 输入事件不进入本场景。
import QtQuick
import RollCanvas 1.0

NotesPaintedItem {
    anchors.fill: parent
}
