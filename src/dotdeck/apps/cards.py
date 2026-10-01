"""Player Card — a football-game style rated player card with tiers, shine and a stats flip."""

from __future__ import annotations

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Color, Kind, register
from ..gfx import Frame, mix, scale
from ..gfx.font import fit
from .pokedex import bake

TIERS = {  # tier -> (card base, card edge, text colour, accent)
    "gold": ((150, 110, 20), (255, 210, 60), (40, 26, 0), (255, 240, 170)),
    "silver": ((110, 110, 125), (220, 220, 235), (20, 20, 30), (255, 255, 255)),
    "bronze": ((110, 60, 25), (205, 125, 60), (30, 12, 0), (255, 200, 150)),
    "icon": ((200, 190, 160), (255, 250, 230), (60, 45, 10), (255, 214, 0)),
    "totw": ((14, 14, 18), (200, 170, 60), (255, 214, 0), (255, 240, 170)),
    "hero": ((40, 20, 80), (160, 80, 255), (255, 255, 255), (0, 220, 255)),
    "special": ((90, 0, 60), (255, 40, 170), (255, 255, 255), (255, 214, 0)),
}
# stat labels: a second tone that stands apart from the ink, so "92 PA 90 DR" never reads as one word
LABEL = {
    "gold": (255, 244, 200),
    "silver": (255, 255, 255),
    "bronze": (255, 215, 170),
    "icon": (150, 105, 20),
    "totw": (190, 190, 205),
    "hero": (0, 220, 255),
    "special": (255, 214, 0),
}
HAIR = {
    "short": "Short",
    "buzz": "Buzz",
    "curly": "Curly",
    "long": "Long",
    "mohawk": "Mohawk",
    "bald": "Bald",
    "bun": "Man bun",
}
STATS = ("PA", "SH", "PS", "DR", "DF", "PH")  # pace, shooting, passing, dribbling, defending, physical


class CardSettings(AppSettings):
    name: str = Field("DOTDECK", max_length=14, title="Name")
    rating: int = Field(91, ge=1, le=99, title="Overall")
    position: str = Choice(
        "ST",
        {p: p for p in ("GK", "CB", "LB", "RB", "CDM", "CM", "CAM", "LW", "RW", "CF", "ST")},
        title="Position",
    )
    tier: str = Choice(
        "gold",
        {
            "gold": "Gold",
            "silver": "Silver",
            "bronze": "Bronze",
            "icon": "Icon",
            "totw": "Team of the week",
            "hero": "Hero",
            "special": "Special",
        },
        title="Card",
    )
    pac: int = Field(92, ge=1, le=99, title="Pace", json_schema_extra={"group": "Stats"})
    sho: int = Field(89, ge=1, le=99, title="Shooting", json_schema_extra={"group": "Stats"})
    pas: int = Field(84, ge=1, le=99, title="Passing", json_schema_extra={"group": "Stats"})
    dri: int = Field(90, ge=1, le=99, title="Dribbling", json_schema_extra={"group": "Stats"})
    defending: int = Field(45, ge=1, le=99, title="Defending", json_schema_extra={"group": "Stats"})
    phy: int = Field(78, ge=1, le=99, title="Physical", json_schema_extra={"group": "Stats"})
    skin: Color = Field("#d9a066", title="Skin", json_schema_extra={"group": "Player look"})
    hair: Color = Field("#2b1a0e", title="Hair colour", json_schema_extra={"group": "Player look"})
    hair_style: str = Choice("short", HAIR, title="Hair style", group="Player look")
    kit: Color = Field("#e8e8f0", title="Kit", json_schema_extra={"group": "Player look"})
    nation_1: Color = Field("#ff9933", title="Flag stripe 1", json_schema_extra={"group": "Nation"})
    nation_2: Color = Field("#ffffff", title="Flag stripe 2", json_schema_extra={"group": "Nation"})
    nation_3: Color = Field("#138808", title="Flag stripe 3", json_schema_extra={"group": "Nation"})
    shine: bool = Field(True, title="Shine sweep")
    flip_to_stats: bool = Field(True, title="Flip to stats page")
    page_seconds: int = Field(5, ge=2, le=30, title="Seconds per side")


