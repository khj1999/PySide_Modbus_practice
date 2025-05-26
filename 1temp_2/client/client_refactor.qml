/* ===================================================================== *
 *  client_refactor.qml – READ(0~4) 위 · WRITE(5~9) 아래
 * ===================================================================== */
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Window 2.15

Window {
    id: root
    width: 1200;  height: 900
    visible: true
    title: "Modbus Client (READ 0~4 / WRITE 5~9)"

    // 단순 라벨용 상수
    property var devices: ["Device 1", "Device 2", "Device 3"]

    /* ──────────────── 스크롤 전체 ──────────────── */
    ScrollView {
        anchors.fill: parent

        Column {
            width: root.width
            spacing: 30
            padding: 20

            /* 3 개 장비 카드 (Unit-ID 1,2,3) */
            Repeater {
                model: devices

                Rectangle {
                    /* 카드 비주얼 */
                    width: parent.width - 60
                    height: body.implicitHeight + 40
                    color: "#f0f0f0"
                    radius: 10
                    border.color: "gray"
                    border.width: 1

                    /* ───── 카드별 상태 ───── */
                    property string unitId : (index + 1).toString()
                    property var    fields : []     // TextField 레퍼런스 0~9
                    property string logTxt : ""
                    property bool   useMultiWrite: false    // 아직 미사용

                    /* ---------- 백엔드 시그널 ---------- */
                    Connections {
                        target: backend

                        /* READ(0~4) 응답 */
                        function onReadReady(u, list) {
                            // console.log("Device " + u + " " + list)
                            
                            if (u !== unitId || fields.length < 5) return;
                            for (var i = 0; i < list.length; ++i) {
                                var a = list[i].addr;          // 0~4
                                if (a >= 0 && a < 5 && fields[a])
                                    fields[a].text =
                                        "0x" + list[i].val.toString(16).toUpperCase();
                            }
                        }

                        /* 로그 */
                        function onLogSignal(u, msg) {
                            if (u === unitId) logTxt += msg + "\n";
                        }
                    }

                    /* ─────────── 카드 내부 레이아웃 ─────────── */
                    Column {
                        id: body
                        width: parent.width - 40
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.margins: 20
                        spacing: 12

                        Rectangle { height: 5; width: 1; color: "transparent" }

                        /* 제목 */
                        Label {
                            text: modelData        // "Device 1" ...
                            width: parent.width
                            font.pixelSize: 18; font.bold: true
                            horizontalAlignment: Text.AlignHCenter
                        }

                        /* ───── READ 0~4 ───── */
                        Label { text: "Read 영역 (0~4) [자동]"; x: 30 }

                        GridLayout {
                            anchors.horizontalCenter: parent.horizontalCenter
                            columns: 5; columnSpacing: 10

                            Repeater {
                                model: 5
                                delegate: TextField {
                                    property int addr: model.index          // 0~4
                                    width: 100
                                    readOnly: true
                                    text: "--"

                                    Component.onCompleted: {
                                        if (!fields[addr])          // 중복 등록 방지
                                            fields[addr] = this
                                    }
                                }
                            }
                        }

                        /* ───── WRITE 5~9 ───── */
                        Label { text: "Write 영역 (5~9) [자동]"; x: 30 }

                        GridLayout {
                            anchors.horizontalCenter: parent.horizontalCenter
                            columns: 5; columnSpacing: 10
                            Repeater {
                                model: 5
                                delegate: TextField {
                                    property int addr: 5 + model.index      // 5~9
                                    width: 100
                                    placeholderText: "0x00"
                                    inputMethodHints: Qt.ImhFormattedNumbersOnly

                                    Component.onCompleted: {
                                        if (!fields[addr])
                                            fields[addr] = this
                                    }

                                    // 네트워크 전송 X, 메모리만 반영
                                    onEditingFinished: {
                                        if (text.trim() === "") return;
                                        backend.storeLocal(unitId, addr, parseInt(text, 16))
                                    }
                                }
                            }
                        }

                        /* 옵션 & 로그 */
                        CheckBox {
                            text: "멀티 쓰기 (0x10) 사용"
                            anchors.left: parent.left
                            anchors.leftMargin: 30
                            onCheckedChanged: {
                                backend.setUseMultiWrite(unitId, checked)
                            }
                        }

                        ScrollView {
                            height: 120
                            anchors.margins: 30
                            anchors.left: parent.left
                            anchors.right: parent.right
                            clip: true

                            TextArea {
                                id: logArea
                                width: parent.width
                                height: parent.height
                                readOnly: true
                                wrapMode: TextEdit.Wrap
                                text: logTxt
                                onTextChanged: cursorPosition = length
                            }
                        }

                        Button {
                            text: "Clear Log"
                            anchors.left: parent.left; anchors.leftMargin: 30
                            onClicked: logTxt = ""
                        }
                    } // Column(body)
                }     // Rectangle(card)
            }         // Repeater(devices)
        }             // Column(contents)
    }                 // ScrollView
}