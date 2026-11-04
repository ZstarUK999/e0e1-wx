# 玩家分发包缓存

单人和多人分发包保存在 `settings.data_dir/packages/`，默认是
`server/backend/data/packages/`。下载完成后保留缓存，文件修改时间满 24 小时后删除。

HTTP 服务启动时清理一次，运行中每小时检查一次，因此文件通常保留 24 至 25 小时。
清理只匹配该目录中的 `e0e1-wx-plugins-*.zip` 普通文件，跳过符号链接；
不会清理发布版本、数据库、许可证私钥或其他目录。
单个文件删除失败会记录错误并继续，下轮再重试。

部署更新后的 `app/domain/packages.py`、`app/http/__init__.py` 和
`app/http/routers/players.py` 后重启：

```bash
sudo systemctl restart e0e1-server
sudo journalctl -u e0e1-server -n 50 --no-pager
```

重启后的首次清理也会处理此前积累的过期玩家包，无需额外配置 cron。
