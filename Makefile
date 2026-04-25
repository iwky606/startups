server_ip=2408:8763:0:909:3249:e390:4abc:2440

run4:
	uvicorn server.main:app --reload --host 0.0.0.0 --port 8000

run6:
	uvicorn server.main:app --host :: --port 80

login_server:
	ssh root@[${server_ip}]

# 触发git hook, 自动重启
deploy:
	git push server master