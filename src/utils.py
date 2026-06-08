"""Common utility functions for training, logging, and checkpoints."""

from __future__ import annotations

import logging
import os
import random
from datetime import datetime
from typing import Dict, Optional

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim


def set_seed(seed: int = 42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def setup_logger(log_dir: str) -> logging.Logger:
    ensure_dir(log_dir)
    logger = logging.getLogger("vanish_train")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    fh = logging.FileHandler(os.path.join(log_dir, f"train_{timestamp}.log"), encoding="utf-8")
    fh.setFormatter(formatter)
    sh = logging.StreamHandler()
    sh.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def save_checkpoint(
    save_path: str,
    model: nn.Module,
    target_model: nn.Module,
    optimizer: optim.Optimizer,
    episode: int,
    epsilon: float,
    best_win_rate: float,
    config: Dict,
):
    ensure_dir(os.path.dirname(save_path))
    torch.save(
        {
            "episode": episode,
            "model_state_dict": model.state_dict(),
            "target_model_state_dict": target_model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "epsilon": epsilon,
            "best_win_rate": best_win_rate,
            "config": config,
        },
        save_path,
    )


def load_checkpoint(
    load_path: str,
    model: nn.Module,
    target_model: Optional[nn.Module],
    optimizer: Optional[optim.Optimizer],
    device: torch.device,
):
    ckpt = torch.load(load_path, map_location=device)
    model.load_state_dict(ckpt["model_state_dict"])
    if target_model is not None and "target_model_state_dict" in ckpt:
        target_model.load_state_dict(ckpt["target_model_state_dict"])
    if optimizer is not None and "optimizer_state_dict" in ckpt:
        optimizer.load_state_dict(ckpt["optimizer_state_dict"])
    return ckpt
