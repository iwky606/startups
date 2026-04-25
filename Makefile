run4:
	uvicorn server.main:app --reload --host 0.0.0.0 --port 8000

run6:
	uvicorn server.main:app --host :: --port 80

server_ip=2408:8763:0:909:3249:e390:4abc:2440

login_server:
	ssh root@[${server_ip}]


# git remote add server ssh://root@[2408:8763:0:909:3249:e390:4abc:2440]/~/startup.git
