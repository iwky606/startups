# Git 直接推送到服务器部署方案

---

## 一、服务器初始化（一次性）

```bash
# 建裸仓库（专门接收 push，不存工作文件）
git init --bare ~/myproject.git

# 建工作目录（实际运行代码的地方）
mkdir ~/myproject
```

---

## 二、本地配置 remote

```bash
# IPv6 地址需要用方括号包住
git remote add server ssh://root@[2001:db8::1]/~/myproject.git

# 推送
git push server master
```

推荐配置 `~/.ssh/config` 简化地址：

```
Host myserver
    HostName 2001:db8::1
    User root
    IdentityFile ~/.ssh/id_ed25519
```

配置后可以直接用名字：

```bash
git remote add server ssh://myserver/~/myproject.git
```

---

## 三、post-receive Hook 自动部署

每次 `git push` 后自动触发，完成代码签出 + 服务重启。

```bash
# 写入 hook
echo '#!/bin/bash' > ~/myproject.git/hooks/post-receive
echo 'git --work-tree=/root/myproject --git-dir=/root/myproject.git checkout -f master' >> ~/myproject.git/hooks/post-receive
echo 'supervisorctl restart myservice' >> ~/myproject.git/hooks/post-receive

# 给执行权限
chmod +x ~/myproject.git/hooks/post-receive
```

hook 完整内容：

```bash
#!/bin/bash
git --work-tree=/root/myproject --git-dir=/root/myproject.git checkout -f master
supervisorctl restart myservice
```

---

## 四、venv 单独目录管理（最佳实践）

**不推荐：** venv 放在工程目录下

```
myproject/
  venv/        ← 容易被 git 误提交，路径变动导致 shebang 失效
  main.py
```

**推荐：** venv 单独存放，与工程解耦

```
/root/
  myproject/           ← 工作目录（git 管理）
  myproject.git/       ← 裸仓库
  venvs/
    myproject-venv/    ← venv 单独管理
```

创建与使用：

```bash
# 创建
python3 -m venv /root/venvs/myproject-venv

# 装依赖
/root/venvs/myproject-venv/bin/pip install -r /root/myproject/requirements.txt

# supervisor 里直接用绝对路径
command=/root/venvs/myproject-venv/bin/uvicorn main:app ...
```

好处：
- 重建工程目录不影响 venv
- venv 路径固定，shebang 永远有效
- 多个项目的 venv 统一管理

---

## 五、日常工作流

```bash
# 本地改完代码，一条命令部署
git push server master
# 服务器自动：签出代码 → 重启服务
```
