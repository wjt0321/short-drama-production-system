#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""H3 原生音轨的音噪诊断（体系第 12 节配套工具）。

通俗说它是干什么的
------------------
拿一段 H3 生成的音轨，量出三件事，用来回答"这段声音为什么听着脏"：

  1. 底噪有多响、是不是白噪  -> 静音段的 RMS + 谱平坦度
  2. "尖锐倒刺"来自哪段频率  -> 6-14kHz 的瞬态尖刺占比
  3. "被压缩感"是削顶还是压扁 -> 峰均比 crest

再拿同一个素材的两个版本（模型直出的无损 FLAC vs 封进 MP4 的 AAC）跑一遍，
就能判定噪声到底是模型带的还是编码带的：
  底噪差 < 1 dB  -> 模型的锅，调码率没用
  底噪差 > 3 dB  -> 编码的锅，提高码率可救

怎么用
------
    python audio_noise_diag.py 音频1.wav [音频2.wav ...]

输入要求是 PCM wav。不是 wav 就先转：

    ffmpeg -i 成片.mp4 -vn -ac 2 -ar 32000 -c:a pcm_s16le out.wav

需要 numpy。本机可用 ComfyUI 自带的解释器，它已装好：
    本机任意带 numpy 的 Python 3.10+ 解释器   （此处为说明，勿写进代码）

怎么看结果
----------
  底噪 RMS    > -50 dBFS  -> 人耳已能听见，需要降噪或替换
  谱平坦度    > 0.3       -> 接近白噪；< 0.05 -> 是有音调的环境声（正常）
  尖刺占比    > 5%        -> 齿音过冲明显，听感"倒刺"
  峰均比      < 10 dB     -> 动态被压扁；12-20 dB 为语音正常区间
