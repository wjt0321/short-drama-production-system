#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""H3 Ref2VA 硬参数闸：帧数、档位与参考槽位。"""
import argparse, sys
MIN_FRAMES,MAX_FRAMES=124,362
VALID_DURATIONS={"5":124,"5s":124,"10":243,"10s":243}
def validate(length=None,ref_images=0,ref_videos=0,duration=None):
    errors=[]
    if ref_images<0 or ref_images>9: errors.append(f"参考图数量 {ref_images} 超过上限 9")
    if ref_videos<0 or ref_videos>3: errors.append(f"参考视频数量 {ref_videos} 超过上限 3")
    if length is not None:
        if not MIN_FRAMES<=length<=MAX_FRAMES: errors.append(f"帧数 {length} 超出 124–362 范围")
        elif (length-5)%17: errors.append(f"帧数 {length} 不符合 17k+5 合法序列")
    if duration is not None:
        key=str(duration).lower()
        expected=VALID_DURATIONS.get(key)
        if expected is None: errors.append(f"不支持的档位 {duration}，只允许 5s/10s")
        elif length is not None and length!=expected: errors.append(f"{duration} 档必须使用 {expected} 帧，当前为 {length}")
    return errors
def selftest():
    cases=[(validate(124,9,3,"5s"),False),(validate(240,0,0),True),(validate(243,10,0,"10s"),True),(validate(243,0,0,"5s"),True)]
    if any(bool(err)!=want for err,want in cases): print("[自检失败] H3 规则回归：",cases); return 2
    print("[自检通过] H3 帧数序列、档位和参考槽位规则通过"); return 0
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--length",type=int); ap.add_argument("--ref-images",type=int,default=0); ap.add_argument("--ref-videos",type=int,default=0); ap.add_argument("--duration"); ap.add_argument("--selftest",action="store_true"); a=ap.parse_args()
    if a.selftest:return selftest()
    if a.length is None and a.ref_images==0 and a.ref_videos==0 and a.duration is None: ap.error("至少提供一个待校验参数")
    errors=validate(a.length,a.ref_images,a.ref_videos,a.duration)
    for x in errors: print("✗ "+x)
    if not errors: print("✓ H3 Ref2VA 参数合法")
    return 1 if errors else 0
if __name__=="__main__":sys.exit(main())
