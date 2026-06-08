"""Neural network model for Vanishing Tic-Tac-Toe Q-value prediction."""

from __future__ import annotations

import torch.nn as nn
import torch.nn.functional as F


class ResidualBlock(nn.Module):
    def __init__(self, channels: int):
        super().__init__()
        self.conv1 = nn.Conv2d(channels, channels, kernel_size=3, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(channels)
        self.conv2 = nn.Conv2d(channels, channels, kernel_size=3, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(channels)

    def forward(self, x):
        residual = x
        x = F.relu(self.bn1(self.conv1(x)), inplace=True)
        x = self.bn2(self.conv2(x))
        x = F.relu(x + residual, inplace=True)
        return x


class VanishQNet(nn.Module):
    """
    Input:  (B, 2, 3, 3)
    Output: (B, 9) Q-values
    """

    def __init__(
        self,
        in_channels: int = 2,
        channels: int = 128,
        num_blocks: int = 5,
        board_size: int = 3,
    ):
        super().__init__()
        self.board_size = board_size
        self.stem = nn.Sequential(
            nn.Conv2d(in_channels, channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(channels),
            nn.ReLU(inplace=True),
        )
        self.blocks = nn.Sequential(*[ResidualBlock(channels) for _ in range(num_blocks)])
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(channels * board_size * board_size, 256),
            nn.ReLU(inplace=True),
            nn.Dropout(p=0.1),
            nn.Linear(256, board_size * board_size),
        )

    def forward(self, x):
        x = self.stem(x)
        x = self.blocks(x)
        return self.head(x)
