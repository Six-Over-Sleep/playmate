"""Discord Worker Lambda 진입점: 봇 토큰을 Secrets Manager에서 콜드 스타트 때 한 번 읽어 기존 Worker 핸들러에 넘긴다.

기존 핸들러(career_share.worker_lambda.handler 등)는 DISCORD_BOT_TOKEN 환경변수를 읽는다. 그 코드를 바꾸지 않으려고
이 모듈이 시크릿 값을 **프로세스 안의** os.environ에만 넣는다 (Lambda 설정·템플릿·로그에는 값이 남지 않는다).

환경변수
  WORKER_TARGET_HANDLER              위임할 핸들러 (허용 목록만: career_share / hot_share / dm_share 의 worker_lambda.handler)
  DISCORD_BOT_TOKEN_SECRET_ARN       토큰 시크릿 ARN (DISCORD_BOT_TOKEN이 이미 있으면 읽지 않는다 = 로컬 시험용)
  DISCORD_BOT_TOKEN_SECRET_JSON_KEY  시크릿이 JSON이면 토큰이 들어 있는 키 (비우면 시크릿 문자열 전체가 토큰)

토큰은 컨테이너가 살아 있는 동안 캐시된다. 토큰을 바꾼 뒤에는 템플릿 파라미터 DiscordBotTokenVersion을 올려 배포한다
(함수 설정이 바뀌어 이전 토큰을 캐시한 실행 환경이 교체된다). 조회 실패는 캐시하지 않는다 (다음 호출에서 다시 읽는다).
"""
import importlib
import json
import os

ALLOWED_TARGETS = (
    "career_share.worker_lambda.handler",
    "hot_share.worker_lambda.handler",
    "dm_share.worker_lambda.handler",
)
_target = None


class TokenSecretError(RuntimeError):
    """토큰 시크릿을 읽을 수 없다. 메시지에 시크릿 값을 넣지 않는다."""


def _secrets_client():
    import boto3  # Lambda Python 런타임에 포함되어 있다
    return boto3.client("secretsmanager")


def load_token(client=None) -> None:
    """DISCORD_BOT_TOKEN을 프로세스 환경에 채운다. 이미 있으면 아무것도 하지 않는다."""
    if (os.environ.get("DISCORD_BOT_TOKEN") or "").strip():
        return
    secret_id = (os.environ.get("DISCORD_BOT_TOKEN_SECRET_ARN") or "").strip()
    if not secret_id:
        raise TokenSecretError("DISCORD_BOT_TOKEN_SECRET_ARN이 없습니다.")
    try:
        response = (client or _secrets_client()).get_secret_value(SecretId=secret_id)
    except Exception as error:  # botocore 예외 이름만 남긴다
        raise TokenSecretError(f"토큰 시크릿 조회 실패: {type(error).__name__}") from None
    value = response.get("SecretString")
    if not isinstance(value, str):
        raise TokenSecretError("토큰 시크릿이 문자열(SecretString)이 아닙니다.")
    key = (os.environ.get("DISCORD_BOT_TOKEN_SECRET_JSON_KEY") or "").strip()
    if key:
        try:
            value = json.loads(value)[key]
        except (ValueError, KeyError, TypeError):
            raise TokenSecretError("토큰 시크릿 JSON에 지정한 키가 없습니다.") from None
        if not isinstance(value, str):
            raise TokenSecretError("토큰 시크릿 JSON 값이 문자열이 아닙니다.")
    token = value.strip()
    if not token:
        raise TokenSecretError("토큰 시크릿이 비어 있습니다.")
    os.environ["DISCORD_BOT_TOKEN"] = token


def _resolve_target():
    name = (os.environ.get("WORKER_TARGET_HANDLER") or "").strip()
    if name not in ALLOWED_TARGETS:
        raise TokenSecretError("WORKER_TARGET_HANDLER가 허용 목록에 없습니다.")
    module_name, function_name = name.rsplit(".", 1)
    return getattr(importlib.import_module(module_name), function_name)


def handler(event, context=None):
    """첫 호출에서 토큰을 읽고 대상 핸들러를 정한다. 실패하면 예외 = 호출 실패(SQS가 재전달, 반복되면 DLQ)."""
    global _target
    if _target is None:
        target = _resolve_target()   # 설정 오류면 시크릿을 읽기 전에 멈춘다
        load_token()
        _target = target
    return _target(event, context)
