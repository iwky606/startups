run4:
	uvicorn server.main:app --reload --host 0.0.0.0 --port 8000

run6:
	uvicorn server.main:app --host :: --port 80