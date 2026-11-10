// Interaction timings follow osu.Game/Graphics/UserInterface/OsuButton.cs.
import QtQuick 2.15

Item {
    id: root
    property string text: ""
    property color baseColor: "#1c2028"
    property color hoverColor: "#ffffff"
    property color textColor: "#c8ccd4"
    property int textSize: 14
    property real radius: 8
    readonly property bool hovered: mouseArea.containsMouse
    readonly property bool pressed: mouseArea.pressed
    signal clicked()

    implicitWidth: Math.max(120, label.implicitWidth + 32)
    implicitHeight: 44
    activeFocusOnTab: enabled

    function restoreScale() {
        pressAnim.stop()
        releaseAnim.restart()
    }

    function resetInteraction() {
        hoverAnim.stop()
        hoverLostAnim.stop()
        pressAnim.stop()
        releaseAnim.stop()
        hoverLayer.opacity = 0
        content.scale = 1
    }

    onEnabledChanged: if (!enabled) resetInteraction()
    onVisibleChanged: if (!visible) resetInteraction()
    Keys.onSpacePressed: if (enabled && !event.isAutoRepeat) clicked()
    Keys.onReturnPressed: if (enabled && !event.isAutoRepeat) clicked()
    Keys.onEnterPressed: if (enabled && !event.isAutoRepeat) clicked()

    // Keep the hit target fixed while only the visual content scales.
    Item {
        id: content
        objectName: "buttonContent"
        anchors.fill: parent
        opacity: root.enabled ? 1 : OsuStyle.disabledAlpha
        Rectangle {
            anchors.fill: parent
            color: root.baseColor
            radius: root.radius
            border.width: root.activeFocus ? 1 : 0
            border.color: root.textColor
        }
        Rectangle {
            id: hoverLayer
            objectName: "hoverLayer"
            anchors.fill: parent
            color: root.hoverColor
            opacity: 0
            radius: root.radius
        }
        Text {
            id: label
            anchors.centerIn: parent
            width: Math.max(0, parent.width - 24)
            text: root.text
            color: root.textColor
            font.pixelSize: root.textSize
            font.weight: Font.Bold
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
        }
    }

    MouseArea {
        id: mouseArea
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onEntered: {
            hoverLostAnim.stop()
            hoverAnim.restart()
        }
        onExited: {
            hoverAnim.stop()
            hoverLostAnim.restart()
        }
        onPressed: {
            root.forceActiveFocus()
            releaseAnim.stop()
            pressAnim.restart()
        }
        onReleased: root.restoreScale()
        onCanceled: root.restoreScale()
        onClicked: root.clicked()
    }

    SequentialAnimation {
        id: hoverAnim
        NumberAnimation {
            target: hoverLayer
            property: "opacity"
            to: OsuStyle.hoverInitialAlpha
            duration: OsuStyle.hoverPeakDuration
            easing.type: OsuStyle.outQuint
        }
        NumberAnimation {
            target: hoverLayer
            property: "opacity"
            to: OsuStyle.hoverFinalAlpha
            duration: OsuStyle.hoverSettleDuration
            easing.type: OsuStyle.outQuint
        }
    }
    NumberAnimation {
        id: hoverLostAnim
        target: hoverLayer
        property: "opacity"
        to: 0
        duration: OsuStyle.hoverLostDuration
        easing.type: OsuStyle.outQuint
    }
    NumberAnimation {
        id: pressAnim
        target: content
        property: "scale"
        to: OsuStyle.pressScale
        duration: OsuStyle.pressDuration
        easing.type: OsuStyle.outQuint
    }
    NumberAnimation {
        id: releaseAnim
        target: content
        property: "scale"
        to: OsuStyle.releaseScale
        duration: OsuStyle.releaseDuration
        easing.type: OsuStyle.outElastic
    }
}
