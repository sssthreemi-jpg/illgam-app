# 빌드 컨텍스트는 **저장소 루트**다 (docker-compose.yml 의 build.context: . 참조).
#   docker build -f backend/Dockerfile .
# backend/ 를 패키지 그대로 복사해야 `backend.main:app` 과 `from backend.calc import ...` 가 풀린다.
# (컨텍스트를 ./backend 로 두면 컨테이너 안에 backend 패키지가 없어 ModuleNotFoundError 가 난다.)
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# 애플리케이션 코드만. `.env` 와 `backend/data/*.json` 은 .dockerignore 로 제외되며
# 런타임에 볼륨/시크릿으로 주입한다.
COPY backend/ backend/

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
