"""Unit tests for app.py"""
import unittest
import mock
import app


class AppTest(unittest.TestCase):
    """unittest.TestCase class"""

    def setUp(self) -> None:
        """set up unittests"""
        app._CLEANUP_TIME = 0

    def test_unique_domains_success(self):
        """Ensure domain suffixes are unique."""
        test_prefixes = ["TEST_PREFIX_", "TEST_PREFIX2_"]
        test_domains = [
            "TEST_PREFIX_DOMAINSUFFIX1",
            "TEST_PREFIX_DOMAINSUFFIX2",
            "TEST_PREFIX2_DOMAINSUFFIX3",
        ]
        self.assertTrue(
            app.check_all_domains_unique(test_domains, test_prefixes),
            "unique domains are not detected unique",
        )

    def test_unique_domains_fail(self):
        """Ensure domain suffixes are not unique."""
        test_prefixes = ["TEST_PREFIX_", "TEST_PREFIX2_"]
        test_domains = [
            "TEST_PREFIX_DOMAINSUFFIX1",
            "TEST_PREFIX_DOMAINSUFFIX2",
            "TEST_PREFIX2_DOMAINSUFFIX1",
        ]
        self.assertFalse(
            app.check_all_domains_unique(test_domains, test_prefixes),
            "non-unique domains are detected as unique",
        )

    def test_unique_domains_not_list(self):
        """Ensure domain prefixes are a list."""
        test_prefixes = "TEST_PREFIX_, TEST_PREFIX2_"
        test_domains = [
            "TEST_PREFIX_DOMAINSUFFIX1",
            "TEST_PREFIX_DOMAINSUFFIX2",
            "TEST_PREFIX2_DOMAINSUFFIX1",
        ]
        with self.assertRaises(TypeError):
            app.check_all_domains_unique(test_domains, test_prefixes)

    @mock.patch.object(app.config, "load_config")
    @mock.patch.object(app.mqtt, "connect", autospec=True)
    def test_main_success(self, connect_mock, config_mock):
        """Ensure we can execute main."""
        connect_mock.return_value = None
        test_prefixes = ["TEST_PREFIX_", "TEST_PREFIX2_"]
        config_mock.return_value = dict(
            domains=[f"{test_prefixes[1]}domain.one"], domain_prefixes=test_prefixes
        )
        with mock.patch("app.flush_workers", return_value=None):
            app.main()
            connect_mock.assert_called_with()

    @mock.patch.object(app.config, "load_config")
    @mock.patch.object(app.mqtt, "connect", autospec=True)
    def test_main_fails_no_domain(self, connect_mock, config_mock):
        """Ensure we fail when domains are not configured."""
        config_mock.return_value = dict(domains=None)
        connect_mock.return_value = None
        with self.assertRaises(app.DomainsNotInConfig):
            app.main()

    @mock.patch.object(app.config, "load_config")
    @mock.patch.object(app.mqtt, "connect", autospec=True)
    def test_main_fails_bad_domain(self, connect_mock, config_mock):
        """Ensure we fail when domains are badly formatted."""
        test_prefixes = ["TEST_PREFIX_", "TEST_PREFIX2_"]
        config_mock.return_value = dict(
            domains=[f"cant_split_domain"], domain_prefixes=test_prefixes
        )
        connect_mock.return_value = None
        with mock.patch("app.flush_workers", return_value=None):
            app.main()
            connect_mock.assert_called_with()

    @mock.patch("time.sleep", side_effect=InterruptedError)
    @mock.patch("app.wg_flush_stale_peers")
    def test_flush_workers(self, flush_mock, sleep_mock):
        """Ensure we fail when domains are badly formatted."""
        flush_mock.return_value = ""
        # Infinite loop in flush_workers has no exit value, so test will generate one, and test for that.
        with self.assertRaises(InterruptedError):
            app.flush_workers("test_domain")


if __name__ == "__main__":
    unittest.main()
