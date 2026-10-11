"""Portable desktop entry point. Run from source or the bundled Windows app."""
from __future__ import annotations

import argparse
import http.client
import json
import locale
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import webbrowser

from server import Bridge, LocalServer, ROOT


TEXT = {
    "en": {
        "title": "Lift Trace", "language": "Language", "open": "Open settings", "quit": "Quit",
        "starting": "Starting…", "running": "Your input display is ready.",
        "reused": "The input display is already running through OBS or another Lift Trace window.",
        "owned_hint": "Keep this small window open while playing. Closing it stops the input display.",
        "reused_hint": "Closing this window leaves the input display running.",
        "failed": "Could not start Lift Trace.",
        "port": "Another app is preventing Lift Trace from starting. Close any other Lift Trace windows you opened, then try again. If it still fails, send this message to the project maintainer.\n\nError: address {port} is in use.",
        "data": "Cannot save settings in:\n{path}\n\nExtract the whole LiftTrace folder into a writable location such as Documents, then try again.",
        "generic": "An unexpected error occurred. Details were saved to:\n{path}",
        "browser": "The browser could not be opened. Copy this address into your browser:\n{url}",
        "lost": "The input display has stopped. Close this window and reopen Lift Trace.",
    },
    "ko": {
        "title": "Lift Trace", "language": "언어", "open": "설정 열기", "quit": "종료",
        "starting": "시작 중…", "running": "입력 표시를 사용할 준비가 됐습니다.",
        "reused": "OBS 또는 다른 Lift Trace 창에서 실행 중입니다.",
        "owned_hint": "사용하는 동안 이 작은 창을 열어 두세요. 닫으면 입력 표시도 멈춥니다.",
        "reused_hint": "이 창을 닫아도 입력 표시는 계속됩니다.",
        "failed": "Lift Trace를 시작할 수 없습니다.",
        "port": "다른 프로그램 때문에 Lift Trace를 시작하지 못했습니다. 직접 열어 둔 다른 Lift Trace 창을 닫고 다시 실행해 주세요. 그래도 안 되면 이 메시지를 프로젝트 관리자에게 보내 주세요.\n\n오류 정보: 연결 주소 {port} 사용 중.",
        "data": "이 위치에 설정을 저장할 수 없습니다:\n{path}\n\nLiftTrace 폴더 전체를 문서 등 저장 가능한 위치에 압축 해제한 뒤 다시 실행하세요.",
        "generic": "오류가 발생했습니다. 자세한 내용은 다음 로그에 저장했습니다:\n{path}",
        "browser": "브라우저를 열지 못했습니다. 아래 주소를 브라우저에 입력하세요:\n{url}",
        "lost": "입력 표시가 멈췄습니다. 이 창을 닫고 Lift Trace를 다시 실행하세요.",
    },
    "ja": {
        "title": "Lift Trace", "language": "言語", "open": "設定を開く", "quit": "終了",
        "starting": "起動中…", "running": "入力を表示する準備ができました。",
        "reused": "OBSまたは別のLift Traceウィンドウですでに動作しています。",
        "owned_hint": "使用中はこの小さなウィンドウを開いたままにしてください。閉じると入力表示が止まります。",
        "reused_hint": "このウィンドウを閉じても入力表示は続きます。",
        "failed": "Lift Traceを起動できませんでした。",
        "port": "別のアプリのためLift Traceを起動できませんでした。自分で開いた別のLift Traceウィンドウを閉じて、もう一度実行してください。直らない場合は、このメッセージをプロジェクトの管理者に送ってください。\n\nエラー情報: 接続先{port}は使用中です。",
        "data": "設定を保存できません:\n{path}\n\nLiftTraceフォルダー全体を「ドキュメント」など書き込み可能な場所に展開して、再度実行してください。",
        "generic": "エラーが発生しました。詳細を次のログに保存しました:\n{path}",
        "browser": "ブラウザーを開けませんでした。次のアドレスをブラウザーに入力してください:\n{url}",
        "lost": "入力表示が止まりました。このウィンドウを閉じてLift Traceを開き直してください。",
    },
}
LANGUAGES = {"English": "en", "한국어": "ko", "日本語": "ja"}


