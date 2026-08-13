import unittest

from ps2_emulator import EE_RESET_VECTOR, PS2System


class EEMemoryHarnessTests(unittest.TestCase):
    def test_ee_fetches_from_reset_vector_through_mmu(self):
        system = PS2System()
        system.load_bios_bytes(bytes([0x10, 0x20, 0x30]) + bytes(64))
        system.power_on()

        self.assertEqual(system.ee.pc, EE_RESET_VECTOR)
        self.assertEqual(system.step(), 0x10)
        self.assertEqual(system.step(), 0x20)
        self.assertEqual(system.ee.pc, EE_RESET_VECTOR + 2)

    def test_memory_map_translates_kseg0_to_physical_ram(self):
        system = PS2System()
        self.assertEqual(system.memory_map.mmu.translate_ee_virtual(0x80000010), 0x00000010)
        system.memory_map.write8(0x80000010, 0x5A, virtual=True)
        self.assertEqual(system.memory_map.read8(0x00000010, virtual=False), 0x5A)

    def test_bios_region_is_read_only(self):
        system = PS2System()
        system.load_bios_bytes(bytes([0x42]) + bytes(16))
        with self.assertRaises(PermissionError):
            system.memory_map.write8(0xBFC00000, 0xFF, virtual=True)


if __name__ == "__main__":
    unittest.main()
