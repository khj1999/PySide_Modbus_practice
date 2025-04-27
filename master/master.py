import sys
import os
from PySide2.QtWidgets import QApplication
from PySide2.QtQml import QQmlApplicationEngine
from PySide2.QtCore import QObject, Signal, Property, Slot
from pymodbus.client.sync import ModbusTcpClient

class Backend(QObject):
    dataChanged = Signal()

    def __init__(self):
        super().__init__()
        self._data = ""
        self.client = ModbusTcpClient("localhost", port=5050)
        self.client.connect()


    @Property(str, notify=dataChanged)
    def data(self):
        return self._data

    def setData(self, value):
        if self._data != value:
            self._data = value
            self.dataChanged.emit()

    def formatPacket(self, pdu):
        return ' '.join(f'{b:02X}' for b in pdu)
    
    def formatHexValue(self, value):
        return f"0x{value:02X}"  # 대문자 + 2자리 고정

    @Slot(str, str)
    def readRegisters(self, hex_address, hex_count):
        try:
            address = int(hex_address, 16)
            count = int(hex_count, 16)
            result = self.client.read_holding_registers(address, count, unit=0)
            if not result.isError():
                hex_values = [self.formatHexValue(val) for val in result.registers]  # 수정
                raw_response = self.formatPacket(result.encode())
                self.setData(f"Response: {hex_values}\nRaw: {raw_response}")
            else:
                self.setData(f"Read Error: {result}")
        except ValueError:
            self.setData("Invalid Hex Input")

    @Slot(str, str)
    def writeSingleRegister(self, hex_address, hex_value):
        try:
            address = int(hex_address, 16)
            value = int(hex_value, 16)
            result = self.client.write_register(address, value, unit=0)
            if not result.isError():
                raw_request = self.formatPacket(result.request.encode())
                raw_response = self.formatPacket(result.encode())
                self.setData(f"Write Single OK\nRequest: {raw_request}\nResponse: {raw_response}")
            else:
                self.setData(f"Write Single Error: {result}")
        except ValueError:
            self.setData("Invalid Hex Input")

    @Slot(str, str)
    def writeMultipleRegisters(self, hex_address, hex_values):
        try:
            address = int(hex_address, 16)
            # 쉼표로 구분된 16진수 값들을 리스트로 변환
            values = [int(val.strip(), 16) for val in hex_values.split(",")]

            result = self.client.write_registers(address, values, unit=0)
            if not result.isError():
                raw_request = self.formatPacket(result.request.encode())
                raw_response = self.formatPacket(result.encode())
                hex_vals = [self.formatHexValue(v) for v in values]
                self.setData(f"Write Multiple OK {hex_vals}\nRequest: {raw_request}\nResponse: {raw_response}")
            else:
                self.setData(f"Write Multiple Error: {result}")
        except ValueError:
            self.setData("Invalid Hex Input")



if __name__ == "__main__":
    app = QApplication(sys.argv)
    engine = QQmlApplicationEngine()

    # master.qml 로드 (절대경로)
    qml_file = os.path.join(os.path.dirname(__file__), "master.qml")
    engine.load(qml_file)

    backend = Backend()
    engine.rootContext().setContextProperty("backend", backend)

    if not engine.rootObjects():
        sys.exit(-1)
    sys.exit(app.exec_())
