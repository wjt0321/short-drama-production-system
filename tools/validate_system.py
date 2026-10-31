from pathlib import Path
import re, sys, json

ROOT = Path(__file__).resolve().parents[1]
PROJECT_TEMPLATE = ROOT/'模板'/'短剧项目模板'
# 体系结构校验只检查可提交的 SOP/模板/工具；私人项目由
# check_project_conformance.py 独立验片，不能反向拖死框架回归。
# 外部参考库＝可选挂载的数据项目（不随本包提供），其内部文档自带外部
# 链接、绝对路径与远端文件名，不是本体系的运行时 SOP；与外部参考库同级
# 处理，避免外部数据反向拖死框架回归。
# `_归档/` 是已封存的历史项目与调研原始件（与 `00-视频项目/` 同级性质）：
# 里面必然带第三方仓库的 README、B 站元数据 JSON、旧版 HTML，全是外链与历史路径。
# 它不是运行时文档，按「归档不参与在制自检」处理；不排除就会把整库结构校验拖红。
EXCLUDED_DIRS = {'.git', 'docs', '00-视频项目', '_归档',
                 '_release', 'archive', '.superpowers'}
errors=[]
warnings=[]

def is_excluded(p):
    """单一目录边界；所有体系扫描统一调用，避免某一路径漏扫私人项目。"""
    return any(part in EXCLUDED_DIRS for part in p.relative_to(ROOT).parts)


all_md=[p for p in ROOT.rglob('*.md') if not is_excluded(p)]
by_name={}
for p in all_md:
    by_name.setdefault(p.name,[]).append(p)

for name in ['SKILL.md','从这里开始.md']:
    p=ROOT/name
    text=p.read_text(encoding='utf-8')
    if 'AGENT-执行协议.md' in text:
        errors.append(f'{p.relative_to(ROOT)}: references missing filename AGENT-执行协议.md')
    if 'AGENTS.md' not in text:
        warnings.append(f'{p.relative_to(ROOT)}: no AGENTS.md route reference')

required=[
 '模板/README.md','模板/短剧项目模板/00-立项/风格提案.md','模板/短剧项目模板/00-立项/能力登记.md',
 '模板/短剧项目模板/00-立项/立项决策表.md','模板/短剧项目模板/01-剧本/大纲.md',
 '模板/短剧项目模板/01-剧本/剧本.md','模板/短剧项目模板/01-剧本/合规审查表.md',
 '模板/短剧项目模板/02-资产/角色/角色卡.md','模板/短剧项目模板/02-资产/场景/场景卡.md',
 '模板/短剧项目模板/02-资产/道具/道具卡.md','模板/短剧项目模板/02-资产/锚句表.md',
 '模板/短剧项目模板/03-分镜/分镜表.md','模板/短剧项目模板/03-分镜/首帧审核表.md',
 '模板/短剧项目模板/03-分镜/首尾帧衔接表.md','模板/短剧项目模板/04-镜头/镜头提示词.md',
 '模板/短剧项目模板/04-镜头/镜头审核包.md','模板/短剧项目模板/04-镜头/重抽日志.md',
 '模板/短剧项目模板/05-音频/配音审核包.md','模板/短剧项目模板/05-音频/音效建议书.md',
 '模板/短剧项目模板/05-音频/BGM候选表.md','模板/短剧项目模板/06-成片/成片质检表.md','模板/短剧项目模板/06-成片/剪辑装配单.md','模板/短剧项目模板/06-成片/字幕事件表.md',
 '模板/短剧项目模板/06-成片/发布包.md','模板/短剧项目模板/06-成片/复盘一页.md',
 '模板/短剧项目模板/执行清单.md','模板/短剧项目模板/用户裁决日志.md',
 '模板/短剧项目模板/变更记录.md','模板/短剧项目模板/素材与授权台账.md','模板/短剧项目模板/成本台账.md',
 '03-角色与视觉资产/场景与道具资产.md',
 '模板/短剧项目模板/项目状态摘要.md',
 '模板/短剧项目模板/README.md','skill-manifest.json'
]
for rel in required:
    if not (ROOT/rel).exists(): errors.append(f'missing required artifact: {rel}')

