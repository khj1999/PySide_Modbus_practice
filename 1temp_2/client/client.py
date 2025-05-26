import asyncio, logging, os, sys
from typing import Dict, List

from PySide2.QtCore    import QObject, Signal, Slot, Property
from PySide2.QtWidgets import QApplication
from PySide2.QtQml     import QQmlApplicationEngine
from qasync            import QEventLoop

from pymodbus.client   import AsyncModbusTcpClient
from pymodbus.framer.socket_framer import ModbusSocketFramer

# Const
SERVER_HOST      = "localhost"
SERVER_PORT      = 15050
READ_INTERVAL_SEC= 0.08
READ_START_ADDR  = 0
WRITE_START_ADDR = 5
WRITE_END_ADDR   = 10
RECONNECT_DELAY  = 1
RECONNECT_DELAY_MAX = 30

logging.basicConfig(format="%(asctime)s %(levelname)-8s %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)


class Device(QObject):
    """QAbstractListModel → QObject 로 변경, Signal만 사용"""
    readReady = Signal(str, list)   # unit, [{"addr":…, "val":…},…]
    logSignal = Signal(str, str)    # unit, message

    def __init__(self, unit, client, parent=None):
        super().__init__(parent)
        self.unit = unit
        self.client = client
        self.memo = [0]*10
        self.isMulti = False

    @Slot(bool)
    def setUseMultiWrite(self, flag):
        self.isMulti = flag

    @Slot(int, int)
    def set_local(self, addr, val):
        """QML storeLocal → 메모리 갱신 + readReady Signal 발행"""
        if WRITE_START_ADDR <= addr < WRITE_END_ADDR:
            self.memo[addr] = val
            self.readReady.emit(str(self.unit), [{"addr": addr, "val": val}])

    # 비동기 READ
    async def _read(self):
        from pymodbus.exceptions import ModbusException
        if not self.client.connected:
            await asyncio.sleep(1)
        try:
            res = await self.client.read_holding_registers(
                address=READ_START_ADDR, count=5, slave=self.unit)
            if res.isError():
                raise ModbusException(res)

            changed = []
            for i, v in enumerate(res.registers):
                self.memo[i] = v
                changed.append({"addr": i, "val": v})

            self.readReady.emit(str(self.unit), changed)
            self.logSignal.emit(str(self.unit), "[READ] -> " + str(res.registers))
        except Exception as e:
            self.logSignal.emit(str(self.unit), f"[ERR READ] {e}")
        await asyncio.sleep(READ_INTERVAL_SEC)

    # 비동기 싱글 WRITE
    async def _write_single(self, addr):
        try:
            await self.client.write_register(addr, self.memo[addr], slave=self.unit)
            self.logSignal.emit(str(self.unit),
                                f"[WRITE_SINGLE] addr={addr} val={self.memo[addr]}")
        except Exception as e:
            self.logSignal.emit(str(self.unit), "[ERR WRITE_SINGLE] " + str(e))

    # 비동기 멀티 WRITE
    async def _write_multi(self):
        try:
            vals = [self.memo[a] for a in range(WRITE_START_ADDR, WRITE_END_ADDR)]
            await self.client.write_registers(WRITE_START_ADDR, vals, slave=self.unit)
            self.logSignal.emit(str(self.unit), "[WRITE_MULTI] vals=" + str(vals))
        except Exception as e:
            self.logSignal.emit(str(self.unit), "[ERR WRITE_MULTI] " + str(e))


class Backend(QObject):
    readReady     = Signal(str, list)  # unit, [{"addr":…, "val":…},…]
    logSignal     = Signal(str, str)
    statusChanged = Signal()

    def __init__(self):
        super().__init__()
        self._status = "대기 중…"
        self.devices: Dict[int, Device] = {}
        self.client = None

    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

    @Slot(str, bool)
    def setUseMultiWrite(self, unit, flag):
        self.devices[int(unit)].setUseMultiWrite(flag)

    @Slot(str, int, int)
    def storeLocal(self, unit, addr, val):
        self.devices[int(unit)].set_local(addr, val)

    async def init(self):
        # 1) Modbus TCP 클라이언트 생성
        client = AsyncModbusTcpClient(
            host=SERVER_HOST, port=SERVER_PORT,
            framer=ModbusSocketFramer, timeout=5,
            reconnect_delay=RECONNECT_DELAY,
            reconnect_delay_max=RECONNECT_DELAY_MAX
        )
        await client.connect()
        self.client = client
        log.info("Connected to %s:%d", SERVER_HOST, SERVER_PORT)

        # 2) Device 객체 생성 및 시그널 연결
        for unit in (1,2,3):
            dev = Device(unit, client, parent=self)
            dev.readReady.connect(self.readReady)
            dev.logSignal.connect(self.logSignal)
            self.devices[unit] = dev

        self._status = "연결 완료"
        self.statusChanged.emit()

        # 3) 통신 루프
        asyncio.create_task(self._run_loop())

    async def _run_loop(self):
        backoff = RECONNECT_DELAY
        while True:
            if not self.client.connected:
                self._status = "연결 끊김 — 재시도 중…"
                self.statusChanged.emit()
                self.logSignal.emit("0", f"[WARN] reconnect in {backoff}s")
                try:
                    await self.client.connect()
                except Exception:
                    pass
                await asyncio.sleep(backoff)
                backoff = min(backoff*2, RECONNECT_DELAY_MAX)
                continue

            for unit, dev in self.devices.items():
                await dev._read()
                if not dev.isMulti:
                    for addr in range(WRITE_START_ADDR, WRITE_END_ADDR):
                        await dev._write_single(addr)
                else:
                    await dev._write_multi()


def main():
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    engine = QQmlApplicationEngine()
    backend = Backend()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(os.path.join(os.path.dirname(__file__), "client_refactor.qml"))
    if not engine.rootObjects():
        sys.exit("QML 로드 실패")

    loop.create_task(backend.init())
    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()