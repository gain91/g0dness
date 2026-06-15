"""
AI Suite — Key Vault (v4.1 加固)
AES-256-GCM 认证加密，随机 salt，60 万次 PBKDF2 迭代
用法:
  python key_vault.py encrypt    # 加密 ~/.model_keys.json → ~/.model_keys.enc
  python key_vault.py decrypt    # 解密查看
  python key_vault.py status     # 查看状态
"""

import os, json, base64, hashlib, getpass
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    import cryptography
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

KEY_FILE = os.path.expanduser("~/.model_keys.json")
ENC_FILE = os.path.expanduser("~/.model_keys.enc")

# v4.1: 600k 迭代 + 随机 salt + AES-GCM
PBKDF2_ITERATIONS = 600_000


def _derive_key(password: str, salt: bytes) -> bytes:
    """从密码派生 256-bit AES key"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(password.encode())


def encrypt_keys(password: str = None):
    """AES-256-GCM 加密 JSON key 文件"""
    if not HAS_CRYPTO:
        print("需要 cryptography 库: pip install cryptography")
        return False
    if not os.path.exists(KEY_FILE):
        print(f"未找到 {KEY_FILE}")
        return False
    if not password:
        password = getpass.getpass("主密码: ")
        confirm = getpass.getpass("确认密码: ")
        if password != confirm:
            print("密码不匹配")
            return False

    with open(KEY_FILE, "r") as f:
        plaintext = f.read().encode()

    salt = os.urandom(32)        # v4.1: 随机 salt
    key = _derive_key(password, salt)
    nonce = os.urandom(12)       # GCM nonce (96-bit)
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(plaintext) + encryptor.finalize()

    # 格式: salt(32) + nonce(12) + tag(16) + ciphertext
    data = base64.b64encode(salt + nonce + encryptor.tag + ciphertext).decode()
    with open(ENC_FILE, "w") as f:
        f.write(data)
    print(f"已加密 → {ENC_FILE} (AES-256-GCM, 600k iterations)")
    return True


def decrypt_keys(password: str = None) -> dict:
    """AES-256-GCM 解密并返回 keys dict"""
    if not password:
        password = os.environ.get("AI_SUITE_MASTER_KEY", "")
        if not password:
            password = getpass.getpass("主密码: ")

    if os.path.exists(ENC_FILE):
        with open(ENC_FILE, "r") as f:
            data = base64.b64decode(f.read().strip())
        # v4.1 格式: salt(32) + nonce(12) + tag(16) + ciphertext
        salt = data[:32]
        nonce = data[32:44]
        tag = data[44:60]
        ciphertext = data[60:]

        key = _derive_key(password, salt)
        cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag))
        decryptor = cipher.decryptor()
        try:
            plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        except Exception:
            raise ValueError("密码错误或数据损坏")
        return json.loads(plaintext.decode())

    elif os.path.exists(KEY_FILE):
        # 降级: 明文文件
        with open(KEY_FILE, "r") as f:
            return json.load(f)
    return {}


def load_keys() -> dict:
    """统一加载 keys — 优先加密文件，降级明文"""
    return decrypt_keys()


def save_keys(keys: dict):
    """保存 keys 到明文 JSON"""
    with open(KEY_FILE, "w") as f:
        json.dump(keys, f, ensure_ascii=False, indent=2)
    # Windows 上也设只读属性
    try:
        os.chmod(KEY_FILE, 0o600)
    except Exception:
        if os.name == "nt":
            import subprocess
            subprocess.run(["icacls", KEY_FILE, "/inheritance:r", "/grant", f"{os.environ.get('USERNAME','Everyone')}:R"],
                          capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)


# ═══════ CLI ═══════

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "encrypt":
        encrypt_keys()
    elif cmd == "decrypt":
        keys = decrypt_keys()
        print(json.dumps({k: v[:20]+"..." if len(v) > 20 else v for k, v in keys.items()}, indent=2, ensure_ascii=False))
    elif cmd == "status":
        if os.path.exists(ENC_FILE):
            print(f"已加密: {ENC_FILE} (AES-256-GCM)")
        elif os.path.exists(KEY_FILE):
            print(f"明文: {KEY_FILE} (建议运行 encrypt)")
        else:
            print("未找到 key 文件")
    else:
        print("用法: python key_vault.py [encrypt|decrypt|status]")
