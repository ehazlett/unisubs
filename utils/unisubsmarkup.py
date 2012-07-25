# Amara, universalsubtitles.org
#
# Copyright (C) 2012 Participatory Culture Foundation
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see
# http://www.gnu.org/licenses/agpl-3.0.html.
"""
Unisubs markup is a markdown like format for tags that are accepted
in subtitles, namely:
 **this text is bold**
 * this text is italic*
 _this has underline_
   
We are not using a markdown parser, as our formats actually differ.
Currently this is an ugly regex subtitution, but if we go ahead we
should probably write a parser for it.
"""
import re

from utils.subtitles import strip_tags as _strip_tags

BOLD_TAG_RE = re.compile("</?s*b\s*>", re.IGNORECASE)
BOLD_MARKER_START_RE = re.compile(r"\*\*(?=\w)", re.IGNORECASE)
BOLD_MARKER_END_RE = re.compile(r"(?!\w)\*\*", re.IGNORECASE)

ITALIC_TAG_RE = re.compile("</?s*i\s*>", re.IGNORECASE)
ITALIC_MARKER_START_RE = re.compile(r"\*(?=[^\s])", re.IGNORECASE) 
ITALIC_MARKER_END_RE = re.compile(r"(?!\w)\*", re.IGNORECASE)

UNDERLINE_TAG_RE = re.compile("</?s*u\s*>", re.IGNORECASE)
UNDERLINE_MARKER_START_RE = re.compile(r"_(?=[^\s])", re.IGNORECASE) 
UNDERLINE_MARKER_END_RE = re.compile(r"(?![^_]\w)_", re.IGNORECASE)

def markup_to_html(text, strip_tags=True):
    """
    Converts the unisubs formatting to html.
    If strip_tags is True will strip all tags, but the
    available for subs.
    """
    text = BOLD_MARKER_START_RE.sub("<b>", text)
    text = BOLD_MARKER_END_RE.sub("</b>", text)
    # order matters, substitute doubles first
    text = ITALIC_MARKER_START_RE.sub("<i>", text)
    text = ITALIC_MARKER_END_RE.sub("</i>", text)
    
    text = UNDERLINE_MARKER_START_RE.sub("<u>", text)
    text = UNDERLINE_MARKER_END_RE.sub("</u>", text)
    
    if strip_tags:
        text = _strip_tags(text)
    return text
    
def html_to_markup(text):
    """
    Very naive html to markdown converter. No parsing just
    a regex hack, since we don't need actual an actual tree, our
    content can be 1 depth level only. Should look into a more
    robust solution in the near future.
    """
    safe_html = _strip_tags(text)
    safe_html = BOLD_TAG_RE.sub("**", safe_html)
    safe_html = ITALIC_TAG_RE.sub("*", safe_html)
    safe_html = UNDERLINE_TAG_RE.sub("_", safe_html)
    return safe_html

