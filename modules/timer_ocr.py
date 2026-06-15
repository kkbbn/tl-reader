from __future__ import annotations

from itertools import product
from pathlib import Path

from .geometry import TIMER_RECT, scale_rect
from .models import Frame, VideoInfo
from .video import read_frame


TEMPLATE_WIDTH = 16
TEMPLATE_HEIGHT = 24
TEMPLATE_BITS = TEMPLATE_WIDTH * TEMPLATE_HEIGHT

SLOT_X = (-2, 18, 44, 64, 90, 109, 127)
SLOT_WIDTH = 23
SLOT_HEIGHT = 30

TEMPLATE_HEX: dict[str, tuple[str, ...]] = {
    "0": (
        "00f883fe83dec30ec60ece0f8e0f1e0e1c0e1c0e1c0e180e180e180c180c3818381838183838387818701fe01fc00f80",
        "4078e1fce3ce87860707060706070e070c060c061c061c061c0e3c0c3c0c3c1c3c1c3c3c3c383c383c701fe00fe00780",
        "807cc0fec3c7c387c787e707e607e607ee07ce07cc07cc07cc079c0e9c0c9c0c9c1c9c1c1c1c1c381c301fe00fe007c0",
        "00fc07fe0f9e0e0e1c0e380f380f780f700f700ef00ee00ee01ee01ce01ce018e038e038e070e0f0e0e0ffc07f803f00",
        "00f883fe83cec70ec60fce0f8e0f1e0e1c0e1c0e1c0e180e180e380c380c3818381838183838187818701fe01fc00f80",
        "c0f8c3fec3dec70e860f8e0f0e0f1e0e1e0e1c0e1c0e180e180c180c380c3818381838383838387818701fe01fc00f80",
        "00f883fe83dec70ec60fce0f8e0f1c0f1c0e1c0e180e180e180e180c380c3818381838183838387818701fe01fc00f80",
        "00f883fe83dec70ec60fce0f8e0f1e0e1c0e1c0e180e180e180c180c180c3818381838383838387838701fe01fc00f80",
        "807c80fec1cfe387e787e707e607e607e607cc07cc06cc06cc06dc0e9c0c9c0c9c0c9c1c9c1c1c381c301fe00fe007c0",
        "01fc07fc0fbe0e0f1c0f3c0f380f780f780f700e700ee00ee00ee01ee01ce03ce038e038e078e0f0e0e0ffc0ff803f00",
        "00f883fe83dec70ec60fce0f8e0f1e0f1c0e1c0e1c0e180e180e380c380c381c381830183838387838701fe01fc00f80",
        "00f883fe83dec70ec60fce0f8e0e1c0e1c0e1c0e180e180e180c380c381c381838183838387838701fe01fc00f80",
        "00fcc1fec3cfc38fc70fc6078e070e071e071c079c0f9c0e9c0e180c180c180c181c3818183818781c701fe01fc00f80",
        "c0f8c3fcc3cec70e860e860f0e0f1e0f1c0e180e180e180e180e180c381c3818381838383838387838701fe01fc00f80",
        "007cc1fec1efe387e787e707e707e607e607ce07cc07cc06cc06dc0e9c0c9c0c9c0c9c1c1c1c1c381c381ff00fe007c0",
        "01f807fe0f9e1e0f1c0f380f380f780f780f700ee00ee00ee01ee01ee01ce03ce03ce038e070e0f0e0e0ffc07f803f00",
        "00fc01fe03ce070f060f8e07ce07de0f9c0f9c0e9c0e1c0e180e180c380c180c38181818383818781c701fe01fc00f80",
        "00fc03fe03cf078f070f8e0fce0fde0f9c0f9c0f9c0e180e180e180e180c180c181c3818383818781c701fe01fc00f80",
        "01fc83fec3cec30fc70fc60fce0f1e0f1c0f1c0e1c0e1c0e180e180e180c380c38183838183818781c701fe01fc00f80",
        "80fcc1fcc3dee38ee706e606ee06ee06ee06ee06cc0edc0edc0c980c981c981c981cb818383918301c700ff00fc00f80",
        "03f807fc0f3c0c1e1c1e381e381e781e701e701ef01ce03ce03ce038e038e038e038e031e061e0e0f1e0ffc07f803e00",
        "00fc83fec3cec30fc70fce0fce0f9e0f1c0f1c0e1c0e1c0e180e180c180c380c38183818383818781c701fe01fc00f80",
        "678e479f4d9b089b089318b318b318331823182318230c230e231c2398229822912291621124132413241e3c1e381c18",
    ),
    "1": (
        "800e800e000c001c001c003c003c003800380038007000700070007000f000f000f000ff01ff01fc01f001c003800380",
        "8006c00ec00ec00ee01ee01cc01c801c003c003800380038007800700070007000f000ff00ff00fc01f001c001c00180",
        "400ce01cc01c801c003c0038003800380070007000700070007000e000e000e000e000ff00fe00f801e001c001800180",
        "800ec00ec01ec01cc01c801c003c003800380038803880788070807080f080f080f000ff01ff01f801e001c001800100",
        "000e800ec00ec01ec01cc01c801c003800380038807880788070007000f000f000fa01ff01ff01f801e001c001800100",
        "80000000000000000000000000000000000000000000000000200e7112da328e228e229e679365166534653479e738c7",
    ),
    "2": (
        "63ffe7ffe3ff00070006001c001c0078007001e003c007800e000e008c009808981818183818383838701ff01fe00fc0",
        "825ecfffcffec00ec01cc01cc03cc070c1f083c087800f000e001c0038003810383038303870387038703fe01fc00f00",
        "e7feefffeffec00ec01c801c8038007000f003c007800f000e001c0038003810381838303830387038703fe03fc00f80",
        "c3ffe7ffc7ff00070007000e003c003800f801e003c007800f000c001c003c0c381c381c383838383c703fe01fe00f80",
        "e3ffe7ffe3ff00070006001c001c0078007001e003c007800e000e009c00981898183818381818381c701ff01fe00f80",
        "87ff87ffc7ffc00ec00ec01cc03cc070c0f0c3e0c3c0cf008e009c009c00b800b81838183838387038703fe01fc00f80",
        "c3ffe7ffc3ff80070007000e003c007c00f001e003c007800f001c001c003c0c381c381c383c3c383c703fe01fe00f80",
    ),
    "3": (
        "40fce3fee3de070706070e070e060e000e000e000f0007c003c007808e008c009c001818181818301c701ff00fe00f80",
        "40fce3fee3de070706070e070e060e000e000e000e0007c003c007808e008c009c101818181818301c701ff00fe00f80",
        "80fce3fee3dee70ee707ee07ee060e040e000e000f0007c003c007c00e000c001c009818181818301c701fe00fc00f80",
        "03fc0fff0f9f1e0f3c07380738077000700078003e003f801f803e007800f000e000e038e070e0f0e0e0ffc07f803f00",
        "60fce3fee3de070706070e070e060e000e000e000f0007c003c00fc08e008c009c001818181818301c701ff00fe00f80",
        "807cc3fec7cee707e607c607cc070c020c000e000f00078007c007800e001c001c00383c383c3c383c703fe01fe00f80",
        "80fce3fee3dee707e607ee06ee060e000e000e000f0007c003c007c00e000c001c009818181818301c701fe00fe00fc0",
        "03fc0fff1f9f1e0f3c07380778077800700078007c003f801f803e007800f000e000e038e070e0f0e0e0ffc0ff803f00",
        "60fce3fee3de070706070e070e060e000e000e000f0007c003c00f808e008c009c181818181818381c701ff00fe00fc0",
        "60fce3fee3de070706070e070e060e000e000e000f0007c003c007808e008c009c001818181818301c701ff00fe00f80",
        "81fce3fee3cee707e607ee07ee060e040e000e000f0007c003c007c00e000c0018009818981818301c701ff00fe00fc0",
        "03fc0fff1f9f1e0f3c07380778077800780078007c003f801f803f807800f000e000e038e078e0f0e0e0ffc0ff803f00",
        "40fce3fee3de070706070e070e060e000e000e000f0007c007c00f808e008c009c101818181818301c701ff00fe00fc0",
        "80fce3fee3dee707e607ee07ee070e000e000e000f0007c003c007c00e000c001c089818981818301c701ff00fe00fc0",
        "03fc07ff1f9f1e0f3c07380778077800780078007c003f801f803f007800f000e010e038e078e0f0f0e0ffc0ff803f00",
        "80fce3fee3cee707ee07ee07ee060e000e000e000e0007c007c00f000e000c001c089818183818301c701ff00fe00f80",
        "03fc07ff0f1f1e073c07780778077000780078003c003f801f803e007800f000e030e038e070e0f0f0e0ffc07f803f00",
        "41fce3fee3df078706070e070e070e000e000e000e0007c007e007808e008e000c181c1818181c301c701ff00fc007c0",
        "61fce3fee3cf070706070e070e070e020e000e000f0007c007c007c08e008e000c181c1818181c381c701ff00fe00fc0",
        "80fce3fee3dfe707e607ee07ee070e000e000e000f0007c007c00fc00e000c001c18981838381c301c701ff00fe00fc0",
        "03f80ffe1e3e1c1e3c0e780e780e7800780078003c003f003f803e007800f000e020e030e061e0e0f1e0ffc07f803e00",
        "2100210821180118031082100210021002100610041004100410041008310831083108391838103010201e201e200220",
    ),
    "4": (
        "01c081c081c083c0c3c0c7ffcfffcfff87878307870e870c8608861886308e600e600ec01fc01f801f001f001e001c00",
        "018001c003c003c003c087fecfffcfffc7878306830e070c0618061806300e600e600ec01fc01f801f001f001e001e00",
        "c0c0e1c0c1800180018007fe0fff0fff078707860704070c071c07380630062006600ec00ec00f800f801f001e000c00",
        "8080c180c180e180e380e7feefff0fff078707860704070c071c07380730062006600ec00c800f800f801f001e001c00",
        "61c0e1c0e1c001c003c007fe0fff0fff07860306030c031c0718061086308e708e600e400fc00f800f000e000e000e00",
        "61c0e1c0e1c001c003c007fe0fff0fff03860386030c071c0718061086308e708e600ec00fc00f800f000f000e000e00",
        "80c0c0c0c180e180e380e7ffcfff07ff078607860784070c071c07380630066006600cc00ec00f800f800f000e000c00",
        "c1c0e180e380e380c3808ffe9fff0fff07860706070c071c073806300e300e600ee00cc00f801f801f801f001e001c00",
        "80c0c1c0e180e180e380e7fcefff0fff078707860784070c071c0738063006600e600cc00ec00f800f801f001e000c00",
    ),
    "5": (
        "00fc83fec78ec707c707ce06cc02dc00dc009c009c041e1c0ffc07fc07fc0038003800380030003000603fe03fe03f00",
        "40fce1ffc3cf8787070706070e020e000e000c000e040e1c0ffc07fc07fc001c001800380038003000f03fe03fe01fc0",
        "03f807fe0f1e1c0f1c073c063806380070007800781878383cf81ff80ff00030003000200060006000e0ffe0ffc07f00",
        "40fce1fec3c707870707060706020e000c000e000e040e1c0ffc07fc07fc001c003800380038003004703ff03fe01400",
        "003880fc83fec78fc787c6078e070c020c001c001c001c0c9e1c8ffc87fc87fc8038803800300030003010f03fe03fe0",
    ),
    "6": (
        "0078c3fec3cec786c706c607ce07cc06cc06cc0ecc0ece1e8ffe87fc87fc801c801c103c383838303c703fe01fe00f80",
        "80f883fe83ce870e86060e060e060e060e0e0e0e0e1e0e1e0ffc07fc07fc001c001c18183838387138703fe01fc00f80",
        "007c81fec3cec707c707c607c607ce06cc06cc0e8c0e8e1e8ffe87fc87cc801c801c383c383838303cf03fe01fe00f80",
        "80fc81fec38ec787c706c607ce07ce07cc06ce0ece0e8e1e8ffe87fc87fc801c801c1838383838303c703fe01fc00f80",
        "807c81fe83c78787870707070607060706070e070e0f071e07be07fe03ee000c001c101c383c3c383c703fe00fe00780",
    ),
    "7": (
        "6007e007c00e000e000c001c001c001800380078007000e000e000c00180038007800f000e001c003c003ffc3ffc0b88",
        "00180018003800380078007000f000e000c001c001800380078007000e000e001c0018007801f001f001fff1fff00c00",
        "00180018003800380078007000f000e000c000c001800380078007000e000c001c0038007801f001f801fff1fff08000",
        "fff0c000e000f000fe00ff00ff00ff80ff80ff80ff80ff80ff80ff80ff80ff81ff03ff07fe07fc07fc07f003e001c000",
    ),
    "8": (
        "40fce1fec3cf0787070706070e070c070e070e040e1c07fc07f807f80e381c3c1c1c381c3c3c3c383c701fe00fe00780",
        "407ce1ffc3cf0787070706070e070c070c070e06061c0ffc07f807f80e381c3c1c1c3c1c3c383c383c701fe01fe00780",
        "80fcc3fec78fe787e707e607cc078c070c070e0e0f1c07fc07f807f80f381c3c1c3c383c383838303c701fe01fe00780",
        "007c83fec3dfc787c707ce07ce07cc07cc06ce0ecf3c87fc87f087f08e389c389c3c38383c383c383c701fe01fe00780",
    ),
    "9": (
        "007c81fec3efc387c707c706c600ce00cc70cffcdffcdf3cdc1c9c0cbc0cb81cb81c381c383c3c383c781ff00fe00780",
        "407ee0ffc1c703870787070606000e000e700ffc1ffc1f3c1e1c1c0c3c0c3c1c3c1c3c1c3c3c3c381c381ff00fe00780",
        "c07ee0fec1e7038707870706060006000ef00ffc1ffc1f3c1e1e1c0c3c0c3c0c3c1c381c383c3c381c381ff00fe00780",
    ),
}

