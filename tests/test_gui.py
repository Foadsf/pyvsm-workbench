import os
import sys
import unittest

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

# Set offscreen platform for headless Qt testing
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from ui.main_window import OpenVSMStudio

class TestOpenVSMGUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(sys.argv)

    def test_studio_initialization(self):
        studio = OpenVSMStudio()
        self.assertIsNotNone(studio.canvas)
        self.assertIsNotNone(studio.scene)
        self.assertIsNotNone(studio.mcu_item)
        self.assertIsNotNone(studio.pot_item)
        self.assertIsNotNone(studio.btn_item)
        self.assertIsNotNone(studio.lcd_item)
        self.assertIsNotNone(studio.freq_item)
        self.assertIsNotNone(studio.i2c_item)
        self.assertIsNotNone(studio.voltmeter_item)
        self.assertIsNotNone(studio.seg_item)
        self.assertIsNotNone(studio.dso_widget)
        self.assertIsNotNone(studio.debugger_widget)

        # Verify initial MCU model
        self.assertEqual(studio.mcu.arch, "PIC18F452")

        # Test single instruction step
        studio.step_single_instruction()
        self.assertGreater(studio.mcu.sim_time, 0.0)

        # Test potentiometer interaction
        studio.pot_item.set_ratio(0.75)
        self.assertAlmostEqual(studio.spice.pot_ratio, 0.75, places=2)

        # Test pushbutton interaction
        studio.btn_item.toggle(True)
        self.assertTrue(studio.spice.button_pressed)
        studio.btn_item.toggle(False)
        self.assertFalse(studio.spice.button_pressed)


        # Test architecture change
        studio._on_arch_changed("ATMEGA328P (AVR 16MHz)")
        self.assertEqual(studio.mcu.arch, "ATMEGA328P")

        # Test rendering & paint() overrides for all scene items
        from PySide6.QtGui import QPixmap, QPainter
        from PySide6.QtWidgets import QStyleOptionGraphicsItem
        pixmap = QPixmap(800, 600)
        painter = QPainter(pixmap)
        opt = QStyleOptionGraphicsItem()
        for it in studio.scene.items():
            it.paint(painter, opt, None)
        painter.end()

        # Clean up
        studio.close()

    def test_wire_disconnection_floats_input(self):
        studio = OpenVSMStudio()
        p_wiper = studio.pot_item.pins["WIPER"]
        p_adc0 = studio.mcu_item.pins["ADC0"]

        self.assertTrue(studio._pins_connected(p_wiper, p_adc0))
        studio._on_frame_tick()
        self.assertAlmostEqual(studio.mcu.pins["ADC0"], 2.50, places=1)

        # Disconnect wiper wire
        wiper_wire = None
        for w in studio.wires:
            if (w.pin_start == p_wiper and w.pin_end == p_adc0) or (w.pin_start == p_adc0 and w.pin_end == p_wiper):
                wiper_wire = w
                break
        self.assertIsNotNone(wiper_wire)
        studio.canvas._remove_wire(wiper_wire)
        studio.wires.remove(wiper_wire)

        self.assertFalse(studio._pins_connected(p_wiper, p_adc0))
        studio._on_frame_tick()
        # Disconnected pin floats to 0.0V
        self.assertEqual(studio.mcu.pins["ADC0"], 0.0)

        studio.close()

    def test_component_deletion(self):
        from PySide6.QtCore import Qt, QEvent
        from PySide6.QtGui import QKeyEvent
        from ui.wires import SchematicWireItem

        studio = OpenVSMStudio()
        # Select voltmeter item
        studio.voltmeter_item.setSelected(True)
        key_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier)
        studio.canvas.keyPressEvent(key_event)

        self.assertNotIn(studio.voltmeter_item, studio.scene.items())
        studio.close()

if __name__ == "__main__":
    unittest.main()

