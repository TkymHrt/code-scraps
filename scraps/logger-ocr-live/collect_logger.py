import json
import math
import os
import re
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread

from win32com.client import DispatchEx, GetActiveObject, dynamic

SETTINGS_FILE = None
DEVICE_ID = 0
READ_INTERVAL = 0.2

# 診断実験: まず --diagnose で記録し、次の項目は1つずつ変更する。
# 変更した条件とログを対にして残すこと。設定は --diagnose のときだけ有効。
DIAG_SKIP_INITIALIZE_ON_ATTACH = False
DIAG_SKIP_IDENTIFIER_ON_ATTACH = False
DIAG_SKIP_OPEN_FILE_ON_ATTACH = False
DIAG_SKIP_STOP = False  # 危険: 装置の収集が継続する可能性。終了後に手動停止必須
DIAG_HOLD_COM_SECONDS = 0.0  # 例: 15.0 / Stop後もCOM参照を保持してGUIの寿命を確認
DIAG_VERIFY_STOP_SECONDS = 2.0  # Stop後のGetStateを最大この秒数だけ確認

# 例: attach時のInitializeだけ除外する実験
# DIAG_SKIP_INITIALIZE_ON_ATTACH = True
# 例: Stop呼出し自体がGUI終了の原因かを調べる実験（必ず実機を手動停止）
# DIAG_SKIP_STOP = True

CHANNEL_NAMES = [
    "U1_CH1",
    "U1_CH2",
    "U1_CH3",
    "U1_CH4",
    "U1_CH5",
    "U1_CH6",
    "U1_CH7",
    "U1_CH8",
]

COLLECTION_STOPPED = 1
COLLECTION_ERROR_STOPPED = 11
INVALID_VOLTAGE_THRESHOLD = 3.3e38


class LoggerTrace:
    """標準出力のJSONLと混ぜず、COM操作と終了段階をファイルへ記録する。"""

    def __init__(self, enabled):
        self.enabled = enabled
        self.output = None
        self.path = None

    def __enter__(self):
        if self.enabled:
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            self.path = (
                Path.cwd() / f"collect_logger_diag_{timestamp}_{os.getpid()}.jsonl"
            )
            self.output = self.path.open("w", encoding="utf-8")
            print(f"診断ログ: {self.path}", file=sys.stderr, flush=True)
            self.record("trace_open", python_pid=os.getpid())
        return self

    def record(self, event, **details):
        if not self.enabled:
            return
        entry = {
            "at": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "event": event,
            **details,
        }
        self.output.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        self.output.flush()

    def __exit__(self, error_type, error, _traceback):
        if self.output is not None:
            if error is not None:
                self.record(
                    "python_exception",
                    error_type=error_type.__name__,
                    error=repr(error),
                )
            self.record("trace_close")
            self.output.close()


def keyboard_stop_requested():
    """WindowsコンソールのQキーを検出。Ctrl+Cイベントは発生させない。"""
    import msvcrt

    while msvcrt.kbhit():
        if msvcrt.getwch().lower() == "q":
            return True
    return False


def verify_stopped(logger, trace):
    """Stopの戻り値だけで判断せず、収集状態を追跡する（診断時のみ）。"""
    deadline = time.monotonic() + DIAG_VERIFY_STOP_SECONDS
    while True:
        try:
            state = logger.GetState()
        except Exception as error:
            trace.record("get_state_after_stop_error", error=repr(error))
            return
        trace.record(
            "get_state_after_stop",
            state=state,
            expected_stopped=state == COLLECTION_STOPPED,
        )
        if state == COLLECTION_STOPPED or time.monotonic() >= deadline:
            return
        time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))