KNOWLEDGE_DIRS={'01-创意与剧本','02-分镜与镜头','03-角色与视觉资产','04-视频生成','05-音频','06-后期与发布','07-端到端管线'}
# Only top-level directories count. A project folder legitimately contains its own
# 05-音频/ and 04-镜头/ subfolders, and those are runtime artifacts, not knowledge-base
# documents — matching on any path component used to misclassify them.
core=[p for p in all_md if p.relative_to(ROOT).parts[0] in KNOWLEDGE_DIRS]
for p in core:
    text=p.read_text(encoding='utf-8')
    if not text.startswith('---\n'): errors.append(f'{p.relative_to(ROOT)}: missing frontmatter')
    if '体系定位' not in text[:1500]: errors.append(f'{p.relative_to(ROOT)}: missing 体系定位 block')

for p in all_md:
    text=p.read_text(encoding='utf-8')
    for line_no,line in enumerate(text.splitlines(),1):
        for m in re.finditer(r'`([^`\n]+\.md)`', line):
            ref=m.group(1)
            if '://' in ref or ref.startswith('{'):
                continue
            # Resolution order:
            #   1. system root              — 01-创意与剧本/短剧编剧引擎.md
            #   2. referencing file's own dir — standard markdown semantics
            #   3. project-template layout  — knowledge-base docs cite paths that
            #      will exist *inside a project* (e.g. 04-镜头/重抽日志.md).
            #      Without this rule those refs only passed while the template was
            #      the sole file carrying that name, and broke the moment a real
            #      project folder existed.
            #   4. unique filename anywhere
            if (ROOT/ref).exists():
                continue
            try:
                if (p.parent/ref).exists():
                    continue
                if PROJECT_TEMPLATE.exists() and (PROJECT_TEMPLATE/ref).exists():
                    continue
            except (OSError, ValueError):
                pass
            candidates=by_name.get(Path(ref).name,[])
            if len(candidates)==1:
                continue
            errors.append(f'{p.relative_to(ROOT)}:{line_no}: unresolved markdown reference `{ref}`')

for p in all_md:
    text=p.read_text(encoding='utf-8')
    rel=str(p.relative_to(ROOT))
    if 'AGENT-执行协议.md' in text and rel != 'AGENTS.md':
        errors.append(f'{rel}: legacy protocol filename still present')
    if '最多重试 3 次' in text or '≤3 次仍' in text:
        errors.append(f'{rel}: active retry policy still says 3 attempts')
    if '提示词V2.1.md' in text or 'V2.1-prose-outputs' in text:
        errors.append(f'{rel}: active Seedance V2.1 output naming remains')

