"""Export this repository's tensor-only PyTorch checkpoint without importing torch.

The restricted reader accepts just OrderedDict and inert dense tensor descriptors.
It never imports or invokes code referenced by a checkpoint. Other formats fail closed.
If torch is installed, --verify compares actual outputs against VanishQNet.eval().
"""

import argparse
from collections import OrderedDict
import io
import json
from pathlib import Path
import pickle
import sys
import zipfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TensorDescriptor:
    def __init__(self, storage, offset, shape, stride, requires_grad, hooks, *rest):
        self.storage, self.offset, self.shape, self.stride = storage, offset, shape, stride


class RestrictedReader(pickle.Unpickler):
    def find_class(self, module, name):
        allowed = {("collections", "OrderedDict"): OrderedDict,
                   ("torch._utils", "_rebuild_tensor_v2"): TensorDescriptor,
                   ("torch", "FloatStorage"): "<f4", ("torch", "LongStorage"): "<i8"}
        if (module, name) not in allowed:
            raise pickle.UnpicklingError("Unsupported checkpoint type: " + module + "." + name)
        return allowed[(module, name)]

    def persistent_load(self, value):
        if not isinstance(value, tuple) or len(value) != 5 or value[0] != "storage":
            raise pickle.UnpicklingError("Unsupported storage descriptor")
        return value


def export(source, destination):
    arrays = {}
    with zipfile.ZipFile(source) as archive:
        entries = [p for p in archive.namelist() if p.endswith("/data.pkl")]
        if len(entries) != 1 or archive.getinfo(entries[0]).file_size > 4_000_000:
            raise ValueError("Unsupported checkpoint metadata")
        base = entries[0].rsplit("/", 1)[0]
        if base + "/byteorder" in archive.namelist() and archive.read(base + "/byteorder") != b"little":
            raise ValueError("Only little-endian checkpoints are supported")
        obj = RestrictedReader(io.BytesIO(archive.read(entries[0]))).load()
        weights = obj["model_state_dict"]
        for key, tensor in weights.items():
            _, dtype, storage_id, _, count = tensor.storage
            if not str(storage_id).isdigit() or not 0 < count < 20_000_000:
                raise ValueError("Invalid tensor storage")
            expected = []
            stride = 1
            for size in reversed(tensor.shape):
                expected.insert(0, stride)
                stride *= size
            if tuple(expected) != tuple(tensor.stride) or tensor.offset < 0:
                raise ValueError("Only contiguous tensor weights are supported")
            data = archive.read(base + "/data/" + str(storage_id))
            if len(data) != count * np.dtype(dtype).itemsize:
                raise ValueError("Storage size mismatch")
            raw = np.frombuffer(data, dtype=dtype)
            arr = raw[tensor.offset:tensor.offset + stride].reshape(tensor.shape).copy()
            arrays[key] = arr
        arrays["meta_json"] = np.array(json.dumps({"episode": obj.get("episode"),
            "best_win_rate": obj.get("best_win_rate"), "config": obj.get("config"),
            "source": Path(source).name}, ensure_ascii=False))
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(destination, **arrays)
    print("Exported", len(weights), "state entries to", destination)


def verify(source, destination):
    from vttt.network import NumpyQNet, TorchQNet
    a, b = NumpyQNet(destination), TorchQNet(source)
    rng = np.random.default_rng(42)
    worst = 0.0
    for _ in range(20):
        obs = rng.integers(0, 4, size=(2, 3, 3)).astype(np.float32)
        left, right = a(obs), b(obs)
        np.testing.assert_allclose(left, right, rtol=1e-4, atol=2e-4)
        worst = max(worst, float(np.max(np.abs(left - right))))
    print("PyTorch/NumPy output comparison passed; max absolute error:", worst)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "results/saved_models/vanish_runs/checkpoints/best.pt")
    parser.add_argument("--output", type=Path, default=ROOT / "results/saved_models/vanish_runs/checkpoints/runtime_model.npz")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    export(args.source, args.output)
    if args.verify:
        verify(args.source, args.output)
