import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

import backup


class FrappeModeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.bench_dir = self.root / "frappe-bench"
        self.bench_dir.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_config(self, frappe_config):
        config_path = self.root / "config.yaml"
        config = {
            "name": "frappe-test",
            "frappe": frappe_config,
            "backup": {
                "temp_dir": str(self.root / "work"),
                "local_dir": str(self.root / "local"),
                "max_archives": 2,
            },
            "logging": {
                "dir": str(self.root / "logs"),
                "max_log_files": 2,
            },
        }
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        return str(config_path)

    def test_enabled_mode_runs_bench_and_skips_generic_collectors(self):
        config_path = self.write_config(
            {
                "enabled": True,
                "bench_dir": str(self.bench_dir),
                "site": "erp.testpro.io",
            }
        )
        local_archive = self.root / "local.tar.gz"
        local_archive.write_bytes(b"test backup archive")

        with (
            patch("subprocess.run") as bench_run,
            patch.object(backup, "setup_logging"),
            patch.object(backup.paths_mod, "stage_sources") as stage_sources,
            patch.object(backup.db_mod, "dump_database") as dump_database,
            patch.object(backup, "make_archive", return_value=str(self.root / "archive.tar.gz")),
            patch.object(backup, "save_to_local", return_value=str(local_archive)),
            patch.object(backup, "rotate_logs"),
            patch.object(backup, "rotate_local"),
        ):
            result = backup.run_backup(config_path, dry_run=False, verbose=False)

        self.assertEqual(result, 0)
        stage_sources.assert_not_called()
        dump_database.assert_not_called()
        bench_run.assert_called_once()

        command = bench_run.call_args.args[0]
        self.assertEqual(
            command[:6],
            ["bench", "--site", "erp.testpro.io", "backup", "--with-files", "--compress"],
        )
        self.assertEqual(command[6], "--backup-path")
        self.assertEqual(Path(command[7]).name, "frappe")
        self.assertEqual(bench_run.call_args.kwargs["cwd"], str(self.bench_dir))
        self.assertTrue(bench_run.call_args.kwargs["check"])

    def test_enabled_mode_requires_site(self):
        config_path = self.write_config(
            {
                "enabled": True,
                "bench_dir": str(self.bench_dir),
            }
        )

        with (
            patch("subprocess.run") as bench_run,
            patch.object(backup, "setup_logging"),
            patch.object(backup, "make_archive", return_value=str(self.root / "archive.tar.gz")),
            patch.object(backup, "save_to_local", return_value=str(self.root / "local.tar.gz")),
            patch.object(backup, "rotate_logs"),
            patch.object(backup, "rotate_local"),
            patch.object(backup, "send_alerts"),
            patch.object(backup.logger, "exception"),
        ):
            result = backup.run_backup(config_path, dry_run=False, verbose=False)

        self.assertEqual(result, 1)
        bench_run.assert_not_called()

    def test_enabled_mode_requires_bench_directory(self):
        config_path = self.write_config(
            {
                "enabled": True,
                "site": "erp.testpro.io",
            }
        )

        with (
            patch("subprocess.run") as bench_run,
            patch.object(backup, "setup_logging"),
            patch.object(backup, "make_archive", return_value=str(self.root / "archive.tar.gz")),
            patch.object(backup, "save_to_local", return_value=str(self.root / "local.tar.gz")),
            patch.object(backup, "rotate_logs"),
            patch.object(backup, "rotate_local"),
            patch.object(backup, "send_alerts"),
            patch.object(backup.logger, "exception"),
        ):
            result = backup.run_backup(config_path, dry_run=False, verbose=False)

        self.assertEqual(result, 1)
        bench_run.assert_not_called()

    def test_enabled_mode_dry_run_does_not_invoke_bench(self):
        config_path = self.write_config(
            {
                "enabled": True,
                "bench_dir": str(self.bench_dir),
                "site": "erp.testpro.io",
            }
        )

        with (
            patch("subprocess.run") as bench_run,
            patch.object(backup, "setup_logging"),
            patch.object(backup.paths_mod, "stage_sources") as stage_sources,
            patch.object(backup.db_mod, "dump_database") as dump_database,
            patch.object(backup, "make_archive", return_value=str(self.root / "archive.tar.gz")),
            patch.object(backup, "save_to_local", return_value=str(self.root / "local.tar.gz")),
            patch.object(backup, "rotate_logs"),
            patch.object(backup, "rotate_local"),
        ):
            result = backup.run_backup(config_path, dry_run=True, verbose=False)

        self.assertEqual(result, 0)
        bench_run.assert_not_called()
        stage_sources.assert_not_called()
        dump_database.assert_not_called()


if __name__ == "__main__":
    unittest.main()
