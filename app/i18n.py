"""한국어·영어 문구. 쓰는 자리에 두 언어를 나란히 적음: T("열기", "Open")."""

_korean = True


def use(language: str) -> None:
    global _korean
    _korean = language != "en"


def is_korean() -> bool:
    return _korean


def T(korean: str, english: str) -> str:
    return korean if _korean else english
