# secrets.py — API 密钥的安全存取封装
# 本文件封装了对操作系统「密钥链（Keychain / Credential Store）」的读写操作。
# 不把 API 密钥存在数据库或配置文件里，而是存在操作系统的安全存储中，原因：
#   - macOS Keychain、Windows Credential Store、Linux Secret Service 都经过系统加密保护
#   - 即使用户的 ~/.dzmm 目录被拷走，密钥也不会泄漏
# keyring 库是跨平台封装，自动选择当前操作系统的安全存储后端。

import keyring  # 第三方库：统一访问各操作系统密钥链（macOS Keychain / Windows DPAPI / Linux libsecret）

# SERVICE 是密钥链里的「服务名」，相当于一个命名空间，
# 用于区分不同应用的密钥。所有 dzmm 的密钥都以 "dzmm" 为 service 存储。
SERVICE = "dzmm"


# ─────────────────────────────────────────────
# store_api_key：把 API 密钥安全地保存到操作系统密钥链
# 参数 ref：密钥的标识符（相当于「账号」），例如 "openai" 或某个模型配置 ID
# 参数 value：密钥的实际值（明文传入，keyring 负责加密存储）
# ─────────────────────────────────────────────
def store_api_key(ref: str, value: str) -> None:
    # keyring.set_password(service, username, password)
    # 以 SERVICE="dzmm" 为服务名、ref 为账号名，把 value 存入系统密钥链
    # 如果该 (service, ref) 组合已存在，则覆盖旧值
    keyring.set_password(SERVICE, ref, value)


# ─────────────────────────────────────────────
# get_api_key：从操作系统密钥链读取 API 密钥
# 参数 ref：之前存储时用的标识符
# 返回值：密钥字符串；如果该标识符不存在则返回 None
# ─────────────────────────────────────────────
def get_api_key(ref: str) -> str | None:
    # keyring.get_password 找不到时返回 None，不抛异常，调用方需自行判断是否为 None
    return keyring.get_password(SERVICE, ref)


# ─────────────────────────────────────────────
# delete_api_key：从操作系统密钥链删除 API 密钥
# 参数 ref：要删除的密钥标识符
# 不抛异常：如果密钥本来就不存在，静默忽略（幂等操作）
# ─────────────────────────────────────────────
def delete_api_key(ref: str) -> None:
    try:
        keyring.delete_password(SERVICE, ref)  # 尝试删除密钥
    except keyring.errors.PasswordDeleteError:
        # PasswordDeleteError：keyring 在找不到指定密钥时抛出的错误
        # 用 pass 静默忽略：「删除一个不存在的密钥」不应该让调用方崩溃，
        # 这符合「幂等」设计原则——多次调用结果相同
        pass


# ─────────────────────────────────────────────
# mask_key：把 API 密钥脱敏，用于在日志或 UI 中展示
# 参数 value：原始密钥字符串（可以为 None）
# 返回值：脱敏后的字符串，例如 "sk-abcd***xyz1"
# 目的：日志里不能出现完整密钥，但完全隐藏又没法确认密钥是否设置正确，
#       所以保留前6位和后4位，中间用 *** 遮盖
# ─────────────────────────────────────────────
def mask_key(value: str | None) -> str:
    # 如果密钥为 None 或太短（少于10位），无法安全脱敏，直接返回 "***"
    if not value or len(value) < 10:
        return "***"
    # f-string 拼接：取前6个字符 + "***" + 取后4个字符
    # 例如 "sk-abcdefghijklmnopqrstuvwxyz1234" → "sk-abc***1234"
    return f"{value[:6]}***{value[-4:]}"
