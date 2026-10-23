"""CPU inference for the supplied residual CNN, using NumPy and exported weights."""

import numpy as np


def conv3(x, weight, bias):
    padded = np.pad(x, ((0, 0), (1, 1), (1, 1)))
    windows = np.lib.stride_tricks.sliding_window_view(padded, (3, 3), axis=(1, 2))
    patches = windows.transpose(1, 2, 0, 3, 4).reshape(9, -1)
    y = patches @ weight.reshape(weight.shape[0], -1).T
    return y.T.reshape(-1, 3, 3) + bias[:, None, None]


class NumpyQNet:
    def __init__(self, path):
        with np.load(path, allow_pickle=False) as archive:
            self.weights = {k: archive[k] for k in archive.files if not k.startswith("meta_")}
        w = self.weights
        if w["stem.0.weight"].shape != (128, 2, 3, 3) or w["head.4.weight"].shape != (9, 256):
            raise ValueError("runtime_model.npz is not the supplied 128-channel residual CNN")
        self.stem = self._fold("stem.0", "stem.1")
        self.blocks = [(self._fold(f"blocks.{i}.conv1", f"blocks.{i}.bn1"),
                        self._fold(f"blocks.{i}.conv2", f"blocks.{i}.bn2")) for i in range(5)]
        for array in w.values():
            if not np.all(np.isfinite(array)):
                raise ValueError("Nonfinite model weight")

    def _fold(self, conv, bn):
        w = self.weights
        scale = w[bn + ".weight"] / np.sqrt(w[bn + ".running_var"] + np.float32(1e-5))
        return (w[conv + ".weight"] * scale[:, None, None, None],
                w[bn + ".bias"] - w[bn + ".running_mean"] * scale)

    def __call__(self, obs):
        x = np.asarray(obs, dtype=np.float32)
        if x.shape != (2, 3, 3):
            raise ValueError("Observation must be (2,3,3)")
        x = np.maximum(conv3(x, *self.stem), 0)
        for first, second in self.blocks:
            residual = x
            x = np.maximum(conv3(x, *first), 0)
            x = np.maximum(conv3(x, *second) + residual, 0)
        w = self.weights
        x = np.maximum(w["head.1.weight"] @ x.reshape(-1) + w["head.1.bias"], 0)
        # Dropout is disabled in evaluation, just as in model.eval().
        return w["head.4.weight"] @ x + w["head.4.bias"]


class TorchQNet:
    def __init__(self, path):
        import torch
        from src.models.vanish_qnet import VanishQNet
        torch.set_num_threads(1)
        self.torch = torch
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        self.model = VanishQNet()
        self.model.load_state_dict(checkpoint["model_state_dict"])
        self.model.eval()

    def __call__(self, obs):
        with self.torch.no_grad():
            return self.model(self.torch.from_numpy(obs).unsqueeze(0)).squeeze(0).numpy()