DIGIT_TEMPLATES = {
    digit: tuple(int(value, 16) for value in values)
    for digit, values in TEMPLATE_HEX.items()
}


def _is_timer_white(r: int, g: int, b: int) -> bool:
    return r > 170 and g > 170 and b > 170 and max(r, g, b) - min(r, g, b) < 80


def _timer_mask(frame: Frame) -> set[tuple[int, int]]:
    x_limit = min(frame.width, round(frame.width * 0.71))
    y_limit = min(frame.height, round(frame.height * 0.70))
    points: set[tuple[int, int]] = set()
    for y in range(y_limit):
        for x in range(x_limit):
            offset = (y * frame.width + x) * 3
            r, g, b = frame.data[offset], frame.data[offset + 1], frame.data[offset + 2]
            if _is_timer_white(r, g, b):
                points.add((x, y))
    return points


def _bbox(points: set[tuple[int, int]]) -> tuple[int, int, int, int] | None:
    if not points:
        return None
    return (
        min(x for x, _ in points),
        min(y for _, y in points),
        max(x for x, _ in points),
        max(y for _, y in points),
    )


def _normalize(slot: set[tuple[int, int]]) -> int | None:
    box = _bbox(slot)
    if box is None:
        return None
    min_x, min_y, max_x, max_y = box
    source_width = max(1, max_x - min_x + 1)
    source_height = max(1, max_y - min_y + 1)
    bits = 0
    for y in range(TEMPLATE_HEIGHT):
        for x in range(TEMPLATE_WIDTH):
            src_x0 = min_x + int(x * source_width / TEMPLATE_WIDTH)
            src_x1 = min_x + max(int((x + 1) * source_width / TEMPLATE_WIDTH), int(x * source_width / TEMPLATE_WIDTH) + 1)
            src_y0 = min_y + int(y * source_height / TEMPLATE_HEIGHT)
            src_y1 = min_y + max(int((y + 1) * source_height / TEMPLATE_HEIGHT), int(y * source_height / TEMPLATE_HEIGHT) + 1)
            filled = 0
            total = 0
            for src_y in range(src_y0, min(src_y1, max_y + 1)):
                for src_x in range(src_x0, min(src_x1, max_x + 1)):
                    total += 1
                    if (src_x, src_y) in slot:
                        filled += 1
            if filled * 2 >= max(1, total):
                bits |= 1 << (y * TEMPLATE_WIDTH + x)
    return bits


