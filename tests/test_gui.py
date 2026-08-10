"""Tests for the GUI's backend layers, and a headless smoke test of the window.

The job runner, environment checks and workflows are display-free by design, so
the awkward parts are tested directly. The window itself is exercised under a
virtual display when one is available.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest
from PIL import Image

from wowicons import generate
from wowicons.gui import environment, workflows
from wowicons.gui.jobs import CancelledError, JobRunner, JobStatus

from .test_compositing import border_template


def wait_for(runner: JobRunner, timeout: float = 5.0) -> None:
    runner.join(timeout)


def drain_all(runner: JobRunner):
    return runner.drain(limit=10_000)


# ---------------------------------------------------------------------------
# Job runner
# ---------------------------------------------------------------------------


def test_successful_job_reports_result_and_status():
    runner = JobRunner()
    runner.start("test", lambda handle: 42)
    wait_for(runner)

    events = drain_all(runner)
    kinds = [event.kind for event in events]

    assert runner.status == JobStatus.SUCCEEDED
    assert "result" in kinds
    assert next(e for e in events if e.kind == "result").payload == 42


def test_worker_logs_and_progress_reach_the_queue():
    runner = JobRunner()

    def work(handle):
        handle.log("line one\nline two")
        handle.progress(0.5, "halfway")
        return None

    runner.start("test", work)
    wait_for(runner)
    events = drain_all(runner)

    logs = [e.message for e in events if e.kind == "log"]
    assert "line one" in logs and "line two" in logs

    progress = next(e for e in events if e.kind == "progress")
    assert progress.fraction == 0.5
    assert progress.message == "halfway"


def test_failing_job_does_not_propagate_and_gives_a_readable_status():
    runner = JobRunner()
    runner.start("test", lambda handle: (_ for _ in ()).throw(ValueError("bad folder")))
    wait_for(runner)

    events = drain_all(runner)
    status = next(e for e in events if e.kind == "status" and e.status == JobStatus.FAILED)

    assert runner.status == JobStatus.FAILED
    assert status.message == "bad folder"
    # The full traceback still goes to the log for diagnosis.
    assert any("Traceback" in e.message for e in events if e.kind == "log")


def test_missing_file_errors_are_translated():
    runner = JobRunner()

    def work(handle):
        raise FileNotFoundError(2, "No such file", "/nope/models.safetensors")

    runner.start("test", work)
    wait_for(runner)
    status = next(
        e for e in drain_all(runner) if e.kind == "status" and e.status == JobStatus.FAILED
    )
    assert "Could not find" in status.message


def test_cancellation_is_observed_by_the_worker():
    runner = JobRunner()
    started = []

    def work(handle):
        started.append(True)
        for _ in range(2000):
            handle.raise_if_cancelled()
            time.sleep(0.001)
        return "finished"

    runner.start("test", work)
    while not started:
        time.sleep(0.005)
    runner.cancel()
    wait_for(runner)

    assert runner.status == JobStatus.CANCELLED


def test_only_one_job_runs_at_a_time():
    runner = JobRunner()
    runner.start("first", lambda handle: time.sleep(0.3))

    with pytest.raises(RuntimeError, match="still running"):
        runner.start("second", lambda handle: None)

    wait_for(runner)


def test_progress_fraction_is_clamped():
    runner = JobRunner()
    runner.start("test", lambda handle: handle.progress(5.0, "over"))
    wait_for(runner)
    progress = next(e for e in drain_all(runner) if e.kind == "progress")
    assert progress.fraction == 1.0


# ---------------------------------------------------------------------------
# Environment checks
# ---------------------------------------------------------------------------


def test_training_check_flags_missing_sd_scripts(tmp_path):
    report = environment.check_training(sd_scripts_dir=str(tmp_path), dataset_dir=str(tmp_path))
    assert not report.ready
    names = [check.name for check in report.blocking]
    assert "sd-scripts" in names
    assert any("github.com/kohya-ss" in check.fix for check in report.checks)


def test_training_check_counts_dataset_images(tmp_path):
    images = tmp_path / "img" / "10_wowicon icon"
    images.mkdir(parents=True)
    (images / "a.png").write_bytes(b"x")

    report = environment.check_training(dataset_dir=str(tmp_path))
    dataset_check = next(c for c in report.checks if c.name == "Dataset")

    assert dataset_check.ok
    assert "1 images" in dataset_check.detail


def test_generation_check_reports_optional_dependencies():
    report = environment.check_generation()
    # torch and diffusers are optional, so their absence must not block.
    assert report.ready
    assert any(check.name == "PyTorch" for check in report.checks)


def test_generation_check_notices_a_missing_lora(tmp_path):
    report = environment.check_generation(lora_path=str(tmp_path / "absent.safetensors"))
    lora = next(c for c in report.checks if c.name == "Trained LoRA")
    assert not lora.ok
    assert "Train one on the Train tab" in lora.fix


def test_summary_is_a_sentence():
    report = environment.check_training(sd_scripts_dir="", dataset_dir="")
    assert report.summary()
    assert not report.summary().startswith("[")


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


def test_dataset_settings_reject_a_missing_folder(tmp_path):
    settings = workflows.DatasetSettings(input_dir=str(tmp_path / "nope"), output_dir=str(tmp_path))
    with pytest.raises(ValueError, match="does not exist"):
        settings.validate()


def test_dataset_settings_require_an_input():
    with pytest.raises(ValueError, match="Choose the folder"):
        workflows.DatasetSettings(output_dir="x").validate()


def test_dataset_build_end_to_end(tmp_path):
    """A real .blp in, a real kohya folder out, through the job runner."""
    from .blp_builders import build_blp1_palettized

    icons = tmp_path / "icons"
    icons.mkdir()
    (icons / "INV_Sword_04.blp").write_bytes(
        build_blp1_palettized(64, 64, [0] * 4096, [(255, 0, 0)])
    )

    output = tmp_path / "dataset"
    runner = JobRunner()
    settings = workflows.DatasetSettings(input_dir=str(icons), output_dir=str(output))
    runner.start("build", lambda handle: workflows.run_dataset_build(handle, settings))
    wait_for(runner, 20)

    result = next(e for e in drain_all(runner) if e.kind == "result").payload

    assert runner.status == JobStatus.SUCCEEDED
    assert result.written == 1
    assert result.categories == {"weapon": 1}
    assert (output / "manifest.csv").is_file()


def test_dataset_build_explains_an_empty_folder(tmp_path):
    icons = tmp_path / "icons"
    icons.mkdir()
    runner = JobRunner()
    settings = workflows.DatasetSettings(input_dir=str(icons), output_dir=str(tmp_path / "out"))
    runner.start("build", lambda handle: workflows.run_dataset_build(handle, settings))
    wait_for(runner, 10)

    status = next(
        e for e in drain_all(runner) if e.kind == "status" and e.status == JobStatus.FAILED
    )
    assert "No icons were converted" in status.message


def test_training_command_contains_the_important_flags(tmp_path):
    images = tmp_path / "img" / "10_wowicon icon"
    images.mkdir(parents=True)
    (images / "a.png").write_bytes(b"x")
    scripts = tmp_path / "sd-scripts"
    scripts.mkdir()
    (scripts / "train_network.py").write_text("")

    command = workflows.build_training_command(
        workflows.TrainingSettings(
            sd_scripts_dir=str(scripts), dataset_dir=str(tmp_path), epochs=7, network_dim=64
        )
    )

    assert "--network_module" in command
    assert command[command.index("--max_train_epochs") + 1] == "7"
    assert command[command.index("--network_dim") + 1] == "64"
    # alpha defaults to half the dim
    assert command[command.index("--network_alpha") + 1] == "32"
    assert command[command.index("--keep_tokens") + 1] == "1"


def test_training_validation_points_at_sd_scripts(tmp_path):
    with pytest.raises(ValueError, match="kohya-ss/sd-scripts"):
        workflows.TrainingSettings(sd_scripts_dir=str(tmp_path)).validate()


def test_training_streams_output_and_detects_failure(tmp_path):
    images = tmp_path / "img" / "10_wowicon icon"
    images.mkdir(parents=True)
    (images / "a.png").write_bytes(b"x")
    scripts = tmp_path / "sd-scripts"
    scripts.mkdir()
    (scripts / "train_network.py").write_text("")

    settings = workflows.TrainingSettings(
        sd_scripts_dir=str(scripts), dataset_dir=str(tmp_path)
    )

    def fake_popen(command, **kwargs):
        return subprocess.Popen(
            [
                "python", "-c",
                "print('epoch 1/10'); print('boom'); raise SystemExit(3)",
            ],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )

    runner = JobRunner()
    runner.start(
        "train", lambda handle: workflows.run_training(handle, settings, popen=fake_popen)
    )
    wait_for(runner, 20)

    events = drain_all(runner)
    assert runner.status == JobStatus.FAILED
    assert any("epoch 1/10" in e.message for e in events if e.kind == "log")
    status = next(e for e in events if e.kind == "status" and e.status == JobStatus.FAILED)
    assert "exit code 3" in status.message


def test_epoch_progress_is_parsed():
    assert workflows._parse_epoch_progress("epoch 5/10", 10) == 0.5
    assert workflows._parse_epoch_progress("steps: 40/900", 10) is None
    assert workflows._parse_epoch_progress("nothing here", 10) is None


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def test_generation_produces_composited_icons(tmp_path):
    template = tmp_path / "border.png"
    border_template().save(template)

    runner = JobRunner()
    settings = workflows.GenerateSettings(
        prompt="weapon, sword",
        seed=7,
        steps=2,
        batch_count=3,
        template_path=str(template),
        force_stub=True,
    )
    runner.start("gen", lambda handle: workflows.run_generation(handle, settings))
    wait_for(runner, 30)

    results = next(e for e in drain_all(runner) if e.kind == "result").payload

    assert runner.status == JobStatus.SUCCEEDED
    assert len(results) == 3
    assert [r.seed for r in results] == [7, 8, 9]
    for result in results:
        assert result.icon.size == (64, 64)
        assert result.icon.getpixel((0, 0))[3] == 0      # corner stayed transparent
        assert result.prompt.startswith("wowicon, ")     # trigger word applied


def test_generation_rejects_an_empty_prompt():
    runner = JobRunner()
    settings = workflows.GenerateSettings(prompt="  ", force_stub=True)
    runner.start("gen", lambda handle: workflows.run_generation(handle, settings))
    wait_for(runner, 10)

    status = next(
        e for e in drain_all(runner) if e.kind == "status" and e.status == JobStatus.FAILED
    )
    assert "Enter a prompt" in status.message


def test_generation_reports_a_missing_template(tmp_path):
    runner = JobRunner()
    settings = workflows.GenerateSettings(
        prompt="sword", steps=1, template_path=str(tmp_path / "absent.png"), force_stub=True
    )
    runner.start("gen", lambda handle: workflows.run_generation(handle, settings))
    wait_for(runner, 10)

    status = next(
        e for e in drain_all(runner) if e.kind == "status" and e.status == JobStatus.FAILED
    )
    assert "Border template not found" in status.message


def test_generation_works_without_a_template():
    runner = JobRunner()
    settings = workflows.GenerateSettings(prompt="sword", steps=1, batch_count=1, force_stub=True)
    runner.start("gen", lambda handle: workflows.run_generation(handle, settings))
    wait_for(runner, 20)

    results = next(e for e in drain_all(runner) if e.kind == "result").payload
    assert results[0].icon.size == (64, 64)


def test_generation_can_be_cancelled():
    runner = JobRunner()
    settings = workflows.GenerateSettings(
        prompt="sword", steps=150, batch_count=8, force_stub=True
    )
    runner.start(
        "gen",
        lambda handle: workflows.run_generation(
            handle, settings, backend=generate.StubBackend(delay_per_step=0.002)
        ),
    )
    time.sleep(0.1)
    runner.cancel()
    wait_for(runner, 20)

    assert runner.status == JobStatus.CANCELLED


def test_stub_backend_is_deterministic():
    first = generate.render_stub_art(42, "wowicon, weapon, sword")
    second = generate.render_stub_art(42, "wowicon, weapon, sword")
    assert first.tobytes() == second.tobytes()
    assert generate.render_stub_art(43, "x").tobytes() != first.tobytes()


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("weapon, sword", "wowicon, weapon, sword"),
        ("wowicon, weapon", "wowicon, weapon"),
        ("WowIcon, weapon", "WowIcon, weapon"),
        ("", "wowicon"),
    ],
)
def test_trigger_word_handling(prompt, expected):
    assert generate.build_prompt(prompt) == expected


def test_create_backend_falls_back_to_the_stub():
    backend = generate.create_backend(force_stub=True)
    assert isinstance(backend, generate.StubBackend)
    assert "placeholder" in backend.description


def test_save_icon_writes_png_and_blp(tmp_path):
    icon = Image.new("RGBA", (64, 64), (255, 0, 0, 255))

    png = workflows.save_icon(icon, str(tmp_path / "a.png"))
    blp_path = workflows.save_icon(icon, str(tmp_path / "a.blp"))

    assert Path(png).is_file()
    assert Path(blp_path).read_bytes()[:4] == b"BLP2"


@pytest.mark.parametrize(
    "prompt,seed,expected",
    [
        ("wowicon, weapon, sword", 42, "wowicon_weapon_sword_42.png"),
        ("", 7, "icon_7.png"),
        ("!!!", 7, "icon_7.png"),
    ],
)
def test_suggested_file_names_are_safe(prompt, seed, expected):
    assert workflows.suggest_file_name(prompt, seed) == expected


# ---------------------------------------------------------------------------
# Window smoke test
# ---------------------------------------------------------------------------

tkinter = pytest.importorskip("tkinter", reason="tkinter is not installed for this interpreter")


@pytest.fixture()
def window():
    try:
        root = tkinter.Tk()
    except tkinter.TclError as exc:
        pytest.skip(f"no display available: {exc}")
    yield root
    try:
        root.destroy()
    except tkinter.TclError:
        pass


def test_window_builds_with_all_tabs(window):
    from wowicons.gui.app import IconForgeApp

    app = IconForgeApp(window)
    window.update()

    tabs = [app.notebook.tab(i, "text").strip() for i in range(app.notebook.index("end"))]
    assert tabs == ["1. Dataset", "2. Train", "3. Generate", "Settings"]
    assert app.status_var.get() == "Ready."
    assert str(app.cancel_button.cget("state")) == "disabled"


def test_window_shows_results_grid(window, tmp_path):
    """Drive a real generation and confirm the previews appear."""
    from wowicons.gui.app import IconForgeApp

    template = tmp_path / "border.png"
    border_template().save(template)

    app = IconForgeApp(window)
    app.template_path.set(str(template))
    app.prompt_text.delete("1.0", "end")
    app.prompt_text.insert("1.0", "weapon, sword")
    app.steps_var.set(1)
    app.batch_var.set(2)
    window.update()

    app._start_generation()
    for _ in range(400):
        window.update()
        app._pump_events()
        if not app.runner.is_running and app._results:
            break
        time.sleep(0.02)

    assert len(app._results) == 2
    assert len(app._preview_images) == 2
    # 64px icon shown at 4x so the pixels stay crisp
    assert app._preview_images[0].width() == 64 * 4
    assert str(app.cancel_button.cget("state")) == "disabled"


def test_window_validates_before_starting(window, monkeypatch):
    from wowicons.gui import app as app_module

    errors = []
    monkeypatch.setattr(
        app_module.messagebox, "showerror", lambda title, message: errors.append(message)
    )

    app = app_module.IconForgeApp(window)
    app.dataset_input.set("")
    app._start_dataset_build()

    assert errors and "Choose the folder" in errors[0]
    assert not app.runner.is_running
