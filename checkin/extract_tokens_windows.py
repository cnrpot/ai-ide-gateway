"""在 Windows 上从本地客户端凭证导出三家 token 到 checkin/config.json。

- 只读本地登录态，不修改任何客户端文件；控制台只打印脱敏 token。
- 依赖：pip install pycryptodome
- 用法：python extract_tokens_windows.py [输出路径，默认同目录 config.json]

改造自社区签到脚本（linux.do/t/topic/2945247）的解密逻辑。
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import re
import struct
import sys
from pathlib import Path

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
except ImportError:
    print("需要 pycryptodome：pip install pycryptodome")
    sys.exit(1)


def _mask(t: str) -> str:
    return f"...{t[-6:]}" if t and len(t) > 6 else "***"


# ==================== Qoder：DPAPI + AES-256-GCM ====================
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_unprotect(data: bytes) -> bytes:
    k32 = ctypes.windll.kernel32
    inp, out = _Blob(), _Blob()
    inp.cbData = len(data)
    inp.pbData = ctypes.create_string_buffer(data)
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)
    ):
        raise OSError("CryptUnprotectData failed（需当前 Windows 用户已登录）")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        k32.LocalFree(out.pbData)


def extract_qoder() -> list[dict]:
    prof = Path(os.environ.get("APPDATA", "")) / "com.qodercn.app.stable"
    ls, dat = prof / "Local State", prof / "auth.v1.dat"
    if not ls.exists() or not dat.exists():
        return []
    raw = base64.b64decode(
        json.loads(ls.read_text(encoding="utf-8"))["os_crypt"]["encrypted_key"]
    )
    if raw[:5] != b"DPAPI":
        raise ValueError("unexpected encrypted_key prefix")
    key = _dpapi_unprotect(raw[5:])
    blob = dat.read_bytes()
    if blob[:3] != b"v10":
        raise ValueError("auth.v1.dat 不是 v10 信封")
    cipher = AES.new(key, AES.MODE_GCM, nonce=blob[3:15])
    plain = cipher.decrypt_and_verify(blob[15:-16], blob[-16:])
    auth = json.loads(plain)
    return [{
        "name": (auth.get("user") or {}).get("name") or "qoder",
        "token": auth["token"],
        "version": "0.3.4",
    }]

# ==================== Trae CN：iCubeAuthInfo 自定义加密 ====================
_TRAE_AUTH_KEY = "iCubeAuthInfo://icube.cloudide"
_URE = bytes([82,9,106,213,48,54,165,56,191,64,163,158,129,243,215,251,124,227,57,130,155,47,255,135,52,142,67,68,196,222,233,203,84,123,148,50,166,194,35,61,238,76,149,11,66,250,195,78,8,46,161,102,40,217,36,178,118,91,162,73,109,139,209,37])
_DRE = bytes([31,221,168,51,136,7,199,49,177,18,16,89,39,128,236,95,96,81,127,169,25,181,74,13,45,229,122,159,147,201,156,239,160,224,59,77,174,42,245,176,200,235,187,60,131,83,153,97,23,43,4,126,186,119,214,38,225,105,20,99,85,33,12,125])


def _decrypt_trae(b64: str) -> dict:
    t = base64.b64decode(b64)
    key = t[6:38]
    sha = hashlib.sha512(key).digest()
    xor = bytes(a ^ b for a, b in zip(_URE, _DRE))
    h = hashlib.sha512(sha + xor).digest()
    aes_key, iv = h[:16], h[16:32]
    plain = unpad(AES.new(aes_key, AES.MODE_CBC, iv).decrypt(t[38:]), 16)
    return json.loads(plain[64:].decode("utf-8"))


def _trae_device_id(appdir: Path) -> str:
    cfg = appdir / "ahanet" / "tt_net_config.config"
    try:
        m = re.search(r"device_id[^\w]*(\d+)", cfg.read_text(encoding="utf-8", errors="ignore"))
        if m:
            return m.group(1)
    except OSError:
        pass
    logs = appdir / "logs"
    if logs.is_dir():
        try:
            recent = sorted(logs.glob("*/main.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            recent = []
        for lp in recent[:5]:
            try:
                m = re.search(r"\[ICDRS\].*?did: (\d+)", lp.read_text(encoding="utf-8", errors="ignore"))
                if m:
                    return m.group(1)
            except OSError:
                continue
    return ""


def extract_trae() -> list[dict]:
    appdir = Path(os.environ.get("APPDATA", "")) / "Trae CN"
    sf = appdir / "User" / "globalStorage" / "storage.json"
    if not sf.exists():
        return []
    enc = json.loads(sf.read_text(encoding="utf-8")).get(_TRAE_AUTH_KEY)
    if not enc:
        return []
    auth = _decrypt_trae(enc)
    return [{
        "name": "trae",
        "token": auth["token"],
        "region": (auth.get("userRegion") or {}).get("region", "cn"),
        "device_id": _trae_device_id(appdir),
    }]

# ==================== WorkBuddy 5.6.0+：$wbEncrypted AES-256-GCM ====================
_AT_REST_SECRET = "Sik9U5aXhCdwTVEwsEySDOmDoB9r9ntFxHF1fst9LQI="
_WB_KEY = hashlib.sha256(_AT_REST_SECRET.encode("utf-8")).digest()
_WB_KEY_ID = hashlib.sha256(_WB_KEY).hexdigest()[:16]
_FRAMING_NUM = {"file": 1, "field": 2, "record": 3, "stream": 4}
_FRAMING_TAG = {"file": b"WBEF1", "field": b"WBEV1", "record": b"WBER1", "stream": b"WBES1"}


def _wb_aad(framing: str, key_id: str, suite: int) -> bytes:
    return b"".join([
        b"WB-AAD\x00", b"\x01",
        struct.pack(">I", len(_FRAMING_TAG[framing])) + _FRAMING_TAG[framing],
        struct.pack(">I", 6) + b"sym-v1",
        struct.pack(">I", suite),
        struct.pack(">I", len(key_id)) + key_id.encode(),
        bytes([_FRAMING_NUM[framing]]), b"\x00", b"\x00",
    ])


def _open_wb_field(value):
    if not isinstance(value, dict) or value.get("$wbEncrypted") != 1:
        return value  # 旧版明文
    env = json.loads(base64.b64decode(value["envelope"]))
    if env.get("keyId") != _WB_KEY_ID:
        raise ValueError(f"WB keyId 不匹配（{env.get('keyId')}），WorkBuddy 版本可能已更新")
    cipher = AES.new(_WB_KEY, AES.MODE_GCM, nonce=base64.b64decode(env["nonce"]))
    cipher.update(_wb_aad("field", env["keyId"], env["suite"]))
    plain = cipher.decrypt_and_verify(
        base64.b64decode(env["ciphertext"]), base64.b64decode(env["authTag"])
    )
    return plain.decode("utf-8")


def extract_workbuddy() -> list[dict]:
    d = Path(os.environ.get("LOCALAPPDATA", "")) / "CodeBuddyExtension" / "Data" / "Public" / "auth"
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.info")):
        try:
            sess = json.loads(p.read_text(encoding="utf-8"))
            auth = sess.get("auth") or {}
            token = _open_wb_field(auth.get("accessToken"))
            if not token:
                continue
            out.append({
                "name": p.stem,
                "access_token": token,
                "uid": str((sess.get("account") or {}).get("uid", "")),
                "domain": auth.get("domain", ""),
                "expires_at": auth.get("expiresAt", 0),
            })
        except Exception as exc:  # noqa: BLE001
            print(f"  [WorkBuddy] 解析 {p.name} 失败: {exc}")
    return out


# ==================== 汇总输出 ====================
def main() -> None:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "config.json"
    config: dict = {"trae": [], "qoder": [], "workbuddy": []}
    for label, fn in (("qoder", extract_qoder), ("trae", extract_trae), ("workbuddy", extract_workbuddy)):
        try:
            items = fn()
            config[label] = items
            for it in items:
                tok = it.get("token") or it.get("access_token") or ""
                print(f"[{label}] {it.get('name')}: token {_mask(tok)}")
            if not items:
                print(f"[{label}] 未找到本地登录态（客户端未安装或未登录）")
        except Exception as exc:  # noqa: BLE001
            print(f"[{label}] 导出失败: {exc}")
    out_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {out_path}（含明文 token，注意保密、勿外传、勿提交 git）")


if __name__ == "__main__":
    if os.name != "nt":
        print("此脚本只能在 Windows 上运行（依赖 DPAPI 与本地客户端路径）")
        sys.exit(1)
    main()


