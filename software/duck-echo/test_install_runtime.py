"""Packaging contracts needed by the continuous microphone upgrade."""
from pathlib import Path
import unittest

import install


class RuntimePackagingTests(unittest.TestCase):
    def test_continuous_controller_is_in_install_and_rollback_manifest(self):
        self.assertIn('continuous_audio.py', install.RUNTIME_FILES)

    def test_service_can_select_toggle_or_hold_from_preserved_defaults(self):
        unit = (Path(install.__file__).parent / 'duck-echo.service').read_text()
        self.assertIn('Environment=ECHO_TRIGGER_MODE=toggle', unit)
        self.assertIn('--trigger-mode ${ECHO_TRIGGER_MODE}', unit)
        self.assertLess(unit.index('Environment=ECHO_TRIGGER_MODE=toggle'),
                        unit.index('EnvironmentFile=-/etc/default/duck-echo'))

    def test_music_runtime_is_installed_and_socket_directory_is_private(self):
        self.assertTrue({'music_feel.py', 'music_interaction.py', 'audio_control.py'} <= set(install.RUNTIME_FILES))
        unit = (Path(install.__file__).parent / 'duck-echo.service').read_text()
        self.assertIn('RuntimeDirectory=duck-echo', unit)
        self.assertIn('RuntimeDirectoryMode=0700', unit)
        self.assertIn('--control-socket /run/duck-echo/control.sock', unit)

    def test_service_default_is_native_duck_and_explicit_echo_is_configurable(self):
        unit = (Path(install.__file__).parent / 'duck-echo.service').read_text()
        self.assertIn('Environment=ECHO_REPLY_MODE=duck', unit)
        self.assertIn('--reply-mode ${ECHO_REPLY_MODE}', unit)


if __name__ == '__main__':
    unittest.main()
