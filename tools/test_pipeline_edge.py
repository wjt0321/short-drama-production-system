# -*- coding: utf-8 -*-
"""边界与异常测试：shortfilm_pipeline.py + 三个导出器 + review_gate.py

auto_select_cards 测过了，流水线这套还没测。风险点：
  · 极端参数（duration=0/1/9999、top=0/9999、cards=0）
  · 非法枚举（style/mood 传错值）
  · 特殊字符题材（引号/换行/反斜杠 → 变文件名）
  · 导出器吃错输入（空 json / 结构不对的 json）
  · review_gate 吃错文件
"""
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.dirname(HERE)                       # <体系>
LIB = os.path.join(SYSTEM_ROOT, "外部参考库", "提示词库")   # 相对定位，可整体搬走
PIPE = os.path.join(LIB, 'shortfilm_pipeline.py')
G3 = os.path.join(LIB, 'export_g3_storyboard.py')
G4 = os.path.join(LIB, 'export_g4_generation.py')
G6 = os.path.join(LIB, 'export_g6_assembly.py')
GATE = os.path.join(LIB, 'review_gate.py')
TMP = os.environ.get('TEMP', '.')

if not os.path.isdir(LIB):
    print('外部参考库未随包提供，流水线边界测试不适用（N/A）。')
    raise SystemExit(0)

fails = []


def run(cmd, timeout=200, env=None):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace',
                           timeout=timeout, env=env)
        return p.returncode, (p.stdout or '') + (p.stderr or '')
    except subprocess.TimeoutExpired:
        return -9, 'TIMEOUT'


def bad(name, why):
    fails.append((name, why))
    print('✗ {:<26s} {}'.format(name, why))


def good(name, ev=''):
    print('✓ {:<26s} {}'.format(name, ev))


print('=' * 78)
print('流水线边界与异常测试')
print('=' * 78)

# ---------- 1. 极端 duration ----------
print('\n--- 极端 duration ---')
for d in ('0', '1', '2', '9999'):
    rc, o = run([sys.executable, PIPE, '测试题材', '--duration', d,
                 '--out', os.path.join(TMP, 'bd1')])
    if rc != 0:
        bad('duration=' + d, 'rc={} {}'.format(rc, o.strip()[-60:]))
    else:
        good('duration=' + d, 'rc=0')

# ---------- 2. 极端 top / cards ----------
print('\n--- 极端 top / cards ---')
for t in ('0', '1', '999'):
    rc, o = run([sys.executable, os.path.join(LIB, 'auto_select_cards.py'),
                 '江南', '--top', t, '--format', 'json',
                 '--out', os.path.join(TMP, 'bd2.json')])
    if rc not in (0, 1):
        bad('top=' + t, 'rc={}'.format(rc))
    else:
        good('top=' + t, 'rc={}'.format(rc))
rc, o = run([sys.executable, PIPE, '测试题材', '--cards', '0',
             '--out', os.path.join(TMP, 'bd3')])
good('cards=0', 'rc={}'.format(rc) if rc == 0 else 'FAIL rc={}'.format(rc))
if rc != 0:
    bad('cards=0', 'rc={}'.format(rc))

# ---------- 3. 全部风格 × 全部情绪 ----------
print('\n--- 风格 × 情绪 组合 ---')
styles = ('水墨', '国漫', '工笔', '写实', '赛博')
moods = ('肃杀', '空灵', '热血', '凄美', '诡谲', '温情')
fail_combo = []
for st in styles:
    for md in moods:
        rc, o = run([sys.executable, PIPE, '组合测试', '--style', st, '--mood', md,
                     '--duration', '30', '--until', '分镜',
                     '--out', os.path.join(TMP, 'bdc')])
        if rc != 0:
            fail_combo.append('{}+{}'.format(st, md))
if fail_combo:
    bad('风格×情绪组合', '{} 个失败: {}'.format(len(fail_combo), fail_combo[:3]))
else:
    good('风格×情绪组合', '{} 组合全通过'.format(len(styles) * len(moods)))

