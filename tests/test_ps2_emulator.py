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
        with tempfile.TemporaryDirectory() as tmp:
            bios_path = Path(tmp) / "bios.bin"
            bios_path.write_bytes(bytes([0x01, 0x02, 0x03, 0x00]))
            emulator.load_bios(bios_path)

        emulator.power_on()
        executed = emulator.run_frame(4)

        self.assertEqual(executed, 4)
        self.assertEqual(emulator.frame_count, 1)
        self.assertEqual(emulator.pc, 0)
        self.assertEqual(emulator.cycles, 10)


if __name__ == "__main__":
    unittest.main()
