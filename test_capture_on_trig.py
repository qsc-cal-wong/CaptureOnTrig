import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch

import CaptureOnTrig as app


class ConsoleFlowTests(unittest.TestCase):
    def test_startup_displays_docstring_and_can_quit_without_connecting(self):
        output = StringIO()
        responses = iter(("invalid", " Q ", ""))

        def respond(prompt):
            self.assertIn(app.__doc__, output.getvalue())
            return next(responses)

        with redirect_stdout(output), \
                patch("builtins.input", side_effect=respond) as user_input, \
                patch.object(app.pyvisa, "ResourceManager") as manager:
            app.main()

        manager.assert_not_called()
        self.assertEqual(user_input.call_count, 3)
        self.assertIn("Press Enter to exit", user_input.call_args.args[0])
        self.assertIn("Stopped by user.", output.getvalue())

    def test_exit_confirmation_follows_cleanup_after_capture_stops(self):
        for result in (False, None, KeyboardInterrupt(), ValueError("test failure")):
            with self.subTest(result=result):
                manager = Mock()
                instrument = manager.open_resource.return_value
                instrument.query.return_value = "TEKTRONIX,MSO54,serial,firmware"
                scope = Mock()
                output = StringIO()
                responses = iter(("", "10.99.100.41", "d", "10"))

                def respond(prompt):
                    if prompt.startswith("Press Enter to exit"):
                        scope.stop.assert_called_once_with()
                        instrument.close.assert_called_once_with()
                        manager.close.assert_called_once_with()
                        return ""
                    return next(responses)

                with redirect_stdout(output), \
                        patch("builtins.input", side_effect=respond) as user_input, \
                        patch.object(app.os, "makedirs"), \
                        patch.object(app.pyvisa, "ResourceManager", return_value=manager), \
                        patch.object(app, "create_scope_adapter", return_value=scope), \
                        patch.object(app, "wait_for_trigger", side_effect=[result]):
                    app.main()

                scope.configure.assert_called_once_with()
                scope.arm.assert_called_once_with()
                scope.capture_image.assert_not_called()
                self.assertIn("Press Enter to exit", user_input.call_args.args[0])

    def test_closed_input_reports_why_confirmation_is_unavailable(self):
        output = StringIO()
        with redirect_stdout(output), \
                patch("builtins.input", side_effect=EOFError), \
                patch.object(app.pyvisa, "ResourceManager") as manager:
            app.main()

        manager.assert_not_called()
        self.assertIn("standard input was closed", output.getvalue())
        self.assertIn("Exit confirmation interrupted", output.getvalue())


class TektronixScopeTests(unittest.TestCase):
    def test_dpo4000_models_use_ethernet_hardcopy(self):
        for model in ("DPO4034", "DPO4054", "DPO4054B", "DPO4104B"):
            with self.subTest(model=model):
                instrument = Mock()
                instrument.read_raw.return_value = b"scope image"
                scope = app.create_scope_adapter(
                    instrument, f"TEKTRONIX,{model},C011273,CF:91.1CT FV:v3.22"
                )
                scope.configure()
                image, image_format = scope.capture_image()
                self.assertEqual((image, image_format), (b"scope image", "png"))
                commands = [call.args[0] for call in instrument.write.call_args_list]
                self.assertIn("SAVE:IMAGe:FILEFormat PNG", commands)
                self.assertIn("HARDCOPY:PORT ETHERNET", commands)
                self.assertEqual(commands[-1], "HARDCopy START")
                instrument.query.assert_not_called()

    def test_mso5_and_mso6_models_use_file_transfer(self):
        for model in (
            "MSO54", "MSO56", "MSO58", "MSO58B",
            "MSO64", "MSO66", "MSO68", "MSO64B", "MSO66B", "MSO68B",
        ):
            with self.subTest(model=model):
                instrument = Mock()
                instrument.read_raw.return_value = b"scope image"
                scope = app.create_scope_adapter(
                    instrument, f"tektronix, {model.lower()} ,serial,firmware"
                )
                scope.configure()
                self.assertEqual(scope.capture_image(), (b"scope image", "png"))
                commands = [call.args[0] for call in instrument.write.call_args_list]
                self.assertFalse(any("HARDCOPY" in cmd.upper() for cmd in commands))
                self.assertEqual(
                    commands[-2:],
                    [
                        f'SAVE:IMAGe "{app.TEKTRONIX_TEMP_IMAGE}"',
                        f'FILESystem:READfile "{app.TEKTRONIX_TEMP_IMAGE}"',
                    ],
                )
                instrument.query.assert_called_once_with("*OPC?")

    def test_configuration_disables_headers_for_trigger_polling(self):
        instrument = Mock()
        headers_enabled = True
        acquisition_state = "0"

        def write(command):
            nonlocal headers_enabled, acquisition_state
            if command == "HEADer OFF":
                headers_enabled = False
            elif command == "ACQuire:STATE 1":
                acquisition_state = "1"

        def query(command):
            self.assertEqual(command, "ACQuire:STATE?")
            prefix = ":ACQUIRE:STATE " if headers_enabled else ""
            return prefix + acquisition_state + "\n"

        instrument.write.side_effect = write
        instrument.query.side_effect = query
        scope = app.create_scope_adapter(
            instrument, "TEKTRONIX,DPO4054B,C011273,CF:91.1CT FV:v3.22"
        )
        scope.configure()
        scope.arm()
        self.assertFalse(scope.has_triggered())
        acquisition_state = "0"
        self.assertTrue(scope.has_triggered())
        commands = [call.args[0] for call in instrument.write.call_args_list]
        self.assertIn("TRIGger:A:MODe NORMal", commands)
        self.assertIn("ACQuire:STOPAfter SEQuence", commands)
        self.assertFalse(any(":SOUrce" in cmd or ":LEVel" in cmd for cmd in commands))

    def test_unsupported_models_are_not_matched_in_serial_or_firmware(self):
        for idn in (
            "TEKTRONIX",
            "TEKTRONIX,TDS2024,DPO4034,MSO58",
            "TEKTRONIX,DPO7000,serial,firmware",
        ):
            with self.subTest(idn=idn):
                with self.assertRaisesRegex(ValueError, "Unsupported Tektronix model"):
                    app.create_scope_adapter(Mock(), idn)


if __name__ == "__main__":
    unittest.main()
