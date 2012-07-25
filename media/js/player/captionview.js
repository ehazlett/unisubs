// Amara, universalsubtitles.org
//
// Copyright (C) 2012 Participatory Culture Foundation
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Affero General Public License as
// published by the Free Software Foundation, either version 3 of the
// License, or (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU Affero General Public License for more details.
//
// You should have received a copy of the GNU Affero General Public License
// along with this program.  If not, see
// http://www.gnu.org/licenses/agpl-3.0.html.

goog.provide('unisubs.player.CaptionView');
goog.require('goog.i18n.bidi');

/**
 * * @constructor
 * @param needsIFrame {bool} If an iframe is needed
 * @param isDraggable {bool=} If the caption can be dragged by the user
 */
unisubs.player.CaptionView = function( needsIFrame, isDraggable) {
    goog.ui.Component.call(this);

    /*
     * @type {bool}
     */
    this.needsIFrame_ = needsIFrame || false;
    /*
     * @type {goog.math.Rect}
     */
    this.boundingBox_ = null;
    /*
     * @type {str}
     */
    this.anchor_ = null;
    /*
     * @type {goog.math.Size}
     */
    this.oldSize_ = new goog.math.Size(-1,-1);

    /*
     * @type  {bool}
     */
    this.isDraggable_ = true;//bool(isDraggable);
    /*
     * @type  {bool}
     */
    this.userHasDragged_ = false;
};

goog.inherits(unisubs.player.CaptionView, goog.ui.Component);

/*
 * @conts {int}
 */
unisubs.player.CaptionView.VERTICAL_MARGIN = 40;

/*
 * @cont {int}
 */
unisubs.player.CaptionView.HORIZONTAL_MARGIN = 10;

/*
 * @const {int}
 */
unisubs.player.CaptionView.MAXIMUM_WIDTH = 400;

/*
 * @param boundingBox {goog.math.Rect} The rectangle to which
 * to attach the caption. This is how the caption nows how to position
 * itself in relation to the playe.
 * @param anchor {str=} Which positioning order to follow, defaults to
 * BOTTOM_CENTER if not provided.
 * @return The same bounding box or null if box is empty
 */
unisubs.player.CaptionView.prototype.setUpPositioning =
    function ( boundingBox, anchor){
    if (!boundingBox){
        return null;
    }
    this.boundingBox_ = boundingBox;
    this.captionWidth_ = Math.min(unisubs.player.CaptionView.MAXIMUM_WIDTH,
        this.boundingBox_.width -
          (unisubs.player.CaptionView.HORIZONTAL_MARGIN * 2));
    this.captionLeft_ =  this.boundingBox_.left +
            ((  this.boundingBox_.width - this.captionWidth_) / 2);
    this.anchor_ = anchor || "BOTTOM_CENTER";
    return boundingBox;
};


/**
 * Split the given text into the given characters per line and maximumlines.
 *
 * @text The text to split in 32x4
 * @ opt_charsPerLine The max number of characters to allow per line
 * @ opt_maxLines The max number of lines to allow
 * @ opt_linebreakStr Which string to use when joining lines, i.e. \n or <bt/>
 * @return An array with lines of a maximum 32 chars
**/
unisubs.player.CaptionView.breakLines = function (text, opt_charsPerLine, opt_maxLines, opt_linebreakStr){

    var charsPerLine = opt_charsPerLine || 32;
    var maxLines = opt_maxLines || 4;
    var linebreakStr = opt_linebreakStr || "<br/>";
    // short circuit most common case
    if (!text){
        return "";
    }
    // the user might have forced line breaks, we should respect that

    // Double newlines to force line breaks.
    // No idea why.
    text = text.replace('\n', '\n\n');

    var lines = [];
    var currentLine  = [];
        charsOnCurrentLine = 0,
        words = text.split(" "),
        word = null;
    while(words.length){
        word = words.shift();
        // if there is a line break, push to a new line and put
        // the remaining substring back on the words stack
        var newLineIndex = word.indexOf('\n');
        if (newLineIndex > -1){
            var leftOver = word.substring(newLineIndex + 1, word.length);
            if (leftOver){
                words.unshift(leftOver);
            }
            word = word.substring(0, newLineIndex);
        }

        charsOnCurrentLine =  currentLine.join(" ").length + word.length + 1;
        if (  charsOnCurrentLine <= charsPerLine  ){
            // next word will fit within a line
            currentLine.push(word);
            if (newLineIndex > -1){
                // terminate this line early
                lines.push(currentLine);
                currentLine = [];
            }
            continue;
        }else{
            // overflow, add to the final lines
            lines.push(currentLine);
            currentLine = [word];
        }
    }
    if (currentLine.length){
        lines.push(currentLine);
    }
    // now join each line with a space, then all lines with a line break char
    var lines = goog.array.map(lines, function(line){
        return line.join(" ");
    }).slice(0, maxLines);
    return lines.join(linebreakStr);
}

