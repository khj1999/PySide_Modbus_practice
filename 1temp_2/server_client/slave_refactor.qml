import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Window 2.15

Window {
    id: root
    width: 1200; height: 900; visible: true
    minimumWidth: 1200; maximumWidth: 1200
    minimumHeight: 900;  maximumHeight: 900
    title: "Modbus Async Server & Client (Slave)"

    // WRITE 용 함수코드 상수 (READ는 Python Device가 보냄)
    property string fcWrite1 : "0x06"
    property string fcWriteN : "0x10"
    property var    devices  : ["Device 1", "Device 2", "Device 3"]

    // Scroll 전체
    ScrollView {
        anchors.fill: parent

        Column {
            width: root.width
            spacing: 30; padding: 20

            // Repeater: 디바이스 3개
            Repeater {
                model: devices         // "Device 1" 등

                Rectangle {
                    // 카드 시각적 프레임
                    width : parent.width - 60
                    height: body.implicitHeight + 40
                    color : "#f0f0f0"; radius: 10
                    border.color: "gray"; border.width: 1

                    // 카드 전용 프로퍼티 (상태 저장)
                    property string unitId  : (index + 1).toString()
                    property var    readFlds   : []   // READ TextField 객체
                    property var    writeFlds  : []   // WRITE TextField 객체
                    property var    writeCache : []   // 값 캐시(문자열)
                    property string logTxt     : ""
                    property bool   useMultiWrite : false  // 체크박스 상태

                    // 멀티 쓰기 조건 검사 -> 자동 전송
                    function sendMultiIfReady() {
                        if (!useMultiWrite) return;      // 체크 OFF
                        var list = [];
                        for (var i = 0; i < 5; ++i) {
                            var v = writeCache[i];
                            if (v === undefined || v.trim() === "")
                                return;                  // 아직 빈칸
                            list.push(v);
                        }
                        backend.writeMulti(unitId, list);  // Python 슬롯 호출
                        logTxt += "[WRITE_N] " + list.join(" ") + "\n";
                    }

                    // Backend -> QML 신호 연결
                    Connections {
                        target: backend

                        // Device READ 결과 (0.5초마다)
                        function onReadData(u, dataList) {
                            if (u !== unitId) return;      // 내 카드만
                            if (readFlds.length < 5) return;

                            for (var i = 0; i < dataList.length; ++i) {
                                var idx = dataList[i].addr - 5; // 0~4
                                if (idx >= 0 && idx < readFlds.length)
                                    readFlds[idx].text =
                                        "0x" + dataList[i].val.toString(16).toUpperCase();
                            }
                        }

                        // 로그(성공·오류)
                        function onLogSignal(u, msg) {
                            if (u !== unitId) return;
                            logTxt += msg + "\n";
                        }
                    }

                    // 카드를 구성할 Column
                    Column {
                        id: body
                        width: parent.width - 40
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.margins: 20
                        spacing: 12

                        Rectangle { width: parent.width; height: 5; color: "transparent" }

                        // 제목
                        Label {
                            text: modelData         // "Device 1"
                            width: parent.width
                            font.bold: true; font.pixelSize: 18
                            horizontalAlignment: Text.AlignHCenter
                        }

                        // Set
                        Label { text: "Write 영역 (0~4)" ; x:30 }

                        GridLayout {
                            anchors.horizontalCenter: parent.horizontalCenter
                            columns: 5; columnSpacing: 10

                            Repeater {
                                model: 5

                                delegate: TextField {
                                    id: wt
                                    width: 100
                                    text: ""        // 초기값 공백

                                    // TextField가 화면에 붙을 때 배열에 참조 저장
                                    Component.onCompleted: {
                                        writeFlds[model.index]  = wt;
                                        writeCache[model.index] = "";
                                    }

                                    // 편집 완료 → 싱글 WRITE & 멀티 검사
                                    onEditingFinished: {
                                        writeCache[model.index] = text;

                                        // 0x06 WRITE (값이 비어 있지 않을 때)
                                        if (text.trim() !== "")
                                            backend.writeSingle(
                                                unitId,      // unit
                                                model.index, // addr (0~4)
                                                parseInt(text)
                                            );

                                        // 멀티(0x10) 조건 판별
                                        sendMultiIfReady();
                                    }
                                }
                            }
                        }

                        // READ 5~9 
                        Label { text: "Read 영역 (5~9)" ; x:30 }

                        GridLayout {
                            anchors.horizontalCenter: parent.horizontalCenter
                            columns: 5; columnSpacing: 10

                            Repeater {
                                model: 5
                                delegate: TextField {
                                    id: rd
                                    width: 100; readOnly: true; text: "--"

                                    // 참조 저장 (READ 결과 갱신용)
                                    Component.onCompleted: readFlds[model.index] = rd
                                }
                            }
                        }

                        // 멀티 쓰기 체크박스
                        CheckBox {
                            text: "멀티 쓰기 (0x10) 사용"
                            anchors.left: parent.left; anchors.leftMargin: 30
                            onCheckedChanged: {
                                useMultiWrite = checked; // 상태 저장
                                sendMultiIfReady();      // 체크 ON 즉시 검사
                            }
                        }

                        // 로그 Scroll 영역
                        ScrollView {
                            height: 120
                            anchors.left: parent.left; anchors.leftMargin: 30
                            anchors.right: parent.right; anchors.rightMargin: 30
                            clip: true
                            
                            TextArea {
                                id: logArea
                                width: parent.width
                                height: parent.height
                                readOnly: true
                                wrapMode: TextEdit.Wrap
                                text: logTxt

                                // 텍스트가 바뀌면 커서를 끝으로 -> 자동 스크롤
                                onTextChanged: logArea.cursorPosition = logArea.length
                            }                            

                        }

                        // 로그 클리어 버튼
                        Button {
                            text: "Clear Log"
                            anchors.left: parent.left; anchors.leftMargin: 30
                            onClicked: logTxt = ""
                        }
                    } /* Column(body) */
                }     /* Rectangle(카드) */
            }         /* Repeater */
        }             /* Column */
    }                 /* ScrollView */
}                     /* Window */
