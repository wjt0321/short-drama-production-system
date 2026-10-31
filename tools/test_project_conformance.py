#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""项目合规闸测试 —— 五类场景覆盖。

覆盖矩阵（与 `_make_project` 中的 layout 一一对应）：

  | 场景          | 期望 fail 关键项         | 期望 warn/Info 关键项            | 阻断？ |
  |---------------|--------------------------|-----------------------------------|--------|
  | 失败片式       | DUR-01 / ROUTE-01        | KNIFE-01 / PROMPT-CT / PROMPT-SS  | 是    |
  | 纯模板         | —                        | TPL-01 / SEG-01 / PROMPT-01       | 否    |
  | 合规           | —                        | 可有 INFO                          | 否    |
  | 归档失败       | 全部转 INFO              | STATE-ARCH（保留失败特征）         | 否    |
  | 旁路目录       | —                        | DIR-01 / PROMPT-02 / SEG-01        | 否    |
  | 运动合同缺失   | —                        | MOTION-CT/WHL/CC/FF（4 项启发式） | 否    |

**为什么需要这层测试**：
`--selftest` 是闸的内置反例，跑过即过。
但 `unittest` 的覆盖矩阵更细：
  · 每类构造独立临时项目，断言「该有的 FAIL/WARN 必须有、必须无」
  · 闸里误删一行不会触发 `--selftest` 失败，但测试矩阵会立刻报

**属性命名说明**：
本测试不使用 `self.fail` / `self.warn` / `self.info`，
因为它们会影子掉 `unittest.TestCase.fail()`，
导致内部失败上报路径崩溃（'list' object is not callable）。
统一使用 `self.fails` / `self.warns` / `self.infos`。
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_project_conformance as c


def _analyse(layout_name):
    """构造一个临时项目并跑闸，返回 5 元组。"""
    td = tempfile.mkdtemp(prefix="proj_{}_".format(layout_name))
    p = c._make_project(os.path.join(td, layout_name), layout_name)
    fails, warns, infos, archived, arch_info = c.analyse(p)
    return td, p, fails, warns, infos, archived, arch_info


class _ProjectFixture(unittest.TestCase):
    """公共 setUp/tearDown，避免每个测试类重复。"""

    layout = None  # 子类覆盖

    def setUp(self):
        (self.td, self.p,
         self.fails, self.warns, self.infos,
         self.archived, self.arch_info) = _analyse(self.layout)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def _codes(self, *lists):
        out = set()
        for lst in lists:
            for code, _ in lst:
                out.add(code)
        return out


class TestFailedFilmStyle(_ProjectFixture):
    """失败片式：时长窄带、静帧为主、刀型未知、合同式反模式。"""

    layout = "failed_film"

    def test_is_active(self):
        """失败片式不应被识别为归档失败（它根本没归档）。"""
        self.assertFalse(self.archived)

    def test_route_distribution_is_failure(self):
        """静帧 + 数字轻推 ≥ 50% 应报 ROUTE-01。"""
        self.assertIn("ROUTE-01", self._codes(self.fails))

    def test_duration_narrow_band_is_failure(self):
        """时长集中在 4-6s 窄带 ≥ 70% 应报 DUR-01。"""
        self.assertIn("DUR-01", self._codes(self.fails))

    def test_knife_unknown_value_is_warn(self):
        """刀型含「中刀」白名单外值应报 KNIFE-01 (WARN)。"""
        self.assertIn("KNIFE-01", self._codes(self.warns))

    def test_prompt_contract_is_warn(self):
        """提示词堆叠 No/never 应报 PROMPT-CT。"""
        self.assertIn("PROMPT-CT", self._codes(self.warns))

    def test_state_kpi_is_failure(self):
        """声明 G6 通过但缺关键交付件应报 STATE-02。"""
        self.assertIn("STATE-02", self._codes(self.fails))

    def test_overall_exit_code_would_be_1(self):
        """活跃项目有 FAIL → 退出码 1。"""
        self.assertTrue(self.fails)


class TestPureTemplate(_ProjectFixture):
    """纯模板：所有关键字段空白。"""

    layout = "pure_template"

    def test_is_active(self):
        self.assertFalse(self.archived)

    def test_no_blocking_failure(self):
        """纯模板不应有 FAIL（只是空白，不是错误）。"""
        self.assertEqual(self.fails, [],
                         "纯模板不应产生 FAIL 项，实际：{}".format(self.fails))

    def test_empty_decision_table_is_warn_or_info(self):
        """已通过决策表为空 → TPL-01 (WARN/INFO)。"""
        self.assertIn("TPL-01", self._codes(self.warns, self.infos))

    def test_missing_execution_fields_is_warn_or_info(self):
        """缺摄影执行字段 → SEG-01。"""
        self.assertIn("SEG-01", self._codes(self.warns, self.infos))