/*
 * @param The html text to show, or null for blank caption
 */
unisubs.player.CaptionView.prototype.setCaptionText = function(text) {
    if (text == null || text == "") {
        this.setVisibility(false);
    } else {
        // TODO: This ugly hack is for N, who require a different standard of
        // displaying subtitles.  We should remove this once we have pluginable
        // popcorn set up.
        if (unisubs.caption_display_mode == 'n') {
            text = unisubs.player.CaptionView.breakLines(text, 32);
        } else {
            text = goog.string.newLineToBr(text);
        }
        // convert to markdown after text layout has been done
        // as to not inflate char count:

        text = unisubs.html.markdownToHtml(text);
        this.getElement().innerHTML = text;

        goog.i18n.bidi.setElementDirAndAlign(this.getElement(),
                goog.i18n.bidi.estimateDirection(text));

        this.redrawInternal();
        this.setVisibility(true);
    }
};

unisubs.player.CaptionView.prototype.createDom  = function (){
    var $d = goog.bind(this.getDomHelper().createDom, this.getDomHelper());
    var el = $d('span', 'unisubs-captionSpan');
    this.setElementInternal(el);
    // ie < 9 will throw an error if acessing offsetParent on an element with a null parent
    // see http://www.google.com/search?q=ie8+offsetParent+unspecified+error
    var videoOffsetParent = el.parent && el.offsetParent;
    if (!videoOffsetParent)
        videoOffsetParent = goog.dom.getOwnerDocument(el).body;
    if (this.needsIFrame_){
        unisubs.style.setVisibility(el, false);
    }
    goog.dom.appendChild(videoOffsetParent, el);
    this.setVisibility(false);
    unisubs.style.setWidth(this.getElement(), this.captionWidth_);
    unisubs.style.setPosition(this.getElement(), this.captionLeft_);
    if (this.isDraggable_){
        this.dragger_ = new goog.fx.Dragger(this.getElement());
    }

};

unisubs.player.CaptionView.prototype.enterDocument = function() {
    unisubs.player.CaptionView.superClass_.enterDocument.call(this);
    if (this.isDraggable_){
        this.getHandler().
            listen(
                this.dragger_,
                goog.fx.Dragger.EventType.START,
                goog.bind(this.startDrag, this)).
            listen(
                this.dragger_,
                goog.fx.Dragger.EventType.DRAG,
                goog.bind(this.onDrag, this));
    };
};

/*
 * @param e {fx.DragEvent} The dragging event.
 */
unisubs.player.CaptionView.prototype.startDrag = function(e){
    this.userHasDragged_ = true;
};
/*
 * @param e {fx.DragEvent} The dragging event.
 */
unisubs.player.CaptionView.prototype.onDrag = function(e){
    unisubs.style.setPosition(this.getElement(),
                               this.dragger_.deltaX ,
                               this.dragger_.deltaY);
};

unisubs.player.CaptionView.prototype.redrawInternal = function(){
    if (this.userHasDragged_) return;

    var captionSize = goog.style.getSize(this.getElement());
    if (captionSize.width == this.oldSize_.width &&
       captionSize.height == this.oldSize_.height){
        return;
    }
    var newTop = (this.boundingBox_.top + this.boundingBox_.height - captionSize.height ) -
        unisubs.player.CaptionView.VERTICAL_MARGIN;
    unisubs.style.setPosition(this.getElement(), this.captionLeft_, newTop);
    if (this.needsIFrame_ && this.captionBgElem_) {
        goog.style.setPosition(this.captionBgElem_, newLeft, newTop);
        goog.style.setSize(this.captionBgElem_, captionSize);
    }
    this.oldSize_.width = captionSize.width;
    this.oldSize_.height = captionSize.height;
};

/*
 * @param {bool} If it will be made visible.
 */
unisubs.player.CaptionView.prototype.setVisibility = function(show){
    if(this.captionBgElem_){
        unisubs.style.setVisibility(this.captionBgElem_, show);
    }
    unisubs.style.setVisibility(this.getElement(), show);
};

unisubs.player.CaptionView.prototype.dispose = function() {
  if (!this.isDisposed()) {
    unisubs.player.CaptionView.superClass_.dispose.call(this);
    this.dragger_ && this.dragger_.dispose();
  }
};
