"""電圧の換算・OCRとの照合を行い、テスト用のゲージメータ板厚を表示する。"""

import csv
import json
import math
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Thread

# CHの割当は実配線に合わせ、単位と基準2点に現場の値を記入する。
# 空の単位やNoneが残っている場合は、取得を開始しない。
CHANNELS = {
    "U1_CH1": {
        "name": "rolling_speed",
        "unit": "",
        "low_point": (None, None),
        "high_point": (None, None),
    },
    "U1_CH2": {
        "name": "load_OP",
        "unit": "",
        "low_point": (None, None),
        "high_point": (None, None),
    },
    "U1_CH3": {
        "name": "load_DR",
        "unit": "",
        "low_point": (None, None),
        "high_point": (None, None),
    },
    "U1_CH4": {
        "name": "tension_in",
        "unit": "",
        "low_point": (None, None),
        "high_point": (None, None),
    },
    "U1_CH5": {
        "name": "tension_out",
        "unit": "",
        "low_point": (None, None),
        "high_point": (None, None),
    },
    "U1_CH6": {
        "name": "bender_Inc",
        "unit": "",
        "low_point": (None, None),
        "high_point": (None, None),
    },
    "U1_CH7": {
        "name": "bender_Dec",
        "unit": "",
        "low_point": (None, None),
        "high_point": (None, None),
    },
    "U1_CH8": {
        "name": "exit_thickness",
        "unit": "",
        "low_point": (None, None),
        "high_point": (None, None),
    },
}
MAX_TIME_GAP = 0.15  # 2つのPC受領時刻の許容差（秒）。現場で調整する。
INPUT_TIMEOUT = 1.0  # 受信が止まったと判断するまでの秒数

# 板厚の出力テスト用の仮値。荷重はCH2(OP)・CH3(DR)の換算値を合計する。
GAUGE_BASE_THICKNESS_MM = 0.0  # h0: ゼロ合わせ時の基準板厚・ギャップ
GAUGE_ZERO_READING = 0.0  # r0: ゼロ合わせ時のOCR表示
GAUGE_DISPLAY_TO_MM = 1.0  # a: 表示差をmmへ換算する係数。開く方向が正。
GAUGE_ZERO_LOAD = 200.0  # P0: OP・DRの換算後と同じ荷重単位
GAUGE_MILL_STIFFNESS = 10000.0  # Mw: 圧延時の剛性。荷重単位/mm。
GAUGE_ZERO_STIFFNESS = 10000.0  # M0: ゼロ合わせ時の剛性。荷重単位/mm。


def validate_settings():
    if not CHANNELS:
        raise ValueError("CHANNELSにチャンネルと換算の設定を指定してください。")
    for seconds in (MAX_TIME_GAP, INPUT_TIMEOUT):
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError(
                "MAX_TIME_GAPとINPUT_TIMEOUTには正の秒数を指定してください。"
            )

    for channel, settings in CHANNELS.items():
        if not settings["unit"]:
            raise ValueError(f"{channel} のunitに換算後の単位を指定してください。")
        low_voltage, low_value = settings["low_point"]
        high_voltage, high_value = settings["high_point"]
        for number in (low_voltage, low_value, high_voltage, high_value):
            if number is None or not math.isfinite(number):
                raise ValueError(
                    f"{channel} のlow_pointとhigh_pointには有限の数値を指定してください。"
                )
        if not -10.0 <= low_voltage < high_voltage <= 10.0:
            raise ValueError(
                f"{channel} の電圧は-10〜10V内で、low_pointよりhigh_pointを大きくしてください。"
            )

    if "U1_CH2" in CHANNELS and "U1_CH3" in CHANNELS:
        if CHANNELS["U1_CH2"]["unit"] != CHANNELS["U1_CH3"]["unit"]:
            raise ValueError("板厚の試算ではU1_CH2とU1_CH3の荷重単位を揃えてください。")
    for number in (
        GAUGE_BASE_THICKNESS_MM, GAUGE_ZERO_READING, GAUGE_DISPLAY_TO_MM,
        GAUGE_ZERO_LOAD, GAUGE_MILL_STIFFNESS, GAUGE_ZERO_STIFFNESS,
    ):
        if number is None or not math.isfinite(number):
            raise ValueError("GAUGE_で始まる試算用の係数には有限の数値を指定してください。")
    if GAUGE_MILL_STIFFNESS <= 0 or GAUGE_ZERO_STIFFNESS <= 0:
        raise ValueError("試算用のミル剛性は0より大きくしてください。")


def convert_voltage(voltage, settings):
    low_voltage, low_value = settings["low_point"]
    high_voltage, high_value = settings["high_point"]
    if voltage is None or not low_voltage <= voltage <= high_voltage:
        return None

    fraction = (voltage - low_voltage) / (high_voltage - low_voltage)
    return low_value + fraction * (high_value - low_value)


def read_output(source, stream, events, stopping):
    # 片側のパイプの読出し待ちで、もう片側の受信を止めない。
    with stream:
        while True:
            line = stream.readline()
            event = (source, line or None, time.monotonic())
            # 終了時はキューが満杯でもパイプを読み続け、子が停止できるようにする。
            while not stopping.is_set():
                try:
                    events.put(event, timeout=0.1)
                    break
                except Full:
                    continue
            if not line:
                break


