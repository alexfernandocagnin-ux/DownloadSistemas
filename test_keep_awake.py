import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import MagicMock, patch

from scripts import keep_awake


class KeepAwakeTests(unittest.TestCase):
    def frame(self, ready=False, asleep=False, error=False):
        frame = MagicMock()
        frame.locator.return_value.first.is_visible.return_value = error
        frame.get_by_role.side_effect = lambda role, **kwargs: (
            self.heading(ready) if role == "heading" else self.button(asleep)
        )
        return frame

    def heading(self, visible):
        locator = MagicMock()
        locator.is_visible.return_value = visible
        return locator

    def button(self, visible):
        locator = MagicMock()
        locator.first.is_visible.return_value = visible
        return locator

    def test_ready_in_main_page_or_iframe(self):
        for frames in ([self.frame(ready=True)], [self.frame(), self.frame(ready=True)]):
            page = MagicMock(frames=frames)
            self.assertEqual(keep_awake.inspect_frames(page), (True, None))

    def test_sleep_button_detected_in_iframe(self):
        page = MagicMock(frames=[self.frame(), self.frame(asleep=True)])
        ready, button = keep_awake.inspect_frames(page)
        self.assertFalse(ready)
        self.assertIsNotNone(button)

    def test_wakes_and_waits_for_portal(self):
        page, button = MagicMock(), MagicMock()
        with patch.object(keep_awake, "inspect_frames", side_effect=[(False, button), (True, None)]):
            keep_awake.wake_portal(page, keep_awake.DEFAULT_URL)
        button.click.assert_called_once_with(timeout=30_000)
        page.wait_for_timeout.assert_called_once_with(1_000)

    def test_loading_timeout_is_failure(self):
        with self.assertRaises(TimeoutError):
            keep_awake.wake_portal(MagicMock(), keep_awake.DEFAULT_URL, timeout=-1)

    def test_streamlit_exception_is_failure(self):
        with self.assertRaises(RuntimeError):
            keep_awake.inspect_frames(MagicMock(frames=[self.frame(error=True)]))

    def test_invalid_url_is_failure(self):
        with patch.dict("os.environ", {"DOWNLOAD_APP_URL": "not-a-url"}), redirect_stdout(StringIO()):
            self.assertEqual(keep_awake.main(), 1)


if __name__ == "__main__":
    unittest.main()
