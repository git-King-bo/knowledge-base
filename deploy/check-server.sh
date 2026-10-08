#!/bin/sh
# 服务器只读检查脚本：不读取密码或密钥，不安装软件，不修改配置或服务。
# 在服务器执行：sh check-server.sh
# 或在 Mac 项目根目录执行：ssh aliyun_41 'sh -s' < deploy/check-server.sh

# 引用未定义的变量时报错，避免因变量拼写错误而继续执行。
# 不设置 set -e：某项检查失败时，仍继续收集其他检查结果。
set -u

# 公共函数：打印分段标题，方便区分每一步的输出。
section() { printf '\n=== %s ===\n' "$1"; }

# 第 1 步：检查操作系统和 CPU 架构，供后续选择安装方式和容器镜像。
section 'System'
# 显示内核名称和硬件架构，例如 Linux x86_64。
uname -sm
# 系统版本文件存在且可读时，显示发行版名称及版本。
if [ -r /etc/os-release ]; then cat /etc/os-release; fi

# 第 2 步：检查 CPU 数量、内存余量和当前系统负载。
section 'CPU and memory'
# 显示当前在线的逻辑 CPU 数量。
getconf _NPROCESSORS_ONLN
# 用易读的单位显示内存和交换空间；available 列可用于判断内存余量。
free -h
# 显示运行时长、登录用户数，以及最近 1、5、15 分钟的平均负载。
uptime

# 第 3 步：检查项目及 Docker 常用目录所在文件系统的剩余空间。
section 'Disk space'
# 显示根目录、/var 和 /opt 所在文件系统的容量、可用空间和使用率。
# 多个目录可能属于同一文件系统；目录不存在时会提示错误，不创建目录。
df -h / /var /opt

# 第 4 步：检查 Docker、Compose 是否可用，以及已有容器的端口占用。
section 'Docker'
# 只判断 docker 命令是否存在；隐藏查找命令本身的输出。
if command -v docker >/dev/null 2>&1; then
  # 显示 Docker 客户端版本，不代表 Docker 服务一定正在运行。
  docker --version
  # 显示 Compose 插件版本；未安装时会报错，脚本仍继续。
  docker compose version
  # 只列出运行中容器的名称、状态和端口，不读取容器环境变量。
  # Docker 服务未启动或当前用户无权限时，此命令会报错。
  docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
else
  # 未找到 Docker 命令时只给出提示，不自动安装。
  printf 'Docker is not installed\n'
fi

# 第 5 步：检查服务器正在监听的 TCP 端口，判断部署端口是否被占用。
section 'Listening TCP ports'
# 先判断系统是否提供 ss 命令。
if command -v ss >/dev/null 2>&1; then
  # -l：仅监听端口；-n：显示数字地址和端口；-t：仅 TCP。
  # 监听端口不等于公网可访问，还取决于防火墙和云安全组。
  ss -lnt
else
  # 工具缺失时只给出提示，不安装额外软件。
  printf 'ss is unavailable\n'
fi

# 第 6 步：读取常见主机防火墙的状态，不修改任何规则。
# 这不是完整的防火墙审计；不会列出所有独立的 iptables/nftables 规则。
# 阿里云安全组需要另外在云控制台检查，本脚本无法读取。
section 'Host firewall (cloud security groups must be checked separately)'
# 如果安装了 UFW，显示启用状态及规则；可能需要 root 权限。
if command -v ufw >/dev/null 2>&1; then ufw status; fi
# 如果安装了 firewalld，显示默认区域的当前配置；不代表所有区域。
# 服务未运行或权限不足时可能报错，不影响前面已收集的结果。
if command -v firewall-cmd >/dev/null 2>&1; then firewall-cmd --list-all; fi

# 第 7 步：标记检查结束；这不代表所有检查项都通过，需结合上方输出判断。
section 'Finished'
