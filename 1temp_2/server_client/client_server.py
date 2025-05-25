# -*- coding: utf-8 -*-
"""
Backend:  각 Device 객체가 독립적으로 주기 READ.
logSignal(unit, msg)  /  readData(unit, list)  → QML
"""
import asyncio, logging, os, sqlite3, sys # 표준 라이브러리 임포트
from typing import Dict, List, Sequence # 타입 힌팅을 위한 모듈 임포트

# PySide2 관련 모듈 임포트
from PySide2.QtCore import QObject, Signal, Slot, Property # Qt 객체, 시그널, 슬롯, 프로퍼티
from PySide2.QtWidgets import QApplication # GUI 애플리케이션
from PySide2.QtQml import QQmlApplicationEngine # QML 엔진
from qasync import QEventLoop # Qt 이벤트 루프와 asyncio 통합 라이브러리

# Pymodbus 관련 모듈 임포트
from pymodbus.client import AsyncModbusTcpClient # 비동기 Modbus TCP 클라이언트
from pymodbus.server import StartAsyncTcpServer # 비동기 Modbus TCP 서버 시작 함수
from pymodbus.datastore import ( # Modbus 데이터 저장소 관련 클래스
    ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
)
from pymodbus.framer.socket_framer import ModbusSocketFramer # Modbus TCP 통신용 프레이머


# ───────────────────────────────────────────
# 전역 상수 정의
DB_PATH, SLAVE_PORT = "modbus_slave.db", 15050 # SQLite 데이터베이스 파일 경로와 Modbus 슬레이브(서버) 포트 번호
READ_INTERVAL_SEC = 3 # 각 Device 객체의 주기적인 READ 동작 간격 (초 단위)

# 로깅 설정
logging.basicConfig(format="%(asctime)s %(levelname)-8s %(message)s", # 로그 메시지 형식 지정
                      level=logging.INFO) # 로그 레벨을 INFO 이상으로 설정
log = logging.getLogger(__name__) # 현재 모듈에 대한 로거 객체 생성


def to_hex(v: int) -> str:          # 정수 값을 두 자리 16진수 문자열(예: "0x0A")로 변환하는 헬퍼 함수
    return f"0x{v:02X}"


# ── SQLite ↔ DataBlock ─────────────────────
# Modbus 데이터 블록과 SQLite 데이터베이스 간의 상호작용을 정의하는 클래스
class DBDataBlock(ModbusSequentialDataBlock):
    # 생성자: SQLite 커서와 테이블 이름을 받아 초기화
    def __init__(self, cur: sqlite3.Cursor, table: str):
        super().__init__(0, [0]*100) # 부모 클래스(ModbusSequentialDataBlock) 초기화. 주소 0부터 100개의 레지스터, 초기값 0
        self.cur, self.table = cur, table # SQLite 커서와 테이블 이름 저장

    # Modbus 마스터가 레지스터 값을 읽으려 할 때 호출되는 메소드
    def getValues(self, addr: int, cnt: int = 1) -> List[int]:
        out = [] # 결과를 저장할 리스트
        for i in range(cnt): # 요청된 개수(cnt)만큼 반복
            # DB에서 해당 주소(addr+i)의 값을 조회
            self.cur.execute(f"SELECT value FROM {self.table} WHERE address=?",
                             (to_hex(addr + i),)) # 주소는 16진수 문자열로 변환하여 사용
            row = self.cur.fetchone() # 조회 결과 가져오기
            out.append(int(row[0], 16) if row else 0) # 값이 있으면 16진수 문자열을 정수로 변환하여 추가, 없으면 0 추가
        return out # 값 리스트 반환

    # Modbus 마스터가 레지스터 값을 쓰려 할 때 호출되는 메소드
    def setValues(self, addr: int, vals: Sequence[int]):
        for i, v in enumerate(vals): # 쓰려는 값들(vals)에 대해 반복
            # DB의 해당 주소(addr+i)에 값을 업데이트
            self.cur.execute(f"UPDATE {self.table} SET value=? WHERE address=?",
                             (to_hex(v), to_hex(addr + i))) # 값과 주소를 16진수 문자열로 변환
        self.cur.connection.commit() # DB 변경사항 커밋 (실제 저장)


