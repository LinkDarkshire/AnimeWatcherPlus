"""Template for your own link resolver (LinkResolver).

Installation: copy this file into the app's plugins folder (Settings →
Download plugins shows where it is) and click "Reload". Then add it on the
download page under "Einrichtung" and enter its settings.

What a link resolver does: some search results don't link to the file but to
an intermediate address -- a short link that forwards somewhere else. Before
a link goes to the download client, every enabled resolver whose `handles`
says yes gets to `resolve` it into the final link (several in a row if the
result is again such a link). Results a resolver takes care of can be sent
directly instead of being opened in the browser.

This template resolves plain short links: it follows the server's HTTP
redirects (301/302/...) for the domains you list, e.g. bit.ly, t.co or
tinyurl.com. Your own resolver only needs to change `handles` and `resolve`.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx

from app.downloads import LinkResolver, LinkResolverError, SettingField


class RedirectResolver(LinkResolver):
    # Unique id. Don't change it later -- saved setups refer to it.
    id = "redirect_resolver"
    name = "Kurz-Links (Weiterleitungen)"
    description = "Folgt den Weiterleitungen von Kurz-Links (z. B. bit.ly, t.co) bis zum eigentlichen Link."
    settings_schema = (
        SettingField(
            "hosts",
            "Domains",
            default="bit.ly, t.co, tinyurl.com",
            help="Kommagetrennt. Links dieser Domains werden aufgelöst.",
        ),
    )

    def _hosts(self) -> set[str]:
        return {h.strip().lower() for h in str(self.config.get("hosts") or "").split(",") if h.strip()}

    def handles(self, link: str) -> bool:
        host = (urlsplit(link).hostname or "").lower()
        return any(host == h or host.endswith(f".{h}") for h in self._hosts())

    async def resolve(self, link: str) -> str:
        try:
            async with httpx.AsyncClient(follow_redirects=True, max_redirects=10, timeout=15.0) as client:
                # GET without reading the body: some services don't answer HEAD.
                async with client.stream("GET", link) as response:
                    return str(response.url)
        except httpx.HTTPError as exc:
            raise LinkResolverError(f"Weiterleitung nicht abrufbar: {exc}") from exc
