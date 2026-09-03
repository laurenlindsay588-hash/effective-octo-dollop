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
    ELFLoader,
    INTC_START,
    MMU,
    MemoryMap,
    MemoryRegion,
    PS2Emulator,
    PS2System,
    TIMER0_START,
    run_cli,
)


class PS2EmulatorTests(unittest.TestCase):
    def _write_bios(self, tmp: str, payload: bytes) -> Path:
        bios_path = Path(tmp) / "bios.bin"
        bios_path.write_bytes(payload)
        return bios_path

    def test_power_on_requires_bios(self):
        emulator = PS2Emulator()
        with self.assertRaises(RuntimeError):
            emulator.power_on()

    def test_load_empty_bios_rejected(self):
        emulator = PS2Emulator()
        with tempfile.TemporaryDirectory() as tmp:
            bios_path = self._write_bios(tmp, b"")
            with self.assertRaises(ValueError):
                emulator.load_bios(bios_path)

    def test_run_frame_updates_state(self):
        emulator = PS2Emulator()
        bios = bytes([0x00, 0x00, 0x00]) + bytes(64)
        with tempfile.TemporaryDirectory() as tmp:
            emulator.load_bios(self._write_bios(tmp, bios))

        emulator.power_on()
        executed = emulator.run_frame(3)
        self.assertEqual(executed, 3)
        self.assertEqual(emulator.frame_count, 1)
        self.assertEqual(emulator.pc, (EE_RESET_VECTOR + 3) & 0xFFFFFFFF)
        self.assertEqual(emulator.cycles, 3)
        self.assertEqual(emulator.status()["scheduler_cycle"], 3)

    def test_instruction_semantics_load_store_jump(self):
        emulator = PS2Emulator()
        bios = bytes([0x80, 0xC1, 0x42]) + bytes(64)
        with tempfile.TemporaryDirectory() as tmp:
            emulator.load_bios(self._write_bios(tmp, bios))
        emulator.power_on()
        emulator.system.memory_map.write8(EE_RAM_START, 0x5A, virtual=False)

        r1 = emulator.system.step()
        r2 = emulator.system.step()
        r3 = emulator.system.step()

        self.assertEqual(r1.mnemonic, "LOAD")
        self.assertEqual(r2.mnemonic, "STORE")
        self.assertEqual(r3.mnemonic, "JUMP")
        self.assertEqual(emulator.system.ee.gpr[1], 0x5A)
        self.assertEqual(emulator.system.memory_map.read8(EE_RAM_START + 1, virtual=False), 0x5A)
        self.assertEqual(emulator.pc, (EE_RESET_VECTOR + 5) & 0xFFFFFFFF)
        self.assertEqual(emulator.cycles, 8)

    def test_reset_behavior_clears_runtime_state(self):
        emulator = PS2Emulator()
        bios = bytes([0x00, 0x00, 0x00, 0x00]) + bytes(64)
        with tempfile.TemporaryDirectory() as tmp:
            emulator.load_bios(self._write_bios(tmp, bios))
        emulator.power_on()
        emulator.run_frame(3)
        emulator.system.intc.mask = 1
        emulator.system.intc.pending = 1
        emulator.system.timer0.counter = 99

        emulator.power_on()
        self.assertEqual(emulator.pc, EE_RESET_VECTOR)
        self.assertEqual(emulator.cycles, 0)
        self.assertEqual(emulator.system.scheduler.current_cycle, 0)
        self.assertEqual(emulator.system.timer0.counter, 0)
        self.assertEqual(emulator.system.intc.pending, 0)
        self.assertEqual(emulator.frame_count, 0)

    def test_timer_and_interrupt_controller_are_wired_to_scheduler(self):
        emulator = PS2Emulator()
        bios = bytes([0x00, 0x00, 0x00, 0x00, 0x00]) + bytes(64)
        with tempfile.TemporaryDirectory() as tmp:
            emulator.load_bios(self._write_bios(tmp, bios))
        emulator.power_on()
        emulator.system.memory_map.write8(TIMER0_START + 4, 0x05, virtual=False)
        emulator.system.memory_map.write8(INTC_START + 4, 0x01, virtual=False)

        emulator.run_frame(5)

        self.assertEqual(emulator.system.timer0.counter, 5)
        self.assertTrue(emulator.system.intc.irq_asserted())
        self.assertEqual(emulator.system.intc.pending & 0x1, 0x1)

    def test_mmu_translation_edge_cases(self):
        mmu = MMU()
        self.assertEqual(mmu.translate_ee_virtual(0x7FFFFFFF), 0x7FFFFFFF)
        self.assertEqual(mmu.translate_ee_virtual(0x80000000), 0x00000000)
        self.assertEqual(mmu.translate_ee_virtual(0x9FFFFFFF), 0x1FFFFFFF)
        self.assertEqual(mmu.translate_ee_virtual(0xA0000000), 0x00000000)
        self.assertEqual(mmu.translate_ee_virtual(0xBFFFFFFF), 0x1FFFFFFF)
        with self.assertRaises(ValueError):
            mmu.translate_ee_virtual(0xC0000000)

    def test_bios_is_mapped_at_physical_bios_region(self):
        emulator = PS2Emulator()
        bios = bytes([0xAA, 0xBB, 0xCC]) + bytes(16)
        with tempfile.TemporaryDirectory() as tmp:
            emulator.load_bios(self._write_bios(tmp, bios))

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
        bios = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00]) + bytes(64)
        with tempfile.TemporaryDirectory() as tmp:
            bios_path = self._write_bios(tmp, bios)
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

    def test_cli_max_cycles_trace_and_status_every(self):
        bios = bytes([0x00] * 32)
        with tempfile.TemporaryDirectory() as tmp:
            bios_path = self._write_bios(tmp, bios)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = run_cli(
                    [
                        "--bios",
                        str(bios_path),
                        "--instructions",
                        "10",
                        "--frames",
                        "2",
                        "--max-cycles",
                        "4",
                        "--trace",
                        "--status-every",
                        "2",
                        "--status-json",
                    ]
                )
        self.assertEqual(code, 0)
        lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
        self.assertTrue(any("opcode=0x00 NOP" in line for line in lines))
        self.assertGreaterEqual(sum(1 for line in lines if line.startswith("{")), 3)
        final_status = json.loads(lines[-1])
        self.assertEqual(final_status["cycles"], 4)
        self.assertEqual(final_status["pc"], (EE_RESET_VECTOR + 4) & 0xFFFFFFFF)

    def test_elf_loader_parses_elf32_header(self):
        raw = bytearray(52)
        raw[0:4] = b"\x7fELF"
        raw[4] = 1
        raw[5] = 1
        raw[24:28] = (0x00100000).to_bytes(4, "little")
        raw[28:32] = (0x34).to_bytes(4, "little")
        raw[44:46] = (2).to_bytes(2, "little")

        image = ELFLoader.parse_elf32(bytes(raw))
        self.assertEqual(image.entry_point, 0x00100000)
        self.assertEqual(image.program_header_offset, 0x34)
        self.assertEqual(image.program_header_count, 2)

    def test_emulator_load_elf_scaffold(self):
        raw = bytearray(52)
        raw[0:4] = b"\x7fELF"
        raw[4] = 1
        raw[5] = 1
        raw[24:28] = (0x00020000).to_bytes(4, "little")
        with tempfile.TemporaryDirectory() as tmp:
            elf_path = Path(tmp) / "homebrew.elf"
            elf_path.write_bytes(bytes(raw))
            emulator = PS2Emulator()
            image = emulator.load_elf(elf_path)
        self.assertEqual(image.entry_point, 0x00020000)
        self.assertEqual(emulator.status()["elf_entry_point"], 0x00020000)

    def test_elf_loader_rejects_non_elf(self):
        with self.assertRaises(ValueError):
            ELFLoader.parse_elf32(b"not-an-elf")


if __name__ == "__main__":
    unittest.main()
