from pymodbus.server.sync import ModbusTcpServer
from pymodbus.framer.socket_framer import ModbusSocketFramer
from pymodbus.datastore import ModbusServerContext, ModbusSlaveContext
from pymodbus.datastore import ModbusSequentialDataBlock
import sqlite3
import logging

def format_hex(value):
    return f"0x{value:02X}"  # 2자리 대문자 16진수

# DB 초기화 및 연결
def init_db():
    conn = sqlite3.connect("modbus_slave.db", check_same_thread=False)  # 스레드 허용
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS holding_registers (
            address TEXT PRIMARY KEY,  -- 주소 TEXT (16진수 문자열)
            value TEXT                 -- 값 TEXT (16진수 문자열)
        )
    """)
    # 기본 데이터 (주소 0~20)
    for addr in range(100):
        hex_addr = format_hex(addr)
        hex_val = format_hex((addr + 1) * 10)
        cursor.execute("INSERT OR IGNORE INTO holding_registers (address, value) VALUES (?, ?)", (hex_addr, hex_val))
    conn.commit()
    return conn, cursor

# DB에서 레지스터 값 읽기
def read_registers(cursor, address, count):
    hex_addresses = [format_hex(address + offset) for offset in range(count)]
    rows = []
    for hex_addr in hex_addresses:
        cursor.execute("SELECT value FROM holding_registers WHERE address = ?", (hex_addr,))
        row = cursor.fetchone()
        if row:
            rows.append(int(row[0], 16))  # 값은 정수로 반환
        else:
            rows.append(0)  # 없는 주소는 0으로
    return rows


# DB에 레지스터 값 쓰기
def write_register(cursor, address, values):
    result = []
    for offset, val in enumerate(values):
        hex_addr = format_hex(address + offset)
        hex_val = format_hex(val)
        result.append(hex_addr + " " + hex_val)
        cursor.execute("UPDATE holding_registers SET value = ? WHERE address = ?", (hex_val, hex_addr))
    return result

# 커스텀 DataBlock (DB 연동)
class DatabaseDataBlock(ModbusSequentialDataBlock):
    def __init__(self, cursor):
        self.cursor = cursor
        # 임시 초기값 (0~100 주소)
        # 해당 라이브러리 자체적으로 주소를 판단하기 때문에
        # 실제 데이터는 DB에서 직접 읽고 쓰더라도 유효성 검증을 위해 초기화 시켜줘야함
        super().__init__(0, [0]*100)

    # 오버라이드
    def getValues(self, address, count=1):
        result = read_registers(self.cursor, address - 1, count)
        print(f"getValue : {result}")
        return result

    def setValues(self, address, values):
        result = write_register(self.cursor, address - 1, values)
        self.cursor.connection.commit()  # DB 커밋
        print(f"setValues : {result}")

if __name__ == "__main__":
    logging.basicConfig()
    log = logging.getLogger()
    log.setLevel(logging.DEBUG)

    conn, cursor = init_db()

    datablock = DatabaseDataBlock(cursor)
    store = ModbusSlaveContext(hr=datablock)
    context = ModbusServerContext(slaves=store, single=True)
    # 슬레이브 직접 지정
    # context = ModbusServerContext(slaves={1: store}, single=False)

    server = ModbusTcpServer(context, address=("localhost", 5050), framer=ModbusSocketFramer)
    try:
        server.serve_forever()
    finally:
        conn.commit()
        conn.close()
