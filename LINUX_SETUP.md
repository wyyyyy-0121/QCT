# FormulaGuard Linux 环境

Linux 工作目录为 `/home/ayaka/QCT`。Windows 原目录保留为迁移备份。

## 使用环境

当前隔离环境位于项目内 `.venv`：

```bash
cd /home/ayaka/QCT
conda activate /home/ayaka/QCT/.venv
```

退出项目环境：

```bash
conda deactivate
```

从头重建环境：

```bash
conda env create --prefix .venv --file environment.yml
python -m pip install --editable .
```

`node_modules/@oai/artifact-tool` 是 Codex 运行时提供的私有工具，不在公共 npm
仓库中，也不会提交到 Git。迁移到另一台机器时需要随项目本地数据单独保留。

## 常用命令

```bash
./run_tests.sh
./diagnose.sh /path/to/workbook.xlsx --top 10
```

Windows 的 `.cmd` 和 `.ps1` 入口作为历史复现材料保留。Linux 下可直接使用
`.venv/bin/python scripts/<script>.py` 和 `.venv/bin/node scripts/<script>.mjs`。

## 实验结果

`results/` 被 Git 忽略，不会随提交上传。单独复制完成后应位于：

```text
/home/ayaka/QCT/results
```

## GitHub SSH

Linux 的 Git 凭据不会从 Windows 自动迁移。推荐为 Linux 单独创建 SSH 密钥，
将公钥添加到 GitHub 的 `Settings > SSH and GPG keys > New SSH key`，然后把远端
改为。当前网络阻断了 SSH 22 端口，因此使用 GitHub 官方支持的 443 端口：

```bash
git remote set-url origin ssh://git@ssh.github.com:443/wyyyyy-0121/QCT.git
git config core.sshCommand \
  "ssh -i /home/ayaka/.ssh/id_ed25519_qct -o IdentitiesOnly=yes"
ssh -T -p 443 -i ~/.ssh/id_ed25519_qct git@ssh.github.com
git push --dry-run origin HEAD
```
