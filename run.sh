nohup uvicorn app:app \
  --timeout-keep-alive 21600 \
  --timeout-graceful-shutdown 1200 \
  --host 0.0.0.0 \
  --port 60718 \
  >>log 2>>err &
