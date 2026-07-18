from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

TVSHOW_NFO = "tvshow.nfo"


def read_anidb_id_from_nfo(anime_dir: Path) -> int | None:
    """FA-04: if tvshow.nfo has <uniqueid type="anidb">, use it directly (no fuzzy lookup)."""
    nfo_path = anime_dir / TVSHOW_NFO
    if not nfo_path.exists():
        return None
    try:
        tree = ET.parse(nfo_path)
    except ET.ParseError:
        return None
    root = tree.getroot()
    for uid in root.findall("uniqueid"):
        if uid.get("type") == "anidb" and uid.text and uid.text.strip().isdigit():
            return int(uid.text.strip())
    return None


def write_tvshow_nfo(
    anime_dir: Path,
    *,
    anidb_id: int,
    title: str,
    original_title: str | None,
    year: int | None,
    description: str | None,
    tags: list[str],
    has_local_poster: bool = False,
) -> Path:
    """Writes/merges tvshow.nfo in Jellyfin/Kodi schema (FA-09). Merge-safe: foreign
    elements the app doesn't own are preserved; only the fields we manage are replaced.
    """
    nfo_path = anime_dir / TVSHOW_NFO
    if nfo_path.exists():
        try:
            tree = ET.parse(nfo_path)
            root = tree.getroot()
        except ET.ParseError:
            root = ET.Element("tvshow")
            tree = ET.ElementTree(root)
    else:
        root = ET.Element("tvshow")
        tree = ET.ElementTree(root)

    _set_child_text(root, "title", title)
    if original_title:
        _set_child_text(root, "originaltitle", original_title)
    if year is not None:
        _set_child_text(root, "year", str(year))
    if description:
        _set_child_text(root, "plot", description)

    for uid in list(root.findall("uniqueid")):
        if uid.get("type") == "anidb":
            root.remove(uid)
    uid_el = ET.SubElement(root, "uniqueid")
    uid_el.set("type", "anidb")
    uid_el.set("default", "true")
    uid_el.text = str(anidb_id)

    for genre in list(root.findall("genre")):
        root.remove(genre)
    for tag in tags:
        genre_el = ET.SubElement(root, "genre")
        genre_el.text = tag

    for thumb in list(root.findall("thumb")):
        if thumb.get("aspect") == "poster":
            root.remove(thumb)
    if has_local_poster:
        # Jellyfin/Kodi auto-detect poster.jpg in the show folder already;
        # this <thumb> is just an explicit, scraper-friendly pointer to it.
        thumb_el = ET.SubElement(root, "thumb")
        thumb_el.set("aspect", "poster")
        thumb_el.text = "poster.jpg"

    anime_dir.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(nfo_path, encoding="utf-8", xml_declaration=True)
    return nfo_path


def write_episode_nfo(
    episode_file: Path, *, title: str | None, ep_number: str, anidb_id: int
) -> Path:
    nfo_path = episode_file.with_suffix(".nfo")
    root = ET.Element("episodedetails")
    _set_child_text(root, "title", title or f"Episode {ep_number}")
    _set_child_text(root, "episode", ep_number)
    uid_el = ET.SubElement(root, "uniqueid")
    uid_el.set("type", "anidb")
    uid_el.text = str(anidb_id)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(nfo_path, encoding="utf-8", xml_declaration=True)
    return nfo_path


def _set_child_text(root: ET.Element, tag: str, text: str) -> None:
    el = root.find(tag)
    if el is None:
        el = ET.SubElement(root, tag)
    el.text = text
