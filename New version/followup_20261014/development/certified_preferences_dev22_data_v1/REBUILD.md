# dev22 认证训练数据

`author_case_states`、`author_case_pairs`、逐折清单、计数及准备锁随Git保存。`training_labels/*.json.gz`是从逐案例认证状态/配对按冻结折清单拼接的本地派生副本；其中两个文件超过GitHub单文件100 MiB限制，不提交。它们的完整SHA-256仍在`preparation_lock.json`和`fold_index.json`中。

在独立检出中重建未提交的逐折文件：

```bash
/home/ayaka/hybridguard/.venv/bin/python qa/rebuild_certified_training_files_dev22.py
/home/ayaka/hybridguard/.venv/bin/python qa/audit_certified_training_dev22.py
```

重建器只读取已发布逐案例文件和元数据，不读取留出答案；每次写入后必须与已发布的逐折SHA完全一致。已经存在的文件只核验，不覆盖。原准备器为保留已锁证据而拒绝覆盖现有目录；不要删除或改写本地原锁。

压缩器固定mtime为0并保留稳定文件名、case顺序及JSON键顺序。重建需相同的上游标签、特征和锁；这些依赖均由准备锁绑定。此目录是已揭示开发数据，不是最终未见验证集。
