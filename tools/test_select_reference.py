#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""select_reference 的闸测试：路由、参数透传、缺资源错误、check。

用临时夹具 + 子进程，不扫描大库做每一项（仅 check 的"正常"用例读真实库，约 1s）。
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "select_reference.py")
ROOT = os.path.abspath(os.path.join(HERE, ".."))
EXTERNAL_LIB = os.path.join(ROOT, "外部参考库", "提示词库")


def run_cli(args, env_extra=None):
    env = dict(os.environ)
    env.pop("AI_SEEK_ROOT", None)
    env.pop("AI_SEEK_RAWLIB", None)
    env.pop("AI_SEEK_HARVEST", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, TOOL] + args,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          cwd=ROOT, env=env, timeout=120)


def make_fixture(tmp):
    """构造最小 seek 数据源夹具：1 条记录 2 个 item，1 张本地封面。"""
    lib = os.path.join(tmp, "05_工作流与Skills", "liblib提示词库")
    covers = os.path.join(lib, "封面")
    harvest = os.path.join(tmp, "05_工作流与Skills", "harvest")
    os.makedirs(covers)
    os.makedirs(harvest)
    with open(os.path.join(harvest, "selfcheck_portable.py"), "w", encoding="utf-8") as f:
        f.write("# marker\n")
    cover_url = "https://example.test/a.png"
    rec = {
        "name": "中文水墨国风", "uuid": "u1",
        "url": "https://www.liblib.art/modelinfo/u1",
        "keyword": "国风", "tags": ["水墨"], "likeCount": 10, "modelTypeName": "LORA",
        "items": [
            {"prompt": "国风水墨,山水", "negativePrompt": "lowres",
             "samplingStep": 30, "cfgScale": 4.0, "seed": -1, "cover": cover_url},
            {"prompt": "江南书生夜雨图", "negativePrompt": "",
             "samplingStep": 20, "cfgScale": 7.0, "seed": 1, "cover": ""},
        ],
    }
    with open(os.path.join(lib, "prompts.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    video_dir = os.path.join(tmp, "02_视觉素材", "视频", "fixture")
    os.makedirs(video_dir)
    with open(os.path.join(video_dir, "_清单.json"), "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False)
    key = hashlib.md5(cover_url.encode()).hexdigest()[:12] + ".png"
    with open(os.path.join(covers, key), "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")  # 只需存在，不校验内容
    return {"AI_SEEK_RAWLIB": lib, "AI_SEEK_HARVEST": harvest,
            "AI_SEEK_ROOT": tmp}


class RoutingTests(unittest.TestCase):
    """用夹具实跑子进程，验证路由 + 参数透传 + JSON 输出结构。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = make_fixture(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_prompt_routes_to_auto_select(self):
        p = run_cli(["prompt", "江南", "--top", "1", "--format", "json"], self.env)
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout)
        card = data[0]["cards"][0]
        self.assertEqual(card["name"], "中文水墨国风")
        self.assertTrue(card["prompt"])
        self.assertEqual(card["negativePrompt"], "")
        self.assertEqual(card["samplingStep"], 20)
        self.assertEqual(card["cfgScale"], 7.0)
        self.assertEqual(card["seed"], 1)
        self.assertEqual(card["source_url"], "https://www.liblib.art/modelinfo/u1")

    def test_prompt_cover_mapping_uses_download_script_algorithm(self):
        p = run_cli(["prompt", "山水", "--format", "json"], self.env)
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout)
        # 封面 URL md5[:12] + .png —— 与 liblib_download_covers.py 命名算法一致
        expect = hashlib.md5("https://example.test/a.png".encode()
                             ).hexdigest()[:12] + ".png"
        hits = [c for d in data for c in d["cards"] if c.get("cover_path")]
        self.assertTrue(hits, "应至少一张卡片带本地封面")
        self.assertTrue(hits[0]["cover_path"].replace("\\", "/").endswith(expect))

    def test_prompt_filters_pass_through(self):
        # --type 限定不存在的类型 → 无命中，底层脚本退出 1（参数确实透传并被使用）
        p = run_cli(["prompt", "江南", "--type", "Checkpoint"], self.env)
        self.assertEqual(p.returncode, 1)
        self.assertIn("没命中", p.stderr)

    def test_prompt_no_hit_clearly_missing(self):
        p = run_cli(["prompt", "完全不存在的题材词xyz"], self.env)
        self.assertEqual(p.returncode, 1)
        self.assertIn("没命中", p.stderr)

    def test_missing_query_is_usage_error(self):
        p = run_cli(["prompt"])
        self.assertEqual(p.returncode, 2)


class StyleCommandTests(unittest.TestCase):
    def test_style_requires_explicit_external_fixture(self):
        p = run_cli(["style", "国风", "--top", "2", "--format", "json"])
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("AI_SEEK_ROOT", p.stderr)

    def test_style_uses_explicit_external_fixture(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = make_fixture(tmp.name)
        p = run_cli(["style", "国风", "--top", "2", "--format", "json"], env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout), [])


class CheckCommandTests(unittest.TestCase):
    def test_check_ok_on_fixture(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = make_fixture(tmp.name)
        p = run_cli(["check"], env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertIn("记录数 1", p.stdout)
        self.assertIn("item 提示词数 2", p.stdout)
        self.assertIn("本地封面数 1", p.stdout)

    def test_check_missing_resources_fails(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # 夹具库存在但 prompts.jsonl 为空（0 记录）→ check 必须失败退出 1
        lib = os.path.join(tmp.name, "05_工作流与Skills", "liblib提示词库")
        os.makedirs(os.path.join(lib, "封面"))
        open(os.path.join(lib, "prompts.jsonl"), "w", encoding="utf-8").close()
        harvest = os.path.join(tmp.name, "05_工作流与Skills", "harvest")
        os.makedirs(harvest)
        with open(os.path.join(harvest, "selfcheck_portable.py"), "w", encoding="utf-8") as f:
            f.write("#\n")
        p = run_cli(["check"], {"AI_SEEK_RAWLIB": lib, "AI_SEEK_HARVEST": harvest})
        self.assertEqual(p.returncode, 1)
        self.assertIn("无记录", p.stderr)


if __name__ == "__main__":
    if not os.path.isdir(EXTERNAL_LIB):
        print("外部参考库未随包提供，参考查询入口测试不适用（N/A）。")
        raise SystemExit(0)
    unittest.main()
