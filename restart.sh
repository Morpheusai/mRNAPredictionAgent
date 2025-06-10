#!/bin/bash

# 获取占用端口 60718 的 PID
PID=$(lsof -t -i :60718)

if [ -z "$PID" ]; then
    echo "没有找到占用端口 60718 的进程。"
else
    echo "找到占用端口 60718 的进程，PID 为 $PID。正在杀死该进程..."
    kill -9 $PID
    echo "进程已杀死。"
fi

# 重新启动 Streamlit 应用
echo "正在重新启动 Streamlit 应用..."
#nohup bash run.sh 1>log_prd 2>err_prd&
bash run.sh 