manifest_path=ROOT/'skill-manifest.json'
if manifest_path.exists():
    try:
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        required_fields={'schema_version','name','display_name','description','entry','protocol','locale','content_type','tool_binding','loading','decision_policy','gates','id','scope'}
        missing=required_fields-set(manifest)
        if missing: errors.append(f'skill-manifest.json: missing fields {sorted(missing)}')
        if manifest.get('schema_version')!='1.0': errors.append('skill-manifest.json: schema_version must be 1.0')
        if not re.fullmatch(r'[a-z0-9-]+', manifest.get('name','')): errors.append('skill-manifest.json: name must be ASCII slug')
        if not manifest.get('display_name'): errors.append('skill-manifest.json: display_name missing')
        if '通用 Agent' not in manifest.get('description',''): errors.append('skill-manifest.json: description must declare universal Agent scope')
        if manifest.get('protocol')!='AGENTS.md' or not (ROOT/'AGENTS.md').exists(): errors.append('skill-manifest.json: protocol must resolve to AGENTS.md')
        if manifest.get('content_type')!='agent-skill': errors.append('skill-manifest.json: content_type must be agent-skill')
        if manifest.get('tool_binding')!='none': errors.append('skill-manifest.json: tool_binding must be none')
        if manifest.get('gates')!=['G0','G1','G2','G3','G4','G5','G6']: errors.append('skill-manifest.json: gates must be G0-G6')
        if manifest.get('entry')!='SKILL.md': errors.append('skill-manifest.json: entry must be SKILL.md')
        if not (ROOT/manifest.get('entry','')).exists(): errors.append('skill-manifest.json: entry file missing')
        if not re.fullmatch(r'[a-z0-9-]+', manifest.get('id','')): errors.append('skill-manifest.json: id must be non-empty ASCII slug')
        if manifest.get('locale')!='zh-CN': errors.append('skill-manifest.json: locale must be zh-CN')
        expected_scope={'short-drama','motion-comic','narrative-short-video'}
        if not expected_scope.issubset(set(manifest.get('scope',[]))): errors.append('skill-manifest.json: universal scope incomplete')
        loading=manifest.get('loading',{})
        if loading.get('current_gate_only') is not True or loading.get('full_library_default') is not False: errors.append('skill-manifest.json: progressive loading flags invalid')
        # 与 AGENTS.md §一.4 对齐：全权委托下只有这五类才必须停下来问用户
        # （花钱 / 外发发布 / 隐私素材上传 / 不可逆操作 / 方向级冲突）；
        # 风格、叙事、预算范围内的取舍由 Agent 自主决定，不再是必问类别。
        required_decisions={'spending_or_budget_expansion','external_send_or_publish',
                            'private_asset_upload','irreversible_change',
                            'truly_incompatible_direction_conflict'}
        actual=set(manifest.get('decision_policy',{}).get('human_decision_required',[]))
        if not required_decisions.issubset(actual): errors.append('skill-manifest.json: human decision categories incomplete')
    except Exception as exc: errors.append(f'skill-manifest.json: invalid JSON: {exc}')

# 通用规范层（原 `通用Agent短剧生产规范.md`）已于 2026-10-12 并入 `AGENTS.md`：
# 原文件级检查改为对合并后的协议做同一组概念与去供应商细节核对。
# **刻意从禁词里去掉 `ComfyUI` / `脚手架`**：AGENTS.md §八.2 必须点名平台以避免语法串台，
# §8.1 讲「推导脚手架」是比喻义——两者都不是把供应商教程灌进规范层。
# 供应商细节的真正边界由 §一（能力层思维）与 §八（先选实现再写适配提示词）承担。
common_path=ROOT/'AGENTS.md'
if common_path.exists():
    common=common_path.read_text(encoding='utf-8')
    for token in ['候选项','L0','L1','L2','L3','L4','真实剪辑镜头','生成段','首尾状态','质量归因']:
        if token not in common: errors.append(f'AGENTS.md: missing merged spec token {token}')
    for forbidden in ['平台 API','供应商线路','登录态','登录资料',
                      '编程开发助手','财务分析助手','合同审查助手','PPT 风格','电商图片','学术写作','邮件助手']:
        if forbidden in common: errors.append(f'AGENTS.md: forbidden detail {forbidden}')

# 根目录入口合并（2026-10-12）：README.md 与新会话启动卡并入 从这里开始.md 后，
# 被删的文件名不得再在体系文档里被当作"当前存在的文件"引用（会变成断链）。
# `通用Agent短剧生产规范.md` 的引用已全部改指 AGENTS.md，故同样列入。
# 归档目录与私人项目（00-视频项目/）不在此列：它们记录历史，不是运行时文档。
RETIRED_ROOT_DOCS=['README.md','新会话启动卡.md','通用Agent短剧生产规范.md','技术资产_环境事实.md']
for p in all_md:
    if p.relative_to(ROOT).parts[0] in {'_归档','docs','00-视频项目'}:
        continue
    text=p.read_text(encoding='utf-8')
    for line_no,line in enumerate(text.splitlines(),1):
        for m in re.finditer(r'`([^`\n]+\.md)`', line):
            ref=Path(m.group(1)).name
            if ref in RETIRED_ROOT_DOCS:
                errors.append(f'{p.relative_to(ROOT)}:{line_no}: references retired doc `{ref}`')


