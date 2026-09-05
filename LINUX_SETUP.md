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
python -m formulaguard.cli /path/to/workbook.xlsx --method v5_psl --json /tmp/v5_psl.json
```

Windows 的 `.cmd` 和 `.ps1` 入口作为历史复现材料保留。Linux 下可直接使用
`.venv/bin/python scripts/<script>.py` 和 `.venv/bin/node scripts/<script>.mjs`。

`V5-PSL-dev1`在内部求值覆盖不足时会自动启动隔离、禁用宏的LibreOffice进程。
候选冻结会拒绝未安装LibreOffice的环境，先核对当前安装：

```bash
libreoffice --version
python scripts/prepare_v5_psl_public_corpora.py show --json
```

六语料下载、清点、补充角色审计和公开压力重审的完整Linux命令见
`research/V5_PSL_PUBLIC_PRESSURE_PROTOCOL.md`。正式SpreadsheetBench审计不得限制
总清单，并须成功诊断最多25个可解析且含公式的工作簿。

公开语料下载到`data/external/v5_psl/raw/`，该目录已被Git忽略。许可不清的语料
即使可以下载，也只能在本机做研究审计，不能随仓库或第三方PUBLIC包再分发。

第三方确认阶段使用三个相互分离的目录：保管人生成的`PUBLIC/`、本地只含无标签
分片的`results/v5_psl_independent_predictions/`，以及预测锁成功后才取得的
`FormulaGuard_V5_PSL_SECRET_360.zip`。不要提前把SECRET解压到项目目录。

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
