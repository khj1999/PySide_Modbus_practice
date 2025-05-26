import asyncio, logging, os, sys
from typing import Dict, List

from PySide2.QtCore    import QObject, Signal, Slot, Property, QAbstractListModel, Qt, QModelIndex
from PySide2.QtWidgets import QApplication
from PySide2.QtQml     import QQmlApplicationEngine
from qasync            import QEventLoop

from pymodbus.client   import AsyncModbusTcpClient
from pymodbus.framer.socket_framer import ModbusSocketFramer


# Const
SERVER_HOST               = "localhost" # Modbus 서버 주소
SERVER_PORT               = 15050   # 포트
READ_INTERVAL_SEC         = 0.08                    # READ 주기 (초)
READ_START_ADDR           = 0                    #  0~4 읽기
WRITE_START_ADDR          = 5                    #  5~9 쓰기
WRITE_END_ADDR            = 10
RECONNECT_DELAY           = 1      # 첫 재시도 간격(초)
RECONNECT_DELAY_MAX       = 30     # 최대 간격(초)


logging.basicConfig(format="%(asctime)s %(levelname)-8s %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)


class Device(QAbstractListModel):
    # 바인딩용 role
    ValueRole = Qt.UserRole + 1
    roles = {ValueRole: b"value"}

    # QML에 보낼 READ 결과 시그널(유닛, 리스트[{addr,val},…])
    readReady = Signal(str, list)
    logSignal = Signal(str, str)

    def __init__(self, unit, client, parent=None):
        super().__init__(parent)
        self.unit, self.client = unit, client
        self.memo = [0] * 10                 # 레지스터 0~9
        self.isMulti = False
        #asyncio.create_task(self._read())    # READ 루프

    def _setUseMultiWrite(self, flag):
        self.isMulti = flag
        print(f"[python] {self.unit}의 useMultiWrit 상태 : {flag}")

    def set_local(self, addr: int, val: int):
    # 메모리 변경 (write)
        if 5 <= addr < len(self.memo):
            self.memo[addr] = val
            self.dataChanged.emit(self.index(addr), self.index(addr), [Device.ValueRole])

    # QAbstractListModel 기본구현
    # 모델 항목 수를 10개로 고정
    def rowCount(self, parent=QModelIndex()):
        return 10

    # QML에서 모델 항목을 가져올 떄 호출
    def data(self, index, role):
        if role == Device.ValueRole and index.isValid():
            return f"0x{self.memo[index.row()]:04X}"
        return None

    # 값을 수정했을 때 호출
    def setData(self, index, value, role):
        if role != Device.ValueRole or not index.isValid():
            return False
        try:
            v = int(value, 0)
        except ValueError:
            return False
        self.memo[index.row()] = v
        self.dataChanged.emit(index, index, [role])
        if index.row() >= WRITE_START_ADDR:          # 5~9 → WRITE
            asyncio.create_task(self._write_single(index.row(), v))
        return True

    # def flags(self, index):
    #     return Qt.ItemIsEnabled | Qt.ItemIsEditable

    # def roleNames(self):
    #     return self.roles

    # READ Func
    async def _read(self):
        from pymodbus.exceptions import ModbusException
        if not self.client.connected:
            await asyncio.sleep(1)
        try:
            res = await self.client.read_holding_registers(address=READ_START_ADDR, count=5, slave=self.unit)
            if res.isError():
                raise ModbusException(res)

            changed = []
            for i, v in enumerate(res.registers):
                self.memo[i] = v
                self.dataChanged.emit(self.index(i), self.index(i), [Device.ValueRole])
                changed.append({"addr": i, "val": v})

            self.readReady.emit(str(self.unit), changed)
            self.logSignal.emit(str(self.unit), "[READ] -> " + str(res.registers))
            print(f"{self.unit}번 Device : {self.memo}")
        except Exception as e:
            self.logSignal.emit(str(self.unit), f"[ERR READ] {e}")
        await asyncio.sleep(READ_INTERVAL_SEC)

    # wirte single
    async def _write_single(self, addr: int):
        try:
            await self.client.write_register(addr, self.memo[addr], slave=self.unit)
            self.logSignal.emit(str(self.unit), f"[WRITE_SINGLE] addr={addr} val={self.memo[addr]}")
        except Exception as e:
            self.logSignal.emit(str(self.unit), "[ERR WRITE_SINGLE] " + str(e))

    # write multi
    async def _write_multi(self):
        # 멀티 0x10 (주소 5~9)
        try:
            vals = [self.memo[addr] for addr in range(WRITE_START_ADDR, WRITE_END_ADDR)]
            await self.client.write_registers(WRITE_START_ADDR, vals, slave=self.unit)                # addr=5
            self.logSignal.emit(str(self.unit), "[WRITE_MULTI] vals=" + str(vals))
        except Exception as e:
            self.logSignal.emit(str(self.unit), "[ERR WRITE_MULTI] " + str(e))


# Backend
class Backend(QObject):
    readReady  = Signal(str, list)      # unit, list<{addr,val}>
    logSignal = Signal(str, str)       # unit, msg
    statusChanged = Signal()
    dataFieldsChanged = Signal()

    def __init__(self):
        super().__init__()
        self._status = "대기 중…"
        self.devices: Dict[int, Device] = {}
        self.client = None

    # QML 바인딩용 상태 문자열
    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

    @Property("QVariantList")
    def deviceModels(self):
        # QML에서 backend.deviceModels 로 접근
        return list(self.devices.values())
    
    @Slot(str, bool)
    def setUseMultiWrite(self, unit: str, flag: bool):
        self.devices[int(unit)]._setUseMultiWrite(flag)
    
    @Slot(str, int, int)
    def storeLocal(self, unit_str, addr, val):
        # QML에서 호출, 단순 메모리 갱신 (5 ~ 9 Write)
        unit = int(unit_str)
        if 5 <= addr < 10:
            self.devices[unit].set_local(addr, val)

    # 비동기 초기화 (루프 시작 후 1회)
    async def init(self):
        client = AsyncModbusTcpClient(
            host=SERVER_HOST, port=SERVER_PORT,
            framer=ModbusSocketFramer, timeout=5,
            reconnect_delay=RECONNECT_DELAY,
            reconnect_delay_max=RECONNECT_DELAY_MAX
        )

        await client.connect()
        self.client = client
        log.info("Connected to %s:%d", SERVER_HOST, SERVER_PORT)

        # Unit-ID 1~3 Device 연결 객체 생성
        for unit in (1, 2, 3):
            device = Device(unit, client, parent=self)
            device.readReady.connect(self.readReady)
            device.logSignal.connect(self.logSignal)
            self.devices[unit] = device

        self._status = "연결 완료"
        self.statusChanged.emit()

        # 통신체크 쓰레드 실행 -> 연결 끊기면 재연결 시도
        asyncio.create_task(self._run_connection())

    async def _run_connection(self):
        backoff = RECONNECT_DELAY
        while True:
            if not self.client.connected:
                self._status = "연결 끊김 — 재시도 중…"
                self.statusChanged.emit()
                self.logSignal.emit("0", f"[WARN] reconnect in {backoff}s")

                try:
                    await self.client.connect()
                except Exception as e:
                    log.error("Reconnect failed: %s", e)
                else:
                    if self.client.connected:
                        self._status = "재연결 성공"
                        self.statusChanged.emit()
                        backoff = RECONNECT_DELAY      # 성공하면 간격 초기화
                        await asyncio.sleep(1)
                        continue

                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_DELAY_MAX)
            else:
                for unit in (1, 2, 3):
                    await self.devices[unit]._read()
                    if not self.devices[unit].isMulti:
                        for addr in range(WRITE_START_ADDR, WRITE_END_ADDR):
                            await self.devices[unit]._write_single(addr)
                    else:
                        await self.devices[unit]._write_multi()
                #await asyncio.sleep(1)                 # 1 초마다 체크

    # # QML WRITE 요청
    # @Slot(str, int, int)
    # def writeSingle(self, unit_str, addr, val):
    #     unit = int(unit_str)
    #     if WRITE_START_ADDR <= addr < WRITE_START_ADDR + 5 and self.client.connected:
    #         asyncio.create_task(self.devices[unit].write_single(addr, val))

    # @Slot(str, "QVariantList")
    # def writeMulti(self, unit_str, vals):
    #     unit = int(unit_str)
    #     int_list = [int(v) for v in vals if str(v).strip()]
    #     if len(int_list) == 5 and self.client.connected:
    #         asyncio.create_task(self.devices[unit].write_multi(WRITE_START_ADDR, int_list))


# main
def main():
    app  = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    engine = QQmlApplicationEngine()
    backend = Backend()
    engine.rootContext().setContextProperty("backend", backend)

    engine.load(os.path.join(os.path.dirname(__file__), "client_refactor.qml"))
    if not engine.rootObjects():
        sys.exit("QML 로드 실패")

    loop.create_task(backend.init())    # 비동기 초기화
    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()