@register
class PlayerCard(App):
    id = "playercard"
    name = "Player Card"
    description = "Your own rated football card — tiers, portrait, nation, six stats, shine and flip."
    icon = "id-card"
    category = "creative"
    Settings = CardSettings
    fps = 10.0
    clip_fps = 10.0  # the fastest GIF rate verified on the panel
    clip_colors = 64
    FLIP = 0.3  # seconds to squeeze a side shut (and to open the next)
    SHINE_AT, SHINE_LEN = 1.0, 1.6  # the shine sweeps once per side, 1 s in, over 1.6 s (3 px per frame)

    def kind(self) -> Kind:
        return "clip"  # a deterministic loop: baked once, played natively (holds cost one frame each)

    def loop_seconds(self) -> float:
        s = self.settings
        return 2.0 * s.page_seconds if s.flip_to_stats else 4.0

    def clip_frames(self) -> Clip:
        return bake(self, self.loop_seconds(), fps=self.clip_fps)

    def render(self, f: Frame, t: float) -> None:
        s = self.settings
        base, edge, ink, accent = TIERS[s.tier]
        t = t % self.loop_seconds()
        side = s.page_seconds if s.flip_to_stats else 4.0
        page = int(t // side) % 2 if s.flip_to_stats else 0
        lt = t % side
        self._card(f, base, edge)
        if page == 0:
            self._front(f, ink, accent)
        else:
            self._stats(f, ink, accent)
        if s.shine:
            self._shine(f, lt)
        if s.flip_to_stats:  # card flip: the side squeezes shut about the centre, the next one opens
            k = min(1.0, (lt + 1 / self.clip_fps) / self.FLIP, (side - lt) / self.FLIP)
            if k < 1:
                w = max(2, round(32 * k / 2) * 2)
                x0 = (32 - w) // 2
                f.px[:, :x0] = 0
                f.px[:, x0 + w :] = 0

    def _card(self, f: Frame, base: tuple[int, int, int], edge: tuple[int, int, int]) -> None:
        f.gradient_v(mix(base, edge, 0.35), base, 0, 32)
        f.rect(0, 0, 32, 32, edge, fill=False)
        for x, y in ((0, 0), (31, 0), (0, 31), (31, 31)):  # clipped corners
            f.set(x, y, (0, 0, 0))
        f.hline(2, 1, 28, mix(edge, (255, 255, 255), 0.4))

    def _front(self, f: Frame, ink: tuple[int, int, int], accent: tuple[int, int, int]) -> None:
        s = self.settings
        f.text(2, 2, str(s.rating), ink, font="small")
        f.text(2, 10, s.position, ink)
        for i, c in enumerate((s.nation_1, s.nation_2, s.nation_3)):  # flag
            f.rect(2, 17 + i, 7, 1, c)
        self._portrait(f, 14, 3)
        f.rect(1, 22, 30, 1, scale(ink, 0.5) if ink != (255, 255, 255) else (120, 120, 140))
        f.text_center(24, fit(s.name.upper(), 29), ink)

    def _portrait(self, f: Frame, x: int, y: int) -> None:
        """A 16x19 head-and-shoulders portrait built from the look settings."""
        s = self.settings
        skin, hair, kit = s.skin, s.hair, s.kit
        shade = scale(skin, 0.8)
        f.rect(x + 1, y + 13, 14, 6, kit)  # shoulders
        f.rect(x + 6, y + 11, 4, 3, shade)  # neck
        f.rect(x + 3, y + 3, 10, 10, skin)  # head
        f.rect(x + 2, y + 6, 1, 3, shade)  # ears
        f.rect(x + 13, y + 6, 1, 3, shade)
        f.rect(x + 5, y + 7, 2, 1, (30, 20, 20))  # eyes
        f.rect(x + 9, y + 7, 2, 1, (30, 20, 20))
        f.hline(x + 6, y + 10, 4, scale(skin, 0.6))  # mouth
        hs = s.hair_style
        if hs == "short":
            f.rect(x + 3, y + 2, 10, 3, hair)
            f.rect(x + 3, y + 4, 1, 2, hair)
        elif hs == "buzz":
            f.rect(x + 3, y + 3, 10, 2, scale(hair, 0.8))
        elif hs == "curly":
            for k in range(0, 11, 2):
                f.circle(x + 3 + k, y + 3, 1, hair)
        elif hs == "long":
            f.rect(x + 3, y + 2, 10, 3, hair)
            f.rect(x + 2, y + 4, 2, 9, hair)
            f.rect(x + 12, y + 4, 2, 9, hair)
        elif hs == "mohawk":
            f.rect(x + 7, y, 2, 5, hair)
        elif hs == "bun":
            f.rect(x + 3, y + 2, 10, 3, hair)
            f.rect(x + 6, y, 4, 2, hair)

    def _stats(self, f: Frame, ink: tuple[int, int, int], accent: tuple[int, int, int]) -> None:
        s = self.settings
        vals = (s.pac, s.sho, s.pas, s.dri, s.defending, s.phy)
        f.text(2, 2, str(s.rating), ink, font="small")
        f.text_right(29, 3, fit(s.name.upper(), 17), ink)
        f.hline(1, 9, 30, scale(ink, 0.5) if ink != (255, 255, 255) else (120, 120, 140))
        lab_c = LABEL.get(s.tier, accent)
        for i, (lab, v) in enumerate(zip(STATS, vals, strict=True)):
            col, row = i // 3, i % 3
            # value then label, 15 px per column, a 1 px gutter between columns, inside the 1 px margins
            x, y = 1 + col * 15, 12 + row * 7
            f.text(x, y, f"{v:>2}", ink)
            f.text(x + 7, y, lab, lab_c)

    def _shine(self, f: Frame, lt: float) -> None:
        ph = (lt - self.SHINE_AT) / self.SHINE_LEN
        if not 0 <= ph <= 1:
            return
        pos = -8 + ph * 48
        for y in range(32):
            for w in range(3):
                x = round(pos - y * 0.5) + w
                if 0 <= x < 32 and f.px[y, x].any():
                    f.blend(x, y, (255, 255, 255), 0.45 - w * 0.12)
