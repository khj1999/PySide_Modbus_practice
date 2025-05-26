"""
PySide2 + qasync + pymodbus-3.x 로 구현한 Modbus TCP Slave
- Unit-ID : 1, 2, 3
- 레지스터 0–4 : 초기값 0 → 마스터가 READ → UI에 표시
- 레지스터 5–9 : 기본 0   → 마스터 WRITE 시 값 저장·UI 갱신
- 슬레이브는 자체적으로 READ/WRITE 요청을 보내지 않음
"""
import asyncio, logging, os, sys
from typing import Dict, List

from PySide2.QtCore    import QObject, Signal, Property
from PySide2.QtWidgets import QApplication
from PySide2.QtQml     import QQmlApplicationEngine
from qasync            import QEventLoop

from pymodbus.server.async_io import StartAsyncTcpServer
from pymodbus.datastore       import ModbusSlaveContext, ModbusServerContext

# 설정
SERVER_HOST, SERVER_PORT = "0.0.0.0", 15050
UNIT_IDS                = (1, 2, 3)

REG_CNT     = 10
READ_ONLY   = range(0, 5)   # 0–4
WRITEABLE   = range(5, 10)  # 5–9
INIT_VALUES = [0] * 5       # 0–4 기본값

logging.basicConfig(format="%(asctime)s %(levelname)-8s %(message)s",
                    level=logging.INFO)
log = logging.getLogger(__name__)


class Device(QObject):
    """단순 QObject: 메모리 갱신 후 readSignal로 UI에 전달만 합니다."""
    readSignal = Signal(str, list)  # unit, [{addr, val}, …]

    def __init__(self, unit: int, parent: QObject):
        super().__init__(parent)
        self.unit = unit
        # 0–4: INIT_VALUES, 5–9: 0
        self.memo = INIT_VALUES + [0] * (REG_CNT - len(INIT_VALUES))

    def _set_local(self, addr: int, val: int):
        """마스터 WRITE 요청으로 들어온 값을 메모리에 저장하고 UI 갱신 신호 전송."""
        if 0 <= addr < REG_CNT:
            self.memo[addr] = val
            self.readSignal.emit(str(self.unit), [{"addr": addr, "val": val}])

    def _random_set(self):
        import random
        rand_vals = [random.randint(1, 100) for _ in range(REG_CNT - 5)]
        



class ListBlock:
    """pymodbus 서버용 DataBlock: Device.memo를 직접 참조합니다."""
    def __init__(self, device: Device):
        self.device = device

    def validate(self, address: int, count: int = 1) -> bool:
        return 0 <= address < REG_CNT and 0 < count <= REG_CNT - address

    def getValues(self, address: int, count: int = 1) -> List[int]:
        return [self.device.memo[address + i] for i in range(count)]

    def setValues(self, address: int, values: List[int]):
        for offset, v in enumerate(values):
            addr = address + offset
            if addr in WRITEABLE:
                self.device._set_local(addr, v)


class Backend(QObject):
    readSignal    = Signal(str, list)  # 단일 Signal로 재방출
    statusChanged = Signal()

    def __init__(self):
        super().__init__()
        self._status = "Initializing…"
        self.devices: Dict[int, Device] = {}
        self.client = None

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    async def init(self):
        # 1) 각 Unit-ID별 Device 생성 및 Signal 연결
        slaves = {}
        for uid in UNIT_IDS:
            dev = Device(uid, self)
            dev.readSignal.connect(self.readSignal)
            self.devices[uid] = dev
            slaves[uid] = ModbusSlaveContext(hr=ListBlock(dev), zero_mode=True)

        context = ModbusServerContext(slaves=slaves, single=False)

        # 2) Modbus TCP 서버 기동
        await StartAsyncTcpServer(context, address=(SERVER_HOST, SERVER_PORT))

        # 3) 초기값(0) 일괄 전송
        for uid, dev in self.devices.items():
            batch = [{"addr": i, "val": v} for i, v in enumerate(dev.memo)]
            self.readSignal.emit(str(uid), batch)

        # 상태 업데이트
        self._status = f"Serving on {SERVER_HOST}:{SERVER_PORT}"
        self.statusChanged.emit()
        log.info(self._status)


def main():
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    engine = QQmlApplicationEngine()
    backend = Backend()
    engine.rootContext().setContextProperty("backend", backend)

    engine.load(os.path.join(os.path.dirname(__file__), "slave_refactor.qml"))
    if not engine.rootObjects():
        sys.exit("QML 로드 실패")

    loop.create_task(backend.init())
    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
