#!/usr/bin/env python3
"""Self-tests for the platform prompt-contract validator.

Uses the standard library only so the all-checks gate does not create pytest
cache files or depend on a third-party test runner.
"""
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools" / "validate_video_prompt.py"


def run_validator(platform, prompt, mode=None):
    args = [sys.executable, str(VALIDATOR), "--platform", platform, "--prompt", prompt, "--json"]
    if mode:
        args += ["--mode", mode]
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


class PromptContractTests(unittest.TestCase):
    def payload(self, result):
        return json.loads(result.stdout)

    def test_h3_base_valid_prompt_passes(self):
        prompt = """integrated_multimodal_description: [Shot 1] Live-action medium shot. (S1) says <d>知道了，妈。</d> The daughter lowers her eyes and keeps the pen still.
overall_soundscape: Quiet hospital room tone and a faint monitor beep.
non_diegetic_music: N/A"""
        result = run_validator("h3", prompt, "i2va")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(self.payload(result)["valid"])

    def test_h3_ref2va_dialogue_probe_passes(self):
        prompt = """subject_definitions:
<Subject 1> is a daughter.
<Picture 1> is the target frame.
summary:
[reference generation + audio reference] A daughter answers her mother.
retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved — preserve identity.
detailed_description:
[Shot 1] Medium shot. (S1) says <d>知道了，妈。</d> The mother remains silent.
overall_soundscape:
Quiet hospital room tone and a faint monitor beep.
non_diegetic_music:
N/A"""
        result = run_validator("h3", prompt, "ref2va")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(self.payload(result)["valid"])

    def test_h3_rejects_missing_fixed_fields(self):
        result = run_validator("h3", "A girl answers softly: 知道了，妈。", "i2va")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("integrated_multimodal_description", " ".join(self.payload(result)["errors"]))

    def test_h3_rejects_dialogue_in_overall_soundscape(self):
        prompt = """integrated_multimodal_description: [Shot 1] A daughter looks down.
overall_soundscape: The daughter's voice says 知道了，妈。
non_diegetic_music: N/A"""
        result = run_validator("h3", prompt, "i2va")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any("overall_soundscape" in error for error in self.payload(result)["errors"]))

    def test_h3_rejects_custom_section_names(self):
        prompt = """Scene: Medium shot.
Speaker and Dialogue: Speaker 1 says <d>知道了，妈。</d>.
Diegetic Sound: Room tone.
Overall Soundscape: Quiet room.
Non-Diegetic Music: N/A.
Audio Restrictions: No random voices."""
        result = run_validator("h3", prompt, "i2va")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any("integrated_multimodal_description" in error for error in self.payload(result)["errors"]))

    def test_natural_language_platform_rejects_h3_dsl_but_accepts_natural_prompt(self):
        bad = run_validator("runway", "integrated_multimodal_description: [Shot 1] A woman walks forward.")
        self.assertNotEqual(bad.returncode, 0)
        good = run_validator("runway", "A woman walks forward while the camera slowly pushes in; the room light flickers once.")
        self.assertEqual(good.returncode, 0, good.stderr + good.stdout)

    def test_seedance_rejects_fake_negative_field(self):
        result = run_validator("seedance", "主体：一名女孩。NEGATIVE: blurry, text.")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any("NEGATIVE" in error for error in self.payload(result)["errors"]))

    def test_sora_is_removed_from_production_route(self):
        result = run_validator("sora", "A woman looks at the camera.")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any("移除" in error or "removed" in error.lower() for error in self.payload(result)["errors"]))

    def test_project_h3_driver_rejects_invalid_ref2va_before_queueing(self):
        # 早期这条例约挂在具体项目的私有驱动（`00-视频项目/…/tools/gen_h3.py`）上验证。
        # 该项目已归档清理，而闸门硬依赖项目文件正是「体系被具体项目反向绑定」的形态。
        # 现改为直接验证体系自身的 validator：契约不变，依赖清零。
        spec = importlib.util.spec_from_file_location("system_validator", VALIDATOR)
        module = importlib.util.module_from_spec(spec)
        self.assertIsNotNone(spec.loader)
        spec.loader.exec_module(module)
        bad_prompt = """subject_definitions:
<Subject 1> is a daughter.
summary:
A dialogue shot.
retention_analysis:
<Subject 1> fully_preserved.
detailed_description:
The daughter is speaking the Chinese line 知道了，妈。
overall_soundscape:
The daughter's voice speaking the Chinese line 知道了，妈。
non_diegetic_music:
N/A"""
        result = module.validate_prompt("h3", bad_prompt, "ref2va")
        self.assertFalse(result["valid"],
                         "ref2va 下把台词写进 overall_soundscape 应当被拒")
        self.assertTrue(any("overall_soundscape" in e or "<d>" in e
                            for e in result["errors"]))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PromptContractTests)
    raise SystemExit(0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1)
