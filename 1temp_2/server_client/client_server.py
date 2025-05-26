"""
PySide2 + qasync + pymodbus-3.x  로 구현한 **Modbus TCP Slave**
Unit-ID : 1, 2, 3
레지스터 0–4 : 초기값 0  → 마스터가 READ
레지스터 5–9 : 기본 0   → 마스터 WRITE 시 값 저장·UI 갱신
슬레이브는 자체적으로 READ/WRITE 요청을 보내지 않음
"""
import asyncio, inspect, logging, os, sys
from typing import Dict, List

from PySide2.QtCore    import (QObject, Signal, Property, QModelIndex,
                               QAbstractListModel, Qt)
from PySide2.QtWidgets import QApplication
from PySide2.QtQml     import QQmlApplicationEngine
from qasync            import QEventLoop

from pymodbus.server.async_io import StartAsyncTcpServer
from pymodbus.datastore       import ModbusSlaveContext, ModbusServerContext

# 설정 
SERVER_HOST, SERVER_PORT = "0.0.0.0", 15050
UNIT_IDS                 = (1, 2, 3)

REG_CNT      = 10
READ_ONLY    = range(0, 5)   # 0–4
WRITEABLE    = range(5, 10)  # 5–9
INIT_VALUES  = [0]*5         # 0–4 기본값

logging.basicConfig(format="%(asctime)s %(levelname)-8s %(message)s",
                    level=logging.INFO)
log = logging.getLogger(__name__)

# Device 모델
class Device(QAbstractListModel):
    ValueRole = Qt.UserRole + 1
    _roles    = {ValueRole: b"value"}

    def __init__(self, unit: int, backend: "Backend"):
        super().__init__(backend)
        self.unit, self.backend = unit, backend
        self.memo = INIT_VALUES + [0]*(REG_CNT - len(INIT_VALUES))

    # QAbstractListModel 구현
    def rowCount(self, parent=QModelIndex()):
        return REG_CNT
    
    def roleNames(self):
        return self._roles
    
    def data(self, index, role):
        if role == Device.ValueRole and index.isValid():
            return f"0x{self.memo[index.row()]:X}"
        return None

    # 내부 : 값 저장 + UI 알림
    def _set_local(self, addr: int, val: int):
        if 0 <= addr < REG_CNT and self.memo[addr] != val:
            self.memo[addr] = val
            self.dataChanged.emit(self.index(addr), self.index(addr),
                                  [Device.ValueRole])
            self.backend.readSignal.emit(str(self.unit), [{"addr": addr, "val": val}])

# DataBlock
class ListBlock:
    def __init__(self, device: Device):
        self.device = device

    def validate(self, addr, cnt=1):
        return 0 <= addr < REG_CNT and 0 < cnt <= REG_CNT-addr
    
    def getValues(self, addr, cnt=1):
        return [self.device.memo[addr+i] for i in range(cnt)]
    
    def setValues(self, addr, values: List[int]):
        for i, v in enumerate(values):
            if (addr+i) in WRITEABLE:
                self.device._set_local(addr+i, v)

# Backend
class Backend(QObject):
    readSignal    = Signal(str, list)   # unit, [{addr,val}]
    statusChanged = Signal()

    def __init__(self):
        super().__init__()
        self._status = "Initializing…"
        self.devices: Dict[int, Device] = {}

    # QML 노출 프로퍼티
    @Property(str, notify=statusChanged)
    def status(self): return self._status

    @Property("QVariantList")
    def deviceModels(self): return list(self.devices.values())

    # 비동기 초기화
    async def init(self):
        # 1) Device + 데이터스토어
        slaves = {}
        for unit in UNIT_IDS:
            device = Device(unit, self)
            self.devices[unit] = device
            slaves[unit] = ModbusSlaveContext(hr=ListBlock(device), zero_mode=True)

        context = ModbusServerContext(slaves=slaves, single=False)

        # 2) 서버 기동 (버전별 인자 호환)
        await StartAsyncTcpServer(context, address=(SERVER_HOST, SERVER_PORT))

        # 3) 초기값 0 → UI 전송
        for unit in UNIT_IDS:
            for a, v in enumerate(self.devices[unit].memo):
                self.readSignal.emit(str(unit), [{"addr": a, "val": v}])

        self._status = f"Serving on {SERVER_HOST}:{SERVER_PORT}"
        self.statusChanged.emit()
        log.info(self._status)

def main():
    app  = QApplication(sys.argv)
    loop = QEventLoop(app); asyncio.set_event_loop(loop)

    eng  = QQmlApplicationEngine()
    backend = Backend()
    eng.rootContext().setContextProperty("backend", backend)

    qml_file = os.path.join(os.path.dirname(__file__), "slave_refactor.qml")
    eng.load(qml_file)
    if not eng.rootObjects(): sys.exit("QML 로드 실패")

    loop.create_task(backend.init())
    with loop: loop.run_forever()

if __name__ == "__main__":
    main()
