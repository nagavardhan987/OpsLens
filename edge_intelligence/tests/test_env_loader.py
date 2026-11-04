import tempfile
import unittest
from pathlib import Path

from env_loader import load_env_file


class TestEnvLoader(unittest.TestCase):
    def test_loads_local_key_value_settings_without_overriding_process_values(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "# local config\n"
                "OPSLENS_LLM_PROVIDER=groq\n"
                "GROQ_API_KEY='unit-test-secret'\n"
                'GROQ_API_ENDPOINT="https://example.test/api#fragment" # comment\n'
                "export OPSLENS_LLM_TIMEOUT=9\n"
                "INVALID KEY=ignored\n",
                encoding="utf-8",
            )
            environment = {"OPSLENS_LLM_PROVIDER": "none"}

            loaded = load_env_file(env_file, environment)

        self.assertEqual(environment["OPSLENS_LLM_PROVIDER"], "none")
        self.assertEqual(environment["GROQ_API_KEY"], "unit-test-secret")
        self.assertEqual(environment["GROQ_API_ENDPOINT"], "https://example.test/api#fragment")
        self.assertEqual(environment["OPSLENS_LLM_TIMEOUT"], "9")
        self.assertNotIn("INVALID KEY", environment)
        self.assertEqual(loaded, 3)

    def test_missing_env_file_is_a_safe_no_op(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = {}
            loaded = load_env_file(Path(directory) / "missing.env", environment)

        self.assertEqual(loaded, 0)
        self.assertEqual(environment, {})


if __name__ == "__main__":
    unittest.main()
