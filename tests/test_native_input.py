import ctypes
import unittest

from native_input import JoyCaps, JoyInfoEx, NativeInput, device_from_caps, normalize_axis


class FakeWinMM:
    connected = True
    buttons = 5
    x = 100

    def joyGetNumDevs(self):
        return 2

    def joyGetDevCapsW(self, device_id, pointer, size):
        if device_id != 0:
            return 165
        caps = ctypes.cast(pointer, ctypes.POINTER(JoyCaps)).contents
        caps.szPname = "Test controller"
        caps.wNumButtons = 4
        caps.wNumAxes = 3
        caps.wCaps = 1
        for name in ("X", "Y", "Z"):
            setattr(caps, f"w{name}min", 100)
            setattr(caps, f"w{name}max", 1100)
        return 0

    def joyGetPosEx(self, device_id, pointer):
        if not self.connected or device_id != 0:
            return 167
        info = ctypes.cast(pointer, ctypes.POINTER(JoyInfoEx)).contents
        info.dwXpos = self.x
        info.dwYpos = 600
        info.dwZpos = 1100
        info.dwButtons = self.buttons
        return 0


class NativeInputTests(unittest.TestCase):
    def test_normalize_device_range_and_clamp(self):
        self.assertEqual(normalize_axis(100, 100, 1100), -1)
        self.assertEqual(normalize_axis(600, 100, 1100), 0)
        self.assertEqual(normalize_axis(1100, 100, 1100), 1)
        self.assertEqual(normalize_axis(99999, 100, 1100), 1)
        self.assertEqual(normalize_axis(50, 100, 1100), -1)
        self.assertEqual(normalize_axis(500, 100, 100), 0)

    def test_scan_and_decode_realistic_sample(self):
        reader = NativeInput(api=FakeWinMM())
        self.assertEqual(reader.scan(), [{"id": 0, "name": "Test controller", "buttons": 4,
                                          "axes": 3, "axisNames": ["X", "Y", "Z"]}])
        sample = reader.poll(0)
        self.assertEqual(sample["buttons"], [True, False, True, False])
        self.assertEqual(sample["axes"], [-1, 0, 1])
        self.assertGreater(sample["time"], 0)
        self.assertIsNone(reader.poll(1))

    def test_unplug_and_reconnect(self):
        api = FakeWinMM()
        reader = NativeInput(api=api)
        reader.scan()
        api.connected = False
        self.assertIsNone(reader.poll(0))
        self.assertEqual(reader.scan(), [])
        api.connected = True
        self.assertEqual(len(reader.scan()), 1)
        self.assertIsNotNone(reader.poll(0))

    def test_capability_axes_and_button_limit(self):
        caps = JoyCaps()
        caps.wNumAxes = 6
        caps.wCaps = 15
        caps.wNumButtons = 100
        device = device_from_caps(3, caps)
        self.assertEqual([item[0] for item in device.ranges], list("XYZRUV"))
        self.assertEqual(device.buttons, 32)
        self.assertEqual(device.name, "Controller 4")

    def test_sparse_axis_names_match_normalized_value_indices(self):
        caps = JoyCaps()
        caps.wNumAxes = 3
        caps.wCaps = 2  # R is available but Z is not.
        device = device_from_caps(0, caps)
        self.assertEqual(device.public()["axisNames"], ["X", "Y", "R"])
        self.assertEqual(device.public()["axes"], 3)


if __name__ == "__main__":
    unittest.main()