def _glyphs(frame: Frame) -> list[int]:
    points = _timer_mask(frame)
    if len(points) < 80:
        return []
    box = _bbox(points)
    if box is None:
        return []
    x0, y0, _x1, y1 = box
    text_height = y1 - y0 + 1
    if text_height < 15:
        return []

    scale = text_height / 25.0
    slot_y = max(0, round(y0 - 2 * scale))
    slot_width = round(SLOT_WIDTH * scale)
    slot_height = round(SLOT_HEIGHT * scale)
    glyphs: list[int] = []
    for relative_x in SLOT_X:
        slot_x = round(x0 + relative_x * scale)
        slot = {
            (x - slot_x, y - slot_y)
            for x, y in points
            if slot_x <= x < slot_x + slot_width and slot_y <= y < slot_y + slot_height
        }
        glyph = _normalize(slot)
        if glyph is None:
            return []
        glyphs.append(glyph)
    return glyphs


def _distance(a: int, b: int) -> float:
    return (a ^ b).bit_count() / TEMPLATE_BITS


def _candidates(glyph: int) -> list[tuple[str, float]]:
    candidates: list[tuple[str, float]] = []
    for digit, templates in DIGIT_TEMPLATES.items():
        candidates.append((digit, min(_distance(glyph, template) for template in templates)))
    return sorted(candidates, key=lambda item: item[1])