"""
import sys
import wave

import numpy as np


def load_wav(path):
    """读 PCM wav -> [单声道 float32(-1..1), 采样率]。"""
    w = wave.open(path, "rb")
    sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
    if sw != 2:
        raise SystemExit("只支持 16-bit PCM wav，请先 -c:a pcm_s16le 转换：%s" % path)
    raw = w.readframes(w.getnframes())
    w.close()
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    x = x.reshape(-1, ch).T.mean(0)          # 混成单声道
    return x, sr


def _rms(v):
    return float(np.sqrt(np.mean(np.asarray(v) ** 2)))


def _db(v):
    return 20.0 * np.log10(float(v) + 1e-12)


def _spectral_flatness(v, nfft=1024):
    """0 = 纯音调，1 = 纯白噪。"""
    n = min(nfft, len(v))
    if n < 64:
        return 0.0
    S = np.abs(np.fft.rfft(v[:n] * np.hanning(n), n)) ** 2 + 1e-20
    return float(np.exp(np.mean(np.log(S))) / (np.mean(S) + 1e-20))


def diagnose(mono, sr):
    """返回一段音轨的全部诊断量。"""
    r_all = _rms(mono)
    peak = float(np.max(np.abs(mono)))

    # ---- 静音段：取 RMS 最低的 8% 帧 ----
    n = int(sr * 0.05)                       # 50ms 一帧
    k = (len(mono) // n) * n
    fr = mono[:k].reshape(-1, n).std(axis=-1)
    order = np.argsort(fr)
    nq = max(3, int(len(fr) * 0.08))
    q = np.concatenate([mono[i * n:(i + 1) * n] for i in np.sort(order[:nq])])

    r_q = _rms(q)
    kq = (len(q) // n) * n
    fr_q = (q[:kq].reshape(-1, n).std(axis=-1)
            if kq >= n else np.array([q.std()]))

    # ---- 6-14kHz 瞬态尖刺 ----
    win = int(sr * 0.01)
    if len(mono) > win:
        st = mono[: (len(mono) // win) * win].reshape(-1, win) * np.hanning(win)
        HS = np.abs(np.fft.rfft(st, 512, axis=-1)) ** 2
        fh = np.fft.rfftfreq(512, 1.0 / sr)
        m = (fh >= 6000) & (fh < 14000)
        e = HS[:, m].mean(axis=-1) if m.any() else np.zeros(len(st))
        spike = float(np.mean(e > np.median(e) * 25)) * 100.0
    else:
        spike = 0.0

    # ---- 高频滚降 ----
    nb = min(16384, len(mono))
    S = np.abs(np.fft.rfft(mono[:nb] * np.hanning(nb), 8192)) ** 2
    f = np.fft.rfftfreq(8192, 1.0 / sr)

    def at(fq):
        i = int(np.argmin(np.abs(f - fq)))
        return 10.0 * np.log10(S[max(0, i - 4):i + 4].mean() + 1e-20)

    return {
        "dur": len(mono) / float(sr),
        "sr": sr,
        "peak": peak,
        "rms": r_all,
        "crest": _db(peak / (r_all + 1e-12)),
        "noise": r_q,
        "snr": _db(r_all / (r_q + 1e-12)),
        "flat": _spectral_flatness(q[:4096]) if len(q) >= 4096 else _spectral_flatness(q),
        "floor_wobble": float(np.std(fr_q) / (np.mean(fr_q) + 1e-12)),
        "spike": spike,
        "hi14": at(14000),
        "hi15": at(15500),
    }


def report(name, m):
    print("=" * 70)
    print("%s    %.2fs @ %d Hz" % (name, m["dur"], m["sr"]))
    print("=" * 70)
    print("峰值 %.4f (%+.1f dBFS)   全局 RMS %.5f (%+.1f dBFS)" %
          (m["peak"], _db(m["peak"]), m["rms"], _db(m["rms"])))
    print("峰均比 crest   %6.1f dB      语音正常 12-20；<10 说明动态被压扁"
          % m["crest"])
    print("底噪 RMS       %.6f (%+.1f dBFS)   全局/底噪 %.1f dB"
          % (m["noise"], _db(m["noise"]), m["snr"]))
    print("底噪谱平坦度   %6.3f           >0.3 近白噪；<0.05 是有音调的环境声"
          % m["flat"])
    print("底噪帧间波动   %6.3f           >0.5 说明有噪声门在开合" % m["floor_wobble"])
    print("6-14k 尖刺占比 %6.2f %%          偏高即「倒刺」来源" % m["spike"])
    print("14kHz 能量     %6.1f dB" % m["hi14"])
    print("15.5kHz 能量   %6.1f dB       （32k 采样 -> 硬上限 16k，此项先天缺失）"
          % m["hi15"])
    print()
    print("  判读：底噪 %s / 平坦度 %s / 尖刺 %s" % (
        "偏响需处理" if m["noise"] > 0.003 else "可接受",
        "近白噪" if m["flat"] > 0.3 else ("有音调" if m["flat"] < 0.05 else "混合"),
        "过冲明显" if m["spike"] > 5 else "正常"))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)

    res = []
    for p in sys.argv[1:]:
        mono, sr = load_wav(p)
        m = diagnose(mono, sr)
        res.append((p, m))
        report(p, m)
        print()

    if len(res) >= 2:
        print("=" * 70)
        print("两两对照（相对第一条）")
        print("=" * 70)
        base = res[0][1]
        for p, m in res[1:]:
            print("%s vs %s" % (res[0][0], p))
            print("  底噪     %+.2f dB  (%+.1f -> %+.1f dBFS)" %
                  (_db(m["noise"]) - _db(base["noise"]),
                   _db(base["noise"]), _db(m["noise"])))
            print("  谱平坦度 %.3f -> %.3f" % (base["flat"], m["flat"]))
            print("  尖刺     %.2f%% -> %.2f%%" % (base["spike"], m["spike"]))
            print("  峰均比   %.1f -> %.1f dB" % (base["crest"], m["crest"]))
            d = abs(_db(m["noise"]) - _db(base["noise"]))
            print("  => %s" % ("差 %.2f dB < 1 dB：编码基本无损，噪声来自模型本身，"
                               "调码率无效" % d if d < 1 else
                               "差 %.2f dB > 3 dB：编码在制造噪声，提高码率可救" % d
                               if d > 3 else
                               "差 %.2f dB：介于两者之间，需结合听感判断" % d))
            print()


if __name__ == "__main__":
    main()
