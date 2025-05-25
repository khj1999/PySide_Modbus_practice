import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Window 2.15

Window {
    id: root
    width: 1200;  height: 900;  visible: true
    title: "Modbus Client  (READ 0~4  /  WRITE 5~9)"

    // 상수
    property string fcWrite1 : "0x06"
    property string fcWriteN : "0x10"
    property var    devices  : ["Device 1", "Device 2", "Device 3"]

    // 스크롤 전체
    ScrollView { anchors.fill: parent
        Column { width: root.width; spacing: 30; padding: 20

            // 3개 (Unit-ID 1,2,3)
            Repeater { model: devices

                Rectangle {
                    width : parent.width - 60
                    height: body.implicitHeight + 40
                    color : "#f0f0f0"; radius: 10
                    border.color: "gray"; border.width: 1

                    // 카드별 상태 
                    property string unitId : (index + 1).toString()
                    property var    readFlds    : []   // addr 0~4
                    property var    writeFlds   : []   // addr 5~9
                    property var    writeCache  : []   // 값 캐시
                    property string logTxt      : ""
                    property bool   useMultiWrite : false

                    // Device → QML 신호 수신
                    Connections {
                        target: backend

                        /* READ 응답(0~4) */
                        function onReadData(u, list) {
                            if (u !== unitId || readFlds.length < 5) return;
                            for (var i = 0; i < list.length; ++i) {
                                var idx = list[i].addr;        // 0~4
                                if (idx >= 0 && idx < 5)
                                    readFlds[idx].text =
                                        "0x" + list[i].val.toString(16).toUpperCase();
                            }
                        }

                        /* 백엔드 로그 */
                        function onLogSignal(u, msg) {
                            if (u !== unitId) return;
                            logTxt += msg + "\n";
                        }
                    }


                    // 멀티 쓰기 조건 검사 & 전송
                    function sendMultiIfReady() {
                        if (!useMultiWrite)  return;
                        var vals = [];
                        for (var i = 0; i < 5; ++i) {
                            var v = writeCache[i];
                            if (v === undefined || v.trim() === "")
                                return;              // 아직 빈칸
                            vals.push(v);
                        }
                        backend.writeMulti(unitId, vals);      // addr 5 부터
                        logTxt += "[WRITE_N] " + vals.join(" ") + "\n";
                    }

                    // 카드 내부 레이아웃
                    Column {
                        id: body
                        width: parent.width - 40
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.margins: 20
                        spacing: 12

                        Rectangle { width: parent.width; height: 5; color: "transparent" }

                        // 제목
                        Label {
                            text: modelData
                            width: parent.width
                            font.bold: true; font.pixelSize: 18
                            horizontalAlignment: Text.AlignHCenter
                        }


                        // (1) READ 0~4   ─ 위쪽
                        Label { text: "Read 영역 (0~4) [자동]" ; x:30 }

                        GridLayout {
                            anchors.horizontalCenter: parent.horizontalCenter
                            columns: 5; columnSpacing: 10
                            Repeater {
                                model: 5
                                delegate: TextField {
                                    id: rd
                                    width: 100; readOnly: true; text: "--"
                                    Component.onCompleted: readFlds[model.index] = rd
                                }
                            }
                        }

                        // (2) WRITE 5~9  ─ 아래쪽
                        Label { text: "Write 영역 (5~9) [수동]" ; x:30 }

                        GridLayout {
                            anchors.horizontalCenter: parent.horizontalCenter
                            columns: 5; columnSpacing: 10
                            Repeater {
                                model: 5
                                delegate: TextField {
                                    id: wt
                                    width: 100; text: ""

                                    Component.onCompleted: {
                                        writeFlds[model.index] = wt;
                                        writeCache[model.index] = "";
                                    }

                                    onEditingFinished: {
                                        writeCache[model.index] = text;
                                        if (text.trim() !== "")
                                            backend.writeSingle(unitId,
                                                5 + model.index,          // addr 5~9
                                                parseInt(text));
                                        sendMultiIfReady();
                                    }
                                }
                            }
                        }

                        // 옵션 & 로그
                        CheckBox {
                            text: "멀티 쓰기 (0x10) 사용"
                            anchors.left: parent.left; anchors.leftMargin: 30
                            onCheckedChanged: {
                                useMultiWrite = checked;
                                sendMultiIfReady();
                            }
                        }

                        ScrollView {
                            height: 120
                            anchors.left: parent.left;  anchors.leftMargin: 30
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