class StartupError(Exception):
    def __init__(self, key: str, **values):
        self.key, self.values = key, values
        super().__init__(key)


def application_dir() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else ROOT


def default_language() -> str:
    try:
        name = locale.getlocale()[0] or "en"
        if os.name == "nt":
            import ctypes
            buffer = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):
                name = buffer.value
        code = name.replace("_", "-").split("-")[0].lower()
        return code if code in TEXT else "en"
    except (ValueError, OSError):
        return "en"


def prepare_data_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path) as probe:
            probe.write(b"Lift Trace")
            probe.flush()
    except OSError as exc:
        raise StartupError("data", path=str(path)) from exc


def configure_logging(data_dir: Path) -> Path:
    """Windowed executables have no stdout/stderr; retain tracebacks safely."""
    log_dir = data_dir
    try:
        prepare_data_dir(log_dir)
    except StartupError:
        log_dir = Path(tempfile.gettempdir()) / "LiftTrace"
        log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "lift-trace.log"
    handler = RotatingFileHandler(path, maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True,
                        format="%(asctime)s %(levelname)s %(message)s")
    # BaseHTTPRequestHandler writes request errors to stderr. Do not replace
    # actual command-line streams; only supply a sink for windowed builds.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, path.open("a", encoding="utf-8", buffering=1))
    return path


def healthy_server(port: int) -> bool:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.7)
    try:
        connection.request("GET", "/api/status")
        response = connection.getresponse()
        if response.status != 200:
            return False
        contents = response.read(32769)
        if len(contents) > 32768:
            return False
        value = json.loads(contents)
        return (isinstance(value, dict) and value.get("app") == "lift-trace"
                and value.get("apiVersion") == 1 and isinstance(value.get("devices"), list)
                and type(value.get("nativeSupported")) is bool
                and "selectedDevice" in value
                and (value["selectedDevice"] is None or type(value["selectedDevice"]) is int))
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


class ServerSession:
    """Own only the server this process created; reuse never grants ownership."""
    def __init__(self, port: int, data_dir: Path):
        self.port, self.data_dir = port, data_dir
        self.server: LocalServer | None = None
        self.bridge: Bridge | None = None
        self.thread: threading.Thread | None = None
        self.reused = False

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def start(self, allow_reuse: bool = True) -> None:
        if allow_reuse and healthy_server(self.port):
            self.reused = True
            logging.info("Reusing an existing Lift Trace server on port %s", self.port)
            return
        prepare_data_dir(self.data_dir)
        self.bridge = Bridge(self.data_dir)
        try:
            self.server = LocalServer(("127.0.0.1", self.port), ROOT / "web", self.bridge)
        except OSError as exc:
            self.bridge.close()
            self.bridge = None
            # Another launch may have won the race between the probe and bind.
            for _ in range(4 if allow_reuse else 0):
                if healthy_server(self.port):
                    self.reused = True
                    return
                time.sleep(0.1)
            raise StartupError("port", port=self.port) from exc
        try:
            self.port = self.server.server_port
            self.bridge.start()
            self.thread = threading.Thread(target=self.server.serve_forever,
                                           kwargs={"poll_interval": 0.1}, daemon=True,
                                           name="lift-trace-http")
            self.thread.start()
        except BaseException:
            self.close()
            raise
        logging.info("Started owned Lift Trace server on port %s", self.port)

    def close(self) -> None:
        if self.server is not None:
            if self.thread is not None and self.thread.is_alive():
                self.server.shutdown()
            if self.bridge is not None:
                self.bridge.close()
            self.server.server_close()
            if self.thread is not None:
                self.thread.join(timeout=2)
            self.server = None
            self.bridge = None
            self.thread = None
            logging.info("Stopped owned Lift Trace server")


