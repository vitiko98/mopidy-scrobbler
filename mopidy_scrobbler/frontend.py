import logging
import re
import time

import pykka
import pylast

from mopidy.core import CoreListener

logger = logging.getLogger(__name__)

API_KEY = "2236babefa8ebb3d93ea467560d00d04"
API_SECRET = "94d9a09c0cd5be955c4afaeaffcaefcd"

PYLAST_ERRORS = tuple(
    getattr(pylast, exc_name)
    for exc_name in (
        "ScrobblingError",
        "NetworkError",
        "MalformedResponseError",
        "WSError",
    )
    if hasattr(pylast, exc_name)
)

_TRIVIAL_RE = re.compile(r"(\(|-\s)[^()]*.*(master|studio).*[^()]*$")


def _remove_trivial(title):
    return _TRIVIAL_RE.sub("", title).strip()


def _handle_artist(track):
    try:
        to_try = (track.album.artists, track.artists)
    except AttributeError:
        return ""

    for item in to_try:
        try:
            return list(item)[0].name or ""
        except IndexError:
            pass

    return ""


class ScrobblerFrontend(pykka.ThreadingActor, CoreListener):
    def __init__(self, config, core):
        super().__init__()
        self.config = config
        self.lastfm = None
        self.last_start_time = None

    def on_start(self):
        try:
            self.lastfm = pylast.LastFMNetwork(
                api_key=API_KEY,
                api_secret=API_SECRET,
                username=self.config["scrobbler"]["username"],
                password_hash=pylast.md5(self.config["scrobbler"]["password"]),
            )
            logger.info("Scrobbler connected to Last.fm")
        except PYLAST_ERRORS as exc:
            logger.error(f"Error during Last.fm setup: {exc}")
            self.stop()

    def track_playback_started(self, tl_track):
        track = tl_track.track
        artists = ", ".join(sorted([a.name for a in track.artists]))
        duration = track.length and track.length // 1000 or 0
        self.last_start_time = int(time.time())
        logger.debug(f"Now playing track: {artists} - {track.name}")
        try:
            self.lastfm.update_now_playing(
                _handle_artist(track),
                _remove_trivial(track.name or ""),
                album=_remove_trivial(track.album and track.album.name or ""),
                duration=str(duration),
                track_number=str(track.track_no or 0),
                mbid=(track.musicbrainz_id or ""),
            )
        except PYLAST_ERRORS as exc:
            logger.warning(f"Error submitting playing track to Last.fm: {exc}")

    def track_playback_ended(self, tl_track, time_position):
        track = tl_track.track
        artists = ", ".join(sorted([a.name for a in track.artists]))
        duration = track.length and track.length // 1000 or 0
        time_position = time_position // 1000
        if duration < 30:
            logger.debug("Track too short to scrobble. (30s)")
            return
        if time_position < duration // 2 and time_position < 240:
            logger.debug(
                "Track not played long enough to scrobble. (50% or 240s)"
            )
            return
        if self.last_start_time is None:
            self.last_start_time = int(time.time()) - duration
        logger.debug(f"Scrobbling track: {artists} - {track.name}")
        try:
            self.lastfm.scrobble(
                _handle_artist(track),
                _remove_trivial(track.name or ""),
                str(self.last_start_time),
                album=_remove_trivial(track.album and track.album.name or ""),
                track_number=str(track.track_no or 0),
                duration=str(duration),
                mbid=(track.musicbrainz_id or ""),
            )
        except PYLAST_ERRORS as exc:
            logger.warning(f"Error submitting played track to Last.fm: {exc}")
