"""Discord 메시지 본문 생성 (순수 함수, discord.py 불필요).

제목과 링크, 중복 확인용 식별 마커만 담는다. 작성자 닉네임, 익명 정보, 본문은 넣지 않는다.
Discord API v10 제한: embed 제목 256, 설명 4096, embed 전체 합계 6000, 일반 메시지 2000. 멘션은 보내지 않는다.
**제목 자체에 개인정보나 기업명이 들어 있을 수 있다.** 공개 서버로 나가는 내용이므로 서버 공개 범위를 확인해야 한다.
"""
import re
import unicodedata
from datetime import date

from career_share.policy import KIND_DIGEST, KIND_IMMEDIATE, classify, DIGEST_LABELS  # noqa: F401

NO_MENTIONS = {"parse": []}
EMBED_TITLE_LIMIT, EMBED_DESCRIPTION_LIMIT, EMBED_TOTAL_LIMIT = 256, 4096, 6000
FOOTER_LIMIT = 2048
TITLE_LIMIT = 200          # 즉시 공유 embed 제목
DIGEST_TITLE_LIMIT = 100   # 묶음 공유의 글 제목 (5개 합쳐도 4096자 이내)
IMMEDIATE_COLOR, DIGEST_COLOR = 0x2F80ED, 0x27AE60
DIGEST_TITLE = "오늘의 취업 준비 정보"
LINK_LABEL = "PlayMate에서 보기"
UNTITLED = "(제목 없음)"
MARKER_PATTERN = re.compile(r"^ref:[a-z0-9-]{1,60}$")
_MD_SPECIAL = re.compile(r"([\\`*_~|>\[\]()#<!])")
_ZWSP = "\u200b"


def post_unit_id(post_id: int) -> str:
    return f"post-{int(post_id)}"


def digest_unit_id(batch_date: date) -> str:
    return f"digest-{batch_date.isoformat()}"


def marker_for(unit_id: str) -> str:
    """메시지에 넣는 식별 마커 (embed footer). 조회로 기존 전송 여부를 확인할 때 쓴다."""
    marker = f"ref:{unit_id}"
    if not MARKER_PATTERN.match(marker):
        raise ValueError("unit_id 형식이 올바르지 않습니다.")
    return marker


def clean_title(title, limit: int) -> str:
    """제목을 한 줄로 만들고 제어문자를 제거하고 길이를 제한한다 (멘션/Markdown 처리는 별도)."""
    text = "".join(ch if unicodedata.category(ch)[0] != "C" or ch in "\n\t" else " " for ch in str(title or ""))
    text = " ".join(text.split()) or UNTITLED
    return text if len(text) <= limit else text[:limit - 1] + "…"


def defuse_mentions(text: str) -> str:
    """@everyone/@here/<@id> 같은 멘션 문자열이 멘션으로 보이지 않게 한다 (allowed_mentions도 비어 있다)."""
    return text.replace("@", "@" + _ZWSP)


def plain_title(title, limit: int) -> str:
    """embed.title처럼 Markdown이 해석되지 않는 곳에 쓰는 제목."""
    return defuse_mentions(clean_title(title, limit))


def markdown_title(title, limit: int) -> str:
    """Markdown이 해석되는 곳(설명)에 쓰는 제목: 링크 문법을 깨는 문자를 이스케이프한다."""
    return _MD_SPECIAL.sub(r"\\\1", defuse_mentions(clean_title(title, limit)))


def safe_url(url) -> str:
    """공백/괄호/제어문자가 없는 http(s) 주소만 허용한다. 아니면 ValueError (잘못된 링크를 만들어 보내지 않는다)."""
    if not isinstance(url, str) or not re.fullmatch(r"https?://[^\s()<>\\]+", url) or len(url) > 400:
        raise ValueError("공유할 수 없는 URL입니다.")
    return url


def _embed_size(embed: dict) -> int:
    return (len(embed.get("title", "")) + len(embed.get("description", "")) +
            len((embed.get("footer") or {}).get("text", "")) + len((embed.get("author") or {}).get("name", "")))


def immediate_payload(post: dict, url: str, label: str) -> dict:
    unit = post_unit_id(post["post_id"])
    embed = {
        "title": plain_title(post.get("title"), TITLE_LIMIT),
        "url": safe_url(url),
        "color": IMMEDIATE_COLOR,
        "author": {"name": f"📢 새 취업 후기 · {label}"},
        "description": f"[{LINK_LABEL}]({safe_url(url)})",
        "footer": {"text": marker_for(unit)},
    }
    _check(embed)
    return {"embeds": [embed], "allowed_mentions": dict(NO_MENTIONS)}


def digest_payload(entries: list[tuple[dict, str, str]], batch_date: date) -> dict:
    """entries: [(post, url, label)] 최대 5건. 한 메시지(embed 1개)로 만든다."""
    if not entries:
        raise ValueError("묶음 공유할 글이 없습니다.")
    lines = [f"**{defuse_mentions(label)}** · [{markdown_title(post.get('title'), DIGEST_TITLE_LIMIT)}]({safe_url(url)})"
             for post, url, label in entries]
    embed = {
        "title": DIGEST_TITLE,
        "color": DIGEST_COLOR,
        "description": "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1)),
        "footer": {"text": marker_for(digest_unit_id(batch_date))},
    }
    _check(embed)
    return {"embeds": [embed], "allowed_mentions": dict(NO_MENTIONS)}


def _check(embed: dict) -> None:
    if (len(embed.get("title", "")) > EMBED_TITLE_LIMIT or len(embed.get("description", "")) > EMBED_DESCRIPTION_LIMIT
            or len((embed.get("footer") or {}).get("text", "")) > FOOTER_LIMIT or _embed_size(embed) > EMBED_TOTAL_LIMIT):
        raise ValueError("Discord embed 길이 제한을 넘었습니다.")


def message_has_marker(message: dict, marker: str) -> bool:
    """기존 메시지가 이 마커를 가진 우리 메시지인가 (embed footer와 정확히 일치할 때만. 부분 일치는 post-12를 post-123으로 오인하므로 쓰지 않는다)."""
    if not isinstance(message, dict):
        return False
    return any(isinstance(e, dict) and (e.get("footer") or {}).get("text") == marker for e in message.get("embeds") or [])
