"""
speech/emotion_recognition.py
語音情緒辨識模組 — 使用 emotion2vec+ base 模型

透過 FunASR 載入本地 emotion2vec_plus_base 模型，
分析 16kHz 音訊並回傳情緒標籤與信心分數。

情緒類別（9 類）：
    0: angry (生氣)
    1: disgusted (厭惡)
    2: fearful (恐懼)
    3: happy (開心)
    4: neutral (中立)
    5: other (其他)
    6: sad (難過)
    7: surprised (吃驚)
    8: unknown (未知)
"""

import os
import sys
import time
import numpy as np

# 確保能 import 上層模組
_speech_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.abspath(os.path.join(_speech_dir, ".."))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

import config

# ═══════════════════════════════════════════════════════
# 模型路徑與標籤定義
# ═══════════════════════════════════════════════════════

EMOTION_MODEL_PATH = config.EMOTION_MODEL_PATH

# 情緒標籤對照表（中英文）
EMOTION_LABELS = {
    0: {"zh": "生氣", "en": "angry"},
    1: {"zh": "厭惡", "en": "disgusted"},
    2: {"zh": "恐懼", "en": "fearful"},
    3: {"zh": "開心", "en": "happy"},
    4: {"zh": "中立", "en": "neutral"},
    5: {"zh": "其他", "en": "other"},
    6: {"zh": "難過", "en": "sad"},
    7: {"zh": "吃驚", "en": "surprised"},
    8: {"zh": "未知", "en": "unknown"},
}

# ═══════════════════════════════════════════════════════
# 全域模型實例（延遲載入）
# ═══════════════════════════════════════════════════════

_emotion_model = None


def _lazy_init_emotion_model():
    """延遲載入 emotion2vec+ 模型（首次呼叫時才載入，避免啟動延遲）"""
    global _emotion_model
    if _emotion_model is not None:
        return True

    try:
        from funasr import AutoModel
        print(f"⚙️ [情緒辨識] 正在載入 emotion2vec+ base 模型...")
        print(f"   模型路徑：{EMOTION_MODEL_PATH}")

        _start = time.time()
        _emotion_model = AutoModel(model=EMOTION_MODEL_PATH)
        print(f"✨ [情緒辨識] 模型載入完成！耗時 {time.time() - _start:.2f}s")
        return True

    except ImportError:
        print("❌ [情緒辨識] funasr 未安裝，請執行: pip install funasr modelscope")
        return False
    except Exception as e:
        print(f"❌ [情緒辨識] 模型載入失敗: {e}")
        _emotion_model = None
        return False


# ═══════════════════════════════════════════════════════
# 核心功能：語音情緒辨識
# ═══════════════════════════════════════════════════════

def recognize_emotion(audio_path: str) -> dict:
    """
    分析音訊檔案的情緒。

    :param audio_path: 音訊檔案路徑（支援 wav/mp3，建議 16kHz）
    :return: 情緒辨識結果字典
        {
            "emotion_zh": "開心",
            "emotion_en": "happy",
            "emotion_index": 3,
            "confidence": 0.85,
            "all_scores": {"angry": 0.02, "happy": 0.85, ...}
        }
        若辨識失敗則回傳預設的 neutral 結果
    """
    # 預設結果（辨識失敗時回傳）
    default_result = {
        "emotion_zh": "中立",
        "emotion_en": "neutral",
        "emotion_index": 4,
        "confidence": 0.0,
        "all_scores": {}
    }

    # 檢查檔案是否存在
    if not audio_path or not os.path.exists(audio_path):
        print(f"⚠️ [情緒辨識] 音訊檔案不存在：{audio_path}")
        return default_result

    # 載入模型
    if not _lazy_init_emotion_model():
        return default_result

    try:
        _start = time.time()

        # 使用 FunASR 進行推論
        result = _emotion_model.generate(
            audio_path,
            granularity="utterance",
            extract_embedding=False
        )

        _elapsed = time.time() - _start

        # 解析結果
        if result and len(result) > 0:
            rec = result[0]
            labels = rec.get("labels", [])
            scores = rec.get("scores", [])

            if labels and scores:
                # 找到最高分的情緒
                max_idx = int(np.argmax(scores))
                max_score = float(scores[max_idx])

                # 取得對應的情緒標籤
                emotion_info = EMOTION_LABELS.get(max_idx, EMOTION_LABELS[8])

                # 組合所有分數
                all_scores = {}
                for i, (label, score) in enumerate(zip(labels, scores)):
                    # label 格式可能是 "生气/angry" 或純英文
                    en_label = EMOTION_LABELS.get(i, {}).get("en", label)
                    all_scores[en_label] = round(float(score), 4)

                result_dict = {
                    "emotion_zh": emotion_info["zh"],
                    "emotion_en": emotion_info["en"],
                    "emotion_index": max_idx,
                    "confidence": round(max_score, 4),
                    "all_scores": all_scores
                }

                print(f"⏱️ [情緒辨識] {_elapsed:.2f}s → {emotion_info['zh']}({emotion_info['en']}) "
                      f"信心度: {max_score:.2%}")
                return result_dict

        print(f"⚠️ [情緒辨識] 模型回傳結果為空")
        return default_result

    except Exception as e:
        print(f"❌ [情緒辨識] 推論失敗: {e}")
        return default_result


