import json
import os
import queue
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import datetime, date, time
from pathlib import Path, PurePosixPath
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from zoneinfo import ZoneInfo


APP_TITLE = "Stock Flow Server Dashboard"


COMMON_FILES = {
    "صفحة الدخول": "templates/login.html",
    "صفحة الرفع": "templates/upload_file.html",
    "البحث للشركات": "templates/search_products.html",
    "مسار مزامنة الربط": "api_routes.py",
    "موديل البيانات": "models.py",
    "واجهة البحث المشتركة": "search_products.html",
}


DEFAULT_CONFIG = {
    "host": "134.209.182.8",
    "user": "root",
    "remote_root": "/var/www/stock_flow",
    "service_name": "stock_flow",
    "ssh_key_path": r"C:\Users\Mohamed nagy\AppData\Local\Packages\5319275A.WhatsAppDesktop_cv1g1gvanyjgm\LocalState\sessions\C06DCC050CD73BBAF4FD181CD3AF34F8C410E46D\transfers\2026-18\id_ed25519",
    "project_root": str(Path(__file__).resolve().parent),
    "restart_after_upload": True,
    "telegram_backup_hour": "6",
    "telegram_backup_minute": "0",
}


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


CONFIG_PATH = app_base_dir() / "server_dashboard_config.json"


class DashboardApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1180x760")
        self.root.minsize(980, 700)

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.running_lock = threading.Lock()
        self.secured_key_cache = None
        self.secured_key_source_signature = None

        self.config = self.load_config()

        self.host_var = tk.StringVar(value=self.config.get("host", ""))
        self.user_var = tk.StringVar(value=self.config.get("user", ""))
        self.remote_root_var = tk.StringVar(value=self.config.get("remote_root", ""))
        self.service_var = tk.StringVar(value=self.config.get("service_name", ""))
        self.key_path_var = tk.StringVar(value=self.config.get("ssh_key_path", ""))
        self.project_root_var = tk.StringVar(value=self.config.get("project_root", str(app_base_dir())))
        self.local_file_var = tk.StringVar()
        self.remote_relative_var = tk.StringVar()
        self.common_file_var = tk.StringVar(value="اختر ملف شائع")
        self.restart_after_upload_var = tk.BooleanVar(value=bool(self.config.get("restart_after_upload", True)))
        self.backup_choice_var = tk.StringVar()
        self.telegram_backup_hour_var = tk.StringVar(value=str(self.config.get("telegram_backup_hour", "6")))
        self.telegram_backup_minute_var = tk.StringVar(value=str(self.config.get("telegram_backup_minute", "0")))
        self.last_downloaded_old_file = None

        self.build_ui()
        self.root.after(150, self.flush_logs)

    def load_config(self):
        if CONFIG_PATH.exists():
            try:
                return {**DEFAULT_CONFIG, **json.loads(CONFIG_PATH.read_text(encoding="utf-8"))}
            except Exception:
                return DEFAULT_CONFIG.copy()
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        payload = {
            "host": self.host_var.get().strip(),
            "user": self.user_var.get().strip(),
            "remote_root": self.remote_root_var.get().strip(),
            "service_name": self.service_var.get().strip(),
            "ssh_key_path": self.key_path_var.get().strip(),
            "project_root": self.project_root_var.get().strip(),
            "restart_after_upload": bool(self.restart_after_upload_var.get()),
            "telegram_backup_hour": self.telegram_backup_hour_var.get().strip(),
            "telegram_backup_minute": self.telegram_backup_minute_var.get().strip(),
        }
        CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log("تم حفظ الإعدادات محلياً.")

    def build_ui(self):
        self.root.configure(bg="#f4f6f9")
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        connection_frame = ttk.LabelFrame(main, text="بيانات الاتصال", padding=12)
        connection_frame.pack(fill="x")

        self.add_labeled_entry(connection_frame, "السيرفر", self.host_var, 0, 0)
        self.add_labeled_entry(connection_frame, "المستخدم", self.user_var, 0, 2)
        self.add_labeled_entry(connection_frame, "الخدمة", self.service_var, 0, 4)
        self.add_labeled_entry(connection_frame, "مجلد المشروع على السيرفر", self.remote_root_var, 1, 0, colspan=3)
        self.add_labeled_entry(connection_frame, "مفتاح الاتصال", self.key_path_var, 2, 0, colspan=5, browse="file")
        self.add_labeled_entry(connection_frame, "مجلد المشروع المحلي", self.project_root_var, 3, 0, colspan=5, browse="dir")

        connection_actions = ttk.Frame(connection_frame)
        connection_actions.grid(row=4, column=0, columnspan=6, sticky="ew", pady=(10, 0))
        ttk.Button(connection_actions, text="حفظ الإعدادات", command=self.save_config).pack(side="right", padx=4)
        ttk.Button(connection_actions, text="اختبار الاتصال", command=self.test_connection).pack(side="right", padx=4)
        ttk.Button(connection_actions, text="حالة الخدمة", command=self.fetch_service_status).pack(side="right", padx=4)
        ttk.Button(connection_actions, text="آخر اللوج", command=self.fetch_logs).pack(side="right", padx=4)

        deploy_frame = ttk.LabelFrame(main, text="رفع ملف وتحديثه", padding=12)
        deploy_frame.pack(fill="x", pady=(12, 0))

        ttk.Label(deploy_frame, text="ملف شائع").grid(row=0, column=0, sticky="w", padx=(0, 8))
        common_combo = ttk.Combobox(
            deploy_frame,
            textvariable=self.common_file_var,
            values=list(COMMON_FILES.keys()),
            state="readonly",
            width=28,
        )
        common_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        common_combo.bind("<<ComboboxSelected>>", self.apply_common_file)
        ttk.Button(deploy_frame, text="تعبئة تلقائية", command=self.apply_common_file).grid(row=0, column=2, sticky="ew")

        self.add_labeled_entry(deploy_frame, "الملف المحلي", self.local_file_var, 1, 0, colspan=4, browse="file")
        self.add_labeled_entry(deploy_frame, "المسار داخل المشروع على السيرفر", self.remote_relative_var, 2, 0, colspan=4)
        ttk.Label(
            deploy_frame,
            text="لو تركت المسار فارغاً سيبحث البرنامج عن نفس اسم الملف داخل مشروع السيرفر ويستخدمه تلقائياً.",
        ).grid(row=3, column=0, columnspan=5, sticky="w", pady=(2, 0))

        ttk.Checkbutton(
            deploy_frame,
            text="إعادة تشغيل الخدمة بعد الرفع",
            variable=self.restart_after_upload_var,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))

        deploy_actions = ttk.Frame(deploy_frame)
        deploy_actions.grid(row=5, column=0, columnspan=5, sticky="ew", pady=(10, 0))
        ttk.Button(deploy_actions, text="رفع الملف", command=self.upload_selected_file).pack(side="right", padx=4)
        ttk.Button(deploy_actions, text="إنشاء باك أب كامل", command=self.create_full_backup).pack(side="right", padx=4)
        ttk.Button(deploy_actions, text="جلب النسخ السابقة", command=self.load_backups_for_file).pack(side="right", padx=4)

        backup_frame = ttk.LabelFrame(main, text="استرجاع النسخ السابقة", padding=12)
        backup_frame.pack(fill="x", pady=(12, 0))

        ttk.Label(backup_frame, text="اختر نسخة سابقة").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.backup_combo = ttk.Combobox(backup_frame, textvariable=self.backup_choice_var, state="readonly")
        self.backup_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(backup_frame, text="استرجاع النسخة المحددة", command=self.restore_selected_backup).grid(row=0, column=2, padx=4)
        ttk.Button(backup_frame, text="استرجاع آخر نسخة مباشرة", command=self.restore_latest_backup).grid(row=0, column=3, padx=4)
        backup_frame.columnconfigure(1, weight=1)

        quick_frame = ttk.LabelFrame(main, text="أوامر سريعة", padding=12)
        quick_frame.pack(fill="x", pady=(12, 0))
        ttk.Button(quick_frame, text="إعادة تشغيل الخدمة", command=self.restart_service).pack(side="right", padx=4)
        ttk.Button(quick_frame, text="قائمة باك أبات المشروع", command=self.list_project_backups).pack(side="right", padx=4)
        ttk.Button(quick_frame, text="عرض ملفات المشروع", command=self.list_remote_project_files).pack(side="right", padx=4)

        telegram_frame = ttk.LabelFrame(main, text="باك أب تيليجرام اليومي", padding=12)
        telegram_frame.pack(fill="x", pady=(12, 0))
        ttk.Label(telegram_frame, text="الساعة بتوقيت القاهرة").grid(row=0, column=0, sticky="w", padx=(0, 8))
        hour_combo = ttk.Combobox(
            telegram_frame,
            textvariable=self.telegram_backup_hour_var,
            values=[str(i) for i in range(24)],
            state="readonly",
            width=6,
        )
        hour_combo.grid(row=0, column=1, sticky="w", padx=(0, 8))
        ttk.Label(telegram_frame, text="الدقيقة").grid(row=0, column=2, sticky="w", padx=(0, 8))
        minute_combo = ttk.Combobox(
            telegram_frame,
            textvariable=self.telegram_backup_minute_var,
            values=[str(i) for i in range(60)],
            state="readonly",
            width=6,
        )
        minute_combo.grid(row=0, column=3, sticky="w", padx=(0, 8))
        ttk.Button(telegram_frame, text="حفظ موعد الباك أب", command=self.update_telegram_backup_schedule).grid(row=0, column=4, padx=4)
        ttk.Button(telegram_frame, text="تشغيل الباك أب الآن", command=self.run_telegram_backup_now).grid(row=0, column=5, padx=4)
        ttk.Button(telegram_frame, text="حالة باك أب تيليجرام", command=self.fetch_telegram_backup_status).grid(row=0, column=6, padx=4)
        ttk.Label(
            telegram_frame,
            text="البرنامج يحول الوقت الذي تختاره من توقيت القاهرة إلى توقيت السيرفر تلقائياً.",
        ).grid(row=1, column=0, columnspan=7, sticky="w", pady=(8, 0))
        for idx in range(7):
            telegram_frame.columnconfigure(idx, weight=0)
        telegram_frame.columnconfigure(6, weight=1)

        log_frame = ttk.LabelFrame(main, text="سجل العمليات", padding=12)
        log_frame.pack(fill="both", expand=True, pady=(12, 0))
        log_frame.pack_propagate(False)
        log_frame.configure(height=260)

        self.log_text = tk.Text(
            log_frame,
            wrap="word",
            font=("Consolas", 10),
            bg="#13202b",
            fg="#eef3f7",
            insertbackground="#eef3f7",
            height=14,
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        log_scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log("الواجهة جاهزة. ابدأ باختبار الاتصال أو ارفع ملفاً مباشراً.")

    def add_labeled_entry(self, parent, label, variable, row, column, colspan=1, browse=None):
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=(0, 8), pady=4)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=column + 1, columnspan=colspan, sticky="ew", padx=(0, 8), pady=4)

        if browse == "file":
            ttk.Button(parent, text="اختيار", command=lambda v=variable: self.browse_file(v)).grid(
                row=row, column=column + 2 + colspan - 1, sticky="ew", pady=4
            )
        elif browse == "dir":
            ttk.Button(parent, text="اختيار", command=lambda v=variable: self.browse_dir(v)).grid(
                row=row, column=column + 2 + colspan - 1, sticky="ew", pady=4
            )

        for idx in range(6):
            parent.columnconfigure(idx, weight=1 if idx in {1, 3, 5} else 0)

    def browse_file(self, variable):
        selected = filedialog.askopenfilename()
        if selected:
            variable.set(selected)

    def browse_dir(self, variable):
        selected = filedialog.askdirectory()
        if selected:
            variable.set(selected)

    def apply_common_file(self, _event=None):
        chosen = self.common_file_var.get().strip()
        relative = COMMON_FILES.get(chosen)
        if not relative:
            return
        self.remote_relative_var.set(relative)
        local_path = Path(self.project_root_var.get().strip()) / relative
        self.local_file_var.set(str(local_path))
        self.log(f"تم اختيار الملف الشائع: {relative}")

    def validate_connection(self):
        fields = {
            "السيرفر": self.host_var.get().strip(),
            "المستخدم": self.user_var.get().strip(),
            "مجلد المشروع": self.remote_root_var.get().strip(),
            "الخدمة": self.service_var.get().strip(),
            "مفتاح الاتصال": self.key_path_var.get().strip(),
        }
        missing = [label for label, value in fields.items() if not value]
        if missing:
            messagebox.showerror("بيانات ناقصة", "اكمل الحقول التالية:\n" + "\n".join(missing))
            return False
        if not Path(self.key_path_var.get().strip()).exists():
            messagebox.showerror("مفتاح غير موجود", "ملف مفتاح الاتصال غير موجود.")
            return False
        return True

    def log(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_queue.put(f"[{timestamp}] {message}")

    def flush_logs(self):
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.insert("end", line + "\n")
            self.log_text.see("end")
        self.root.after(150, self.flush_logs)

    def run_async(self, title, func):
        if not self.running_lock.acquire(blocking=False):
            messagebox.showwarning("عملية جارية", "في عملية حالية شغالة. انتظر حتى تنتهي.")
            return

        def worker():
            try:
                self.log(f"بدأت العملية: {title}")
                func()
                self.log(f"انتهت العملية: {title}")
            except Exception as exc:
                self.log(f"فشلت العملية: {title} | {exc}")
                self.root.after(0, lambda: messagebox.showerror("خطأ", str(exc)))
            finally:
                self.running_lock.release()

        threading.Thread(target=worker, daemon=True).start()

    def ssh_base_command(self):
        key_path = self.prepare_ssh_key()
        return [
            "ssh",
            "-i",
            key_path,
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "IdentitiesOnly=yes",
            f"{self.user_var.get().strip()}@{self.host_var.get().strip()}",
        ]

    def scp_base_command(self):
        key_path = self.prepare_ssh_key()
        return [
            "scp",
            "-i",
            key_path,
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "IdentitiesOnly=yes",
        ]

    def prepare_ssh_key(self):
        source = Path(self.key_path_var.get().strip())
        if not source.exists():
            raise RuntimeError("ملف مفتاح الاتصال غير موجود.")

        signature = (str(source), source.stat().st_mtime_ns, source.stat().st_size)
        if self.secured_key_cache and self.secured_key_source_signature == signature:
            cached = Path(self.secured_key_cache)
            if cached.exists():
                return str(cached)

        temp_dir = Path(tempfile.gettempdir()) / "stockflow_dashboard"
        temp_dir.mkdir(parents=True, exist_ok=True)

        old_cached = self.secured_key_cache
        secured_path = temp_dir / f"id_ed25519_dashboard_{uuid.uuid4().hex}"
        shutil.copy2(source, secured_path)

        username = os.environ.get("USERNAME", "").strip()
        acl_commands = [
            ["icacls", str(secured_path), "/inheritance:r"],
            ["icacls", str(secured_path), "/remove:g", "BUILTIN\\Users", "NT AUTHORITY\\Authenticated Users"],
        ]
        if username:
            acl_commands.append(["icacls", str(secured_path), "/grant:r", f"{username}:(R)"])

        for command in acl_commands:
            subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False)

        self.secured_key_cache = str(secured_path)
        self.secured_key_source_signature = signature

        if old_cached:
            try:
                old_path = Path(old_cached)
                if old_path.exists():
                    subprocess.run(
                        ["attrib", "-R", str(old_path)],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        shell=False,
                    )
                    old_path.unlink(missing_ok=True)
            except Exception:
                pass

        return str(secured_path)

    def run_local_command(self, command, cwd=None):
        self.log("تشغيل: " + " ".join(command))
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
        if result.stdout.strip():
            self.log(result.stdout.strip())
        if result.stderr.strip():
            self.log(result.stderr.strip())
        if result.returncode != 0:
            raise RuntimeError(f"فشل تنفيذ الأمر. كود الخروج: {result.returncode}")
        return result.stdout.strip()

    def run_ssh(self, remote_command):
        command = self.ssh_base_command() + [remote_command]
        return self.run_local_command(command)

    def cairo_schedule_to_utc(self):
        try:
            hour = int(self.telegram_backup_hour_var.get().strip())
            minute = int(self.telegram_backup_minute_var.get().strip())
        except Exception:
            raise RuntimeError("اكتب ساعة ودقيقة صحيحتين لباك أب تيليجرام.")

        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise RuntimeError("وقت باك أب تيليجرام غير صحيح.")

        cairo_dt = datetime.combine(
            date.today(),
            time(hour=hour, minute=minute),
            tzinfo=ZoneInfo("Africa/Cairo"),
        )
        utc_dt = cairo_dt.astimezone(ZoneInfo("UTC"))
        return utc_dt.hour, utc_dt.minute

    def remote_absolute_path(self):
        relative = self.remote_relative_var.get().strip().replace("\\", "/").lstrip("/")
        if not relative:
            raise RuntimeError("اكتب مسار الملف داخل المشروع على السيرفر.")
        return f"{self.remote_root_var.get().strip().rstrip('/')}/{relative}"

    def resolve_remote_path_for_local_file(self, local_file: Path):
        relative = self.remote_relative_var.get().strip().replace("\\", "/").lstrip("/")
        if relative:
            return f"{self.remote_root_var.get().strip().rstrip('/')}/{relative}"

        remote_root = self.remote_root_var.get().strip().rstrip("/")
        basename = local_file.name
        command = (
            f"cd {shlex.quote(remote_root)} && "
            f"find . -type f -iname {shlex.quote(basename)} | sort"
        )
        output = self.run_ssh(command)
        matches = [line.strip() for line in output.splitlines() if line.strip()]

        if not matches:
            raise RuntimeError("لم أجد ملفاً بنفس الاسم على السيرفر. اكتب المسار داخل المشروع مرة واحدة فقط.")
        if len(matches) > 1:
            joined = "\n".join(matches[:20])
            raise RuntimeError(f"وجدت أكثر من ملف بنفس الاسم على السيرفر. اختر المسار يدوياً:\n{joined}")

        relative_match = matches[0].lstrip("./")
        self.remote_relative_var.set(relative_match)
        self.log(f"تم تحديد الملف على السيرفر تلقائياً: {relative_match}")
        return f"{remote_root}/{relative_match}"

    def download_remote_file_backup(self, remote_path):
        local_backup_dir = app_base_dir() / "downloaded_server_versions"
        local_backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        remote_name = PurePosixPath(remote_path).name
        destination = local_backup_dir / f"{timestamp}__{remote_name}"
        remote_source = f"{self.user_var.get().strip()}@{self.host_var.get().strip()}:{remote_path}"
        scp_cmd = self.scp_base_command() + [remote_source, str(destination)]
        self.run_local_command(scp_cmd)
        self.last_downloaded_old_file = destination
        self.log(f"تم تنزيل النسخة القديمة على جهازك: {destination}")
        return destination

    def prompt_delete_local_old_backup(self, backup_path: Path):
        if not backup_path or not Path(backup_path).exists():
            return
        answer = messagebox.askyesno(
            "النسخة القديمة المحلية",
            f"تم الرفع بنجاح.\n\nهل تريد حذف النسخة القديمة التي نزلناها عندك؟\n{backup_path}",
        )
        if answer:
            try:
                Path(backup_path).unlink(missing_ok=True)
                self.log(f"تم حذف النسخة القديمة المحلية: {backup_path}")
            except Exception as exc:
                messagebox.showerror("تعذر الحذف", str(exc))
        else:
            self.log(f"تم الاحتفاظ بالنسخة القديمة المحلية: {backup_path}")

    def test_connection(self):
        if not self.validate_connection():
            return

        def task():
            self.run_ssh("echo connected && hostname && pwd")

        self.run_async("اختبار الاتصال", task)

    def fetch_service_status(self):
        if not self.validate_connection():
            return

        def task():
            service = shlex.quote(self.service_var.get().strip())
            self.run_ssh(f"systemctl status {service} --no-pager -n 25")

        self.run_async("قراءة حالة الخدمة", task)

    def fetch_logs(self):
        if not self.validate_connection():
            return

        def task():
            service = shlex.quote(self.service_var.get().strip())
            self.run_ssh(f"journalctl -u {service} --no-pager -n 80")

        self.run_async("قراءة اللوج", task)

    def fetch_telegram_backup_status(self):
        if not self.validate_connection():
            return

        def task():
            self.run_ssh(
                "systemctl status stockflow-telegram-backup.timer --no-pager -n 30 "
                "&& systemctl status stockflow-telegram-backup.service --no-pager -n 30 "
                "&& systemctl list-timers stockflow-telegram-backup.timer --all --no-pager"
            )

        self.run_async("قراءة حالة باك أب تيليجرام", task)

    def restart_service(self):
        if not self.validate_connection():
            return
        if not messagebox.askyesno("تأكيد", "هل تريد إعادة تشغيل الخدمة الآن؟"):
            return

        def task():
            service = shlex.quote(self.service_var.get().strip())
            self.run_ssh(f"systemctl restart {service} && systemctl is-active {service}")

        self.run_async("إعادة تشغيل الخدمة", task)

    def update_telegram_backup_schedule(self):
        if not self.validate_connection():
            return

        try:
            utc_hour, utc_minute = self.cairo_schedule_to_utc()
        except Exception as exc:
            messagebox.showerror("وقت غير صحيح", str(exc))
            return

        if not messagebox.askyesno(
            "تأكيد",
            f"سيتم ضبط باك أب تيليجرام اليومي على {self.telegram_backup_hour_var.get().strip()}:{self.telegram_backup_minute_var.get().strip().zfill(2)} بتوقيت القاهرة. هل تريد المتابعة؟",
        ):
            return

        def task():
            timer_text = (
                "[Unit]\n"
                f"Description=Run Stock Flow Telegram backup daily at {self.telegram_backup_hour_var.get().strip()}:{self.telegram_backup_minute_var.get().strip().zfill(2)} Cairo time\n\n"
                "[Timer]\n"
                f"OnCalendar=*-*-* {utc_hour:02d}:{utc_minute:02d}:00 UTC\n"
                "Persistent=true\n"
                "Unit=stockflow-telegram-backup.service\n\n"
                "[Install]\n"
                "WantedBy=timers.target\n"
            )

            temp_timer = Path(tempfile.gettempdir()) / f"stockflow-telegram-backup-{uuid.uuid4().hex}.timer"
            temp_timer.write_text(timer_text, encoding="utf-8")
            try:
                remote_target = f"{self.user_var.get().strip()}@{self.host_var.get().strip()}:/etc/systemd/system/stockflow-telegram-backup.timer"
                scp_cmd = self.scp_base_command() + [str(temp_timer), remote_target]
                self.run_local_command(scp_cmd)
                self.run_ssh(
                    "chmod 644 /etc/systemd/system/stockflow-telegram-backup.timer "
                    "&& systemctl daemon-reload "
                    "&& systemctl restart stockflow-telegram-backup.timer "
                    "&& systemctl status stockflow-telegram-backup.timer --no-pager -n 20 "
                    "&& systemctl list-timers stockflow-telegram-backup.timer --all --no-pager"
                )
            finally:
                try:
                    temp_timer.unlink(missing_ok=True)
                except Exception:
                    pass

        self.run_async("تحديث موعد باك أب تيليجرام", task)

    def run_telegram_backup_now(self):
        if not self.validate_connection():
            return
        if not messagebox.askyesno("تأكيد", "سيتم تشغيل باك أب تيليجرام الآن فوراً. هل تريد المتابعة؟"):
            return

        def task():
            self.run_ssh(
                "systemctl start stockflow-telegram-backup.service "
                "&& systemctl status stockflow-telegram-backup.service --no-pager -n 60"
            )

        self.run_async("تشغيل باك أب تيليجرام الآن", task)

    def upload_selected_file(self):
        if not self.validate_connection():
            return

        local_file = Path(self.local_file_var.get().strip())
        if not local_file.exists():
            messagebox.showerror("ملف غير موجود", "اختر ملفاً محلياً صحيحاً قبل الرفع.")
            return

        if not messagebox.askyesno("تأكيد", "سيتم تنزيل النسخة الحالية من السيرفر عندك أولاً، ثم رفع الملف الجديد. هل تريد المتابعة؟"):
            return

        def task():
            remote_path = self.resolve_remote_path_for_local_file(local_file)
            remote_parent = str(PurePosixPath(remote_path).parent)
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = f"{remote_path}.bak-{timestamp}"

            local_old_copy = self.download_remote_file_backup(remote_path)
            self.run_ssh(
                f"mkdir -p {shlex.quote(remote_parent)} "
                f"&& cp {shlex.quote(remote_path)} {shlex.quote(backup_path)}"
            )
            self.log(f"تم إنشاء نسخة رجوع على السيرفر: {backup_path}")

            remote_target = f"{self.user_var.get().strip()}@{self.host_var.get().strip()}:{remote_path}"
            scp_cmd = self.scp_base_command() + [str(local_file), remote_target]
            self.run_local_command(scp_cmd)

            if self.restart_after_upload_var.get():
                service = shlex.quote(self.service_var.get().strip())
                self.run_ssh(f"systemctl restart {service} && systemctl is-active {service}")

            self.run_ssh(f"ls -la {shlex.quote(remote_path)}")
            self.root.after(0, lambda p=local_old_copy: self.prompt_delete_local_old_backup(p))

        self.run_async("رفع الملف", task)

    def load_backups_for_file(self):
        if not self.validate_connection():
            return

        if not self.remote_relative_var.get().strip():
            messagebox.showerror("مسار ناقص", "حدد أولاً الملف الذي تريد عرض نسخه السابقة.")
            return

        def task():
            remote_path = self.remote_absolute_path()
            output = self.run_ssh(f"ls -1t {shlex.quote(remote_path)}.bak-* 2>/dev/null | head -n 30")
            choices = [line.strip() for line in output.splitlines() if line.strip()]
            self.root.after(0, lambda: self.update_backup_choices(choices))

        self.run_async("جلب النسخ السابقة", task)

    def update_backup_choices(self, choices):
        self.backup_combo["values"] = choices
        if choices:
            self.backup_choice_var.set(choices[0])
            self.log(f"تم العثور على {len(choices)} نسخة سابقة.")
        else:
            self.backup_choice_var.set("")
            self.log("لا توجد نسخ سابقة لهذا الملف.")

    def restore_selected_backup(self):
        backup_path = self.backup_choice_var.get().strip()
        if not backup_path:
            messagebox.showerror("لا توجد نسخة", "اختر نسخة سابقة أولاً.")
            return
        if not self.validate_connection():
            return
        if not messagebox.askyesno("تأكيد", "سيتم استبدال الملف الحالي بالنسخة المحددة. هل تريد المتابعة؟"):
            return

        def task():
            remote_path = self.remote_absolute_path()
            service = shlex.quote(self.service_var.get().strip())
            self.run_ssh(
                f"cp {shlex.quote(backup_path)} {shlex.quote(remote_path)} "
                f"&& systemctl restart {service} "
                f"&& systemctl is-active {service}"
            )

        self.run_async("استرجاع النسخة المحددة", task)

    def restore_latest_backup(self):
        if not self.validate_connection():
            return
        if not self.remote_relative_var.get().strip():
            messagebox.showerror("مسار ناقص", "حدد أولاً الملف المطلوب.")
            return
        if not messagebox.askyesno("تأكيد", "سيتم استرجاع آخر نسخة محفوظة للملف الحالي. هل تريد المتابعة؟"):
            return

        def task():
            remote_path = self.remote_absolute_path()
            service = shlex.quote(self.service_var.get().strip())
            latest = self.run_ssh(f"ls -1t {shlex.quote(remote_path)}.bak-* 2>/dev/null | head -n 1")
            latest = latest.strip()
            if not latest:
                raise RuntimeError("لا توجد نسخة سابقة لهذا الملف.")
            self.run_ssh(
                f"cp {shlex.quote(latest)} {shlex.quote(remote_path)} "
                f"&& systemctl restart {service} "
                f"&& systemctl is-active {service}"
            )

        self.run_async("استرجاع آخر نسخة", task)

    def create_full_backup(self):
        if not self.validate_connection():
            return
        save_dir = filedialog.askdirectory(title="اختر مكان حفظ الباك أب الكامل على جهازك")
        if not save_dir:
            return
        if not messagebox.askyesno("تأكيد", "سيتم ضغط نسخة كاملة من الموقع على السيرفر ثم تنزيلها إلى المكان الذي اخترته على جهازك. هل تريد المتابعة؟"):
            return

        def task():
            root_dir = self.remote_root_var.get().strip().rstrip("/")
            parent_dir = str(PurePosixPath(root_dir).parent)
            base_name = PurePosixPath(root_dir).name
            backup_dir = f"{root_dir}/backups"
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            archive_name = f"{backup_dir}/stockflow-backup-{timestamp}.tar.gz"
            local_target = Path(save_dir) / f"stockflow-backup-{timestamp}.tar.gz"
            command = (
                f"mkdir -p {shlex.quote(backup_dir)} "
                f"&& tar -czf {shlex.quote(archive_name)} "
                f"--exclude={shlex.quote(base_name + '/venv')} "
                f"--exclude={shlex.quote(base_name + '/__pycache__')} "
                f"-C {shlex.quote(parent_dir)} {shlex.quote(base_name)} "
                f"&& ls -lh {shlex.quote(archive_name)}"
            )
            self.run_ssh(command)
            remote_source = f"{self.user_var.get().strip()}@{self.host_var.get().strip()}:{archive_name}"
            scp_cmd = self.scp_base_command() + [remote_source, str(local_target)]
            self.run_local_command(scp_cmd)
            self.log(f"تم تنزيل الباك أب الكامل على جهازك: {local_target}")

        self.run_async("إنشاء باك أب كامل", task)

    def list_project_backups(self):
        if not self.validate_connection():
            return

        def task():
            backup_dir = f"{self.remote_root_var.get().strip().rstrip('/')}/backups"
            self.run_ssh(f"ls -1th {shlex.quote(backup_dir)} 2>/dev/null | head -n 30")

        self.run_async("عرض باك أبات المشروع", task)

    def list_remote_project_files(self):
        if not self.validate_connection():
            return

        def task():
            self.run_ssh(f"cd {shlex.quote(self.remote_root_var.get().strip())} && find . -maxdepth 2 -type f | sort | head -n 200")

        self.run_async("عرض ملفات المشروع", task)


def main():
    root = tk.Tk()
    DashboardApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