# SQLite 데이터베이스를 초기화하는 함수
def init_db():
    # DB 연결 (check_same_thread=False는 멀티스레드 환경에서 SQLite 사용 시 권장)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = con.cursor() # 커서 생성
    for sid in (1, 2, 3): # 슬레이브 ID 1, 2, 3에 대해 반복
        tbl = f"holding_registers_{sid}" # 각 슬레이브 ID별 테이블 이름 (예: holding_registers_1)
        # 테이블 생성 SQL (테이블이 이미 존재하지 않으면 생성)
        cur.execute(f"CREATE TABLE IF NOT EXISTS {tbl}(address TEXT PRIMARY KEY,value TEXT)")
        for a in range(10): # 주소 0부터 9까지 10개 레지스터에 대해
            # 초기 데이터 삽입 SQL (데이터가 이미 존재하면 무시)
            cur.execute(f"INSERT OR IGNORE INTO {tbl} VALUES(?,?)",
                        (to_hex(a), to_hex((a + 1) * 10 + sid))) # 주소와 초기값 설정 (예: sid=1, a=0 -> 값 0x0A)
    con.commit() # DB 변경사항 커밋
    return con, cur # 연결 객체와 커서 객체 반환


# ── Device 객체 ────────────────────────────
# 개별 Modbus 장치(슬레이브)를 나타내는 클래스
class Device(QObject): # PySide2의 QObject를 상속받아 시그널/슬롯 기능 사용
    # 시그널 정의: QML이나 다른 객체로 정보를 전달하기 위함
    readReady = Signal(str, list)       # unit ID와 읽은 데이터([ {주소,값}, ... ])를 전달하는 시그널
    logSignal = Signal(str, str)        # unit ID와 로그 메시지를 전달하는 시그널

    # 생성자: unit ID, Modbus 클라이언트 인스턴스, 부모 객체를 인자로 받음
    def __init__(self, unit: int, client: AsyncModbusTcpClient, parent: QObject = None):
        super().__init__(parent) # 부모 클래스 생성자 호출
        self.unit, self.cli = unit, client # unit ID와 Modbus 클라이언트 저장
        asyncio.create_task(self._loop())  # ★ 객체 생성 시 비동기 _loop 메소드를 태스크로 만들어 실행 (독립적인 READ 루프 시작)

    # 주기적으로 Modbus READ 동작을 수행하는 비동기 메소드
    async def _loop(self):
        """READ_INTERVAL_SEC 마다 고정된 주소(5번지부터 5개)를 READ"""
        while True: # 무한 루프
            try:
                # Modbus 클라이언트를 사용하여 홀딩 레지스터 읽기 요청 (비동기)
                rsp = await self.cli.read_holding_registers(
                    address=5, count=5, slave=self.unit)  # address: 시작 주소, count: 읽을 개수, slave: 대상 unit ID
                if rsp.isError(): raise Exception(rsp) # 응답에 에러가 있으면 예외 발생
                regs = rsp.registers # 응답에서 레지스터 값 리스트 추출
                # QML로 전달하기 편한 형식으로 데이터 가공 ({'addr': 주소, 'val': 값}의 리스트)
                data = [{"addr": 5 + i, "val": v} for i, v in enumerate(regs)]
                self.readReady.emit(str(self.unit), data) # readReady 시그널 발생 -> 연결된 슬롯(Backend.readData)으로 전달
                self.logSignal.emit(str(self.unit), # logSignal 시그널 발생
                                    "[READ] -> %s" % regs)
            except Exception as e: # READ 동작 중 예외 발생 시
                self.logSignal.emit(str(self.unit), # 에러 로그 시그널 발생
                                    "[ERR] READ: %s" % e)
            await asyncio.sleep(READ_INTERVAL_SEC) # READ_INTERVAL_SEC 초 만큼 비동기적으로 대기

    # QML에서 수동으로 단일 레지스터 쓰기(Write Single Register, FC06)를 요청할 때 호출되는 비동기 메소드
    async def write_single(self, addr: int, val: int):
        try:
            # Modbus 클라이언트를 사용하여 단일 레지스터 쓰기 요청 (비동기)
            await self.cli.write_register(addr, val, slave=self.unit) # addr: 쓸 주소, val: 쓸 값
            self.logSignal.emit(str(self.unit), # 성공 로그 시그널 발생
                                "[WRITE1] addr=%d val=%s" % (addr, val))
        except Exception as e: # 쓰기 동작 중 예외 발생 시
            self.logSignal.emit(str(self.unit), "[ERR] WRITE1: %s" % e) # 에러 로그 시그널 발생

    # QML에서 수동으로 다중 레지스터 쓰기(Write Multiple Registers, FC16)를 요청할 때 호출되는 비동기 메소드
    async def write_multi(self, addr: int, vals: List[int]):
        try:
            # Modbus 클라이언트를 사용하여 다중 레지스터 쓰기 요청 (비동기)
            await self.cli.write_registers(addr, vals, slave=self.unit) # addr: 시작 주소, vals: 쓸 값들의 리스트
            self.logSignal.emit(str(self.unit), # 성공 로그 시그널 발생
                                "[WRITE_N] vals=%s" % vals)
        except Exception as e: # 쓰기 동작 중 예외 발생 시
            self.logSignal.emit(str(self.unit), "[ERR] WRITE_N: %s" % e) # 에러 로그 시그널 발생