# ---------- 4. 非法枚举 ----------
print('\n--- 非法枚举值 ---')
for flag, val in (('--style', '不存在风格'), ('--mood', '不存在情绪'),
                  ('--until', '不存在步骤'), ('--format', 'xml')):
    rc, o = run([sys.executable, PIPE, '测试', flag, val,
                 '--out', os.path.join(TMP, 'bd4')])
    # 期望：argparse 报错退出（非 0），且提示是 choices 相关
    ok = rc != 0 and ('invalid choice' in o or '无效' in o or 'choices' in o)
    if ok:
        good('{} {}'.format(flag, val), '正确拒绝')
    else:
        bad('{} {}'.format(flag, val), 'rc={} 未正确拒绝'.format(rc))

# ---------- 5. 特殊字符题材（会变文件名） ----------
print('\n--- 特殊字符题材 ---')
nasty = ['a"b', "a'b", 'a\\b', 'a/b', 'a:b', 'a*b', 'a?b', 'a|b', 'a<b>c',
         ' 前后空格  ', 'a\nb']
for q in nasty:
    rc, o = run([sys.executable, PIPE, q, '--duration', '15',
                 '--out', os.path.join(TMP, 'bd5')])
    if rc != 0:
        bad('题材 {!r}'.format(q), 'rc={} {}'.format(rc, o.strip()[-50:]))

# ---------- 6. 导出器吃错输入 ----------
print('\n--- 导出器健壮性 ---')
bad_json = os.path.join(TMP, 'bad.json')
open(bad_json, 'w', encoding='utf-8').write('{ 这不是合法 JSON ')
empty_json = os.path.join(TMP, 'empty.json')
open(empty_json, 'w', encoding='utf-8').write('[]')
nopipe_json = os.path.join(TMP, 'nopipe.json')
json.dump([{'topic': 'X', 'storyboard': []}], open(nopipe_json, 'w', encoding='utf-8'),
          ensure_ascii=False)

for label, path in (('非法 JSON', bad_json), ('空数组', empty_json),
                    ('无分镜', nopipe_json)):
    for name, script in (('G3', G3), ('G4', G4), ('G6', G6)):
        rc, o = run([sys.executable, script, path, '--out',
                     os.path.join(TMP, 'bd6.md')])
        if rc == -9:
            bad('{} 吃{}'.format(name, label), '超时')
        elif rc not in (0, 1):
            bad('{} 吃{}'.format(name, label), '未捕获崩溃 rc={}'.format(rc))
        else:
            good('{} 吃{}'.format(name, label), 'rc={}'.format(rc))

# ---------- 7. review_gate 吃错文件 ----------
print('\n--- review_gate 健壮性 ---')
cases = [
    ('不存在的文件', os.path.join(TMP, 'nope.md')),
    ('不是 md 的文件', bad_json),
    ('空文件', (lambda p: (open(p, 'w').close(), p)[1])(os.path.join(TMP, 'e.md'))),
]
for label, path in cases:
    rc, o = run([sys.executable, GATE, path, '--status'])
    if rc == -9:
        bad('gate {}'.format(label), '超时')
    elif rc not in (0, 1):
        bad('gate {}'.format(label), 'rc={}'.format(rc))
    else:
        good('gate {}'.format(label), 'rc={}'.format(rc))

# ---------- 8. review_gate 非法关卡号 ----------
print('\n--- review_gate 非法关卡 ---')
real_pack = None
d = os.path.join(TMP, 'bd1')
if os.path.isdir(d):
    ms = [f for f in os.listdir(d) if f.endswith('.md')]
    if ms:
        real_pack = os.path.join(d, ms[0])
if real_pack:
    for g in ('⑥', '0', '9', 'abc', '-1', ''):
        rc, o = run([sys.executable, GATE, real_pack, '--sign', g,
                     '--verdict', '通过'])
        if rc == -9:
            bad('关卡 {!r}'.format(g), '超时')
        elif rc not in (0, 1):
            bad('关卡 {!r}'.format(g), 'rc={} {}'.format(rc, o.strip()[-50:]))
        else:
            good('关卡 {!r}'.format(g), 'rc={}'.format(rc))
else:
    bad('review_gate 关卡测试', '没找到可用的制作包')