def _decode_digits(glyphs: list[int]) -> tuple[str, float] | None:
    if len(glyphs) != 7:
        return None
    candidate_sets = [_candidates(glyph)[:4] for glyph in glyphs]
    best: tuple[str, float] | None = None
    for combination in product(*candidate_sets):
        digits = "".join(digit for digit, _distance_value in combination)
        seconds = int(digits[2:4])
        milliseconds = int(digits[4:7])
        if seconds > 59 or milliseconds > 999:
            continue
        score = sum(distance for _digit, distance in combination) / len(combination)
        if best is None or score < best[1]:
            best = (digits, score)
    if best is None:
        return None
    digits, score = best
    if score > 0.16:
        return None
    return best


def read_battle_timer_frame(frame: Frame) -> float | None:
    decoded = _decode_digits(_glyphs(frame))
    if decoded is None:
        return None
    digits, _score = decoded
    minutes = int(digits[0:2])
    seconds = int(digits[2:4])
    milliseconds = int(digits[4:7])
    return minutes * 60 + seconds + milliseconds / 1000


def read_battle_timer(video: Path, info: VideoInfo, time_sec: float) -> float | None:
    offsets = (
        0.000,
        -0.033,
        0.033,
        -0.067,
        0.067,
        -0.100,
        0.100,
        -0.167,
        0.167,
        -0.250,
        0.250,
        -0.333,
        0.333,
        -0.500,
        0.500,
        -0.750,
        0.750,
        -1.000,
        1.000,
        -1.250,
        1.250,
        -1.500,
        1.500,
        -2.000,
        2.000,
        -2.500,
        2.500,
        -3.000,
        3.000,
    )
    for offset in offsets:
        attempt = time_sec + offset
        if attempt < 0 or attempt > info.duration:
            continue
        try:
            frame = read_frame(video, info, attempt, scale_rect(TIMER_RECT, info))
        except RuntimeError:
            continue
        timer = read_battle_timer_frame(frame)
        if timer is not None:
            return timer
    return None
