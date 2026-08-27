"""backend package initializer."""
import os

from dotenv import load_dotenv

# backend/.env 를 네이티브 실행에서도 읽는다.
#
# 여기(패키지 __init__)에 두는 이유: auth.py 와 main.py 가 import 시점에 모듈 레벨로
# os.environ 을 읽으므로(JWT_SECRET / ADMIN_* / ALLOWED_ORIGINS), 그보다 먼저 실행돼야 한다.
#
# 경로를 명시하는 이유: 인자 없는 load_dotenv() 는 CWD 부터 위로 훑어서 `.env` 를 찾는데,
# 이 저장소의 파일은 루트가 아니라 backend/.env 다.
#
# override=False(기본값) 이므로 우선순위는
#   실제 환경변수  >  backend/.env  >  코드의 기본값
# 도커에서는 compose 가 env_file 로 진짜 환경변수를 주입하고 이미지 안에는 .env 가 없다
# (.dockerignore 의 `**/.env`). 따라서 컨테이너 동작은 바뀌지 않는다.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

__version__ = "0.1"