def show_readings(events):
    writer = csv.writer(sys.stdout, lineterminator="\n")
    columns = ["received_at"]
    for channel, settings in CHANNELS.items():
        columns.extend([f"{channel}_V", f"{settings['name']}_{settings['unit']}"])
    columns.extend([
        "ocr_received_at", "ocr_value", "time_gap_s", "voltage_status", "ocr_status"
    ])
    writer.writerow(columns)
    sys.stdout.flush()

    latest_ocr = None
    started_at = time.monotonic()
    last_arrived = {"logger": started_at, "ocr": started_at}
    while True:
        try:
            source, line, arrived_at = events.get(timeout=0.1)
        except Empty:
            source = None

        now = time.monotonic()
        for name, last_arrived_at in last_arrived.items():
            if last_arrived_at is not None and now - last_arrived_at > INPUT_TIMEOUT:
                print(f"{name} の受信が止まりました。照合は欠測です。", file=sys.stderr)
                last_arrived[name] = None
                if name == "ocr":
                    latest_ocr = None

        if source is None:
            continue
        if line is None:
            return source
        if now - arrived_at > INPUT_TIMEOUT:
            continue

        message = json.loads(line)
        last_arrived[source] = arrived_at
        if source == "ocr":
            had_value = latest_ocr is not None and latest_ocr["value"] is not None
            if had_value and message["value"] is None:
                print("OCR値が未確定になりました。照合は欠測です。", file=sys.stderr)
            latest_ocr = message
            continue

        row = [message["received_at"]]
        voltages = message["voltages"]
        converted_values = {}
        voltage_status = "valid"
        for channel, settings in CHANNELS.items():
            if channel not in voltages:
                raise ValueError(f"ロガーから {channel} の電圧が届きませんでした。")
            voltage = voltages[channel]
            value = convert_voltage(voltage, settings)
            converted_values[channel] = value
            if value is None:
                voltage_status = "invalid"
            row.extend([voltage, value])

        ocr_received_at = None
        ocr_value = None
        time_gap = None
        ocr_status = "waiting"
        if latest_ocr is not None:
            ocr_received_at = latest_ocr["received_at"]
            ocr_value = latest_ocr["value"]
            logger_time = datetime.fromisoformat(message["received_at"])
            ocr_time = datetime.fromisoformat(ocr_received_at)
            time_gap = abs((logger_time - ocr_time).total_seconds())
            if ocr_value is None:
                ocr_status = "unreadable"
            elif time_gap > MAX_TIME_GAP:
                ocr_status = "time_gap"
            else:
                ocr_status = "ready"
        row.extend([
            ocr_received_at, ocr_value, time_gap, voltage_status, ocr_status
        ])
        writer.writerow(row)
        sys.stdout.flush()

        load_op = converted_values.get("U1_CH2")
        load_dr = converted_values.get("U1_CH3")
        gauge_test_text = "missing"
        if load_op is not None and load_dr is not None and ocr_status == "ready":
            total_load = load_op + load_dr
            gap_change_mm = GAUGE_DISPLAY_TO_MM * (ocr_value - GAUGE_ZERO_READING)
            mill_stretch_mm = total_load / GAUGE_MILL_STIFFNESS
            zero_stretch_mm = GAUGE_ZERO_LOAD / GAUGE_ZERO_STIFFNESS
            test_thickness_mm = (
                GAUGE_BASE_THICKNESS_MM + gap_change_mm
                + mill_stretch_mm - zero_stretch_mm
            )
            gauge_test_text = f"{test_thickness_mm:.6f}"
        # CSVへ混ざらないよう、試算のprintは標準エラー出力へ出す。
        print(
            f"[gauge test] {message['received_at']} h_test_mm={gauge_test_text}",
            file=sys.stderr, flush=True,
        )


def main():
    validate_settings()
    folder = Path(__file__).resolve().parent
    events = Queue(maxsize=64)
    stopping = Event()
    processes = {}
    try:
        for source, script in (
            ("logger", "collect_logger.py"),
            ("ocr", "read_meter.py"),
        ):
            command = [sys.executable, str(folder / script), "--managed"]
            if source == "logger":
                command.extend(CHANNELS)
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                encoding="utf-8",
            )
            processes[source] = process
            reader = Thread(
                target=read_output,
                args=(source, process.stdout, events, stopping),
                daemon=True,
            )
            reader.start()

        finished_source = show_readings(events)
        print(f"{finished_source} の取得が終了しました。", file=sys.stderr)
    finally:
        # 先に両方へ停止を伝えてから、COMとカメラの後始末を待つ。
        stopping.set()
        for process in processes.values():
            process.stdin.close()
        for source, process in processes.items():
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print(f"{source} が応答しないため強制終了します。", file=sys.stderr)
                process.kill()
                process.wait()

    for source, process in processes.items():
        if process.returncode != 0:
            raise RuntimeError(
                f"{source} の取得が異常終了しました（終了コード {process.returncode}）。"
            )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("照合を終了しました。", file=sys.stderr)
