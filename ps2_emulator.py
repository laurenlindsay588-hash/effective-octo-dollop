"""Milestone-1 PlayStation 2 hardware architecture skeleton.

This module introduces subsystem boundaries and an EE+memory-map harness:
- EE core skeleton (reset/step/cycle counting)
- MMU address translation helpers
- Memory-map region routing with read-only BIOS region support
- Event scheduler scaffold for future device synchronization
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar


EE_RAM_START = 0x00000000
EE_RAM_SIZE = 32 * 1024 * 1024
IOP_RAM_START = 0x1C000000
IOP_RAM_SIZE = 2 * 1024 * 1024
BIOS_START = 0x1FC00000
BIOS_SIZE = 4 * 1024 * 1024
SCRATCHPAD_START = 0x70000000
SCRATCHPAD_SIZE = 16 * 1024
EE_RESET_VECTOR = 0xBFC00000


@dataclass
class MemoryRegion:
    name: str
    start: int
    size: int
    read_only: bool = False
    data: bytearray = field(default_factory=bytearray)

    def __post_init__(self) -> None:
        if not self.data:
            self.data = bytearray(self.size)
        if len(self.data) != self.size:
            raise ValueError(f"{self.name} region size mismatch")

    def contains(self, address: int) -> bool:
        return self.start <= address < (self.start + self.size)

    def read8(self, address: int) -> int:
        return self.data[address - self.start]

    def write8(self, address: int, value: int) -> None:
        if self.read_only:
            raise PermissionError(f"{self.name} is read-only")
        self.data[address - self.start] = value & 0xFF


@dataclass
class MMU:
    """EE address translation helper."""

    def translate_ee_virtual(self, address: int) -> int:
        # KSEG0/KSEG1 virtual aliases for physical 0x0000_0000..0x1FFF_FFFF
        if 0x80000000 <= address <= 0x9FFFFFFF:
            return address - 0x80000000
        if 0xA0000000 <= address <= 0xBFFFFFFF:
            return address - 0xA0000000
        return address


@dataclass
class MemoryMap:
    mmu: MMU = field(default_factory=MMU)
    regions: list[MemoryRegion] = field(default_factory=list)

    def map_region(self, region: MemoryRegion) -> None:
        self.regions.append(region)

    def resolve(self, address: int, virtual: bool = True) -> tuple[MemoryRegion, int]:
        physical = self.mmu.translate_ee_virtual(address) if virtual else address
        for region in self.regions:
            if region.contains(physical):
                return region, physical
        raise ValueError(f"Unmapped address: 0x{address:08X} -> 0x{physical:08X}")

    def read8(self, address: int, virtual: bool = True) -> int:
        region, physical = self.resolve(address, virtual=virtual)
        return region.read8(physical)

    def write8(self, address: int, value: int, virtual: bool = True) -> None:
        region, physical = self.resolve(address, virtual=virtual)
        region.write8(physical, value)


@dataclass
class EventScheduler:
    """Cycle-domain skeleton for future device sync points."""

    current_cycle: int = 0

    def advance(self, cycles: int) -> None:
        if cycles < 0:
            raise ValueError("cycles must be non-negative")
        self.current_cycle += cycles


@dataclass
class EECore:
    _CYCLE_TABLE: ClassVar[tuple[int, int, int, int]] = (1, 2, 3, 4)

    powered_on: bool = False
    pc: int = EE_RESET_VECTOR
    cycles: int = 0
    gpr: list[int] = field(default_factory=lambda: [0] * 32)

    def reset(self) -> None:
        self.powered_on = True
        self.pc = EE_RESET_VECTOR
        self.cycles = 0
        self.gpr = [0] * 32

    def step(self, memory_map: MemoryMap) -> int:
        if not self.powered_on:
            raise RuntimeError("EE core is not powered on")

        opcode = memory_map.read8(self.pc, virtual=True)
        self.pc = (self.pc + 1) & 0xFFFFFFFF
        cycle_cost = self._CYCLE_TABLE[opcode & 0b11]
        self.cycles += cycle_cost
        return opcode


@dataclass
class PS2System:
    memory_map: MemoryMap = field(default_factory=MemoryMap)
    ee: EECore = field(default_factory=EECore)
    scheduler: EventScheduler = field(default_factory=EventScheduler)
    bios_loaded: bool = False

    def __post_init__(self) -> None:
        self.memory_map.map_region(MemoryRegion("EE_RAM", EE_RAM_START, EE_RAM_SIZE))
        self.memory_map.map_region(MemoryRegion("IOP_RAM", IOP_RAM_START, IOP_RAM_SIZE))
        self.memory_map.map_region(
            MemoryRegion("BIOS", BIOS_START, BIOS_SIZE, read_only=True)
        )
        self.memory_map.map_region(
            MemoryRegion("SCRATCHPAD", SCRATCHPAD_START, SCRATCHPAD_SIZE)
        )

    def load_bios_bytes(self, bios: bytes) -> None:
        if not bios:
            raise ValueError("BIOS file is empty")
        if len(bios) > BIOS_SIZE:
            raise ValueError("BIOS is larger than mapped BIOS region")

        bios_region, _ = self.memory_map.resolve(BIOS_START, virtual=False)
        bios_region.data[: len(bios)] = bios
        self.bios_loaded = True

    def power_on(self) -> None:
        if not self.bios_loaded:
            raise RuntimeError("Load a BIOS before powering on")
        self.ee.reset()
        self.scheduler.current_cycle = 0

    def step(self) -> int:
        opcode = self.ee.step(self.memory_map)
        self.scheduler.advance(self.ee._CYCLE_TABLE[opcode & 0b11])
        return opcode

    def run_instructions(self, instruction_budget: int) -> int:
        if instruction_budget <= 0:
            raise ValueError("instruction_budget must be positive")
        if not self.ee.powered_on:
            raise RuntimeError("EE core is not powered on")

        for _ in range(instruction_budget):
            self.step()
        return instruction_budget


@dataclass
class PS2Emulator:
    """Compatibility facade over PS2System milestone architecture."""

    system: PS2System = field(default_factory=PS2System)
    bios: bytes | None = None
    powered_on: bool = False
    pc: int = EE_RESET_VECTOR
    cycles: int = 0
    frame_count: int = 0

    def load_bios(self, bios_path: str | Path) -> None:
        """Load BIOS bytes from disk."""
        path = Path(bios_path)
        data = path.read_bytes()
        self.system.load_bios_bytes(data)
        self.bios = data

    def power_on(self) -> None:
        """Reset and power on the emulator."""
        self.system.power_on()
        self.powered_on = self.system.ee.powered_on
        self.pc = self.system.ee.pc
        self.cycles = self.system.ee.cycles
        self.frame_count = 0

    def step(self) -> int:
        """Execute one pseudo-instruction and return opcode byte."""
        opcode = self.system.step()
        self.powered_on = self.system.ee.powered_on
        self.pc = self.system.ee.pc
        self.cycles = self.system.ee.cycles
        return opcode

    def run_frame(self, instruction_budget: int = 1000) -> int:
        """Execute a frame worth of pseudo-instructions."""
        executed = self.system.run_instructions(instruction_budget)
        self.powered_on = self.system.ee.powered_on
        self.pc = self.system.ee.pc
        self.cycles = self.system.ee.cycles
        self.frame_count += 1
        return executed

    def status(self) -> dict[str, int | bool]:
        """Return current emulator status values."""
        return {
            "powered_on": self.powered_on,
            "pc": self.pc,
            "cycles": self.cycles,
            "scheduler_cycle": self.system.scheduler.current_cycle,
            "frame_count": self.frame_count,
            "bios_size": len(self.bios) if self.bios is not None else 0,
        }


if __name__ == "__main__":
    emulator = PS2Emulator()
    print(
        "PS2 milestone architecture ready. "
        "Load a BIOS with PS2Emulator.load_bios(...) and call power_on()."
    )