# ── Backend (QML 노출 객체) ─────────────────────
# QML과 Python 로직 간의 주요 인터페이스 역할을 하는 클래스
class Backend(QObject):
    # 시그널 정의: QML UI 업데이트나 로깅을 위함
    readData  = Signal(str, list)     # Device 객체로부터 받은 READ 데이터를 QML로 전달 (unit ID, 데이터 리스트)
    logSignal = Signal(str, str)      # Device 객체로부터 받은 로그 메시지를 QML로 전달 (unit ID, 메시지)
    statusChanged = Signal()          # Backend의 상태 변경을 QML에 알리는 시그널

    def __init__(self):
        super().__init__()
        self._status = "대기 중…" # 내부 상태 변수 (초기값: "대기 중…")
        self.devices: Dict[int, Device] = {} # {unit_id: Device_instance} 형식으로 Device 객체들을 저장할 딕셔너리

    # QML에서 'status' 프로퍼티로 접근 가능하게 함. 값이 변경되면 statusChanged 시그널 발생
    @Property(str, notify=statusChanged)
    def status(self) -> str: return self._status # 현재 _status 값을 반환

    # Backend 객체의 비동기 초기화 메소드. DB 커서를 인자로 받음
    async def init(self, cur: sqlite3.Cursor):
        # 1) Modbus 슬레이브(서버) 설정 및 시작
        # 각 슬레이브 ID(1,2,3)에 대해 DBDataBlock 인스턴스 생성
        blks = {sid: DBDataBlock(cur, f"holding_registers_{sid}") for sid in (1, 2, 3)}
        # 각 슬레이브 ID에 대해 ModbusSlaveContext 생성 (데이터 블록 연결)
        slaves_ctx = {sid: ModbusSlaveContext(hr=b, zero_mode=True) for sid, b in blks.items()} # hr: holding registers
        # 여러 슬레이브 컨텍스트를 관리하는 ModbusServerContext 생성 (single=False는 다중 슬레이브 모드)
        ctx = ModbusServerContext(slaves=slaves_ctx, single=False)
        # 비동기 Modbus TCP 서버 시작 (백그라운드 태스크로 실행)
        asyncio.create_task(StartAsyncTcpServer(ctx, address=("localhost", SLAVE_PORT)))
        log.info("Slave async %d 시작", SLAVE_PORT) # 서버 시작 로그

        # 2) 비동기 Modbus TCP 클라이언트 생성 및 연결
        await asyncio.sleep(0.5)
        client = AsyncModbusTcpClient(host="localhost", port=SLAVE_PORT, # 접속할 서버 주소 및 포트
                                     framer=ModbusSocketFramer, timeout=5) # 프레이머 및 타임아웃 설정
        await client.connect() # 서버에 비동기적으로 연결
        log.info("Modbus Async 클라이언트 연결 완료")

        # 3) Device 객체 생성 및 시그널 연결
        for unit_id in (1, 2, 3): # unit ID 1, 2, 3에 대해 반복
            # Device 객체 생성. Modbus 클라이언트와 부모(Backend 자신) 전달
            dev = Device(unit_id, client, parent=self)
            # Device 객체의 시그널을 Backend 객체의 해당 시그널로 연결
            # 이렇게 하면 Device에서 발생한 시그널이 Backend를 거쳐 QML로 전달될 수 있음
            dev.readReady.connect(self.readData)  # Device의 readReady -> Backend의 readData
            dev.logSignal.connect(self.logSignal)  # Device의 logSignal -> Backend의 logSignal
            self.devices[unit_id] = dev # 생성된 Device 객체를 딕셔너리에 저장

        self._status = "초기화 완료"; self.statusChanged.emit() # 상태를 "초기화 완료"로 변경하고 QML에 알림

    # ---- QML 슬롯: QML에서의 Modbus WRITE 요청 처리 ---------------------
    # QML에서 호출 가능한 슬롯. 단일 레지스터 쓰기 요청을 처리
    @Slot(str, int, int) # 인자 타입: (str unit_id, int address, int value)
    def writeSingle(self, unit_str: str, addr: int, val: int):
        u = int(unit_str) # QML에서 받은 문자열 unit ID를 정수로 변환
        # 해당 unit ID의 Device 객체의 write1 메소드를 비동기 태스크로 실행
        asyncio.create_task(self.devices[u].write_single(addr, val))

    # QML에서 호출 가능한 슬롯. 다중 레지스터 쓰기 요청을 처리
    @Slot(str, list) # 인자 타입: (str unit_id, list values)
    def writeMulti(self, unit_str: str, vals_qml: list):
        # QML에서 받은 값 리스트(주로 문자열이나 QVariantList)를 Python 정수 리스트로 변환
        # 빈 문자열은 제외
        ints = [int(v) for v in vals_qml if str(v).strip() != ""]
        if not ints: return # 변환된 정수 리스트가 비어있으면 아무것도 하지 않음
        u = int(unit_str) # 문자열 unit ID를 정수로 변환
        # 해당 unit ID의 Device 객체의 writeN 메소드를 비동기 태스크로 실행 (시작 주소는 0으로 고정)
        asyncio.create_task(self.devices[u].write_multi(0, ints)) # TODO: 주소(0)를 QML에서 받을 수 있도록 수정 가능


