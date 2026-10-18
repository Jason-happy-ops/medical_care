"""pytest 根级配置。

作用有两个：
1. 让项目根目录进入 sys.path，保证 `import app` 在测试中可用；
2. 注入一个虚拟 AI_API_KEY，避免测试误读真实 .env 中的密钥（测试不会真正调用视觉 API）。
"""
import os

os.environ.setdefault("AI_API_KEY", "test-dummy-key")
