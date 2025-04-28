import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Window 2.15

Window {
    visible: true
    width: 600
    height: 600
    title: qsTr("Modbus Client")

    property string inputAddress: ""
    property string inputValue: ""
    property string inputCount: ""

    Column {
        anchors.centerIn: parent
        spacing: 10

        TextField {
            placeholderText: "Input hex address (e.g., 0x01)"
            onTextChanged: inputAddress = text
            width: 400
        }

        TextField {
            placeholderText: "Input hex values (e.g., 0x10,0x20,0x30)"
            onTextChanged: inputValue = text
            width: 400
        }

        TextField {
            placeholderText: "Input hex count (e.g., 0x03)"
            onTextChanged: inputCount = text
            width: 400
        }

        Row {
            spacing: 10

            Button {
                text: "Read Registers (0x03)"
                onClicked: backend.readRegisters(inputAddress, inputCount)
            }

            Button {
                text: "Write Single Register (0x06)"
                onClicked: backend.writeSingleRegister(inputAddress, inputValue)
            }

            Button {
                text: "Write Multiple Registers (0x10)"
                onClicked: backend.writeMultipleRegisters(inputAddress, inputValue)
            }
        }

        ScrollView {
            width: 500
            height: 200
            Text {
                text: backend.data
                wrapMode: Text.Wrap
                font.pixelSize: 16
            }
        }
    }
}