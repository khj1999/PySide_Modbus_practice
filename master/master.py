import sys
import os
from PySide2.QtWidgets import QApplication
from PySide2.QtQml import QQmlApplicationEngine
from PySide2.QtCore import QObject, Signal, Property, Slot
from pymodbus.client.sync import ModbusTcpClient
from pymodbus.framer.socket_framer import ModbusSocketFramer
from pymodbus.register_read_message import ReadHoldingRegistersRequest # 0x03
from pymodbus.register_write_message import WriteSingleRegisterRequest # 0x06
from pymodbus.register_write_message import WriteMultipleRegistersRequest # 0x10

class Backend(QObject):
    dataChanged = Signal()

    def __init__(self):
        super().__init__()
        self._data = ""
        # self.client = ModbusTcpClient("localhost", port=5050)
        self.client = ModbusTcpClient("localhost", port=5050, framer=ModbusSocketFramer)
        self.client.connect()

    @Property(str, notify=dataChanged)
    def data(self):
        return self._data

    def setData(self, value):
        if self._data != value:
            self._data = value
            self.dataChanged.emit()

    def parsePacket(self, pdu):
        return ' '.join(f"{b:02X}" for b in pdu)

    # 0x03
    @Slot(str, str)
    def readRegisters(self, hex_address, hex_count):
        try:
            address = int(hex_address, 16)
            count = int(hex_count, 16)

            # 요청 PDU 생성
            request = ReadHoldingRegistersRequest(address, count)
            request_pdu = request.encode()

            # 실제 요청
            result = self.client.read_holding_registers(address, count, unit=1)

            if not result.isError():
                response_pdu = result.encode()
                output = (
                    f"[Request] 03 {self.parsePacket(request_pdu)}\n"
                    f"[Response] 03 {self.parsePacket(response_pdu)}"
                )
                self.setData(output)
            else:
                self.setData(f"Read Error: {result}")
        except Exception as e:
            self.setData(f"Exception: {e}")

    # 0x06
    @Slot(str, str)
    def writeSingleRegister(self, hex_address, hex_value):
        try:
            address = int(hex_address, 16)
            value = int(hex_value, 16)

            result = self.client.write_register(address, value, unit=1)

            if not result.isError():
                request_pdu = result.request.encode()
                response_pdu = result.encode()
                output = (
                    f"[Request] 06 {self.parsePacket(request_pdu)}\n"
                    f"[Response] 06 {self.parsePacket(response_pdu)}"
                )
                self.setData(output)
            else:
                self.setData(f"Write Single Error: {result}")
        except Exception as e:
            self.setData(f"Exception: {e}")

    # 0x10
    @Slot(str, str)
    def writeMultipleRegisters(self, hex_address, hex_values):
        try:
            address = int(hex_address, 16)
            values = [int(v.strip(), 16) for v in hex_values.split(",")]

            # 요청 PDU 직접 생성
            request = WriteMultipleRegistersRequest(address, values)
            request_pdu = request.encode()

            # 실제 요청
            result = self.client.write_registers(address, values, unit=1)

            if not result.isError():
                response_pdu = result.encode()
                output = (
                    f"[Request] 10 {self.parsePacket(request_pdu)}\n"
                    f"[Response] 10 {self.parsePacket(response_pdu)}"
                )
                self.setData(output)
            else:
                self.setData(f"Write Multiple Error: {result}")
        except Exception as e:
            self.setData(f"Exception: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    engine = QQmlApplicationEngine()
    qml_file = os.path.join(os.path.dirname(__file__), "master.qml")
    engine.load(qml_file)
    backend = Backend()
    engine.rootContext().setContextProperty("backend", backend)
    if not engine.rootObjects():
        sys.exit(-1)
    sys.exit(app.exec_())