# ── main ───────────────────────────────────
# 애플리케이션의 메인 실행 함수
def main():
    con, cur = init_db() # 데이터베이스 초기화 및 연결/커서 객체 가져오기

    app = QApplication(sys.argv) # PySide2 GUI 애플리케이션 객체 생성
    loop = QEventLoop(app) # qasync를 사용하여 Qt 이벤트 루프와 asyncio 이벤트 루프 통합
    asyncio.set_event_loop(loop) # asyncio의 기본 이벤트 루프를 qasync의 루프로 설정

    eng = QQmlApplicationEngine() # QML 엔진 객체 생성
    be = Backend() # Backend 객체(Python 로직) 생성
    # Backend 객체를 "backend"라는 이름으로 QML 전역 컨텍스트 프로퍼티로 등록
    # 이렇게 하면 QML에서 'backend'라는 이름으로 Backend 객체의 메소드나 프로퍼티에 접근 가능
    eng.rootContext().setContextProperty("backend", be)
    # QML 파일 로드. os.path.join으로 현재 스크립트와 같은 디렉토리에 있는 QML 파일 경로 지정
    qml_file = os.path.join(os.path.dirname(__file__), "slave_refactor.qml") # QML 파일 이름 확인 필요
    eng.load(qml_file)

    if not eng.rootObjects(): # QML 파일 로드에 실패하여 루트 객체가 없으면
        log.critical("QML 로드 실패: %s", qml_file) # 치명적 오류 로그 남기고
        sys.exit(-1) # 프로그램 종료

    # Backend의 비동기 초기화 함수(init)를 이벤트 루프에 태스크로 등록하여 실행
    # 이는 이벤트 루프가 시작된 후에 init 코루틴이 실행되도록 함
    loop.create_task(be.init(cur))

    with loop: # 이벤트 루프 시작 (애플리케이션 실행)
        loop.run_forever() # 이벤트 루프가 명시적으로 중지될 때까지 계속 실행


if __name__ == "__main__": # 이 스크립트가 직접 실행될 때
    main() # main 함수 호출