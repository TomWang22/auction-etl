"""Match listing photos to Discogs covers so identity is not title-only."""

from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Mapping, Sequence

import httpx
from PIL import Image

from auction_etl.services.discogs_identity import SearchHit


COVER_HASH_SIZE = 16
COVER_MAX_DISTANCE = 40
COVER_UNIQUE_GAP = 12
COVER_SHORTLIST_MAX_DISTANCE = 72
COVER_SHORTLIST_UNIQUE_GAP = 8
COVER_ARTIST_PHOTO_MAX_DISTANCE = 24
COVER_ARTIST_PHOTO_UNIQUE_GAP = 16
PHOTO_CONFIRM_MAX_DISTANCE = 80
SAME_COVER_MAX_DISTANCE = 32
SAME_COVER_COLOR_DISTANCE = 42.0


def _center_square(image: Image.Image) -> Image.Image:
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


def _letterbox_square(image: Image.Image) -> Image.Image:
    """Keep obi / title text; center-crop turns SSAR and MR 3065 into faces."""
    width, height = image.size
    side = max(width, height)
    canvas = Image.new("RGB", (side, side), (255, 255, 255))
    canvas.paste(image, ((side - width) // 2, (side - height) // 2))
    return canvas


def average_hash(image: Image.Image, *, size: int = COVER_HASH_SIZE) -> int:
    """Perceptual average hash for sleeve / listing photos."""
    gray = _center_square(image).convert("L").resize(
        (size, size),
        Image.Resampling.LANCZOS,
    )
    pixels = list(gray.tobytes())
    mean = sum(pixels) / len(pixels)
    bits = 0
    for index, pixel in enumerate(pixels):
        if pixel >= mean:
            bits |= 1 << index
    return bits


def layout_hash(image: Image.Image, *, size: int = COVER_HASH_SIZE) -> int:
    """Hash the whole jacket, including obi and footer type."""
    gray = _letterbox_square(image).convert("L").resize(
        (size, size),
        Image.Resampling.LANCZOS,
    )
    pixels = list(gray.tobytes())
    mean = sum(pixels) / len(pixels)
    bits = 0
    for index, pixel in enumerate(pixels):
        if pixel >= mean:
            bits |= 1 << index
    return bits


def image_hashes(image: Image.Image) -> tuple[int, ...]:
    """Center crop plus letterboxed layout so collage sleeves still match."""
    hashes = (average_hash(image), layout_hash(image))
    return hashes if hashes[0] != hashes[1] else hashes[:1]


def hamming_distance(left: int, right: int) -> int:
    """Bit distance between two average hashes."""
    return (left ^ right).bit_count()


def choose_cover_match(
    listing_hash: int,
    candidates: Sequence[tuple[Any, int]],
    *,
    max_distance: int = COVER_MAX_DISTANCE,
    unique_gap: int = COVER_UNIQUE_GAP,
) -> Any | None:
    """Return the unique cover that is close to the listing photo.

    Identical hashes are one sleeve (reissues of the same jacket) so they
    do not block a match the way two different nearby covers would.
    """
    if not candidates:
        return None
    by_hash: dict[int, Any] = {}
    for payload, image_hash in candidates:
        by_hash.setdefault(image_hash, payload)
    ranked = sorted(
        (
            hamming_distance(listing_hash, image_hash),
            image_hash,
            payload,
        )
        for image_hash, payload in by_hash.items()
    )
    best_distance, _image_hash, best = ranked[0]
    if best_distance > max_distance:
        return None
    if len(ranked) > 1:
        second_distance = ranked[1][0]
        if (
            second_distance <= max_distance
            and second_distance - best_distance < unique_gap
        ):
            return None
    return best


def choose_cover_match_multi(
    listing_hashes: Sequence[int],
    candidates: Sequence[tuple[Any, int]],
    *,
    max_distance: int = COVER_MAX_DISTANCE,
    unique_gap: int = COVER_UNIQUE_GAP,
) -> Any | None:
    """Pick a unique cover; sleeve crops are tried before the full seller photo."""
    if not listing_hashes or not candidates:
        return None
    for listing_hash in listing_hashes:
        chosen = choose_cover_match(
            listing_hash,
            candidates,
            max_distance=max_distance,
            unique_gap=unique_gap,
        )
        if chosen is not None:
            return chosen
    return None


def choose_cover_hit(
    listing_hash: int,
    hits: Sequence[SearchHit],
    hashes: Sequence[int | None],
) -> SearchHit | None:
    """Pick a shortlist hit whose Discogs thumb matches the listing photo."""
    return choose_cover_hit_multi((listing_hash,), hits, hashes)


def choose_cover_hit_multi(
    listing_hashes: Sequence[int],
    hits: Sequence[SearchHit],
    hashes: Sequence[int | None],
    *,
    max_distance: int = COVER_SHORTLIST_MAX_DISTANCE,
    unique_gap: int = COVER_SHORTLIST_UNIQUE_GAP,
) -> SearchHit | None:
    """Pick a shortlist hit using sleeve crops from a seller photo."""
    paired: list[tuple[SearchHit, int]] = []
    for hit, image_hash in zip(hits, hashes):
        if image_hash is None:
            continue
        paired.append((hit, image_hash))
    chosen = choose_cover_match_multi(
        listing_hashes,
        paired,
        max_distance=max_distance,
        unique_gap=unique_gap,
    )
    return chosen if isinstance(chosen, SearchHit) else None


def rank_cover_hits(
    listing_hashes: Sequence[int],
    hits: Sequence[SearchHit],
    hashes: Sequence[int | None],
    *,
    max_distance: int = COVER_SHORTLIST_MAX_DISTANCE,
) -> tuple[SearchHit, ...]:
    """Order Discogs hits by sleeve distance; drop covers that are not close."""
    if not listing_hashes:
        return ()
    scored: list[tuple[int, int, SearchHit]] = []
    for hit, image_hash in zip(hits, hashes):
        if image_hash is None:
            continue
        distance = min(
            hamming_distance(listing_hash, image_hash)
            for listing_hash in listing_hashes
        )
        if distance <= max_distance:
            scored.append((distance, hit.discogs_id, hit))
    scored.sort(key=lambda item: (item[0], item[1]))
    ranked: list[SearchHit] = []
    seen: set[int] = set()
    for _distance, discogs_id, hit in scored:
        if discogs_id in seen:
            continue
        seen.add(discogs_id)
        ranked.append(hit)
    return tuple(ranked)


def _top_square(image: Image.Image) -> Image.Image:
    """Album jackets sit at the top of table photos; center crops eat them."""
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    return image.crop((left, 0, left + side, side))


def listing_windows(image: Image.Image) -> tuple[Image.Image, ...]:
    """Sleeve-like crops from seller collages: left, grid, then full frame."""
    width, height = image.size
    windows: list[Image.Image] = []
    if width >= 48 and height >= 48:
        sleeve = min(min(width, height), max(32, int(min(width, height) * 0.52)))
        windows.append(image.crop((0, 0, sleeve, sleeve)))
        windows.append(image.crop((0, 0, max(width // 2, 32), height)))
        left = int(width * 0.08)
        top = int(height * 0.06)
        right = max(left + 32, int(width * 0.58))
        bottom = max(top + 32, int(height * 0.78))
        windows.append(image.crop((left, top, min(right, width), min(bottom, height))))
        windows.append(image.crop((0, 0, width, max(height // 2, 32))))
        for col in (0.0, 0.5):
            for row in (0.0, 0.5):
                x0 = int(width * col)
                y0 = int(height * row)
                windows.append(
                    image.crop(
                        (
                            x0,
                            y0,
                            min(width, x0 + max(32, width // 2)),
                            min(height, y0 + max(32, height // 2)),
                        )
                    )
                )
    windows.append(image)
    return tuple(windows)


def _mean_rgb(image: Image.Image) -> tuple[float, float, float]:
    sample = image.resize((32, 32), Image.Resampling.BOX).convert("RGB")
    pixels = sample.load()
    width, height = sample.size
    red = green = blue = 0.0
    count = width * height or 1
    for y in range(height):
        for x in range(width):
            pixel = pixels[x, y]
            red += pixel[0]
            green += pixel[1]
            blue += pixel[2]
    return red / count, green / count, blue / count


def image_color_side(image: Image.Image) -> str:
    """warm / cool / neutral from a 32px mean. Concert orange vs Stereo Sound blue."""
    red, green, blue = _mean_rgb(image)
    chroma = max(red, green, blue) - min(red, green, blue)
    if chroma < 12:
        return "neutral"
    if blue + green >= 2 * red - 10:
        return "cool"
    return "warm"


def listing_color_side(image: Image.Image) -> str:
    """Use the most colorful sleeve crop so a white table does not wash the hue."""
    best_side = "neutral"
    best_chroma = -1.0
    for window in listing_windows(image):
        red, green, blue = _mean_rgb(window)
        chroma = max(red, green, blue) - min(red, green, blue)
        if chroma <= best_chroma:
            continue
        best_chroma = chroma
        best_side = image_color_side(window)
    return best_side


def listing_cover_hashes(image: Image.Image) -> tuple[int, ...]:
    """Hash sleeve-like crops before the full seller photo."""
    hashes: list[int] = []
    seen: set[int] = set()
    for window in listing_windows(image):
        for crop in (window, _top_square(window)):
            for hashed in image_hashes(crop):
                if hashed not in seen:
                    seen.add(hashed)
                    hashes.append(hashed)
    return tuple(hashes)


def best_listing_cover_distance(listing: Image.Image, cover: Image.Image) -> int:
    """Lowest Hamming distance from any listing crop to the Discogs sleeve."""
    cover_hashes = image_hashes(cover)
    listing_hashes = listing_cover_hashes(listing)
    return min(
        hamming_distance(image_hash, cover_hash)
        for image_hash in listing_hashes
        for cover_hash in cover_hashes
    )


def listing_agrees_with_cover(
    listing: Image.Image,
    cover: Image.Image,
    *,
    max_distance: int = PHOTO_CONFIRM_MAX_DISTANCE,
) -> bool:
    """True when a listing photo crop is the same sleeve as the Discogs thumb."""
    return best_listing_cover_distance(listing, cover) <= max_distance


def fetch_image(
    url: str | None,
    *,
    client: httpx.Client,
) -> Image.Image | None:
    """Download one listing or Discogs thumb. One try, no retries."""
    address = str(url or "").strip()
    if not address or "spacer.gif" in address or "noimage" in address:
        return None
    try:
        response = client.get(address)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    try:
        return Image.open(io.BytesIO(response.content)).convert("RGB")
    except OSError:
        return None


def hash_image_url(
    url: str | None,
    *,
    client: httpx.Client,
    cache: dict[str, int | None],
) -> int | None:
    """Cached average hash for a remote image URL."""
    address = str(url or "").strip()
    if not address:
        return None
    if address in cache:
        return cache[address]
    image = fetch_image(address, client=client)
    hashed = layout_hash(image) if image is not None else None
    cache[address] = hashed
    return hashed


def _rgb_distance(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    return sum((channel - other) ** 2 for channel, other in zip(left, right)) ** 0.5


def best_color_distance(listing: Image.Image, cover: Image.Image) -> float:
    """Lowest mean-color distance from a listing crop to the Discogs sleeve."""
    cover_rgb = _mean_rgb(_letterbox_square(cover))
    return min(
        _rgb_distance(_mean_rgb(window), cover_rgb)
        for window in listing_windows(listing)
    )


def sleeves_are_same_cover(distance: int | None, color_distance: float | None) -> bool:
    """Same sleeve only when the pixels and the colors both agree.

    Two portraits of the same singer can share a face-shaped hash and still
    be different covers. A red gown and a white jacket stay separate.
    """
    if not isinstance(distance, int) or isinstance(distance, bool):
        return False
    if not isinstance(color_distance, (int, float)) or isinstance(color_distance, bool):
        return False
    return distance <= SAME_COVER_MAX_DISTANCE and color_distance <= SAME_COVER_COLOR_DISTANCE


def cover_matches_listing(distance: int | None) -> bool:
    """True when a sleeve hash is within the loose confirm range."""
    return isinstance(distance, int) and not isinstance(distance, bool) and distance <= PHOTO_CONFIRM_MAX_DISTANCE


def order_hits_by_photo(
    hits: Sequence[Mapping[str, Any]],
    scores: Mapping[Any, tuple[int, float]],
) -> list[dict[str, Any]]:
    """Float exact sleeves first, then closer colors, and keep every hit.

    The same catalog can have more than one cover. Those stay separate
    cards. Only a tight pixel and color match is called the same cover.
    """
    annotated: list[dict[str, Any]] = []
    for hit in hits:
        card = dict(hit)
        release_id = card.get("id")
        if release_id in scores:
            distance, color_distance = scores[release_id]
            card["photo_distance"] = distance
            card["photo_color_distance"] = round(color_distance, 1)
            card["photo_same"] = sleeves_are_same_cover(distance, color_distance)
        annotated.append(card)

    def sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, float, int]:
        index, card = item
        if card.get("photo_same") is True:
            return (0, float(card.get("photo_distance") or 0), index)
        color_distance = card.get("photo_color_distance")
        if isinstance(color_distance, (int, float)) and not isinstance(color_distance, bool):
            return (1, float(color_distance), index)
        return (2, float(index), 0)

    return [card for _index, card in sorted(enumerate(annotated), key=sort_key)]


def rank_catalog_covers(
    hits: Sequence[Mapping[str, Any]],
    listing_url: str | None = None,
    *,
    client: httpx.Client | None = None,
    images: Mapping[str, Image.Image] | None = None,
    listing_image: Image.Image | None = None,
    limit: int = 48,
) -> list[dict[str, Any]]:
    """Compare result thumbs to the listing photo and sort the close covers first.

    This is a pixel hash, not a model. A spine or disc photo will not match
    a front cover, and those rows keep their search order.
    """
    cards = [dict(hit) for hit in hits if isinstance(hit, dict)]
    if listing_image is None and images is None:
        address = str(listing_url or "").strip()
        if not address:
            return cards
        if client is None:
            with httpx.Client(timeout=6.0, follow_redirects=True) as owned:
                return rank_catalog_covers(
                    cards,
                    address,
                    client=owned,
                    limit=limit,
                )
        listing_image = fetch_image(address, client=client)
    if listing_image is None:
        return cards
    compared: list[dict[str, Any]] = []
    for card in cards:
        thumb = str(card.get("thumb") or "").strip()
        if not thumb:
            continue
        compared.append(card)
        if len(compared) >= limit:
            break
    scores: dict[Any, tuple[int, float]] = {}

    def score(card: dict[str, Any]) -> tuple[Any, int, float] | None:
        thumb = str(card.get("thumb") or "").strip()
        cover = images.get(thumb) if images is not None else None
        if cover is None and client is not None:
            cover = fetch_image(thumb, client=client)
        if cover is None:
            return None
        return (
            card.get("id"),
            best_listing_cover_distance(listing_image, cover),
            best_color_distance(listing_image, cover),
        )

    if images is not None or client is None:
        scored = [score(card) for card in compared]
    else:
        workers = min(8, len(compared)) or 1
        with ThreadPoolExecutor(max_workers=workers) as pool:
            scored = list(pool.map(score, compared))
    for item in scored:
        if item is None:
            continue
        release_id, distance, color_distance = item
        scores[release_id] = (distance, color_distance)
    return order_hits_by_photo(cards, scores)