stage_requirements={
 '02-分镜与镜头/分镜工作流.md':['真实剪辑镜头','生成段','弹性拆镜'],  # 2026-10-12 片 7：原 分镜叙事工作流.md 合并后改名
 '02-分镜与镜头/跨镜连续性与帧链法.md':['首/尾状态字段','下一段首状态'],
 '03-角色与视觉资产/角色一致性.md':['身份合同','动作合同','镜头合同'],  # 2026-10-12 片 6：原 多镜头角色一致性.md 合并后改名
 '03-角色与视觉资产/场景与道具资产.md':['资产合同','项目状态摘要.md'],
 '模板/短剧项目模板/项目状态摘要.md':['当前关卡','已冻结资产','当前问题与候选','相关文件']
}
for rel,tokens in stage_requirements.items():
    p=ROOT/rel
    if not p.exists():
        errors.append(f'{rel}: required integrated stage file missing')
        continue
    text=p.read_text(encoding='utf-8')
    for token in tokens:
        if token not in text: errors.append(f'{rel}: missing integrated concept {token}')

for rel in ['从这里开始.md','AGENTS.md','模板/短剧项目模板/项目状态摘要.md']:
    try: (ROOT/rel).read_text(encoding='utf-8')
    except Exception as exc: errors.append(f'{rel}: Chinese path/UTF-8 read failed: {exc}')

runtime_docs=[ROOT/x for x in ['SKILL.md','AGENTS.md','从这里开始.md']]
runtime_docs += [p for p in all_md if p.relative_to(ROOT).parts[0] in KNOWLEDGE_DIRS|{'模板'}]

# Runtime and documentation hygiene: no environment-specific paths or external links.
# 外部参考库中的 JSON 仍可能包含第三方工作流、提示词语料或嵌入代码，
# 不是运行时文档。JSON 中的反斜杠、正则和路径字符串会被下面的路径/网址启发式误判，
# 因此数据 JSON 免检；同目录的方法与研究 Markdown 仍属于知识文档，继续正常检查。
# 封面审核表.md is a catalog (every line *is* an external URL by design); it is
# data too, not documentation, so it gets the same treatment.
DATA_DIRS={'外部参考库'}
DATA_MD_FILES={'外部参考库/提示词库/封面审核表.md'}



def is_data_json(p):
    parts=p.relative_to(ROOT).parts
    if p.suffix.lower()!='.json':
        return False
    if any(part in DATA_DIRS for part in parts):
        return True
    return False


def is_data_md(p):
    rel=str(p.relative_to(ROOT)).replace('\\','/')
    if rel in DATA_MD_FILES:
        return True
    parts=p.relative_to(ROOT).parts
    return False

scan_files=[p for p in ROOT.rglob('*')
            if p.is_file() and p.suffix.lower() in {'.md','.json','.ps1'}
            and not is_excluded(p)
            and not is_data_json(p) and not is_data_md(p)]
for doc in scan_files:
    rel=str(doc.relative_to(ROOT))
    text=doc.read_text(encoding='utf-8', errors='ignore')
    if re.search(r'(?<![A-Za-z])(?:[A-Za-z]:[\\/]|\\\\|/home/|/Users/)', text):
        errors.append(f'{rel}: environment-specific absolute path detected')
    if re.search(r'https?://', text):
        errors.append(f'{rel}: external URL detected; keep runtime docs self-contained')

    if doc.exists():
        text = doc.read_text(encoding='utf-8')
        if '§一.2' in text:
            errors.append(f'{doc.relative_to(ROOT)}: stale autonomy reference; use AGENTS §一.4')
        if '§八.1「先选实现' in text or re.search(r'§[八8]\.1[^\n]*预检', text):
            errors.append(f'{doc.relative_to(ROOT)}: stale preflight reference; use AGENTS §8.0')

print(f'checked markdown files: {len(all_md)}')
print(f'errors: {len(errors)}')
for item in errors: print('ERROR:',item)
print(f'warnings: {len(warnings)}')
for item in warnings: print('WARN:',item)
if errors:
    sys.exit(1)
print('VALIDATION PASSED')
