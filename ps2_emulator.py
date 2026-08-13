"""Minimal PlayStation 2 emulator scaffold.

This module provides a tiny, testable emulator core with clear extension
points. It is not a full hardware-accurate implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PS2Emulator:
    """A minimal PS2 emulator core scaffold."""

    bios: bytes | None = None
    powered_on: bool = False
    pc: int = 0
    cycles: int = 0
    frame_count: int = 0
    _cycle_table: tuple[int, int, int, int] = field(default=(1, 2, 3, 4), init=False)

    def load_bios(self, bios_path: str | Path) -> None:
        """Load BIOS bytes from disk."""
        path = Path(bios_path)
        data = path.read_bytes()
        if not data:
            raise ValueError("BIOS file is empty")
        self.bios = data

    def power_on(self) -> None:
        """Reset and power on the emulator."""
        if self.bios is None:
            raise RuntimeError("Load a BIOS before powering on")
        self.powered_on = True
        self.pc = 0
        self.cycles = 0
        self.frame_count = 0

    def step(self) -> int:
        """Execute one pseudo-instruction and return opcode byte."""
        if not self.powered_on:
            raise RuntimeError("Emulator is not powered on")
        assert self.bios is not None

        opcode = self.bios[self.pc]
        self.pc = (self.pc + 1) % len(self.bios)
        self.cycles += self._cycle_table[opcode & 0b11]
        return opcode

    def run_frame(self, instruction_budget: int = 1000) -> int:
        """Execute a frame worth of pseudo-instructions."""
        if instruction_budget <= 0:
            raise ValueError("instruction_budget must be positive")

        executed = 0
        for _ in range(instruction_budget):
            self.step()
            executed += 1
        self.frame_count += 1
        return executed

    def status(self) -> dict[str, int | bool]:
        """Return current emulator status values."""
        return {
            "powered_on": self.powered_on,
            "pc": self.pc,
            "cycles": self.cycles,
            "frame_count": self.frame_count,
            "bios_size": len(self.bios) if self.bios is not None else 0,
        }


if __name__ == "__main__":
    emulator = PS2Emulator()
    print(
        "PS2 emulator scaffold ready. "
        "Load a BIOS with PS2Emulator.load_bios(...) and call power_on()."
    )