def run_manager(session: ServerSession, language: str, no_browser: bool, data_dir: Path,
                log_path: Path) -> int:
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title("Lift Trace")
    root.geometry("560x250")
    root.minsize(470, 240)
    state = {"language": language, "status": "starting", "closed": False, "exit_code": 0}
    frame = ttk.Frame(root, padding=22)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Lift Trace", font=("Segoe UI", 20, "bold")).pack(anchor="w")
    language_row = ttk.Frame(frame)
    language_row.pack(fill="x", pady=(8, 12))
    language_label = ttk.Label(language_row)
    language_label.pack(side="left")
    selection = tk.StringVar(value=next(name for name, code in LANGUAGES.items() if code == language))
    language_box = ttk.Combobox(language_row, state="readonly", width=14,
                               values=list(LANGUAGES), textvariable=selection)
    language_box.pack(side="right")
    status = ttk.Label(frame, wraplength=500)
    status.pack(anchor="w")
    hint = ttk.Label(frame, wraplength=500)
    hint.pack(anchor="w", pady=(7, 12))
    def wrap_labels(event):
        available = max(180, event.width - 44)
        status.configure(wraplength=available)
        hint.configure(wraplength=available)
    frame.bind("<Configure>", wrap_labels)
    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", side="bottom")

    def words():
        return TEXT[state["language"]]

    def repaint():
        text = words()
        language_label.configure(text=text["language"])
        status.configure(text=text[state["status"]])
        hint.configure(text=text["reused_hint" if session.reused else "owned_hint"])
        settings_button.configure(text=text["open"])
        quit_button.configure(text=text["quit"])

    def change_language(_event=None):
        state["language"] = LANGUAGES[selection.get()]
        try:
            (data_dir / "desktop.json").write_text(json.dumps({"language": state["language"]}), "utf-8")
        except OSError:
            logging.exception("Could not save desktop language")
        repaint()

    def open_settings():
        url = session.url + "?lang=" + state["language"]
        try:
            if webbrowser.open(url):
                return
        except Exception:
            logging.exception("Could not open settings browser")
        messagebox.showinfo("Lift Trace", words()["browser"].format(url=url), parent=root)

    def close():
        state["closed"] = True
        session.close()
        root.destroy()

    def check_connection():
        if state["closed"]:
            return
        if not healthy_server(session.port):
            state["status"] = "lost"
            settings_button.configure(state="disabled")
        else:
            state["status"] = "reused" if session.reused else "running"
            settings_button.configure(state="normal")
        repaint()
        root.after(3000, check_connection)

    def start():
        try:
            session.start()
            state["status"] = "reused" if session.reused else "running"
            settings_button.configure(state="normal")
            repaint()
            if not no_browser:
                open_settings()
            root.after(3000, check_connection)
        except Exception as exc:
            state["exit_code"] = 1
            logging.exception("Desktop startup failed")
            message = (words()[exc.key].format(**exc.values) if isinstance(exc, StartupError)
                       else words()["generic"].format(path=log_path))
            messagebox.showerror(words()["failed"], message, parent=root)
            close()

    settings_button = ttk.Button(buttons, command=open_settings, state="disabled")
    settings_button.pack(side="left")
    quit_button = ttk.Button(buttons, command=close)
    quit_button.pack(side="right")
    language_box.bind("<<ComboboxSelected>>", change_language)
    root.protocol("WM_DELETE_WINDOW", close)
    repaint()
    root.after(50, start)
    root.mainloop()
    return state["exit_code"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Lift Trace desktop and bundled overlay server")
    parser.add_argument("--serve", action="store_true", help="Run only the server (used by OBS)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open settings automatically")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=application_dir() / "data")
    parser.add_argument("--language", choices=tuple(TEXT))
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    args.data_dir = args.data_dir.resolve()
    language = args.language or default_language()
    if not args.language:
        try:
            saved = json.loads((args.data_dir / "desktop.json").read_text("utf-8"))
            if saved.get("language") in TEXT:
                language = saved["language"]
        except (OSError, ValueError, AttributeError):
            pass
    log_path = configure_logging(args.data_dir)
    session = ServerSession(args.port, args.data_dir)
    try:
        if args.serve:
            # OBS owns this process. A competing server is an error, not a
            # reason to keep an idle process alive pretending it owns the port.
            session.start(allow_reuse=False)
            while session.thread is not None and session.thread.is_alive():
                session.thread.join(timeout=0.5)
            return 0
        return run_manager(session, language, args.no_browser, args.data_dir, log_path)
    except KeyboardInterrupt:
        return 0
    except Exception:
        logging.exception("Lift Trace failed")
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
