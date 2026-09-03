import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from ps2_emulator import (
    BIOS_START,
    EE_RAM_START,
    EE_RESET_VECTOR,
    MemoryMap,
    MemoryRegion,
    PS2Emulator,
    PS2System,
    run_cli,
)


class PS2EmulatorTests(unittest.TestCase):
    def test_power_on_requires_bios(self):
        emulator = PS2Emulator()
        with self.assertRaises(RuntimeError):
            emulator.power_on()

    def test_load_empty_bios_rejected(self):
        emulator = PS2Emulator()
        with tempfile.TemporaryDirectory() as tmp:
            bios_path = Path(tmp) / "empty.bin"
            bios_path.write_bytes(b"")
            with self.assertRaises(ValueError):
                emulator.load_bios(bios_path)

    def test_run_frame_updates_state(self):
        emulator = PS2Emulator()
        bios = bytes([0x01, 0x02, 0x03, 0x00]) + bytes(64)
        with tempfile.TemporaryDirectory() as tmp:
            bios_path = Path(tmp) / "bios.bin"
            bios_path.write_bytes(bios)
            emulator.load_bios(bios_path)

        emulator.power_on()
        instruction_budget = 3
        executed = emulator.run_frame(instruction_budget)
        # Milestone scaffold currently models one byte fetched per step.
        expected_pc = (EE_RESET_VECTOR + instruction_budget) & 0xFFFFFFFF
        # Opcodes 0x01, 0x02, 0x03 map to cycle costs 2, 3, 4 via opcode&0b11.
        expected_cycles = 2 + 3 + 4

        self.assertEqual(executed, instruction_budget)
        self.assertEqual(emulator.frame_count, 1)
        self.assertEqual(emulator.pc, expected_pc)
        self.assertEqual(emulator.cycles, expected_cycles)
        self.assertEqual(emulator.status()["scheduler_cycle"], expected_cycles)

    def test_bios_is_mapped_at_physical_bios_region(self):
        emulator = PS2Emulator()
        bios = bytes([0xAA, 0xBB, 0xCC]) + bytes(16)
        with tempfile.TemporaryDirectory() as tmp:
            bios_path = Path(tmp) / "bios.bin"
            bios_path.write_bytes(bios)
            emulator.load_bios(bios_path)

        self.assertEqual(emulator.system.memory_map.read8(BIOS_START, virtual=False), 0xAA)
        self.assertEqual(
            emulator.system.memory_map.read8(BIOS_START + 1, virtual=False), 0xBB
        )

    def test_bios_cannot_be_reloaded_on_same_system(self):
        emulator = PS2Emulator()
        with tempfile.TemporaryDirectory() as tmp:
            bios_a = Path(tmp) / "bios_a.bin"
            bios_b = Path(tmp) / "bios_b.bin"
            bios_a.write_bytes(bytes([0x01]) + bytes(8))
            bios_b.write_bytes(bytes([0x02]) + bytes(8))
            emulator.load_bios(bios_a)
            with self.assertRaises(RuntimeError):
                emulator.load_bios(bios_b)

    def test_memory_map_rejects_overlapping_regions(self):
        memory_map = MemoryMap()
        memory_map.map_region(MemoryRegion("A", 0x1000, 0x100))
        with self.assertRaises(ValueError):
            memory_map.map_region(MemoryRegion("B", 0x1080, 0x100))

    def test_read_only_region_raw_load_is_internal_only(self):
        bios_region = MemoryRegion("BIOS", BIOS_START, 0x100, read_only=True)
        with self.assertRaises(PermissionError):
            bios_region._load_bytes(b"\x01")
        bios_region._load_bytes(b"\x01", allow_read_only=True)
        self.assertEqual(bios_region.read8(BIOS_START), 0x01)

    def test_ram_regions_use_sparse_backing(self):
        system = PS2System()
        ee_ram, _ = system.memory_map.resolve(EE_RAM_START, virtual=False)
        self.assertIsNone(ee_ram.data)
        self.assertEqual(system.memory_map.read8(EE_RAM_START, virtual=False), 0)
        system.memory_map.write8(EE_RAM_START, 0xAB, virtual=False)
        self.assertEqual(system.memory_map.read8(EE_RAM_START, virtual=False), 0xAB)

    def test_cli_without_args_prints_guidance(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = run_cli([])
        self.assertEqual(code, 0)
        self.assertIn("Run with --bios", stdout.getvalue())

    def test_cli_with_bios_runs_and_prints_json_status(self):
        bios = bytes([0x01, 0x02, 0x03, 0x00]) + bytes(64)
        with tempfile.TemporaryDirectory() as tmp:
            bios_path = Path(tmp) / "bios.bin"
            bios_path.write_bytes(bios)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = run_cli(
                    [
                        "--bios",
                        str(bios_path),
                        "--instructions",
                        "3",
                        "--frames",
                        "2",
                        "--status-json",
                    ]
                )
        self.assertEqual(code, 0)
        status = json.loads(stdout.getvalue())
        self.assertTrue(status["powered_on"])
        self.assertEqual(status["frame_count"], 2)
        self.assertEqual(status["pc"], (EE_RESET_VECTOR + 6) & 0xFFFFFFFF)
        self.assertEqual(status["bios_size"], len(bios))


if __name__ == "__main__":
    unittest.main()
