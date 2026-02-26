from __future__ import annotations

import sys
from types import SimpleNamespace

from zotero_files2md.converter import _pick_gpu_ocr_backend


def test_pick_gpu_ocr_backend_prefers_onnxruntime_cuda(monkeypatch) -> None:
    fake_ort = SimpleNamespace(
        get_available_providers=lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"]
    )
    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: True)
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    backend = _pick_gpu_ocr_backend()
    assert backend is not None
    name, params = backend
    assert name == "onnxruntime"
    assert params["EngineConfig.onnxruntime.use_cuda"] is True


def test_pick_gpu_ocr_backend_falls_back_to_torch(monkeypatch) -> None:
    fake_ort = SimpleNamespace(
        get_available_providers=lambda: ["CPUExecutionProvider"]
    )
    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: True)
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    backend = _pick_gpu_ocr_backend()
    assert backend is not None
    name, params = backend
    assert name == "torch"
    assert params["EngineConfig.torch.use_cuda"] is True


def test_pick_gpu_ocr_backend_returns_none_without_gpu(monkeypatch) -> None:
    fake_ort = SimpleNamespace(
        get_available_providers=lambda: ["CPUExecutionProvider"]
    )
    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: False)
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    assert _pick_gpu_ocr_backend() is None
