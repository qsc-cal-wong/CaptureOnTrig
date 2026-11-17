"""Capture oscilloscope display images after each normal-mode trigger.

Enter a VISA resource (an IP address is expanded to a TCPIP INSTR resource).
The program preserves the trigger source and level, arms one acquisition at a
time, and saves each completed capture on the user's desktop by default.

Tested with Rigol DS1000Z, Tektronix DPO4034 and MSO58, and LeCroy 
WaveRunner 8108HD.

"""

import time
import datetime
import os
from pathlib import Path
from glob import glob
import msvcrt
import pyvisa


DEFAULT_IP_ADDRESS = "192.168.1.123"
# Find user desktop one level down from home [~/* /Desktop] as optional path to account for OneDrive
DESKTOP_PATH = glob(os.path.expanduser("~\\*\\Desktop"))
DEFAULT_SAVE_DIRECTORY = os.path.join(DESKTOP_PATH[0] if DESKTOP_PATH else os.path.expanduser("~\\Desktop"), "CaptureOnTrig")
POLL_INTERVAL_SECONDS = 0.05
RIGOL_POLL_INTERVAL_SECONDS = 0.01
ARM_SETTLE_SECONDS = 0.5
DEFAULT_TRIGGER_TIMEOUT_SECONDS = 300
MIN_TRIGGER_TIMEOUT_SECONDS = 10
MAX_TRIGGER_TIMEOUT_SECONDS = 300
INSTRUMENT_TIMEOUT_MS = 30000
TEKTRONIX_TEMP_IMAGE = "C:/CaptureOnTrig.png"


