import tempfile
import unittest
from pathlib import Path

from ps2_emulator import BIOS_START, EE_RESET_VECTOR, PS2Emulator


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
        expected_pc = (EE_RESET_VECTOR + instruction_budget) & 0xFFFFFFFF
        expected_cycles = sum(
            emulator.system.ee._CYCLE_TABLE[opcode & 0b11]
            for opcode in bios[:instruction_budget]
        )

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


if __name__ == "__main__":
    unittest.main()