def main(channel_names, managed, attach=False, diagnose=False, stop_on_key=False):
    if not channel_names and not managed:
        channel_names = CHANNEL_NAMES
    if not channel_names:
        raise ValueError("取得する電圧CHを指定（例 U1_CH1）")
    unit_number = 1
    channel_indexes = {}
    for channel_name in channel_names:
        channel_match = re.fullmatch(r"U1_CH([1-8])", channel_name)
        if channel_match is None:
            raise ValueError(f"電圧CHはU1_CH1〜U1_CH8（指定値 {channel_name}）")
        channel_number = int(channel_match.group(1))
        channel_indexes[channel_name] = channel_number - 1

    if SETTINGS_FILE is None or not Path(SETTINGS_FILE).is_file():
        raise ValueError("SETTINGS_FILEに既存の .ucf を指定")
    if not 0 <= DEVICE_ID <= 3:
        raise ValueError("DEVICE_IDは0〜3")
    if not math.isfinite(READ_INTERVAL) or READ_INTERVAL <= 0:
        raise ValueError("READ_INTERVALは正の秒数")
    if stop_on_key and (managed or os.name != "nt" or not sys.stdin.isatty()):
        raise ValueError("--stop-on-keyはWindowsコンソールの単体起動で指定")
    if diagnose and (
        DIAG_VERIFY_STOP_SECONDS < 0
        or not math.isfinite(DIAG_VERIFY_STOP_SECONDS)
        or DIAG_HOLD_COM_SECONDS < 0
        or not math.isfinite(DIAG_HOLD_COM_SECONDS)
    ):
        raise ValueError("診断用の待機秒数は0以上の有限値")

    with LoggerTrace(diagnose) as trace:
        trace.record(
            "configuration",
            connect_mode="attach" if attach else "new",
            managed=managed,
            stop_on_key=stop_on_key,
            skip_initialize=attach and DIAG_SKIP_INITIALIZE_ON_ATTACH,
            skip_identifier=attach and DIAG_SKIP_IDENTIFIER_ON_ATTACH,
            skip_open_file=attach and DIAG_SKIP_OPEN_FILE_ON_ATTACH,
            skip_stop=DIAG_SKIP_STOP,
            hold_com_seconds=DIAG_HOLD_COM_SECONDS,
            verify_stop_seconds=DIAG_VERIFY_STOP_SECONDS,
        )

        stop_requested = Event()
        ctrl_c_seen = Event()
        previous_sigint_handler = signal.getsignal(signal.SIGINT)

        def request_stop(_signum, _frame):
            ctrl_c_seen.set()
            stop_requested.set()

        signal.signal(signal.SIGINT, request_stop)
        try:
            if managed:
                Thread(
                    target=watch_parent, args=(stop_requested,), daemon=True
                ).start()

            trace.record("prepare_begin")
            logger, waveform = prepare_logger(
                SETTINGS_FILE, DEVICE_ID, attach=attach, trace=trace
            )
            trace.record("prepare_done")
            try:
                if stop_requested.is_set():
                    trace.record("stop_before_start", ctrl_c=ctrl_c_seen.is_set())
                    return

                start_result = None
                try:
                    trace.record("start_begin")
                    start_result = logger.Start()
                    trace.record("start_result", result=repr(start_result))
                    check_com_result(start_result, "収集開始失敗")
                    has_started_reading = False
                    last_collection_state = None
                    while not stop_requested.is_set():
                        if stop_on_key and keyboard_stop_requested():
                            trace.record("stop_key_q")
                            stop_requested.set()
                            break

                        collection_state = logger.GetState()
                        if collection_state != last_collection_state:
                            trace.record("collection_state", state=collection_state)
                            last_collection_state = collection_state
                        if collection_state == COLLECTION_ERROR_STOPPED:
                            error_code = logger.GetErrorCode()
                            raise RuntimeError(f"収集異常停止（{error_code}）")
                        if collection_state < 0:
                            raise RuntimeError(f"収集状態取得失敗（{collection_state}）")
                        if collection_state == COLLECTION_STOPPED:
                            if has_started_reading:
                                trace.record("collection_stopped_by_device")
                                break
                            stop_requested.wait(READ_INTERVAL)
                            continue
                        has_started_reading = True

                        voltages = {}
                        for channel_name, channel_index in channel_indexes.items():
                            voltage = waveform.GetCurrentData(unit_number, channel_index)
                            if (
                                not math.isfinite(voltage)
                                or abs(voltage) >= INVALID_VOLTAGE_THRESHOLD
                            ):
                                voltage = None
                            voltages[channel_name] = voltage

                        received_at = datetime.now(UTC).isoformat(
                            timespec="milliseconds"
                        )
                        message = {"received_at": received_at, "voltages": voltages}
                        print(json.dumps(message, allow_nan=False), flush=True)
                        stop_requested.wait(READ_INTERVAL)
                finally:
                    trace.record(
                        "cleanup_begin",
                        start_result=repr(start_result),
                        stop_requested=stop_requested.is_set(),
                        ctrl_c_seen=ctrl_c_seen.is_set(),
                    )
                    try:
                        if diagnose and DIAG_SKIP_STOP:
                            trace.record("stop_skipped_by_experiment")
                            print(
                                "警告: 診断設定によりStop()を省略しました。"
                                "実機で必ず収集停止を確認してください。",
                                file=sys.stderr,
                                flush=True,
                            )
                        elif start_result is None or start_result == 0:
                            trace.record("stop_begin")
                            try:
                                result = logger.Stop()
                            except Exception as error:
                                trace.record("stop_exception", error=repr(error))
                                raise
                            trace.record(
                                "stop_result",
                                result=repr(result),
                                expected_success=result == 0,
                            )
                        else:
                            trace.record(
                                "stop_skipped_start_failed", result=repr(start_result)
                            )
                        if diagnose:
                            verify_stopped(logger, trace)
                    finally:
                        # COM参照を保持したまま待つ。GUIがこの間に消えるか、
                        # Python終了時に消えるかでCOM寿命依存を切り分ける。
                        if diagnose and DIAG_HOLD_COM_SECONDS:
                            trace.record("hold_com_begin")
                            time.sleep(DIAG_HOLD_COM_SECONDS)
                            trace.record("hold_com_end")
            finally:
                trace.record("releasing_com_references")
                # logger/waveformのPython参照はこの関数の終了時に解放される。
        finally:
            signal.signal(signal.SIGINT, previous_sigint_handler)
            trace.record("signal_restored")



