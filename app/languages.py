"""Bảng ngôn ngữ dùng chung cho Whisper (ASR), Google Translate và NLLB-200."""

from __future__ import annotations

# code: ISO-639-1 (Whisper + Google dùng chung, trừ vài ngoại lệ ở GOOGLE_OVERRIDE)
# nllb: mã FLORES-200 của model NLLB
LANGUAGES: list[dict] = [
    {"code": "vi", "vi": "Tiếng Việt", "en": "Vietnamese", "flag": "🇻🇳", "nllb": "vie_Latn"},
    {"code": "en", "vi": "Tiếng Anh", "en": "English", "flag": "🇬🇧", "nllb": "eng_Latn"},
    {"code": "zh", "vi": "Tiếng Trung", "en": "Chinese", "flag": "🇨🇳", "nllb": "zho_Hans"},
    {"code": "ja", "vi": "Tiếng Nhật", "en": "Japanese", "flag": "🇯🇵", "nllb": "jpn_Jpan"},
    {"code": "ko", "vi": "Tiếng Hàn", "en": "Korean", "flag": "🇰🇷", "nllb": "kor_Hang"},
    {"code": "th", "vi": "Tiếng Thái", "en": "Thai", "flag": "🇹🇭", "nllb": "tha_Thai"},
    {"code": "fr", "vi": "Tiếng Pháp", "en": "French", "flag": "🇫🇷", "nllb": "fra_Latn"},
    {"code": "de", "vi": "Tiếng Đức", "en": "German", "flag": "🇩🇪", "nllb": "deu_Latn"},
    {"code": "es", "vi": "Tiếng Tây Ban Nha", "en": "Spanish", "flag": "🇪🇸", "nllb": "spa_Latn"},
    {"code": "pt", "vi": "Tiếng Bồ Đào Nha", "en": "Portuguese", "flag": "🇵🇹", "nllb": "por_Latn"},
    {"code": "ru", "vi": "Tiếng Nga", "en": "Russian", "flag": "🇷🇺", "nllb": "rus_Cyrl"},
    {"code": "it", "vi": "Tiếng Ý", "en": "Italian", "flag": "🇮🇹", "nllb": "ita_Latn"},
    {"code": "id", "vi": "Tiếng Indonesia", "en": "Indonesian", "flag": "🇮🇩", "nllb": "ind_Latn"},
    {"code": "ms", "vi": "Tiếng Mã Lai", "en": "Malay", "flag": "🇲🇾", "nllb": "zsm_Latn"},
    {"code": "hi", "vi": "Tiếng Hindi", "en": "Hindi", "flag": "🇮🇳", "nllb": "hin_Deva"},
    {"code": "ar", "vi": "Tiếng Ả Rập", "en": "Arabic", "flag": "🇸🇦", "nllb": "arb_Arab"},
    {"code": "tr", "vi": "Tiếng Thổ Nhĩ Kỳ", "en": "Turkish", "flag": "🇹🇷", "nllb": "tur_Latn"},
    {"code": "nl", "vi": "Tiếng Hà Lan", "en": "Dutch", "flag": "🇳🇱", "nllb": "nld_Latn"},
    {"code": "pl", "vi": "Tiếng Ba Lan", "en": "Polish", "flag": "🇵🇱", "nllb": "pol_Latn"},
    {"code": "uk", "vi": "Tiếng Ukraina", "en": "Ukrainian", "flag": "🇺🇦", "nllb": "ukr_Cyrl"},
    {"code": "cs", "vi": "Tiếng Séc", "en": "Czech", "flag": "🇨🇿", "nllb": "ces_Latn"},
    {"code": "sv", "vi": "Tiếng Thụy Điển", "en": "Swedish", "flag": "🇸🇪", "nllb": "swe_Latn"},
    {"code": "no", "vi": "Tiếng Na Uy", "en": "Norwegian", "flag": "🇳🇴", "nllb": "nob_Latn"},
    {"code": "da", "vi": "Tiếng Đan Mạch", "en": "Danish", "flag": "🇩🇰", "nllb": "dan_Latn"},
    {"code": "fi", "vi": "Tiếng Phần Lan", "en": "Finnish", "flag": "🇫🇮", "nllb": "fin_Latn"},
    {"code": "el", "vi": "Tiếng Hy Lạp", "en": "Greek", "flag": "🇬🇷", "nllb": "ell_Grek"},
    {"code": "he", "vi": "Tiếng Do Thái", "en": "Hebrew", "flag": "🇮🇱", "nllb": "heb_Hebr"},
    {"code": "fa", "vi": "Tiếng Ba Tư", "en": "Persian", "flag": "🇮🇷", "nllb": "pes_Arab"},
    {"code": "ro", "vi": "Tiếng Rumani", "en": "Romanian", "flag": "🇷🇴", "nllb": "ron_Latn"},
    {"code": "hu", "vi": "Tiếng Hungary", "en": "Hungarian", "flag": "🇭🇺", "nllb": "hun_Latn"},
    {"code": "bg", "vi": "Tiếng Bulgaria", "en": "Bulgarian", "flag": "🇧🇬", "nllb": "bul_Cyrl"},
    {"code": "hr", "vi": "Tiếng Croatia", "en": "Croatian", "flag": "🇭🇷", "nllb": "hrv_Latn"},
    {"code": "sr", "vi": "Tiếng Serbia", "en": "Serbian", "flag": "🇷🇸", "nllb": "srp_Cyrl"},
    {"code": "sk", "vi": "Tiếng Slovakia", "en": "Slovak", "flag": "🇸🇰", "nllb": "slk_Latn"},
    {"code": "ta", "vi": "Tiếng Tamil", "en": "Tamil", "flag": "🇱🇰", "nllb": "tam_Taml"},
    {"code": "bn", "vi": "Tiếng Bengal", "en": "Bengali", "flag": "🇧🇩", "nllb": "ben_Beng"},
    {"code": "ur", "vi": "Tiếng Urdu", "en": "Urdu", "flag": "🇵🇰", "nllb": "urd_Arab"},
    {"code": "tl", "vi": "Tiếng Philippines", "en": "Filipino", "flag": "🇵🇭", "nllb": "tgl_Latn"},
    {"code": "km", "vi": "Tiếng Khmer", "en": "Khmer", "flag": "🇰🇭", "nllb": "khm_Khmr"},
    {"code": "lo", "vi": "Tiếng Lào", "en": "Lao", "flag": "🇱🇦", "nllb": "lao_Laoo"},
    {"code": "my", "vi": "Tiếng Miến Điện", "en": "Burmese", "flag": "🇲🇲", "nllb": "mya_Mymr"},
]

BY_CODE = {item["code"]: item for item in LANGUAGES}

# Vài mã Google khác ISO-639-1
GOOGLE_OVERRIDE = {"zh": "zh-CN", "he": "iw", "tl": "tl"}

# RTL — dùng để chèn dấu định hướng khi render phụ đề
RTL = {"ar", "he", "fa", "ur"}


def google_code(code: str) -> str:
    return GOOGLE_OVERRIDE.get(code, code)


def nllb_code(code: str) -> str:
    item = BY_CODE.get(code)
    return item["nllb"] if item else "eng_Latn"


def name_vi(code: str | None) -> str:
    if not code:
        return "Tự động"
    item = BY_CODE.get(code)
    return item["vi"] if item else code


def name_en(code: str | None) -> str:
    if not code:
        return "auto-detected"
    item = BY_CODE.get(code)
    return item["en"] if item else code
