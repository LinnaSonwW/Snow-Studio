import QtQuick 2.15

Rectangle {
    id: root
    color: "#16191d"
    focus: true
    Keys.onEscapePressed: newInterfaceHost.returnToLegacy()

    Rectangle {
        id: toolbar
        anchors.top: parent.top
        width: parent.width
        height: 76
        color: "#20252a"

        Text {
            anchors.left: parent.left
            anchors.leftMargin: 24
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(0, parent.width - returnButton.width - 72)
            text: "Snow 原琴工作站 · 新界面"
            color: "#edf0f3"
            font.pixelSize: 20
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }

        OsuButton {
            id: returnButton
            objectName: "returnLegacyButton"
            anchors.right: parent.right
            anchors.rightMargin: 24
            anchors.verticalCenter: parent.verticalCenter
            width: 156
            height: 44
            text: "返回旧界面"
            baseColor: "#35433c"
            textColor: "#edf0f3"
            onClicked: newInterfaceHost.returnToLegacy()
        }
    }

    Rectangle {
        anchors.top: toolbar.bottom
        width: parent.width
        height: 1
        color: "#384047"
    }

    Item {
        objectName: "workspace"
        anchors.top: toolbar.bottom
        anchors.bottom: parent.bottom
        width: parent.width
    }
}