def watch_parent(stop_requested):
    os.read(sys.stdin.fileno(), 1)
    stop_requested.set()


def prepare_logger(settings_file, device_id, attach=False, trace=None):
    if attach:
        try:
            application = GetActiveObject("WaveLoggerPro2.Application")
        except Exception as exc:
            raise RuntimeError(
                "起動済みのWAVE LOGGER PROに接続できません。"
                "アプリを先に起動し、Automation接続に対応していることを確認してください"
            ) from exc
    else:
        application = DispatchEx("WaveLoggerPro2.Application")
    logger = dynamic.Dispatch(application)
    logger._FlagAsMethod(
        "Initialize",
        "SetIdentifier",
        "OpenFile",
        "GetActiveFile",
        "Start",
        "GetState",
        "GetErrorCode",
        "Stop",
    )
    if trace is not None:
        trace.record("com_connected", mode="attach" if attach else "new")

    if attach and trace is not None and trace.enabled and DIAG_SKIP_INITIALIZE_ON_ATTACH:
        trace.record("initialize_skipped")
    else:
        if trace is not None:
            trace.record("initialize_begin")
        initialize_result = logger.Initialize()
        if trace is not None:
            trace.record("initialize_result", result=repr(initialize_result))
    logger.Visible = True
    if trace is not None:
        trace.record("visible_set", value=True)

    usb_identifier = 4 + device_id
    if attach and trace is not None and trace.enabled and DIAG_SKIP_IDENTIFIER_ON_ATTACH:
        trace.record("set_identifier_skipped")
    else:
        if trace is not None:
            trace.record("set_identifier_begin")
        identifier_result = logger.SetIdentifier(usb_identifier)
        if trace is not None:
            trace.record("set_identifier_result", result=repr(identifier_result))
        check_com_result(identifier_result, "機器ID設定失敗")

    if attach and trace is not None and trace.enabled and DIAG_SKIP_OPEN_FILE_ON_ATTACH:
        trace.record("open_file_skipped")
    else:
        absolute_settings_path = Path(settings_file).resolve()
        if trace is not None:
            trace.record("open_file_begin", file=str(absolute_settings_path))
        open_result = logger.OpenFile(str(absolute_settings_path))
        if trace is not None:
            trace.record("open_file_result", result=repr(open_result))
        check_com_result(open_result, "設定ファイル読込失敗")
    if trace is not None:
        trace.record("get_active_file_begin")
    waveform = logger.GetActiveFile()
    if trace is not None:
        trace.record("get_active_file_done")
    waveform._FlagAsMethod("GetCurrentData")
    return logger, waveform


def check_com_result(result, error_message):
    if result != 0:
        raise RuntimeError(f"{error_message}（{result}）")


if __name__ == "__main__":
    arguments = sys.argv[1:]
    managed = "--managed" in arguments
    if managed:
        arguments.remove("--managed")
    attach = "--attach" in arguments
    if attach:
        arguments.remove("--attach")
    diagnose = "--diagnose" in arguments
    if diagnose:
        arguments.remove("--diagnose")
    stop_on_key = "--stop-on-key" in arguments
    if stop_on_key:
        arguments.remove("--stop-on-key")
    try:
        main(
            arguments, managed, attach=attach,
            diagnose=diagnose, stop_on_key=stop_on_key
        )
    except KeyboardInterrupt:
        print("ロガー取得終了", file=sys.stderr)
