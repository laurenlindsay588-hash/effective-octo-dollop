"""Milestone-1 PlayStation 2 hardware architecture skeleton.

This module introduces subsystem boundaries and an EE+memory-map harness:
- EE core skeleton (reset/step/cycle counting)
- MMU address translation helpers
- Memory-map region routing with read-only BIOS region support
- Event scheduler scaffold for future device synchronization
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol


EE_RAM_START = 0x00000000
EE_RAM_SIZE = 32 * 1024 * 1024
IOP_RAM_START = 0x1C000000
IOP_RAM_SIZE = 2 * 1024 * 1024
BIOS_START = 0x1FC00000
BIOS_SIZE = 4 * 1024 * 1024
SCRATCHPAD_START = 0x70000000
SCRATCHPAD_SIZE = 16 * 1024
EE_RESET_VECTOR = 0xBFC00000
TIMER0_START = 0x10000000
TIMER0_SIZE = 0x10
INTC_START = 0x10001000
INTC_SIZE = 0x10


@dataclass(frozen=True)
class BootROM:
    image: bytes
    entry_point: int = EE_RESET_VECTOR


class BootstrapLoader:
    @staticmethod
    def from_bios_bytes(bios: bytes) -> BootROM:
        if not bios:
            raise ValueError("BIOS file is empty")
        if len(bios) > BIOS_SIZE:
            raise ValueError("BIOS is larger than mapped BIOS region")
        return BootROM(image=bios)

    @staticmethod
    def from_bios_path(path: str | Path) -> BootROM:
        return BootstrapLoader.from_bios_bytes(Path(path).read_bytes())


@dataclass(frozen=True)
class ELFImage:
    entry_point: int
    program_header_offset: int
    program_header_count: int


class ELFLoader:
    @staticmethod
    def parse_elf32(raw: bytes) -> ELFImage:
        if len(raw) < 52:
            raise ValueError("ELF file too small for ELF32 header")
        if raw[:4] != b"\x7fELF":
            raise ValueError("Invalid ELF magic")
        if raw[4] != 1:
            raise ValueError("Only ELF32 is supported in this milestone")
        if raw[5] != 1:
            raise ValueError("Only little-endian ELF is supported in this milestone")
        entry_point = int.from_bytes(raw[24:28], "little")
        phoff = int.from_bytes(raw[28:32], "little")
        phnum = int.from_bytes(raw[44:46], "little")
        return ELFImage(
            entry_point=entry_point,
            program_header_offset=phoff,
            program_header_count=phnum,
        )

    @staticmethod
    def parse_elf32_path(path: str | Path) -> ELFImage:
        return ELFLoader.parse_elf32(Path(path).read_bytes())


class AddressableRegion(Protocol):
    name: str
    start: int
    size: int

    def contains(self, address: int) -> bool: ...

    def read8(self, address: int) -> int: ...

    def write8(self, address: int, value: int) -> None: ...


@dataclass
class MemoryRegion:
    name: str
    start: int
    size: int
    read_only: bool = False
    data: bytearray | None = None
    _sparse_data: dict[int, int] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.data is None:
            if self.read_only:
                self.data = bytearray(self.size)
            return
        if len(self.data) == 0:
            self.data = bytearray(self.size)
        if len(self.data) != self.size:
            raise ValueError(f"{self.name} region size mismatch")

    def contains(self, address: int) -> bool:
        return self.start <= address < (self.start + self.size)

    def read8(self, address: int) -> int:
        offset = address - self.start
        if self.data is not None:
            return self.data[offset]
        return self._sparse_data.get(offset, 0)

    def write8(self, address: int, value: int) -> None:
        if self.read_only:
            raise PermissionError(f"{self.name} is read-only")
        value8 = value & 0xFF
        offset = address - self.start
        if self.data is not None:
            self.data[offset] = value8
            return
        if value8 == 0:
            self._sparse_data.pop(offset, None)
            return
        self._sparse_data[offset] = value8

    def _load_bytes(
        self, payload: bytes, offset: int = 0, *, allow_read_only: bool = False
    ) -> None:
        if self.read_only and not allow_read_only:
            raise PermissionError(f"{self.name} is read-only")
        end = offset + len(payload)
        if offset < 0 or end > self.size:
            raise ValueError(f"{self.name} load out of bounds")
        if self.data is not None:
            self.data[offset:end] = payload
            return
        for index, byte in enumerate(payload):
            self.write8(self.start + offset + index, byte)


@dataclass
class TimerDevice:
    counter: int = 0
    compare: int = 0
    interrupt_latched: bool = False

    def tick(self, cycles: int) -> bool:
        self.counter = (self.counter + cycles) & 0xFFFFFFFF
        if self.compare != 0 and self.counter >= self.compare and not self.interrupt_latched:
            self.interrupt_latched = True
            return True
        return False

    def read8(self, offset: int) -> int:
        if 0 <= offset < 4:
            return (self.counter >> (offset * 8)) & 0xFF
        if 4 <= offset < 8:
            return (self.compare >> ((offset - 4) * 8)) & 0xFF
        return 0

    def write8(self, offset: int, value: int) -> None:
        value8 = value & 0xFF
        if 0 <= offset < 4:
            shift = offset * 8
            self.counter = (self.counter & ~(0xFF << shift)) | (value8 << shift)
            self.interrupt_latched = False
            return
        if 4 <= offset < 8:
            shift = (offset - 4) * 8
            self.compare = (self.compare & ~(0xFF << shift)) | (value8 << shift)
            self.interrupt_latched = False


@dataclass
class InterruptController:
    pending: int = 0
    mask: int = 0

    def request(self, line: int) -> None:
        self.pending |= 1 << line

    def irq_asserted(self) -> bool:
        return (self.pending & self.mask) != 0

    def read8(self, offset: int) -> int:
        if 0 <= offset < 4:
            return (self.pending >> (offset * 8)) & 0xFF
        if 4 <= offset < 8:
            return (self.mask >> ((offset - 4) * 8)) & 0xFF
        return 0

    def write8(self, offset: int, value: int) -> None:
        value8 = value & 0xFF
        if 0 <= offset < 4:
            shift = offset * 8
            self.pending &= ~(value8 << shift)
            return
        if 4 <= offset < 8:
            shift = (offset - 4) * 8
            self.mask = (self.mask & ~(0xFF << shift)) | (value8 << shift)


@dataclass
class DeviceRegion:
    name: str
    start: int
    size: int
    read_handler: Callable[[int], int]
    write_handler: Callable[[int, int], None]

    def contains(self, address: int) -> bool:
        return self.start <= address < (self.start + self.size)

    def read8(self, address: int) -> int:
        return self.read_handler(address - self.start)

    def write8(self, address: int, value: int) -> None:
        self.write_handler(address - self.start, value & 0xFF)


@dataclass(frozen=True)
class InstructionResult:
    pc_before: int
    pc_after: int
    opcode: int
    mnemonic: str
    cycle_cost: int


@dataclass
class MMU:
    """EE address translation helper."""

    def translate_ee_virtual(self, address: int) -> int:
        # Milestone-1: partial map (KUSEG identity, KSEG0/KSEG1 direct aliases).
        # KSEG2/SSEG is intentionally not modeled yet and raises below.
        if 0x00000000 <= address <= 0x7FFFFFFF:
            return address
        # KSEG0/KSEG1 virtual aliases for physical 0x0000_0000..0x1FFF_FFFF
        if 0x80000000 <= address <= 0x9FFFFFFF:
            return address - 0x80000000
        if 0xA0000000 <= address <= 0xBFFFFFFF:
            return address - 0xA0000000
        raise ValueError(f"Unsupported EE virtual address segment: 0x{address:08X}")


@dataclass
class MemoryMap:
    mmu: MMU = field(default_factory=MMU)
    regions: list[AddressableRegion] = field(default_factory=list)

    def map_region(self, region: AddressableRegion) -> None:
        region_end = region.start + region.size
        for existing in self.regions:
            existing_end = existing.start + existing.size
            if region.start < existing_end and existing.start < region_end:
                raise ValueError(
                    f"Region {region.name} overlaps existing region {existing.name}"
                )
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
    listeners: list[Callable[[int, int], None]] = field(default_factory=list)

    def register_listener(self, listener: Callable[[int, int], None]) -> None:
        self.listeners.append(listener)

    def advance(self, cycles: int) -> None:
        if cycles < 0:
            raise ValueError("cycles must be non-negative")
        self.current_cycle += cycles
        for listener in self.listeners:
            listener(cycles, self.current_cycle)


@dataclass
class EECore:
    powered_on: bool = False
    pc: int = EE_RESET_VECTOR
    cycles: int = 0
    gpr: list[int] = field(default_factory=lambda: [0] * 32)

    def reset(self) -> None:
        self.powered_on = True
        self.pc = EE_RESET_VECTOR
        self.cycles = 0
        self.gpr = [0] * 32

    def step(self, memory_map: MemoryMap) -> InstructionResult:
        if not self.powered_on:
            raise RuntimeError("EE core is not powered on")

        pc_before = self.pc
        opcode = memory_map.read8(self.pc, virtual=True)
        cycle_cost = 1
        mnemonic = "NOP"
        next_pc = (self.pc + 1) & 0xFFFFFFFF

        if opcode == 0x00:
            mnemonic = "NOP"
            cycle_cost = 1
        elif 0x40 <= opcode <= 0x7F:
            mnemonic = "JUMP"
            offset = opcode & 0x3F
            if offset & 0x20:
                offset -= 0x40
            next_pc = (self.pc + 1 + offset) & 0xFFFFFFFF
            cycle_cost = 2
        elif 0x80 <= opcode <= 0xBF:
            mnemonic = "LOAD"
            address = EE_RAM_START + (opcode & 0x3F)
            self.gpr[1] = memory_map.read8(address, virtual=False)
            cycle_cost = 3
        elif 0xC0 <= opcode <= 0xFF:
            mnemonic = "STORE"
            address = EE_RAM_START + (opcode & 0x3F)
            memory_map.write8(address, self.gpr[1], virtual=False)
            cycle_cost = 3
        else:
            mnemonic = "NOP"
            cycle_cost = 1

        self.pc = next_pc
        self.cycles += cycle_cost
        return InstructionResult(
            pc_before=pc_before,
            pc_after=self.pc,
            opcode=opcode,
            mnemonic=mnemonic,
            cycle_cost=cycle_cost,
        )


@dataclass
class PS2System:
    memory_map: MemoryMap = field(default_factory=MemoryMap)
    ee: EECore = field(default_factory=EECore)
    scheduler: EventScheduler = field(default_factory=EventScheduler)
    timer0: TimerDevice = field(default_factory=TimerDevice)
    intc: InterruptController = field(default_factory=InterruptController)
    bios_loaded: bool = False
    boot_rom: BootROM | None = None

    def __post_init__(self) -> None:
        self.memory_map.map_region(MemoryRegion("EE_RAM", EE_RAM_START, EE_RAM_SIZE))
        self.memory_map.map_region(MemoryRegion("IOP_RAM", IOP_RAM_START, IOP_RAM_SIZE))
        self.memory_map.map_region(
            MemoryRegion("BIOS", BIOS_START, BIOS_SIZE, read_only=True)
        )
        self.memory_map.map_region(
            MemoryRegion("SCRATCHPAD", SCRATCHPAD_START, SCRATCHPAD_SIZE)
        )
        self.memory_map.map_region(
            DeviceRegion(
                "TIMER0",
                TIMER0_START,
                TIMER0_SIZE,
                self.timer0.read8,
                self.timer0.write8,
            )
        )
        self.memory_map.map_region(
            DeviceRegion(
                "INTC",
                INTC_START,
                INTC_SIZE,
                self.intc.read8,
                self.intc.write8,
            )
        )
        self.scheduler.register_listener(self._on_scheduler_advance)

    def _on_scheduler_advance(self, cycles: int, _current_cycle: int) -> None:
        if self.timer0.tick(cycles):
            self.intc.request(0)

    def install_boot_rom(self, boot_rom: BootROM) -> None:
        if self.bios_loaded:
            raise RuntimeError("BIOS already loaded; create a new system to reload")
        bios_region, _ = self.memory_map.resolve(BIOS_START, virtual=False)
        bios_region._load_bytes(boot_rom.image, allow_read_only=True)
        self.boot_rom = boot_rom
        self.bios_loaded = True

    def load_bios_bytes(self, bios: bytes) -> None:
        self.install_boot_rom(BootstrapLoader.from_bios_bytes(bios))

    def power_on(self) -> None:
        if not self.bios_loaded:
            raise RuntimeError("Load a BIOS before powering on")
        self.ee.reset()
        self.scheduler.current_cycle = 0
        self.timer0.counter = 0
        self.timer0.interrupt_latched = False
        self.intc.pending = 0

    def step(self) -> InstructionResult:
        result = self.ee.step(self.memory_map)
        self.scheduler.advance(result.cycle_cost)
        return result

    def run_instructions(
        self,
        instruction_budget: int,
        *,
        max_cycles: int | None = None,
        instruction_hook: Callable[[InstructionResult], None] | None = None,
    ) -> int:
        if instruction_budget <= 0:
            raise ValueError("instruction_budget must be positive")
        if not self.ee.powered_on:
            raise RuntimeError("EE core is not powered on")
        if max_cycles is not None and max_cycles < 0:
            raise ValueError("max_cycles must be non-negative")

        executed = 0
        for _ in range(instruction_budget):
            if max_cycles is not None and self.ee.cycles >= max_cycles:
                break
            result = self.step()
            if instruction_hook is not None:
                instruction_hook(result)
            executed += 1
        return executed


@dataclass
class PS2Emulator:
    """Compatibility facade over PS2System milestone architecture."""

    system: PS2System = field(default_factory=PS2System)
    bios: bytes | None = None
    elf_image: ELFImage | None = None
    frame_count: int = 0

    @property
    def powered_on(self) -> bool:
        return self.system.ee.powered_on

    @property
    def pc(self) -> int:
        return self.system.ee.pc

    @property
    def cycles(self) -> int:
        return self.system.ee.cycles

    def load_bios(self, bios_path: str | Path) -> None:
        """Load BIOS bytes from disk."""
        boot_rom = BootstrapLoader.from_bios_path(bios_path)
        self.system.install_boot_rom(boot_rom)
        self.bios = boot_rom.image

    def load_elf(self, elf_path: str | Path) -> ELFImage:
        """Parse ELF32 metadata as milestone scaffold for future program loading."""
        self.elf_image = ELFLoader.parse_elf32_path(elf_path)
        return self.elf_image

    def power_on(self) -> None:
        """Reset and power on the emulator."""
        self.system.power_on()
        self.frame_count = 0

    def step(self) -> int:
        """Execute one pseudo-instruction and return opcode byte."""
        return self.system.step().opcode

    def run_frame(
        self,
        instruction_budget: int = 1000,
        *,
        max_cycles: int | None = None,
        instruction_hook: Callable[[InstructionResult], None] | None = None,
    ) -> int:
        """Execute a frame worth of pseudo-instructions."""
        executed = self.system.run_instructions(
            instruction_budget,
            max_cycles=max_cycles,
            instruction_hook=instruction_hook,
        )
        if executed > 0:
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
            "timer0_counter": self.system.timer0.counter,
            "timer0_compare": self.system.timer0.compare,
            "intc_pending": self.system.intc.pending,
            "intc_mask": self.system.intc.mask,
            "irq_asserted": self.system.intc.irq_asserted(),
            "elf_entry_point": self.elf_image.entry_point if self.elf_image else 0,
        }


def run_cli(argv: list[str] | None = None) -> int:
    args_list = sys.argv[1:] if argv is None else argv
    if not args_list:
        print(
            "PS2 milestone architecture ready. "
            "Run with --bios /absolute/path/to/bios.bin to execute frames."
        )
        return 0

    parser = argparse.ArgumentParser(description="Run PS2 emulator scaffold")
    parser.add_argument("--bios", required=True, help="Absolute path to BIOS image")
    parser.add_argument(
        "--instructions",
        type=int,
        default=1000,
        help="Instructions to run per frame (default: 1000)",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=1,
        help="Number of frames to execute (default: 1)",
    )
    parser.add_argument(
        "--status-json",
        action="store_true",
        help="Print final emulator status as JSON",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Stop execution once total cycles reach this value",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Print one trace line per executed instruction",
    )
    parser.add_argument(
        "--status-every",
        type=int,
        default=0,
        help="Print JSON status every N executed instructions",
    )
    parsed = parser.parse_args(args_list)
    if parsed.instructions <= 0:
        parser.error("--instructions must be positive")
    if parsed.frames <= 0:
        parser.error("--frames must be positive")
    if parsed.max_cycles is not None and parsed.max_cycles < 0:
        parser.error("--max-cycles must be non-negative")
    if parsed.status_every < 0:
        parser.error("--status-every must be non-negative")

    emulator = PS2Emulator()
    emulator.load_bios(parsed.bios)
    emulator.power_on()
    total_instructions = 0

    def on_instruction(result: InstructionResult) -> None:
        nonlocal total_instructions
        total_instructions += 1
        if parsed.trace:
            print(
                f"pc=0x{result.pc_before:08X} opcode=0x{result.opcode:02X} "
                f"{result.mnemonic} -> pc=0x{result.pc_after:08X} cycles={result.cycle_cost}"
            )
        if parsed.status_every and total_instructions % parsed.status_every == 0:
            print(json.dumps(emulator.status(), sort_keys=True))

    for _ in range(parsed.frames):
        executed = emulator.run_frame(
            parsed.instructions,
            max_cycles=parsed.max_cycles,
            instruction_hook=on_instruction,
        )
        if (
            executed == 0
            and parsed.max_cycles is not None
            and emulator.cycles >= parsed.max_cycles
        ):
            break

    status = emulator.status()
    if parsed.status_json:
        print(json.dumps(status, sort_keys=True))
    else:
        print(status)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
