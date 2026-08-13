import tempfile
import unittest
from pathlib import Path

from ps2_emulator import PS2Emulator


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
        bios = bytes([0x01, 0x02, 0x03, 0x00])
        with tempfile.TemporaryDirectory() as tmp:
            bios_path = Path(tmp) / "bios.bin"
            bios_path.write_bytes(bios)
            emulator.load_bios(bios_path)

        emulator.power_on()
        instruction_budget = 3
        executed = emulator.run_frame(instruction_budget)
        expected_pc = instruction_budget % len(bios)
        expected_cycles = sum(
            emulator._CYCLE_TABLE[opcode & 0b11] for opcode in bios[:instruction_budget]
        )

        self.assertEqual(executed, instruction_budget)
        self.assertEqual(emulator.frame_count, 1)
        self.assertEqual(emulator.pc, expected_pc)
        self.assertEqual(emulator.cycles, expected_cycles)


if __name__ == "__main__":
    unittest.main()
