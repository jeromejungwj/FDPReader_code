"""서명 모듈: 입력 기록 재생, 실제 장치 descriptor 로 만든 보고서 해석."""

import ctypes as C
import struct
import unittest
from ctypes import wintypes as W

from features.sign import touchpad_input as tp
from features.sign.contacts import Contact, FingerTracker, FrameAssembler
from features.sign.signature_store import SignatureStore
from features.sign.stroke_processor import StrokeBuilder, stroke_segments, to_graphic
from tests import helpers


def touch(cid=0, x=0.5, y=0.5, tip=True, confident=True):
    return Contact(cid, x, y, tip, confident)


def replay(frames):
    tracker = FingerTracker()
    events = []
    for now, contacts in frames:
        events += tracker.feed(contacts, now)
    return [event[0] for event in events]


class Tracking(unittest.TestCase):
    def test_one_finger_stroke(self):
        frames = [(0, [touch()]), (0.01, [touch(x=0.6)]), (0.02, [touch(tip=False)])]
        self.assertEqual(replay(frames), ["down", "move", "up"])

    def test_lift_by_absence_then_second_stroke_starts_at_its_own_position(self):
        tracker = FingerTracker()
        tracker.feed([touch(x=0.1, y=0.1)], 0)
        self.assertEqual(tracker.feed([], 0.2), [("up",)])
        self.assertEqual(tracker.feed([touch(1, 0.9, 0.8)], 0.5), [("down", 0.9, 0.8, 0.5)])

    def test_two_finger_scroll_is_ignored(self):
        pair = [touch(0), touch(1)]
        self.assertEqual(replay([(0, pair), (0.1, pair), (0.2, [touch(0)]), (0.3, [])]), [])

    def test_second_finger_right_after_first_cancels(self):
        frames = [(0, [touch(0)]), (0.05, [touch(0), touch(1)]), (0.1, [touch(0)]), (0.2, [])]
        self.assertEqual(replay(frames), ["down", "cancel"])

    def test_late_second_finger_does_not_take_over(self):
        frames = [(0, [touch(0)]), (0.5, [touch(0), touch(1)]), (0.6, [touch(1)]), (0.7, [])]
        self.assertEqual(replay(frames), ["down", "move", "up"])

    def test_palm_never_draws(self):
        palm = touch(3, confident=False)
        self.assertEqual(replay([(0, [palm]), (0.1, [touch(3)]), (0.2, [])]), [])

    def test_contact_that_becomes_palm_is_cancelled(self):
        frames = [(0, [touch()]), (0.1, [touch(confident=False)]), (0.2, [])]
        self.assertEqual(replay(frames), ["down", "cancel"])

    def test_palm_next_to_writing_finger(self):
        palm = touch(9, confident=False)
        frames = [(0, [palm]), (0.1, [palm, touch()]), (0.2, [palm, touch()]), (0.3, [palm])]
        self.assertEqual(replay(frames), ["down", "move", "up"])

    def test_parallel_and_hybrid_reports(self):
        slots = [touch(i) for i in range(5)]
        assembler = FrameAssembler()
        self.assertEqual(assembler.feed(2, slots), slots[:2])
        self.assertEqual(assembler.feed(0, slots), [])
        self.assertIsNone(assembler.feed(3, [slots[0]]))
        self.assertIsNone(assembler.feed(0, [slots[1]]))
        self.assertEqual(assembler.feed(0, [slots[2]]), slots[:3])


class Strokes(unittest.TestCase):
    def test_tap_is_a_dot(self):
        segments = stroke_segments([(0.5, 0.5, 0.0)], 1.4, 0.02)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0][:2], segments[0][2:4])

    def test_stroke_reaches_both_ends(self):
        points = [(0.1 + i * 0.02, 0.2, i * 0.01) for i in range(30)]
        segments = stroke_segments(points, 1.0, 0.02)
        self.assertAlmostEqual(segments[0][0], points[0][0], delta=0.005)
        self.assertAlmostEqual(segments[-1][2], points[-1][0], delta=1e-6)

    def test_fast_is_thinner_than_slow(self):
        slow = stroke_segments([(i * 0.005, 0.5, i * 0.01) for i in range(40)], 1.0, 0.02)
        fast = stroke_segments([(i * 0.05, 0.5, i * 0.01) for i in range(20)], 1.0, 0.02)
        self.assertLess(fast[-2][4], slow[-2][4] * 0.7)

    def test_pressure_controls_width(self):
        light = stroke_segments([(i * 0.02, 0.5, i * 0.01, 0.1) for i in range(20)], 1.0, 0.02)
        hard = stroke_segments([(i * 0.02, 0.5, i * 0.01, 0.9) for i in range(20)], 1.0, 0.02)
        self.assertLess(light[-2][4], hard[-2][4])

    def test_live_drawing_equals_saved_result(self):
        points = [(i * 0.03, 0.4 + (i % 3) * 0.05, i * 0.008) for i in range(25)]
        builder, live = StrokeBuilder(0.02), []
        for x, y, t in points:
            live += builder.add(x * 1.4, y, t)
        live += builder.finish()
        saved = to_graphic({"kind": "ink", "aspect": 1.4, "width": 0.02, "color": [0, 0, 0],
                            "strokes": [points]})
        self.assertEqual(list(saved.segments), live)

    def test_margins_are_trimmed(self):
        graphic = to_graphic({"kind": "ink", "aspect": 1.0, "width": 0.02, "color": [0, 0, 0],
                              "strokes": [[(0.4, 0.4, 0), (0.6, 0.5, 0.1)]]})
        x0, y0, x1, y1 = graphic.bounds
        self.assertGreater(x0, 0.37)
        self.assertLess(x1, 0.63)
        self.assertGreater(y0, 0.37)
        self.assertLess(y1, 0.53)


