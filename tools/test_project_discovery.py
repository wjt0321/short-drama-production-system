"""项目容器发现回归测试；仅使用临时目录，不生成实际项目。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import check_shot_duration_variance as checker


class ProjectDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch = patch.object(checker, "__file__", str(self.root / "tools" / "check.py"))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def project(self, relative):
        p = self.root / relative
        (p / "03-分镜").mkdir(parents=True)
        (p / "03-分镜" / "分镜表.md").write_text("# 测试分镜", encoding="utf-8")
        return str(p)

    def test_projects_in_container_are_discovered(self):
        a = self.project("00-视频项目/《测试片》")
        b = self.project("00-视频项目/未定名小样")
        self.assertEqual(set(checker.discover_projects()), {a, b})

    def test_legacy_projects_remain_visible_but_templates_do_not(self):
        p = self.project("《旧片》项目")
        self.project("模板/短剧项目模板")
        self.project("普通资料")
        self.assertEqual(checker.discover_projects(), [p])

    def test_empty_container_and_incomplete_project_are_not_audited(self):
        (self.root / "00-视频项目" / "《待立项》").mkdir(parents=True)
        self.assertEqual(checker.discover_projects(), [])


if __name__ == "__main__":
    unittest.main()