class ScopeAdapter:
    """Common capture interface implemented by supported scope families."""

    arm_settle_seconds = ARM_SETTLE_SECONDS

    def __init__(self, instrument):
        self.instrument = instrument

    def configure(self):
        raise NotImplementedError

    def arm(self):
        raise NotImplementedError

    def has_triggered(self):
        raise NotImplementedError

    def capture_image(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def is_armed(self):
        return True


class RigolScope(ScopeAdapter):
    """Rigol DS1000Z display capture using its native PNG transfer."""

    arm_settle_seconds = 0

    def __init__(self, instrument):
        ScopeAdapter.__init__(self, instrument)
        self._trigger_ready = True
        self._armed_status_seen = False
        self._running = False
        self.last_status = None

    def configure(self):
        self.instrument.write(":TRIGger:SWEep NORMal")

    def arm(self):
        if not self._running:
            self.instrument.write(":RUN")
            self._running = True
            self._trigger_ready = True
            self._armed_status_seen = False

    def has_triggered(self):
        status = self.instrument.query(":TRIGger:STATus?").strip().upper()
        self.last_status = status
        if status in ("WAIT", "RUN"):
            self._armed_status_seen = True
            self._trigger_ready = True
            return False
        if status == "TD":
            if self._trigger_ready:
                self._trigger_ready = False
                return True
        if (
            status == "STOP"
            and self._armed_status_seen
            and self._trigger_ready
        ):
            self._trigger_ready = False
            return True
        return False

    def is_armed(self):
        return self._armed_status_seen

    def capture_image(self):
        image_data = self.instrument.query_binary_values(
            ":DISPlay:DATA? ON,OFF,PNG",
            datatype="B",
            header_fmt="ieee",
            expect_termination=True,
            container=bytes,
        )
        return image_data, "png"

    def stop(self):
        self.instrument.write(":STOP")
        self._running = False


class TektronixScope(ScopeAdapter):
    """Tektronix DPO4 and MSO5 display capture using native PNG data."""

    def __init__(self, instrument, idn):
        ScopeAdapter.__init__(self, instrument)
        self.is_mso5 = "MSO58" in idn.upper() or "MSO5" in idn.upper()

    def configure(self):
        self.instrument.write("TRIGger:A:MODe NORMal")
        self.instrument.write("ACQuire:STOPAfter SEQuence")
        if not self.is_mso5:
            self.instrument.write("SAVE:IMAGe:FILEFormat PNG")
            self.instrument.write("HARDCOPY:INKSAVER OFF")
            self.instrument.write("HARDCOPY:PORT ETHERNET")

    def arm(self):
        self.instrument.write("ACQuire:STATE 1")

    def has_triggered(self):
        return self.instrument.query("ACQuire:STATE?").strip() == "0"

    def capture_image(self):
        if self.is_mso5:
            self.instrument.write(
                'SAVE:IMAGe "' + TEKTRONIX_TEMP_IMAGE + '"'
            )
            self.instrument.query("*OPC?")
            self.instrument.write(
                'FILESystem:READfile "' + TEKTRONIX_TEMP_IMAGE + '"'
            )
        else:
            self.instrument.write("HARDCopy START")
        return self.instrument.read_raw(), "png"

    def stop(self):
        self.instrument.write("ACQuire:STATE 0")


class LeCroyScope(ScopeAdapter):
    """LeCroy WaveRunner screen capture using its hardcopy interface."""

    def configure(self):
        self.instrument.write("TRMD NORM")
        background = get_lecroy_background()
        self.instrument.write(
            f"HCSU DEV,PNG,FORMAT,PORTRAIT,BCKG,{background},"
            "DEST,REMOTE,PORT,NET,AREA,GRIDAREAONLY"
        )

    def arm(self):
        self.instrument.write("TRMD SINGLE; ARM")

    def has_triggered(self):
        status = self.instrument.query("TRMD?").strip().upper()
        return status in ("STOP", "TRMD STOP")

    def capture_image(self):
        self.instrument.write("SCDP")
        return self.instrument.read_raw(), "png"

    def stop(self):
        self.instrument.write("TRMD STOP")


def get_visa_resource():
    """Prompt for a VISA resource string or expand a plain IP address."""
    address = input(
        "Enter the scope IP address or full VISA resource "
        f"(default {DEFAULT_IP_ADDRESS}): "
    ).strip()
    if not address:
        address = DEFAULT_IP_ADDRESS
    if "::" in address:
        return address
    return f"TCPIP0::{address}::INSTR"


def get_lecroy_background():
    """Prompt for the LeCroy PNG background color."""
    while True:
        response = input(
            "LeCroy PNG background: [B]lack (normal) or [W]hite (print), "
            "default B: "
        ).strip().lower()
        if not response or response == "b":
            return "BLACK"
        if response == "w":
            return "WHITE"
        print("Enter B for black or W for white.")


def get_trigger_timeout():
    """Prompt for a valid wait time between triggers; zero means unlimited."""
    while True:
        response = input(
            "Enter trigger wait timeout in seconds "
            "(10-300, or 0 to wait forever; default 300): "
        ).strip()
        if not response:
            return DEFAULT_TRIGGER_TIMEOUT_SECONDS
        try:
            timeout_seconds = int(response)
        except ValueError:
            print("Enter a whole number from 10 to 300, or 0 to wait forever.")
            continue
        if timeout_seconds == 0 or (
            MIN_TRIGGER_TIMEOUT_SECONDS
            <= timeout_seconds
            <= MAX_TRIGGER_TIMEOUT_SECONDS
        ):
            return timeout_seconds
        print("Enter a whole number from 10 to 300, or 0 to wait forever.")


def create_scope_adapter(instrument, idn):
    """Choose a supported capture implementation from the instrument ID."""
    upper_idn = idn.upper()
    if "RIGOL" in upper_idn:
        return RigolScope(instrument)
    if "TEKTRONIX" in upper_idn:
        if (
            "DPO4034" in upper_idn
            or "MSO58" in upper_idn
            or "MSO5" in upper_idn
        ):
            return TektronixScope(instrument, idn)
        raise ValueError(f"Unsupported Tektronix model: {idn}")
    if "LECROY" in upper_idn or "TELEDYNE" in upper_idn:
        return LeCroyScope(instrument)
    raise ValueError(f"Unsupported oscilloscope manufacturer: {idn}")


def save_capture(
    image_data,
    image_format,
    save_directory,
    capture_number,
    trigger_time=None,
):
    """Save validated capture bytes with a unique, timestamped filename."""
    if image_format.lower() == "png":
        image_data = extract_png_payload(image_data)
    if trigger_time is None:
        trigger_time = datetime.datetime.now().astimezone()
    timestamp = trigger_time.strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{timestamp}_{capture_number:06d}.{image_format}"
    filepath = os.path.join(save_directory, filename)
    with open(filepath, "wb") as image_file:
        image_file.write(image_data)
    return filepath


def extract_png_payload(image_data):
    """Remove an IEEE 488.2 binary-block header and validate the PNG payload."""
    if image_data.startswith(b"#"):
        if len(image_data) < 2 or not image_data[1:2].isdigit():
            raise ValueError("Invalid PNG transfer: malformed binary-block header")
        length_digits = image_data[1] - ord("0")
        length_end = 2 + length_digits
        if length_digits == 0 or len(image_data) < length_end:
            raise ValueError("Invalid PNG transfer: incomplete binary-block header")
        length_field = image_data[2:length_end]
        if not length_field.isdigit():
            raise ValueError("Invalid PNG transfer: malformed binary-block length")
        payload_length = int(length_field)
        payload_end = length_end + payload_length
        if len(image_data) < payload_end:
            raise ValueError("Invalid PNG transfer: incomplete binary-block payload")
        image_data = image_data[length_end:payload_end]

    if not image_data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid PNG transfer: PNG signature not found")
    return image_data


def quit_requested():
    """Check for Q without blocking while the program waits for a trigger."""
    while msvcrt.kbhit():
        key = msvcrt.getwch()
        if key in ("\x00", "\xe0"):
            msvcrt.getwch()
        elif key.lower() == "q":
            return True
    return False


def wait_for_trigger(scope, timeout_seconds, next_trigger_number):
    """Wait for a trigger, Q, or the timeout; zero disables the timeout."""
    deadline = (
        None
        if timeout_seconds == 0
        else time.monotonic() + timeout_seconds
    )
    if scope.arm_settle_seconds:
        time.sleep(scope.arm_settle_seconds)
    ready_reported = False
    last_rigol_status = None
    while True:
        if quit_requested():
            return False
        if deadline is not None and time.monotonic() >= deadline:
            return None
        trigger_detected = scope.has_triggered()
        if isinstance(scope, RigolScope):
            if scope.last_status != last_rigol_status:
                print(f"Rigol status: {scope.last_status}", flush=True)
                last_rigol_status = scope.last_status
        if not ready_reported and scope.is_armed():
            print(f"Ready for trigger {next_trigger_number}.")
            ready_reported = True
        if trigger_detected:
            return True
        poll_interval = (
            RIGOL_POLL_INTERVAL_SECONDS
            if isinstance(scope, RigolScope)
            else POLL_INTERVAL_SECONDS
        )
        time.sleep(poll_interval)


def main():
    resource_manager = None
    instrument = None
    scope = None
    operation = "opening the VISA resource"
    try:
        visa_resource = get_visa_resource()
        user_path_input = input(
            f"Enter data path (Default = Desktop)   'd' for default: "
        ).strip()
        save_directory = (
            DEFAULT_SAVE_DIRECTORY
            if user_path_input.lower() == "d" or not user_path_input
            else user_path_input
        )
        trigger_timeout_seconds = get_trigger_timeout()
        os.makedirs(save_directory, exist_ok=True)

        resource_manager = pyvisa.ResourceManager("@py")
        instrument = resource_manager.open_resource(visa_resource)
        instrument.timeout = INSTRUMENT_TIMEOUT_MS
        instrument.chunk_size = 1024 * 1024
        operation = "querying scope identification"
        idn = instrument.query("*IDN?").strip()
        print(f"Connected to: {idn}")

        scope = create_scope_adapter(instrument, idn)
        operation = "configuring the scope"
        scope.configure()
        print(f"Captures will be saved to: {save_directory}")
        if trigger_timeout_seconds == 0:
            print(
                "Waiting indefinitely for triggers; "
                "press 'q' or Ctrl+C to stop."
            )
        else:
            print(
                f"Waiting up to {trigger_timeout_seconds} seconds per trigger; "
                "press 'q' or Ctrl+C to stop."
            )

        capture_number = 0
        while True:
            operation = "arming the scope"
            scope.arm()
            operation = "waiting for a trigger"
            trigger_result = wait_for_trigger(
                scope, trigger_timeout_seconds, capture_number + 1
            )
            if trigger_result is False:
                print("Stopped by user.")
                break
            if trigger_result is None:
                print(
                    f"No trigger detected within {trigger_timeout_seconds} "
                    "seconds; stopping."
                )
                break

            capture_number += 1
            trigger_time = datetime.datetime.now().astimezone()
            timestamp = trigger_time.strftime("%Y-%m-%d %H:%M:%S.%f %z")
            print(
                f"Trigger {capture_number} detected at {timestamp}.",
                flush=True,
            )
            print(f"Saving trigger {capture_number}...", flush=True)
            operation = "transferring the PNG"
            transfer_started = time.monotonic()
            image_data, image_format = scope.capture_image()
            transfer_seconds = time.monotonic() - transfer_started
            operation = "saving the PNG"
            filepath = save_capture(
                image_data,
                image_format,
                save_directory,
                capture_number,
                trigger_time,
            )
            print(
                f"Saved {filepath} "
                f"(PNG transfer {transfer_seconds:.1f} seconds)"
            )
    except KeyboardInterrupt:
        print("Stopped by user.")
    except pyvisa.errors.VisaIOError as error:
        print(f"Capture stopped while {operation}: {error}")
    except (OSError, ValueError) as error:
        print(f"Capture stopped: {error}")
    finally:
        if scope is not None and instrument is not None:
            try:
                scope.stop()
            except pyvisa.errors.VisaIOError as error:
                print(f"Could not stop scope acquisition: {error}")
        if instrument is not None:
            instrument.close()
        if resource_manager is not None:
            resource_manager.close()


if __name__ == "__main__":
    main()