# ---------- 9. 时长守恒：各场秒数之和必须等于 --duration ----------
# 这条是实测踩出来的：60 秒被拆成 7.5+7.5 各进位成 8，
# 三幕合计 62 秒，而产物里没有任何地方提示「和目标差 2 秒」。
# 制片交付时时长对不上要返工，所以必须机器查，不能靠人记。
print('\n--- 时长守恒 ---')
sys.path.insert(0, LIB)
try:
    import importlib.util
    _sp_spec = importlib.util.spec_from_file_location('_sp_mod', PIPE)
    _sp = importlib.util.module_from_spec(_sp_spec)
    _sp_spec.loader.exec_module(_sp)
    bad_dur = []
    for d in (15, 30, 45, 60, 75, 90, 120, 180):
        _p = _sp.step2_plot('时长守恒', d, '肃杀')
        _s = _sp.step3_script('时长守恒', _p, d, '肃杀', '工笔')
        _sec = [x['seconds'] for x in _s['scenes']]
        _act = sum(a['seconds'] for a in _p['acts'])
        if sum(_sec) != d or _act != d:
            bad_dur.append('{}→幕{}场{}'.format(d, _act, sum(_sec)))
    if bad_dur:
        bad('时长守恒', '不守恒: {}'.format(bad_dur[:3]))
    else:
        good('时长守恒', '8 个时长档全部严格等于目标')
except Exception as exc:            # noqa: BLE001
    bad('时长守恒', '无法执行: {}: {}'.format(type(exc).__name__, str(exc)[:40]))

# ---------- 10. 景别曲线必须单调收紧 ----------
# 原来景别是用 idx 机械轮转的，6 镜出来是
#   大远景→中景→远景→近景→全景→特写
# 先跳进、再跳出、又跳进、再大幅跳出，节奏是乱的，
# 观众建立不起「越靠近、越紧张」的体感。
# 景别好不好看得用眼睛，**是不是单调收紧**可以机器查。
print('\n--- 景别曲线 ---')
try:
    import importlib.util as _iu
    _s2 = _iu.spec_from_file_location('_sp_mod2', PIPE)
    _m2 = _iu.module_from_spec(_s2)
    _s2.loader.exec_module(_m2)
    bad_curve, no_func = [], []
    for st in ('工笔', '水墨', '赛博'):
        _p = _m2.step2_plot('景别曲线', 60, '肃杀')
        _sc = _m2.step3_script('景别曲线', _p, 60, '肃杀', st)
        _v = [_m2.SHOT_TIGHTNESS[x['shot_size']] for x in _sc['scenes']]
        if not all(_v[i] <= _v[i + 1] for i in range(len(_v) - 1)):
            bad_curve.append('{}:{}'.format(st, _v))
        for x in _sc['scenes']:
            if (x['act'][:3], x['shot_size']) not in _m2.NARRATIVE_FUNC:
                no_func.append('{} {}/{}'.format(
                    st, x['act'][:3], x['shot_size']))
    if bad_curve:
        bad('景别单调收紧', '有回退: {}'.format(bad_curve[:2]))
    elif no_func:
        bad('每镜有叙事功能', '缺: {}'.format(no_func[:3]))
    else:
        good('景别曲线', '3 种风格均单调收紧，且每镜都有叙事功能')
except Exception as exc:            # noqa: BLE001
    bad('景别曲线', '无法执行: {}: {}'.format(type(exc).__name__, str(exc)[:40]))

print('\n' + '=' * 78)
if fails:
    print('发现 {} 个问题:'.format(len(fails)))
    for n, why in fails:
        print('  - {}: {}'.format(n, why))
    # **必须非零退出**。这里原来只打印不退出，于是无论发现多少问题，
    # 退出码永远是 0 —— 编排器只看 returncode，这道闸就是个摆设。
    # 实测：把时长守恒打回原样后，它明明打印了「✗ 时长守恒 不守恒: …」，
    # 编排器那边仍然显示 OK。（配合编排器自身的 status bug，两层都漏。）
    sys.exit(1)
print('全部通过（10 组边界场景）')
sys.exit(0)


