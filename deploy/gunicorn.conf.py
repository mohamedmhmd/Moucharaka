import multiprocessing
import os

bind = os.environ.get("BIND", "0.0.0.0:" + os.environ.get("PORT", "8000"))
workers = int(os.environ.get("WEB_CONCURRENCY", min(multiprocessing.cpu_count() * 2 + 1, 6)))
timeout = 60
accesslog = "-"
errorlog = "-"
forwarded_allow_ips = "*"