def recognize_emotion_from_array(audio_array: np.ndarray, sample_rate: int = 16000) -> dict:
    """
    從 numpy array 分析情緒（供 voice_assistant.py 直接傳入錄音資料使用）。

    :param audio_array: float32 numpy array 音訊資料
    :param sample_rate: 取樣率（預設 16000）
    :return: 同 recognize_emotion() 的回傳格式
    """
    import tempfile
    import soundfile as sf

    default_result = {
        "emotion_zh": "中立",
        "emotion_en": "neutral",
        "emotion_index": 4,
        "confidence": 0.0,
        "all_scores": {}
    }

    if audio_array is None or len(audio_array) == 0:
        return default_result

    try:
        # 將 numpy array 暫存為 wav 檔案
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        sf.write(tmp_path, audio_array, sample_rate)

        # 呼叫主辨識函數
        result = recognize_emotion(tmp_path)

        # 清理暫存檔
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        return result

    except Exception as e:
        print(f"❌ [情緒辨識] array 推論失敗: {e}")
        return default_result


# ═══════════════════════════════════════════════════════
# 情緒歷史追蹤（供 today_summary 整合用）
# ═══════════════════════════════════════════════════════

# 當日情緒記錄（記憶體中暫存，每次互動追加）
_today_emotion_log: list = []


def log_emotion(emotion_result: dict):
    """
    將一次情緒辨識結果加入當日記錄。

    :param emotion_result: recognize_emotion() 的回傳值
    """
    from datetime import datetime
    _today_emotion_log.append({
        "time": datetime.now().strftime("%H:%M"),
        "emotion_zh": emotion_result.get("emotion_zh", "中立"),
        "emotion_en": emotion_result.get("emotion_en", "neutral"),
        "confidence": emotion_result.get("confidence", 0.0),
    })


def get_emotion_summary() -> dict:
    """
    彙整當日所有情緒辨識結果，回傳摘要。

    :return: {
        "dominant_emotion_zh": "開心",
        "dominant_emotion_en": "happy",
        "emotion_distribution": {"happy": 5, "neutral": 3, "sad": 1},
        "total_detections": 9,
        "latest_emotion_zh": "開心",
        "emotion_timeline": "09:30 開心 → 10:15 中立 → 11:00 開心"
    }
    """
    if not _today_emotion_log:
        return {
            "dominant_emotion_zh": "尚未偵測",
            "dominant_emotion_en": "none",
            "emotion_distribution": {},
            "total_detections": 0,
            "latest_emotion_zh": "尚未偵測",
            "emotion_timeline": ""
        }

    # 統計情緒分布
    distribution = {}
    for entry in _today_emotion_log:
        en = entry["emotion_en"]
        distribution[en] = distribution.get(en, 0) + 1

    # 找出主導情緒（出現最多次）
    dominant_en = max(distribution, key=distribution.get)
    # 從 EMOTION_LABELS 找中文
    dominant_zh = "中立"
    for info in EMOTION_LABELS.values():
        if info["en"] == dominant_en:
            dominant_zh = info["zh"]
            break

    # 最新情緒
    latest = _today_emotion_log[-1]

    # 情緒時間軸（最多顯示最近 10 筆）
    recent = _today_emotion_log[-10:]
    timeline_parts = [f"{e['time']} {e['emotion_zh']}" for e in recent]
    timeline_str = " → ".join(timeline_parts)

    return {
        "dominant_emotion_zh": dominant_zh,
        "dominant_emotion_en": dominant_en,
        "emotion_distribution": distribution,
        "total_detections": len(_today_emotion_log),
        "latest_emotion_zh": latest["emotion_zh"],
        "emotion_timeline": timeline_str
    }


def reset_emotion_log():
    """重置當日情緒記錄（每日凌晨或手動呼叫）"""
    global _today_emotion_log
    _today_emotion_log = []


# ═══════════════════════════════════════════════════════
# 單獨測試
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        # 使用模型內建的測試音檔
        test_wav = os.path.join(EMOTION_MODEL_PATH, "example", "test.wav")
        if not os.path.exists(test_wav):
            print("用法: python emotion_recognition.py <音訊檔案路徑>")
            print(f"  或確認測試音檔存在: {test_wav}")
            sys.exit(1)
    else:
        test_wav = sys.argv[1]

    print(f"\n🎤 分析音訊：{test_wav}\n")
    result = recognize_emotion(test_wav)

    print(f"\n🎯 情緒辨識結果:")
    print(f"   情緒：{result['emotion_zh']} ({result['emotion_en']})")
    print(f"   信心度：{result['confidence']:.2%}")
    print(f"   所有分數：")
    for label, score in sorted(result['all_scores'].items(), key=lambda x: -x[1]):
        bar = "█" * int(score * 30)
        print(f"     {label:12s} {score:.4f} {bar}")
