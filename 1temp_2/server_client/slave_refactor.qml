/* slave_refactor.qml */
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Window 2.15

Window {
    id: root
    width: 1200; height: 900
    visible: true
    title: "Modbus Slave Monitor"

    property var devices: ["Device 1", "Device 2", "Device 3"]

    ScrollView {
        anchors.fill: parent

        Column {
            width: root.width
            spacing: 30
            padding: 20

            Repeater { model: devices
                Rectangle {
                    width: parent.width - 60
                    height: body.implicitHeight + 40
                    color: "#f0f0f0"; radius: 10
                    border.color: "gray"; border.width: 1

                    property string unitId: (index+1).toString()
                    property var    fields: []    // 0~9 TextField ref
                    property string logTxt: ""

                    /* ─── 백엔드 → 값 수신 ─── */
                    Connections {
                        target: backend
                        function onReadSignal(u, list) {
                            if (u !== unitId || fields.length < 10) return
                            for (var i = 0; i < list.length; ++i) {
                                var addr = list[i].addr
                                if (fields[addr])
                                    fields[addr].text =
                                        "0x" + list[i].val.toString(16).toUpperCase()
                            }
                        }
                    }

                    Column {
                        id: body
                        width: parent.width - 40
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.margins: 20
                        spacing: 12

                        Label {
                            text: modelData
                            width: parent.width
                            font.pixelSize: 18; font.bold: true
                            horizontalAlignment: Text.AlignHCenter
                        }

                        /* Read 영역 (0~4) */
                        Label { text: "Read 영역 (0~4)"; x: 30 }
                        GridLayout {
                            anchors.horizontalCenter: parent.horizontalCenter
                            columns: 5; columnSpacing: 10

                            Repeater { model: 5
                                delegate: TextField {
                                    property int addr: model.index  // 0~4
                                    width: 100
                                    readOnly: true
                                    text: "0x0"                   // 초기값
                                    Component.onCompleted: {
                                        fields[addr] = this
                                    }
                                }
                            }
                        }

                        /* Write 영역 (5~9) */
                        Label { text: "Write 영역 (5~9)"; x: 30 }
                        GridLayout {
                            anchors.horizontalCenter: parent.horizontalCenter
                            columns: 5; columnSpacing: 10

                            Repeater { model: 5
                                delegate: TextField {
                                    property int addr: 5 + model.index  // 5~9
                                    width: 100
                                    readOnly: true
                                    text: "0x0"                       // 초기값
                                    Component.onCompleted: {
                                        fields[addr] = this
                                    }
                                }
                            }
                        }

                        /* 로그 */
                        ScrollView {
                            height: 120
                            anchors.left: parent.left; anchors.leftMargin: 30
                            anchors.right: parent.right; anchors.rightMargin: 30
                            clip: true

                            TextArea {
                                id: logArea
                                width: parent.width; height: parent.height
                                readOnly: true; wrapMode: TextEdit.Wrap
                                text: logTxt
                                onTextChanged: cursorPosition = length
                            }
                        }

                        Button {
                            text: "Clear Log"
                            anchors.left: parent.left; anchors.leftMargin: 30
                            onClicked: logTxt = ""
                        }
                    }
                }
            }
        }
    }
}