class Store(helpers.TempCase):
    def test_encrypted_round_trip_and_delete(self):
        store = SignatureStore()
        signature = {"kind": "ink", "aspect": 1.4, "width": 0.02, "color": [0, 0, 0],
                     "strokes": [[[0.123456, 0.2, 0.0]]]}
        name = store.add(signature)
        stored = (store.folder / f"{name}.sig").read_bytes()
        self.assertNotIn(b"strokes", stored)
        self.assertNotIn(b"0.123456", stored)
        self.assertEqual(store.all(), [(name, signature)])
        store.delete(name)
        self.assertEqual(store.all(), [])
        self.assertEqual(list(store.folder.iterdir()), [])

    def test_unreadable_file_is_skipped(self):
        store = SignatureStore()
        (store.folder / "x.sig").write_bytes(b"not encrypted")
        with self.assertLogs("features.sign.signature_store"):
            self.assertEqual(store.all(), [])


class RealDescriptor(unittest.TestCase):
    """이 PC 트랙패드의 preparsed data 로 보고서를 만들어 해석기에 넣음 (손가락 불필요)."""

    def setUp(self):
        pads = tp.find_touchpads()
        if not pads:
            self.skipTest("Precision Touchpad 없음")
        self.pad = pads[0]
        self.put = C.WinDLL("hid").HidP_SetUsageValue
        self.put.argtypes = [C.c_int, W.USHORT, W.USHORT, W.USHORT, W.ULONG,
                             C.c_void_p, C.c_void_p, W.ULONG]
        self.put.restype = W.ULONG
        self.press = C.WinDLL("hid").HidP_SetUsages
        self.press.argtypes = [C.c_int, W.USHORT, W.USHORT, C.c_void_p, C.c_void_p,
                               C.c_void_p, C.c_void_p, W.ULONG]
        self.press.restype = W.ULONG

    def report(self, fingers):
        pad = self.pad
        for report_id in range(256):
            raw = C.create_string_buffer(bytes([report_id]) + bytes(pad.report_bytes - 1),
                                         pad.report_bytes)
            if self.put(0, 0x0D, pad.count_link, tp.USAGE_CONTACT_COUNT, len(fingers),
                        pad.preparsed, raw, pad.report_bytes) == tp._HIDP_SUCCESS:
                break
        else:
            self.fail("접촉 보고서 ID 를 찾지 못함")
        for slot, (cid, x, y, confident) in zip(pad.fingers, fingers):
            for page, usage, value in (
                (1, tp.USAGE_X, round(slot.x[0] + x * (slot.x[1] - slot.x[0]))),
                (1, tp.USAGE_Y, round(slot.y[0] + y * (slot.y[1] - slot.y[0]))),
                (0x0D, tp.USAGE_CONTACT_ID, cid),
            ):
                self.assertEqual(self.put(0, page, slot.link, usage, value, pad.preparsed, raw,
                                          pad.report_bytes), tp._HIDP_SUCCESS)
            flags = [tp.USAGE_TIP] + ([tp.USAGE_CONFIDENCE] if confident else [])
            usages = (W.USHORT * len(flags))(*flags)
            count = W.ULONG(len(flags))
            self.assertEqual(self.press(0, 0x0D, slot.link, usages, C.byref(count), pad.preparsed,
                                        raw, pad.report_bytes), tp._HIDP_SUCCESS)
        return raw.raw[: pad.report_bytes]

    def decode(self, *reports):
        header = tp.RawHeader(2, 0, self.pad.handle, 0)
        body = b"".join(reports)
        raw = bytes(header) + struct.pack("<II", len(reports[0]), len(reports)) + body
        return tp.TouchpadInput([self.pad]).decode(raw)

    def test_corners_map_to_unit_square(self):
        for x, y in ((0, 0), (1, 0), (1, 1), (0, 1), (0.25, 0.75)):
            frame = self.decode(self.report([(1, x, y, True)]))[0]
            self.assertEqual(len(frame), 1)
            self.assertAlmostEqual(frame[0].x, x, delta=0.001)
            self.assertAlmostEqual(frame[0].y, y, delta=0.001)
            self.assertTrue(frame[0].tip and frame[0].confident)

    def test_palm_bit_and_several_fingers(self):
        if len(self.pad.fingers) < 2:
            self.skipTest("hybrid 장치")
        frame = self.decode(self.report([(1, 0.2, 0.2, True), (2, 0.8, 0.8, False)]))[0]
        self.assertEqual([(c.id, c.confident) for c in frame], [(1, True), (2, False)])

    def test_several_reports_in_one_message(self):
        frames = self.decode(self.report([(1, 0.1, 0.1, True)]), self.report([(1, 0.2, 0.1, True)]))
        self.assertEqual([round(f[0].x, 2) for f in frames], [0.1, 0.2])


if __name__ == "__main__":
    unittest.main()
