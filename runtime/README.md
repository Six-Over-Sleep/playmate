# EC2 Discord Gateway 실행기 (`start_gateway.py`)

`playmate-discord-gateway` systemd 서비스가 root로 실행하는 스크립트다. 순서는 다음과 같다.

1. `/etc/playmate/api.env`에서 `DB_*`, `PGSSLROOTCERT`만 읽는다.
2. `/etc/playmate/discord-gateway.conf`에서 허용된 `PLAYMATE_*` 키만 읽는다.
3. 기능 스위치를 검사한다. 실패하면 **종료 코드 78**로 멈추고 아래 단계는 실행하지 않는다.
4. Secrets Manager `playmate/beta/discord-gateway`에서 `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`를 읽는다.
5. `ubuntu`로 권한을 내린 뒤 `/opt/playmate-discord/.venv/bin/python bot.py`를 `execve`로 실행한다.

## 기능 스위치

`discord-gateway.conf`에 적은 값은 실행기가 덮어쓰지 않는다 (Issue #190 이전에는 아래 네 값을 강제로 덮어썼다).

| 키 | 없음·빈 값 | 허용 값 | 그 밖의 값 |
|---|---|---|---|
| `PLAYMATE_CAREER_NOTICE_ENABLED` | 켜짐 (18:00 취업 공지) | true/false/1/0/yes/no/on/off | 종료 78 |
| `PLAYMATE_DM_POLL_ENABLED` | 켜짐 (10초 DM 폴링) | true/false/1/0/yes/no/on/off | 종료 78 |
| `PLAYMATE_TEST_MODE` | 꺼짐 | true/false | 종료 78 |
| `PLAYMATE_STRAY_REVOKE_ENABLED` | 꺼짐 (dry-run) | true/false | 종료 78 |

대소문자, 앞뒤 공백, 따옴표는 무시한다. `/알림설정`, 모임 채널 생성·권한·라이프사이클, 공식 채널은 스위치와 관계없이 동작한다.

**서버리스와의 중복 방지**: Career·DM은 키가 없으면 켜진다 (기존 동작 호환). Career·DM 서버리스를 켜기 전에
해당 키를 반드시 `false`로 **명시**하고 `--check`로 확인한다. 운영 conf에는 네 키를 모두 명시하는 것을 권장한다.

## 설정 사전 검사

```bash
sudo <서비스와 같은 python> /opt/playmate-discord/runtime/start_gateway.py --check
```

두 설정 파일만 읽는다. Secrets Manager·Discord·DB에 접근하지 않고 권한도 바꾸지 않는다.
성공하면 종료 코드 0과 스위치 요약(`키=값`, 기본값이면 `(기본값)`)을 출력하고, 실패하면 78과 오류 키 이름을 출력한다.
설정 값이나 비밀값은 출력하지 않는다. 서비스의 python 경로는 `systemctl cat playmate-discord-gateway`의 `ExecStart`로 확인한다.

## systemd 필수 설정

설정 오류(78)는 재시작해도 고쳐지지 않는다. `Restart=on-failure`만 있으면 재시작이 반복되므로
서비스의 `[Service]`에 다음을 둔다 (기존 unit은 이 저장소에 없으므로 EC2에서 확인 후 승인을 받아 추가한다).

```ini
[Service]
Restart=on-failure
RestartPreventExitStatus=78
```

확인: `systemctl show playmate-discord-gateway -p RestartPreventExitStatus` → `RestartPreventExitStatus=78`.
unit을 바꾼 뒤에는 `sudo systemctl daemon-reload`가 필요하다.
Secrets Manager 조회 실패, Discord·DB 연결 실패처럼 일시적일 수 있는 오류는 78이 아니므로 기존처럼 재시작된다.
실행기를 거치지 않고 `python bot.py`를 직접 실행할 때의 스위치 오류는 bot의 `config.py`가 막지만 종료 코드는 1이다.

## `.env` 혼입 주의

bot의 `config.py`는 `load_dotenv()`로 `playmate-discord-bot/` 폴더부터 상위 폴더까지 올라가며 처음 찾은 `.env`를 읽는다.
실행기가 넘긴 값은 덮어쓰지 않지만, **실행기가 넘기지 않은 키(conf에 없거나 빈 값인 스위치 포함)는 `.env` 값으로 채워진다**.
배포 전에 다음 위치에 `.env`가 없는지 확인한다 (내용은 출력하지 않는다).

```bash
for d in /opt/playmate-discord/playmate-discord-bot /opt/playmate-discord /opt /; do sudo test -e "$d/.env" && echo "있음: $d/.env"; done
```

## 기존 EC2 파일 교체 (Git 미추적 → 추적)

이 파일이 Git에 들어가기 전 EC2에는 같은 경로에 미추적 파일이 있다. 그대로 `git pull`하면
`untracked working tree files would be overwritten`으로 실패한다.

1. 서비스가 중지되어 있는지 확인한다: `systemctl is-active playmate-discord-gateway`
2. 기존 파일을 백업한다: `sudo cp -p /opt/playmate-discord/runtime/start_gateway.py /root/start_gateway.py.before-190`
3. 백업과 새 버전을 비교해 차이가 기능 스위치 처리, `--check`, 설정 오류 처리뿐인지 확인한다.
4. 기존 미추적 파일을 치운 뒤(`sudo mv` 등) 승인된 커밋으로 갱신하고 `git status`로 깨끗한지 확인한다.
5. `--check`를 실행하고, systemd에 `RestartPreventExitStatus=78`이 있는지 확인한다.
6. 서비스 시작은 별도 승인 후에 한다.
