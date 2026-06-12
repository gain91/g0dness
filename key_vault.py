"""
AI Suite — Key Vault (v4.0)
加密存储 API Keys，支持主密码加解密
用法:
  python key_vault.py encrypt    # 加密 ~/.model_keys.json → ~/.model_keys.enc
  python key_vault.py decrypt    # 解密查看
"""

import os, json, base64, hashlib, getpass
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

KEY_FILE = os.path.expanduser("~/.model_keys.json")
ENC_FILE = os.path.expanduser("~/.model_keys.enc")
SALT = b"ai-suite-key-vault-v4"

def _derive_key(password: str) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=SALT, iterations=100000)
    return kdf.derive(password.encode())

def encrypt_keys(password: str = None):
    """加密 JSON key 文件"""
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

    key = _derive_key(password)
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()

    # PKCS7 padding
    pad_len = 16 - (len(plaintext) % 16)
    padded = plaintext + bytes([pad_len] * pad_len)
    ciphertext = encryptor.update(padded) + encryptor.finalize()

    data = base64.b64encode(iv + ciphertext).decode()
    with open(ENC_FILE, "w") as f:
        f.write(data)
    print(f"已加密 → {ENC_FILE}")
    return True

def decrypt_keys(password: str = None) -> dict:
    """解密并返回 keys dict"""
    if not password:
        # Try env var first
        password = os.environ.get("AI_SUITE_MASTER_KEY", "")
        if not password:
            password = getpass.getpass("主密码: ")

    if os.path.exists(ENC_FILE):
        with open(ENC_FILE, "r") as f:
            data = base64.b64decode(f.read().strip())
        iv, ciphertext = data[:16], data[16:]
        key = _derive_key(password)
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        pad_len = padded[-1]
        plaintext = padded[:-pad_len]
        return json.loads(plaintext.decode())
    elif os.path.exists(KEY_FILE):
        # Fallback: plaintext file
        with open(KEY_FILE, "r") as f:
            return json.load(f)
    return {}

def load_keys() -> dict:
    """统一加载 keys — 优先加密文件，降级明文"""
    return decrypt_keys()


# ═══════ CLI ═══════

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "encrypt":
        encrypt_keys()
    elif cmd == "decrypt":
        keys = decrypt_keys()
        print(json.dumps({k: v[:20]+"..." for k, v in keys.items()}, indent=2, ensure_ascii=False))
    elif cmd == "status":
        if os.path.exists(ENC_FILE):
            print(f"已加密: {ENC_FILE}")
        elif os.path.exists(KEY_FILE):
            print(f"明文: {KEY_FILE} (建议运行 encrypt)")
        else:
            print("未找到 key 文件")
    else:
        print("用法: python key_vault.py [encrypt|decrypt|status]")
