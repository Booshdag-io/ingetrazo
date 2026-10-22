# SPDX-License-Identifier: GPL-3.0-or-later
"""Who draws the viewport — the diagnosis behind "IngeTrazo is unusably
slow on my Windows machine"."""
from __future__ import annotations

from core.glinfo import (GL_RENDERER, GL_VENDOR, GL_VERSION, describe,
                         is_software_renderer, read_gl_info, write_gl_report)


class _GL:
    def __init__(self, strings, fail=False):
        self.strings, self.fail = strings, fail

    def glGetString(self, enum):
        if self.fail:
            raise RuntimeError("no context")
        return self.strings.get(enum)


def test_software_rasterisers_are_recognised_and_gpus_are_not():
    assert is_software_renderer("GDI Generic", "Microsoft Corporation")
    assert is_software_renderer("llvmpipe (LLVM 17.0.6, 256 bits)", "Mesa")
    assert is_software_renderer("Google SwiftShader")
    assert not is_software_renderer("NVIDIA GeForce RTX 3060/PCIe/SSE2", "NVIDIA Corporation")
    assert not is_software_renderer("Intel(R) Iris(R) Xe Graphics", "Intel")
    assert not is_software_renderer("AMD Radeon RX 6600 (radeonsi, navi23)", "AMD")


def test_read_gl_info_decodes_bytes_and_flags_software():
    gl = _GL({GL_VENDOR: b"Microsoft Corporation", GL_RENDERER: b"GDI Generic",
              GL_VERSION: b"1.1.0"})
    info = read_gl_info(gl)
    assert info == {"vendor": "Microsoft Corporation", "renderer": "GDI Generic",
                    "version": "1.1.0", "software": True}
    gpu = read_gl_info(_GL({GL_VENDOR: "NVIDIA Corporation",
                            GL_RENDERER: "NVIDIA GeForce GTX 1650/PCIe/SSE2",
                            GL_VERSION: "3.3.0 NVIDIA 552.44"}))
    assert gpu["software"] is False
    assert describe(gpu) == ("NVIDIA GeForce GTX 1650/PCIe/SSE2 (NVIDIA Corporation) "
                             "— OpenGL 3.3.0 NVIDIA 552.44")


def test_a_silent_driver_never_breaks_start_up():
    info = read_gl_info(_GL({}, fail=True))
    assert info == {"vendor": "", "renderer": "", "version": "", "software": False}
    assert describe(info) == ""


def test_the_report_lands_in_the_log_folder(tmp_path):
    info = {"vendor": "Intel", "renderer": "Intel(R) UHD Graphics 620",
            "version": "4.6.0 - Build 31.0.101.2111", "software": False}
    out = write_gl_report(info, tmp_path / "logs" / "ingetrazo-gl.txt")
    text = out.read_text(encoding="utf-8")
    assert "renderer : Intel(R) UHD Graphics 620" in text
    assert "software : no" in text


# ---- #751: a context older than the shaders is said, not crashed on --------

class _Fmt:
    def __init__(self, major, minor):
        self.major, self.minor = major, minor

    def majorVersion(self):
        return self.major

    def minorVersion(self):
        return self.minor


def test_the_context_version_is_what_the_driver_gave():
    from core.glinfo import context_version
    # The live format wins over the string…
    assert context_version(_Fmt(3, 0), "4.6.0 NVIDIA 576.02") == (3, 0)
    # …and the string answers when the format says nothing.
    assert context_version(_Fmt(0, 0), "3.0 Mesa 11.2.2") == (3, 0)
    assert context_version(None, "4.6.0 NVIDIA 576.02") == (4, 6)
    assert context_version(None, "OpenGL ES 3.2 Mesa 24.0") == (3, 2)
    assert context_version(None, "") == (0, 0)


def test_below_3_3_is_flagged_and_nothing_known_is_not():
    from core.glinfo import below_minimum
    # The 0.5.9 Windows package's software rasteriser (minipc, 21-10).
    assert below_minimum({"context": (3, 0)})
    assert below_minimum({"context": (2, 1)})
    assert not below_minimum({"context": (3, 3)})
    assert not below_minimum({"context": (4, 5)})
    # A silent driver never earns a warning it may not deserve.
    assert not below_minimum({"context": (0, 0)})
    assert not below_minimum({})


def test_the_report_says_the_context_and_when_it_is_too_old(tmp_path):
    info = {"vendor": "VMware, Inc.",
            "renderer": "llvmpipe (LLVM 3.6, 256 bits)",
            "version": "3.0 Mesa 11.2.2", "software": True, "context": (3, 0)}
    text = write_gl_report(info, tmp_path / "gl.txt").read_text(encoding="utf-8")
    assert "context  : 3.0  (below 3.3)" in text
    info["context"] = (4, 5)
    text = write_gl_report(info, tmp_path / "gl.txt").read_text(encoding="utf-8")
    assert "context  : 4.5\n" in text


def test_the_window_warns_once_about_an_old_context(monkeypatch):
    from PySide6.QtWidgets import QApplication
    import views.main_window as mw
    shown = []
    monkeypatch.setattr(mw.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: shown.append(a[2])))
    win = mw.MainWindow()
    try:
        old = {"vendor": "VMware, Inc.", "renderer": "llvmpipe (LLVM 3.6)",
               "version": "3.0 Mesa 11.2.2", "software": True,
               "context": (3, 0)}
        win._on_gl_ready(old)
        win._on_gl_ready(old)           # a recreated context: still once
        for _ in range(3):
            QApplication.processEvents()
        assert len(shown) == 1
        assert "OpenGL 3.0" in shown[0] and "3.3" in shown[0]
        # A good context never sees the dialog.
        win2_shown = len(shown)
        win._gl_warned = False
        win._on_gl_ready({**old, "context": (4, 5), "software": False})
        QApplication.processEvents()
        assert len(shown) == win2_shown
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
