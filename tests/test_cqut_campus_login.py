import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import urllib.parse

import cqut_campus_login as app


class CampusLoginTests(unittest.TestCase):
    def test_double_encoding_matches_eportal_frontend(self):
        self.assertEqual(
            app.js_double_encode("A B&@移动"),
            "A%2520B%2526%2540%25E7%25A7%25BB%25E5%258A%25A8",
        )

    def test_login_body_keeps_fields_separate(self):
        body = app.build_login_body(
            "student",
            "p&ss",
            "移动",
            "wlanuserip=10.0.0.1&mac=abc",
            "0123",
            False,
        ).decode("ascii")
        self.assertIn("userId=student", body)
        self.assertIn("password=p%2526ss", body)
        self.assertIn(
            "queryString=wlanuserip%253D10.0.0.1%2526mac%253Dabc",
            body,
        )
        self.assertTrue(body.endswith("&passwordEncrypt=false"))

    def test_service_parser(self):
        payload = {
            "serviceJson": (
                '[{"serviceName":"student_mobile",'
                '"serviceShowName":"中国移动"},'
                '{"serviceName":"student_telecom",'
                '"serviceShowName":"中国电信"}]'
            )
        }
        self.assertEqual(
            app.parse_services(payload),
            [("中国移动", "student_mobile"), ("中国电信", "student_telecom")],
        )
        self.assertEqual(
            app.parse_services_text(
                "student@%%username@%%student_mobile@student_telecom"
            ),
            [
                ("student_mobile", "student_mobile"),
                ("student_telecom", "student_telecom"),
            ],
        )

    def test_query_extraction(self):
        location = (
            "http://202.202.145.132/eportal/index.jsp?"
            "wlanuserip=10.0.0.2&wlanacname=ac1&nasip=202.202.145.132"
        )
        self.assertEqual(
            app.extract_query_string(location),
            "wlanuserip=10.0.0.2&wlanacname=ac1&nasip=202.202.145.132",
        )

    def test_known_captcha_font(self):
        image = (
            "iVBORw0KGgoAAAANSUhEUgAAAFAAAAAeCAIAAAA0IQ7mAAAA7klEQVR42u2YURLDIAhEvVoP2tPl"
            "IO1vJ1bK7gKxE5z8iYGniMB43WyMBm7gBr4X8PF8fH7+JYoiTkAFnv9uKyO2ZqXI3kHo/0M0YqXs"
            "RAv5gi0MmaEC06fhscYpaQB7tAx940OAdbFqYG6W8wIlNG4EnGrGRsBRlzwFmIhb0BtjB/Y6YE+0"
            "EM//69N6WlUK/NOIcId37kIi8CqdUK6oB3h2+Drg8JgEzW4EXBPhrwfWkwp0tijxSM0ZCeD0XDq1"
            "JIDS42uAKys+ZyUYXx4SqErRB9Vn8Q0AonExv9h+34ZCA9o86iZeAzdwA//VeAMbBkaPF+/mfwAA"
            "AABJRU5ErkJggg=="
        )
        self.assertEqual(app.recognize_captcha(base64.b64decode(image)), "9160")

    def test_sso_rsa_public_key(self):
        modulus, exponent = app.parse_rsa_public_key(app.SSO_PUBLIC_KEY)
        self.assertEqual(modulus.bit_length(), 1024)
        self.assertEqual(exponent, 65537)

    def test_sso_secret_is_encoded_rsa_array(self):
        value = app.sso_secret_param("test-password")
        values = json.loads(urllib.parse.unquote(value))
        self.assertIsInstance(values, list)
        self.assertEqual(len(values), 1)
        self.assertEqual(len(base64.b64decode(values[0])), 128)

    def test_school_redirect_allow_list(self):
        self.assertTrue(app.is_trusted_school_host("sid.cqut.edu.cn"))
        self.assertTrue(app.is_trusted_school_host("uis.cqut.edu.cn"))
        self.assertTrue(app.is_trusted_school_host("202.202.145.132"))
        self.assertFalse(app.is_trusted_school_host("example.com"))
        self.assertFalse(app.is_trusted_school_host("evilcqut.edu.cn"))

    def test_settings_are_normalized_and_bounded(self):
        settings = app.normalize_settings(
            {
                "portal_candidates": "http://portal.example",
                "check_interval": 1,
                "request_timeout": 500,
                "max_captcha_attempts": "not-a-number",
                "service_keyword": "  电信  ",
            }
        )
        self.assertEqual(settings["portal_candidates"], ["http://portal.example"])
        self.assertEqual(settings["check_interval"], 20)
        self.assertEqual(settings["request_timeout"], 30)
        self.assertEqual(
            settings["max_captcha_attempts"],
            app.DEFAULT_SETTINGS["max_captcha_attempts"],
        )
        self.assertEqual(settings["service_keyword"], "电信")

    def test_redaction_replaces_longer_secrets_first(self):
        self.assertEqual(
            app.redact("abc123 abc", "abc", "abc123", ""),
            "*** ***",
        )

    def test_logger_prevents_forged_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "login.log"
            logger = app.Logger(quiet=True, path=log_path)
            logger.write("normal\n[2026-01-01 00:00:00] [ERROR] forged")
            lines = log_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertNotIn("\n", lines[0])
        self.assertIn("[ERROR] forged", lines[0])

    def test_startup_vbs_escapes_paths(self):
        content = app.build_startup_vbs(
            Path('C:/Program Files/Test "A"/pythonw.exe'),
            Path('C:/Scripts/campus "login".py'),
        )
        self.assertIn('Test ""A""', content)
        self.assertIn('campus ""login"".py', content)
        self.assertIn("shell.Run cmd, 0, False", content)

    def test_windows_launcher_uses_crlf(self):
        launcher = Path(__file__).resolve().parent.parent / "启动校园网登录.cmd"
        data = launcher.read_bytes()
        self.assertTrue(data)
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))

    def test_submitted_login_does_not_resubmit_through_sso(self):
        location = (
            "http://202.202.145.132/eportal/index.jsp?"
            "wlanuserip=10.0.0.2&wlanacname=ac1"
        )
        for edge_result in (app.EDGE_SUBMITTED, app.EDGE_NO_FORM):
            with self.subTest(edge_result=edge_result):
                with (
                    mock.patch.object(app.os, "name", "nt"),
                    mock.patch.object(app, "check_online", return_value=(False, "")),
                    mock.patch.object(
                        app,
                        "find_portal_location",
                        return_value=(location, "wlanuserip=10.0.0.2"),
                    ),
                    mock.patch.object(
                        app, "edge_sso_login", return_value=edge_result
                    ),
                    mock.patch.object(app, "wait_for_online", return_value=False),
                    mock.patch.object(app, "sso_login") as sso,
                ):
                    with self.assertRaises(app.PendingReleaseError):
                        app.login_once(
                            mock.Mock(),
                            app.DEFAULT_SETTINGS,
                            "student",
                            "password",
                            mock.Mock(),
                            interactive=False,
                        )
                sso.assert_not_called()

    def test_credentials_refuse_plaintext_storage_off_windows(self):
        with mock.patch.object(app.os, "name", "posix"):
            with self.assertRaisesRegex(app.LoginError, "DPAPI"):
                app.save_credentials("student", "password")

    def test_edge_helper_gets_password_only_through_stdin(self):
        completed = mock.Mock(
            stdout=b'{"ok":true,"stage":"success","url":"https://uis.cqut.edu.cn/"}\n',
            stderr=b"",
        )
        with tempfile.TemporaryDirectory() as directory:
            logger = app.Logger(quiet=True, path=Path(directory) / "login.log")
            with (
                mock.patch.object(app.shutil, "which", return_value="node"),
                mock.patch.object(app.subprocess, "run", return_value=completed) as run,
                mock.patch.dict(
                    app.os.environ,
                    {"CQUT_USERNAME": "student", "CQUT_PASSWORD": "secret"},
                ),
            ):
                self.assertEqual(
                    app.edge_sso_login(
                        "https://uis.cqut.edu.cn/login",
                        "student",
                        "secret",
                        logger,
                    ),
                    app.EDGE_SUCCESS,
                )
        arguments = run.call_args.args[0]
        options = run.call_args.kwargs
        self.assertNotIn("secret", arguments)
        self.assertIn('"password": "secret"', options["input"].decode("utf-8"))
        self.assertIn('"serviceKeyword": "移动"', options["input"].decode("utf-8"))
        self.assertNotIn("CQUT_PASSWORD", options["env"])
        self.assertNotIn("CQUT_USERNAME", options["env"])


if __name__ == "__main__":
    unittest.main()
