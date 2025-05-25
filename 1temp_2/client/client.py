import asyncio, logging, os, sys
from typing import Dict, List

from PySide2.QtCore    import QObject, Signal, Slot, Property
from PySide2.QtWidgets import QApplication
from PySide2.QtQml     import QQmlApplicationEngine
from qasync            import QEventLoop

from pymodbus.client   import AsyncModbusTcpClient
from pymodbus.framer.socket_framer import ModbusSocketFramer


# Const
SERVER_HOST               = "localhost" # Modbus 서버 주소
SERVER_PORT               = 15050   # 포트
READ_INTERVAL_SEC         = 3                    # READ 주기 (초)
READ_START_ADDR           = 0                    #  0~4 읽기
WRITE_START_ADDR          = 5                    #  5~9 쓰기
RECONNECT_DELAY           = 1      # 첫 재시도 간격(초)
RECONNECT_DELAY_MAX       = 30     # 최대 간격(초)


logging.basicConfig(format="%(asctime)s %(levelname)-8s %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)


# Device 객체 
class Device(QObject):
    # Unit-ID 하나 담당: 주기 READ + WRITE API
    readReady = Signal(str, list)     # unit, [{addr,val},…]
    logSignal = Signal(str, str)      # unit, msg

    def __init__(self, unit: int, client: AsyncModbusTcpClient, parent=None):
        super().__init__(parent)
        self.unit, self.client = unit, client
        # 독립 READ 루프 시작
        asyncio.create_task(self._loop())

    async def _loop(self):
        # READ_INTERVAL_SEC 마다 0x03 READ(주소 0~4)

        disconnected = False     # 로그 중복 방지용 플래그

        while True:
            # 1) 연결 상태 점검 ─────────────────────────
            if not self.client.connected:          # ★ 연결 끊김
                if not disconnected:
                    self.logSignal.emit(str(self.unit), "[WARN] 연결 끊김 → READ 일시중단")
                    disconnected = True
                await asyncio.sleep(1)          # 1 초 뒤 다시 확인
                continue                        # → while True 맨 위로
            else:
                if disconnected:                # 복구된 경우
                    self.logSignal.emit(str(self.unit), "[INFO] 연결 복구 → READ 재개")
                    disconnected = False

            # 2) 정상 연결이면 READ 수행 ────────────────
            try:
                res = await self.client.read_holding_registers(
                    address=READ_START_ADDR,
                    count=5,
                    slave=self.unit,
                )
                if res.isError():
                    raise Exception(res)

                regs = res.registers
                data = [{"addr": READ_START_ADDR + i, "val": v}
                        for i, v in enumerate(regs)]
                self.readReady.emit(str(self.unit), data)
                self.logSignal.emit(str(self.unit),
                                    "[READ] " + str(regs))

            except Exception as e:
                # pymodbus 가 내부에서 소켓을 끊어 버리면
                # 다음 루프에서 self.cli.connected 가 False 가 됨
                self.logSignal.emit(str(self.unit),
                                    "[ERR READ] " + str(e))

            await asyncio.sleep(READ_INTERVAL_SEC)
    # WRITE API: QML 슬롯에서 호출
    async def write_single(self, addr: int, val: int):
        try:
            await self.client.write_register(addr, val, slave=self.unit)
            self.logSignal.emit(str(self.unit),
                                f"[WRITE1] addr={addr} val={val}")
        except Exception as e:
            self.logSignal.emit(str(self.unit), "[ERR WRITE1] " + str(e))

    async def write_multi(self, vals: List[int]):
        # 멀티 0x10 (주소 5~9)
        try:
            await self.client.write_registers(
                WRITE_START_ADDR, vals, slave=self.unit)                # addr=5
            self.logSignal.emit(str(self.unit),
                                "[WRITE_N] vals=" + str(vals))
        except Exception as e:
            self.logSignal.emit(str(self.unit), "[ERR WRITE_N] " + str(e))


# Backend (QML 노출)
class Backend(QObject):
    readData  = Signal(str, list)      # unit, list<{addr,val}>
    logSignal = Signal(str, str)       # unit, msg
    statusChanged = Signal()

    def __init__(self):
        super().__init__()
        self._status = "대기 중…"
        self.devices: Dict[int, Device] = {}
        self.client = None

    # QML 바인딩용 상태 문자열
    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

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
            dev = Device(unit, client, parent=self)
            dev.readReady.connect(self.readData)
            dev.logSignal.connect(self.logSignal)
            self.devices[unit] = dev

        self._status = "연결 완료"
        self.statusChanged.emit()

        # 연결체크 함수 -> 연결 끊기면 재연결 시도
        asyncio.create_task(self._check_connection())

    async def _check_connection(self):
        backoff = RECONNECT_DELAY
        while True:
            if not self.client.connected:              # .connected 는 bool
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
                await asyncio.sleep(1)                 # 1 초마다 체크


    # ── QML 슬롯: WRITE 요청 ──
    @Slot(str, int, int)
    def writeSingle(self, unit_s: str, addr: int, val: int):
        # 0x06 싱글 WRITE (허용 주소: 5~9)
        if not (WRITE_START_ADDR <= addr < WRITE_START_ADDR + 5):
            return  # 범위 외 → 무시
        if self.client.connect():
            asyncio.create_task(self.devices[int(unit_s)].write_single(addr, val))
        else:
            log.error("DisConnected")

    @Slot(str, list)
    def writeMulti(self, unit_s: str, vals):
        # 0x10 멀티 WRITE (5개 값이 모두 채워졌을 때 호출)
        # 항상 주소 5 부터 연속 5개에 기록한다.

        ints = [int(v) for v in vals if str(v).strip() != ""]
        if len(ints) != 5:
            return
        if self.client.connect():
            asyncio.create_task(self.devices[int(unit_s)].write_multi(ints))
        else:
            log.erroe("DisConnected")


# main
def main():
    app  = QApplication(sys.argv)
    loop = QEventLoop(app); asyncio.set_event_loop(loop)

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
