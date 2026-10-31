#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真片闸豁免登记读取（tools/_film_gate_waivers.yaml）。

豁免语义（2026-10-18 校准：注释只承诺代码真做得到的）：
- 命中 (project, gate) 的项目在对应闸的无参全扫输出里打印 WAIVED，不计入失败；
- `until` 过期的豁免自动失效：不豁免，且 load 时返回中文报错（各闸逐条打印），
  防止豁免变成永久；
- 只豁免 2026-10-12 SOP 改造前立项的旧项目：条目必须带 `立项日`（YYYY-MM-DD），
  缺该字段或 `立项日 >= 2026-10-12` 时该条目**不生效**并返回报错——旧版注释承诺了
  这条规则而代码没实现，等于任何新项目都能写进豁免表；
- 豁免只影响无参全扫模式，单项目定点扫描照常真实报告；
- 汇总口径（tally_line）：通过 / WAIVED / 未评估 三个数必须分开打印，
  只要 WAIVED 或 未评估 非零就不许出现「全部合格」「无阻断项」——
  豁免是「已知不合格但不追」，不是通过。
"""
import datetime
import os

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
WAIVERS_PATH = os.path.join(HERE, "_film_gate_waivers.yaml")

# 豁免只对「2026-10-12 SOP 改造前立项」的旧项目开放（与 AGENTS.md 改造日同源）
SOP_CUTOVER = datetime.date(2026, 10, 12)


def tally_line(n_pass, n_waived, n_unevaluated, n_fail=0):
    """统一汇总行：通过 / WAIVED / 未评估（D4）。"""
    tail = " / 失败 {}".format(n_fail) if n_fail else ""
    return "汇总：通过 {} / WAIVED {} / 未评估 {}{}".format(
        n_pass, n_waived, n_unevaluated, tail)


def is_all_green(n_waived, n_unevaluated, n_fail=0):
    """三数全零才允许说「全部合格」——豁免与跳过不是通过。"""
    return n_waived == 0 and n_unevaluated == 0 and n_fail == 0


def load_waivers(today=None):
    """返回 (waivers, errors)。

    waivers: {(project, gate): entry_dict}，仅含未过期项；
    errors:  字符串列表（过期豁免的报错等）。登记文件不存在时返回 ({}, [])。
    """
    if today is None:
        today = datetime.date.today()
    if not os.path.isfile(WAIVERS_PATH):
        return {}, []
    try:
        with open(WAIVERS_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as e:
        return {}, ["豁免登记文件读取失败 {}：{}".format(WAIVERS_PATH, e)]

    waivers, errors = {}, []
    for entry in data.get("waivers") or []:
        project = entry.get("project", "")
        gates = entry.get("gates") or []
        until = entry.get("until")
        inception = entry.get("立项日")
        if inception is None:
            errors.append(
                "豁免条目 {} 缺 `立项日`，无法校验「2026-10-12 前立项」，"
                "本条目不生效（请在 yaml 里补立项日）".format(project))
            continue
        if isinstance(inception, datetime.date):
            inception_date = inception
        else:
            try:
                inception_date = datetime.date.fromisoformat(str(inception))
            except ValueError:
                errors.append("豁免条目 {} 的 立项日 无效：{!r}（应为 YYYY-MM-DD）"
                              .format(project, inception))
                continue
        if inception_date >= SOP_CUTOVER:
            errors.append(
                "豁免条目 {} 立项日 {} 不早于 SOP 改造日 {}——新项目不得豁免，"
                "本条目不生效".format(project, inception_date, SOP_CUTOVER))
            continue
        if isinstance(until, datetime.date):
            until_date = until
        else:
            try:
                until_date = datetime.date.fromisoformat(str(until))
            except ValueError:
                errors.append("豁免条目 {} 的 until 无效：{!r}（应为 YYYY-MM-DD）"
                              .format(project, until))
                continue
        if today > until_date:
            errors.append("豁免已过期自动失效：{}（until {}，已超期；请补齐缺口"
                          "或删除该条目）".format(project, until_date))
            continue
        for gate in gates:
            waivers[(project, gate)] = entry
    return waivers, errors


def is_waived(waivers, project, gate):
    return (project, gate) in waivers
