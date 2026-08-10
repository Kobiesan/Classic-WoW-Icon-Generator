"""The WoW Icon Forge desktop window.

Three numbered tabs in the order you use them: build a dataset from your icon
files, train on it, then generate new icons. Everything long-running goes
through :mod:`wowicons.gui.jobs`, so the window never freezes and every job can
be cancelled.

This module is deliberately thin. All the real work lives in
:mod:`wowicons.gui.workflows`, which is tested without a display.
"""

from __future__ import annotations

import json
import random
import sys
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .. import compositing, generate
from . import environment, workflows
from .jobs import JobRunner, JobStatus

__all__ = ["IconForgeApp", "main"]

APP_TITLE = "WoW Icon Forge"
POLL_INTERVAL_MS = 80
PREVIEW_ZOOM = 4
PREVIEW_COLUMNS = 2
SETTINGS_FILE = Path.home() / ".wowiconforge" / "gui-settings.json"


class IconForgeApp:
    """The main window."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1040x760")
        self.root.minsize(900, 640)

        self.runner = JobRunner()
        self.settings: Dict[str, object] = self._load_settings()

        # Keeping references to PhotoImages is mandatory: Tk does not own them
        # and they vanish from the display the moment Python collects them.
        self._preview_images: List[ImageTk.PhotoImage] = []
        self._results: List[workflows.GeneratedResult] = []
        self._sample_images: List[ImageTk.PhotoImage] = []

        self._build_ui()
        self._restore_settings()
        self._after_id: Optional[str] = None
        self._closing = False
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._after_id = self.root.after(POLL_INTERVAL_MS, self._pump_events)

    # -- layout ------------------------------------------------------------

    def _build_ui(self) -> None:
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        self.dataset_tab = ttk.Frame(self.notebook, padding=12)
        self.train_tab = ttk.Frame(self.notebook, padding=12)
        self.generate_tab = ttk.Frame(self.notebook, padding=12)
        self.settings_tab = ttk.Frame(self.notebook, padding=12)

        self.notebook.add(self.dataset_tab, text="  1. Dataset  ")
        self.notebook.add(self.train_tab, text="  2. Train  ")
        self.notebook.add(self.generate_tab, text="  3. Generate  ")
        self.notebook.add(self.settings_tab, text="  Settings  ")

        self._build_dataset_tab()
        self._build_train_tab()
        self._build_generate_tab()
        self._build_settings_tab()
        self._build_status_bar()

    def _build_status_bar(self) -> None:
        bar = ttk.Frame(self.root, padding=(12, 6))
        bar.pack(fill="x", side="bottom")

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress = ttk.Progressbar(
            bar, variable=self.progress_var, maximum=1.0, length=260
        )
        self.progress.pack(side="left")

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(bar, textvariable=self.status_var).pack(side="left", padx=12)

        self.cancel_button = ttk.Button(
            bar, text="Cancel", command=self._cancel_job, state="disabled"
        )
        self.cancel_button.pack(side="right")

    # -- tab 1: dataset ----------------------------------------------------

    def _build_dataset_tab(self) -> None:
        frame = self.dataset_tab

        ttk.Label(
            frame,
            text="Turn a folder of WoW icon files into training material.",
            font=("", 11, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(
            frame,
            text="You need .blp files extracted from a WoW client - normally the "
                 "Interface/Icons folder.",
            foreground="#555555",
            wraplength=900,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 12))

        self.dataset_input = self._add_path_row(
            frame, 2, "Folder with your .blp icons", self._browse_directory
        )
        self.dataset_output = self._add_path_row(
            frame, 3, "Save the dataset to", self._browse_directory
        )
        self.dataset_overrides = self._add_path_row(
            frame, 4, "Caption corrections (optional)", self._browse_json
        )

        size_row = ttk.Frame(frame)
        size_row.grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 12))
        ttk.Label(size_row, text="Ignore icons smaller than").pack(side="left")
        self.dataset_min_size = tk.IntVar(value=64)
        ttk.Spinbox(
            size_row, from_=1, to=1024, width=6, textvariable=self.dataset_min_size
        ).pack(side="left", padx=6)
        ttk.Label(size_row, text="pixels").pack(side="left")

        self.dataset_button = ttk.Button(
            frame, text="Build dataset", command=self._start_dataset_build
        )
        self.dataset_button.grid(row=6, column=0, sticky="w")
        ttk.Button(
            frame, text="Open dataset folder", command=self._open_dataset_folder
        ).grid(row=6, column=1, sticky="w", padx=8)

        self.dataset_log = self._add_log(frame, row=7)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(7, weight=1)

    # -- tab 2: train ------------------------------------------------------

    def _build_train_tab(self) -> None:
        frame = self.train_tab

        ttk.Label(
            frame, text="Teach a model your icon style.", font=("", 11, "bold")
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(
            frame,
            text="Training needs a graphics card and takes a while. You can close "
                 "this tab and come back - it keeps running.",
            foreground="#555555",
            wraplength=900,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 12))

        self.train_scripts = self._add_path_row(
            frame, 2, "sd-scripts folder", self._browse_directory
        )
        ttk.Button(
            frame,
            text="Where do I get this?",
            command=lambda: webbrowser.open("https://github.com/kohya-ss/sd-scripts"),
        ).grid(row=2, column=3, padx=(6, 0))

        self.train_dataset = self._add_path_row(
            frame, 3, "Dataset folder", self._browse_directory
        )

        options = ttk.Frame(frame)
        options.grid(row=4, column=0, columnspan=4, sticky="w", pady=(8, 12))

        self.train_epochs = self._add_spin(options, "Passes over the data", 10, 1, 200, 0)
        self.train_batch = self._add_spin(options, "Images at a time", 4, 1, 64, 1)
        self.train_dim = self._add_spin(options, "Detail capacity", 32, 4, 256, 2)

        self.train_button = ttk.Button(
            frame, text="Start training", command=self._start_training
        )
        self.train_button.grid(row=5, column=0, sticky="w")
        ttk.Button(
            frame, text="Check what's needed", command=self._check_training_environment
        ).grid(row=5, column=1, sticky="w", padx=8)

        self.train_log = self._add_log(frame, row=6)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(6, weight=1)

    # -- tab 3: generate ---------------------------------------------------

    def _build_generate_tab(self) -> None:
        frame = self.generate_tab
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(0, weight=1)

        left = ttk.Frame(frame)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 14))

        ttk.Label(left, text="Describe your icon", font=("", 11, "bold")).pack(anchor="w")
        self.prompt_text = tk.Text(left, width=38, height=4, wrap="word")
        self.prompt_text.pack(fill="x", pady=(4, 2))
        self.prompt_text.insert("1.0", "weapon, sword, glowing blue runes")

        ttk.Label(left, text="Things to avoid (optional)", foreground="#555555").pack(anchor="w")
        self.negative_text = tk.Text(left, width=38, height=2, wrap="word")
        self.negative_text.pack(fill="x", pady=(2, 8))
        self.negative_text.insert("1.0", "blurry, photo, text, watermark")

        seed_row = ttk.Frame(left)
        seed_row.pack(fill="x", pady=2)
        ttk.Label(seed_row, text="Seed").pack(side="left")
        self.seed_var = tk.IntVar(value=42)
        ttk.Entry(seed_row, textvariable=self.seed_var, width=12).pack(side="left", padx=6)
        ttk.Button(seed_row, text="Randomize", command=self._randomize_seed).pack(side="left")

        grid = ttk.Frame(left)
        grid.pack(fill="x", pady=(8, 8))
        self.steps_var = self._add_spin(grid, "Quality (steps)", 24, 1, 150, 0, vertical=True)
        self.cfg_var = self._add_spin(
            grid, "Prompt strength", 7.5, 1, 30, 1, vertical=True, is_float=True
        )
        self.batch_var = self._add_spin(grid, "How many", 4, 1, 8, 2, vertical=True)

        self.generate_button = ttk.Button(
            left, text="Generate icons", command=self._start_generation
        )
        self.generate_button.pack(fill="x", pady=(6, 4))

        self.backend_label = ttk.Label(left, text="", foreground="#555555", wraplength=280)
        self.backend_label.pack(anchor="w", pady=(4, 0))

        right = ttk.Frame(frame)
        right.grid(row=0, column=1, sticky="nsew")
        ttk.Label(right, text="Results", font=("", 11, "bold")).pack(anchor="w")

        # Eight 64px previews at 4x are ~2.5 screens tall, so the grid scrolls
        # rather than being clipped at the pane edge.
        canvas_holder = ttk.Frame(right)
        canvas_holder.pack(fill="both", expand=True, pady=(6, 0))

        self.results_canvas = tk.Canvas(canvas_holder, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            canvas_holder, orient="vertical", command=self.results_canvas.yview
        )
        self.results_canvas.configure(yscrollcommand=scrollbar.set)
        self.results_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.results_frame = ttk.Frame(self.results_canvas)
        self._results_window = self.results_canvas.create_window(
            (0, 0), window=self.results_frame, anchor="nw"
        )
        self.results_frame.bind(
            "<Configure>",
            lambda _e: self.results_canvas.configure(
                scrollregion=self.results_canvas.bbox("all")
            ),
        )
        self.results_canvas.bind(
            "<Configure>",
            lambda e: self.results_canvas.itemconfigure(self._results_window, width=e.width),
        )
        self.results_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.results_canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.results_canvas.bind_all("<Button-5>", self._on_mousewheel)

        self._refresh_backend_label()

    # -- settings ----------------------------------------------------------

    def _build_settings_tab(self) -> None:
        frame = self.settings_tab

        ttk.Label(frame, text="Appearance", font=("", 11, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        self.template_path = self._add_path_row(
            frame, 1, "Border template (64x64 PNG)", self._browse_image
        )
        self.output_dir = self._add_path_row(
            frame, 2, "Save icons to", self._browse_directory
        )

        sharpen_row = ttk.Frame(frame)
        sharpen_row.grid(row=3, column=0, columnspan=3, sticky="w", pady=8)
        ttk.Label(sharpen_row, text="Sharpening").pack(side="left")
        self.sharpen_var = tk.DoubleVar(value=compositing.DEFAULT_SHARPEN_AMOUNT)
        ttk.Scale(
            sharpen_row, from_=0.0, to=2.0, variable=self.sharpen_var, length=220
        ).pack(side="left", padx=8)

        trigger_row = ttk.Frame(frame)
        trigger_row.grid(row=4, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Label(trigger_row, text="Style keyword").pack(side="left")
        self.trigger_var = tk.StringVar(value=generate.DEFAULT_TRIGGER_WORD)
        ttk.Entry(trigger_row, textvariable=self.trigger_var, width=20).pack(side="left", padx=8)

        ttk.Label(frame, text="Model", font=("", 11, "bold")).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(16, 4)
        )
        self.lora_path = self._add_path_row(
            frame, 6, "Your trained style file (.safetensors)", self._browse_safetensors
        )

        ttk.Button(
            frame, text="Check what's installed", command=self._check_generation_environment
        ).grid(row=7, column=0, sticky="w", pady=(10, 0))

        self.settings_log = self._add_log(frame, row=8, height=10)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(8, weight=1)

    # -- small widget helpers ---------------------------------------------

    def _add_path_row(self, parent, row, label, browser) -> tk.StringVar:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        var = tk.StringVar()
        entry = ttk.Entry(parent, textvariable=var)
        entry.grid(row=row, column=1, sticky="ew", padx=8, pady=3)
        ttk.Button(parent, text="Browse...", command=lambda: browser(var)).grid(
            row=row, column=2, pady=3
        )
        return var

    def _add_spin(
        self, parent, label, default, low, high, column, vertical=False, is_float=False
    ):
        holder = ttk.Frame(parent)
        holder.grid(row=0, column=column, padx=(0, 14), sticky="w")
        ttk.Label(holder, text=label).pack(anchor="w")
        var = tk.DoubleVar(value=default) if is_float else tk.IntVar(value=default)
        ttk.Spinbox(
            holder,
            from_=low,
            to=high,
            width=8,
            textvariable=var,
            increment=0.5 if is_float else 1,
        ).pack(anchor="w")
        return var

    def _add_log(self, parent, row, height=14) -> tk.Text:
        holder = ttk.Frame(parent)
        holder.grid(row=row, column=0, columnspan=4, sticky="nsew", pady=(12, 0))
        text = tk.Text(holder, height=height, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(holder, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return text

    def _append_log(self, widget: tk.Text, message: str) -> None:
        widget.configure(state="normal")
        widget.insert("end", message + "\n")
        widget.see("end")
        widget.configure(state="disabled")

    # -- browsing ----------------------------------------------------------

    def _browse_directory(self, var: tk.StringVar) -> None:
        chosen = filedialog.askdirectory(initialdir=var.get() or str(Path.home()))
        if chosen:
            var.set(chosen)

    def _browse_json(self, var: tk.StringVar) -> None:
        chosen = filedialog.askopenfilename(filetypes=[("JSON files", "*.json"), ("All files", "*")])
        if chosen:
            var.set(chosen)

    def _browse_image(self, var: tk.StringVar) -> None:
        chosen = filedialog.askopenfilename(filetypes=[("PNG images", "*.png"), ("All files", "*")])
        if chosen:
            var.set(chosen)

    def _browse_safetensors(self, var: tk.StringVar) -> None:
        chosen = filedialog.askopenfilename(
            filetypes=[("Model files", "*.safetensors"), ("All files", "*")]
        )
        if chosen:
            var.set(chosen)

    # -- jobs --------------------------------------------------------------

    def _job_running(self) -> bool:
        if self.runner.is_running:
            messagebox.showinfo(
                APP_TITLE, "Something is already running. Wait for it, or press Cancel."
            )
            return True
        return False

    def _start_dataset_build(self) -> None:
        if self._job_running():
            return

        settings = workflows.DatasetSettings(
            input_dir=self.dataset_input.get().strip(),
            output_dir=self.dataset_output.get().strip(),
            overrides_path=self.dataset_overrides.get().strip(),
            min_size=int(self.dataset_min_size.get()),
        )

        try:
            settings.validate()
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        self._active_log = self.dataset_log
        self._clear_log(self.dataset_log)
        self.runner.start(
            "Dataset build", lambda handle: workflows.run_dataset_build(handle, settings)
        )
        self._set_busy(True)

    def _start_training(self) -> None:
        if self._job_running():
            return

        settings = workflows.TrainingSettings(
            sd_scripts_dir=self.train_scripts.get().strip(),
            dataset_dir=self.train_dataset.get().strip() or self.dataset_output.get().strip(),
            epochs=int(self.train_epochs.get()),
            batch_size=int(self.train_batch.get()),
            network_dim=int(self.train_dim.get()),
        )

        try:
            settings.validate()
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        if not messagebox.askyesno(
            APP_TITLE,
            "Training can run for hours and will use your graphics card heavily.\n\n"
            "Start now?",
        ):
            return

        self._active_log = self.train_log
        self._clear_log(self.train_log)
        self.runner.start("Training", lambda handle: workflows.run_training(handle, settings))
        self._set_busy(True)

    def _start_generation(self) -> None:
        if self._job_running():
            return

        settings = workflows.GenerateSettings(
            prompt=self.prompt_text.get("1.0", "end").strip(),
            negative_prompt=self.negative_text.get("1.0", "end").strip(),
            seed=int(self.seed_var.get()),
            steps=int(self.steps_var.get()),
            cfg_scale=float(self.cfg_var.get()),
            batch_count=int(self.batch_var.get()),
            trigger_word=self.trigger_var.get().strip() or generate.DEFAULT_TRIGGER_WORD,
            template_path=self.template_path.get().strip(),
            sharpen_amount=float(self.sharpen_var.get()),
            lora_path=self.lora_path.get().strip(),
        )

        self._active_log = self.settings_log
        self.runner.start(
            "Generation", lambda handle: workflows.run_generation(handle, settings)
        )
        self._set_busy(True)

    def _cancel_job(self) -> None:
        self.runner.cancel()
        self.status_var.set("Stopping...")

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for button in (self.dataset_button, self.train_button, self.generate_button):
            button.configure(state=state)
        self.cancel_button.configure(state="normal" if busy else "disabled")

    def _clear_log(self, widget: tk.Text) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.configure(state="disabled")

    # -- event pump --------------------------------------------------------

    def _pump_events(self) -> None:
        """Drain worker events on the UI thread. The only place widgets change."""
        if self._closing:
            return

        log = getattr(self, "_active_log", self.dataset_log)

        for event in self.runner.drain():
            if event.kind == "log":
                self._append_log(log, event.message)
            elif event.kind == "progress":
                if event.fraction is not None:
                    self.progress_var.set(event.fraction)
                if event.message:
                    self.status_var.set(event.message)
            elif event.kind == "status":
                self.status_var.set(event.message)
                if event.status is not None and event.status.is_finished:
                    self._set_busy(False)
                    if event.status == JobStatus.FAILED:
                        self._append_log(log, event.message)
                        messagebox.showerror(APP_TITLE, event.message)
            elif event.kind == "result":
                self._handle_result(event.payload)

        self._after_id = self.root.after(POLL_INTERVAL_MS, self._pump_events)

    def _handle_result(self, payload) -> None:
        if isinstance(payload, workflows.DatasetResult):
            messagebox.showinfo(
                APP_TITLE,
                f"Dataset ready: {payload.written} icons.\n\n"
                "Next, go to the Train tab.",
            )
            if not self.train_dataset.get().strip():
                self.train_dataset.set(payload.output_dir)
        elif isinstance(payload, list) and payload and isinstance(
            payload[0], workflows.GeneratedResult
        ):
            self._show_results(payload)

    # -- results grid ------------------------------------------------------

    def _show_results(self, results: List[workflows.GeneratedResult]) -> None:
        for child in self.results_frame.winfo_children():
            child.destroy()
        self._preview_images.clear()
        self._results = results
        self.results_canvas.yview_moveto(0.0)

        for index, result in enumerate(results):
            row, column = divmod(index, PREVIEW_COLUMNS)
            cell = ttk.Frame(self.results_frame, padding=6)
            cell.grid(row=row, column=column, sticky="n")

            preview = result.icon.resize(
                (result.icon.width * PREVIEW_ZOOM, result.icon.height * PREVIEW_ZOOM),
                # Nearest neighbour so the pixels stay crisp instead of smearing.
                Image.NEAREST,
            )
            photo = ImageTk.PhotoImage(preview)
            self._preview_images.append(photo)

            ttk.Label(cell, image=photo, relief="solid", borderwidth=1).pack()
            ttk.Label(cell, text=f"seed {result.seed}", foreground="#555555").pack()

            buttons = ttk.Frame(cell)
            buttons.pack(pady=2)
            ttk.Button(
                buttons, text="PNG", width=5,
                command=lambda r=result: self._save_result(r, "png"),
            ).pack(side="left", padx=1)
            ttk.Button(
                buttons, text="BLP", width=5,
                command=lambda r=result: self._save_result(r, "blp"),
            ).pack(side="left", padx=1)
            ttk.Button(
                buttons, text="Again", width=6,
                command=lambda r=result: self._regenerate(r),
            ).pack(side="left", padx=1)

    def _on_mousewheel(self, event) -> None:
        """Scroll the results grid. Windows/macOS use delta, X11 uses buttons 4/5."""
        if event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        try:
            self.results_canvas.yview_scroll(delta, "units")
        except tk.TclError:
            pass

    def _save_result(self, result: workflows.GeneratedResult, extension: str) -> None:
        suggested = workflows.suggest_file_name(result.prompt, result.seed, extension)
        path = filedialog.asksaveasfilename(
            initialdir=self.output_dir.get() or str(Path.home()),
            initialfile=suggested,
            defaultextension=f".{extension}",
            filetypes=[(f"{extension.upper()} files", f"*.{extension}")],
        )
        if not path:
            return
        try:
            workflows.save_icon(result.icon, path)
        except Exception as exc:  # noqa: BLE001 - a failed save must not kill the app
            messagebox.showerror(APP_TITLE, f"Could not save the icon:\n{exc}")
        else:
            self.status_var.set(f"Saved {Path(path).name}")

    def _regenerate(self, result: workflows.GeneratedResult) -> None:
        self.seed_var.set(result.seed)
        self.batch_var.set(1)
        self._start_generation()

    def _randomize_seed(self) -> None:
        self.seed_var.set(random.randrange(0, 2**31 - 1))

    # -- environment checks ------------------------------------------------

    def _refresh_backend_label(self) -> None:
        backend = generate.create_backend(lora_path=self.lora_path.get().strip()
                                          if hasattr(self, "lora_path") else "")
        self.backend_label.configure(text=f"{backend.name}: {backend.description}")

    def _check_generation_environment(self) -> None:
        report = environment.check_generation(lora_path=self.lora_path.get().strip())
        self._clear_log(self.settings_log)
        self._active_log = self.settings_log
        for check in report.checks:
            self._append_log(self.settings_log, f"[{check.icon}] {check.name}: {check.detail}")
            if not check.ok and check.fix:
                self._append_log(self.settings_log, f"         {check.fix}")
        self._refresh_backend_label()

    def _check_training_environment(self) -> None:
        report = environment.check_training(
            sd_scripts_dir=self.train_scripts.get().strip(),
            dataset_dir=self.train_dataset.get().strip() or self.dataset_output.get().strip(),
        )
        self._active_log = self.train_log
        self._clear_log(self.train_log)
        for check in report.checks:
            self._append_log(self.train_log, f"[{check.icon}] {check.name}: {check.detail}")
            if not check.ok and check.fix:
                self._append_log(self.train_log, f"         {check.fix}")

    def _open_dataset_folder(self) -> None:
        path = self.dataset_output.get().strip()
        if not path or not Path(path).is_dir():
            messagebox.showinfo(APP_TITLE, "Build a dataset first.")
            return
        _open_in_file_manager(path)

    # -- persistence -------------------------------------------------------

    def _load_settings(self) -> Dict[str, object]:
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _restore_settings(self) -> None:
        mapping = {
            "dataset_input": self.dataset_input,
            "dataset_output": self.dataset_output,
            "dataset_overrides": self.dataset_overrides,
            "train_scripts": self.train_scripts,
            "train_dataset": self.train_dataset,
            "template_path": self.template_path,
            "output_dir": self.output_dir,
            "lora_path": self.lora_path,
        }
        for key, var in mapping.items():
            value = self.settings.get(key)
            if isinstance(value, str):
                var.set(value)

        if not self.dataset_output.get():
            suggested = environment.suggest_default_directory("dataset")
            if suggested:
                self.dataset_output.set(suggested)

        trigger = self.settings.get("trigger_word")
        if isinstance(trigger, str) and trigger:
            self.trigger_var.set(trigger)

        self._refresh_backend_label()

    def _save_settings(self) -> None:
        data = {
            "dataset_input": self.dataset_input.get(),
            "dataset_output": self.dataset_output.get(),
            "dataset_overrides": self.dataset_overrides.get(),
            "train_scripts": self.train_scripts.get(),
            "train_dataset": self.train_dataset.get(),
            "template_path": self.template_path.get(),
            "output_dir": self.output_dir.get(),
            "lora_path": self.lora_path.get(),
            "trigger_word": self.trigger_var.get(),
        }
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass  # settings are a convenience; never block closing on them

    def _on_close(self) -> None:
        if self.runner.is_running and not messagebox.askyesno(
            APP_TITLE, "Something is still running. Stop it and quit?"
        ):
            return
        # Cancel the pending tick before tearing the window down, or Tk fires
        # it against widgets that no longer exist.
        self._closing = True
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

        self.runner.cancel()
        self._save_settings()
        self.root.destroy()


def _open_in_file_manager(path: str) -> None:
    import subprocess

    if sys.platform == "win32":
        subprocess.Popen(["explorer", str(Path(path))])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def main(argv: Optional[List[str]] = None) -> int:
    """Launch the window."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(
            f"Could not open a window: {exc}\n"
            "On Linux you may need to install python3-tk.",
            file=sys.stderr,
        )
        return 1

    IconForgeApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