class TestConformant(_ProjectFixture):
    """合规样例：刀型白名单、长短刀、时长宽窄搭配、提示词有摄影机路径。"""

    layout = "conformant"

    def test_is_active(self):
        self.assertFalse(self.archived)

    def test_no_failure(self):
        self.assertEqual(self.fails, [],
                         "合规样例不应有 FAIL，实际：{}".format(self.fails))

    def test_no_knife_warn(self):
        """合规样例不应有 KNIFE-01 告警。"""
        self.assertNotIn("KNIFE-01", self._codes(self.warns))

    def test_no_contract_warn(self):
        """合规样例不应有 PROMPT-CT 告警。"""
        self.assertNotIn("PROMPT-CT", self._codes(self.warns))


class TestArchivedFailure(_ProjectFixture):
    """归档失败项目：不阻断，但保留失败特征。"""

    layout = "archived_failure"

    def test_recognized_as_archived(self):
        """项目状态摘要含「失败裁决」+「归档」字样应被识别为归档失败。"""
        self.assertTrue(self.archived)

    def test_failure_info_retained(self):
        """归档路径与失败类型应被解析出来。"""
        self.assertIsNotNone(self.arch_info)
        self.assertIn("PPT", self.arch_info.get("类型", ""))
        self.assertIn("v01", self.arch_info.get("归档路径", ""))

    def test_no_blocking_failure_even_if_disk_inconsistent(self):
        """归档失败项目即使磁盘与状态不一致，也不应 FAIL。"""
        # archived_failure 故意不写分镜表/提示词（模拟「失败归档后停止依赖」），
        # 这些缺口在活跃项目会 STATE-02 / STATE-03 FAIL，
        # 但归档项目应被允许并降级为 INFO。
        self.assertEqual(self.fails, [],
                         "归档失败项目不应被 FAIL：{}".format(self.fails))

    def test_no_warn_only_info(self):
        """归档失败项目的不一致应只出现在 INFO，不应阻塞 WARN。"""
        self.assertEqual(self.warns, [],
                         "归档失败项目不应有 WARN：{}".format(self.warns))


class TestBypassDir(_ProjectFixture):
    """旁路目录：提示词写在非 04-镜头/ 标准目录。"""

    layout = "bypass_dir"

    def test_is_active(self):
        self.assertFalse(self.archived)

    def test_bypass_dir_detected(self):
        """H3_提示词/ 这种非标准目录应被识别为旁路。"""
        self.assertIn("DIR-01", self._codes(self.warns, self.infos))

    def test_prompt_out_of_std_detected(self):
        """提示词在 04-镜头/ 之外应被识别为可发现性风险。"""
        self.assertIn("PROMPT-02", self._codes(self.warns, self.infos))


class TestMotionContractGap(_ProjectFixture):
    """演员调度 / 运动学合同缺失：含交互动作但缺 §一.9 9 项。

    来源：
          `04-视频生成/平台提示词契约.md` §一.9。
    一次 S03 A/B 实证：状态差 / 摄影机路径 / 接力是必要条件，
    但仅靠它们镜头仍会失败——必须补 §一.9 9 项。
    """

    layout = "motion_gap"

    def test_is_active(self):
        self.assertFalse(self.archived)

    def test_no_blocking_failure(self):
        """MOTION-* 是 WARN，不阻断交付。"""
        self.assertEqual(self.fails, [],
                         "运动合同缺失是 WARN 级，不应阻断：{}".format(self.fails))

    def test_motion_ct_core_fields_missing(self):
        """核心运动合同字段（屏幕坐标 / 朝向 / 脚步 / 接触）≥3 缺失 → MOTION-CT。"""
        self.assertIn("MOTION-CT", self._codes(self.warns))

    def test_motion_whl_wheel_coupling_missing(self):
        """含 cart / 推车但缺车轮耦合 → MOTION-WHL。"""
        self.assertIn("MOTION-WHL", self._codes(self.warns))

    def test_motion_cc_contact_missing(self):
        """含 grip / 接触动词但缺接触点 → MOTION-CC。"""
        self.assertIn("MOTION-CC", self._codes(self.warns))

    def test_motion_ff_negative_contract(self):
        """堆叠 no / doesn't + 缺正向机械 → MOTION-FF。"""
        self.assertIn("MOTION-FF", self._codes(self.warns))


if __name__ == "__main__":
    unittest.main(verbosity=2)
